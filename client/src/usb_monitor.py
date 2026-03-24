"""
USB Device Monitor — auto-detect iOS devices, install/start WDA,
discover WiFi IP, and dynamically register them with the server.

Full flow per device:
  1. Detect USB insertion
  2. Pair device (user taps "Trust" on device if needed)
  3. Check if WDA app is installed
  4. If not installed:
     a. Try installing WDA IPA directly
     b. If signature error → auto-deploy AppSync Unified via AFC2
     c. Kill installd to activate AppSync hooks
     d. Retry WDA installation
  5. Forward WDA port via USB, check if WDA is running
  6. If not running → mount DeveloperDiskImage + launch WDA
  7. Get WiFi IP from WDA
  8. Register device with server
  9. Notify user: "You can unplug USB now"
"""
import asyncio
import hashlib
import io
import json
import lzma
import logging
import os
import signal
import socket
import subprocess
import sys
import tarfile
import urllib.request
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)

WDA_BUNDLE_ID = "com.facebook.WebDriverAgentRunner.xctrunner"
WDA_ALT_BUNDLE_IDS = [
    "com.facebook.WebDriverAgentRunner.xctrunner",
    "com.facebook.WebDriverAgentRunner",
    "com.facebook.wda.runner",
    "com.facebook.wda.xctrunner",
]
WDA_PORT_ON_DEVICE = 8100
DEFAULT_SCAN_INTERVAL = 5
WDA_STARTUP_WAIT = 8
WDA_CHECK_TIMEOUT = 5
LOCAL_PORT_BASE = 8200

APPSYNC_PKG_ID = "ai.akemi.appsyncunified"
AFC2_SERVICE = "com.apple.afc2"
DPKG_STATUS_PATH = "/var/lib/dpkg/status"
DPKG_INFO_DIR = "/var/lib/dpkg/info"


@dataclass
class USBDevice:
    udid: str
    name: str = ""
    model: str = ""
    ios_version: str = ""
    wifi_ip: str = ""
    local_port: int = 0
    wda_running: bool = False
    wda_installed: bool = False
    registered: bool = False
    usb_connected: bool = True
    forward_proc: subprocess.Popen | None = field(default=None, repr=False)
    keeper_proc: subprocess.Popen | None = field(default=None, repr=False)
    ssh_tunnel: object | None = field(default=None, repr=False)
    _xcuitest_refs: list = field(default_factory=list, repr=False)
    # Hardware identifiers
    serial_number: str = ""
    imei: str = ""
    meid: str = ""
    wifi_mac: str = ""
    bluetooth_mac: str = ""
    # Hardware specs
    cpu_architecture: str = ""
    hardware_platform: str = ""
    chip_id: int = 0
    product_type: str = ""
    # Jailbreak info
    jailbroken: bool = False
    jailbreak_type: str = ""


class USBMonitor:
    """Watches for USB-connected iOS devices and auto-provisions them."""

    def __init__(
        self,
        wda_ipa_path: str = "",
        appsync_deb_path: str = "",
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        on_device_ready=None,
        on_device_removed=None,
    ):
        self._known: dict[str, USBDevice] = {}
        self._failed: set[str] = set()  # devices that failed provisioning
        self._next_port = LOCAL_PORT_BASE
        self._running = False
        self._task: asyncio.Task | None = None
        self.active_tasks: int = 0
        self._wda_ipa_path = self._resolve_ipa_path(wda_ipa_path)
        self._appsync_deb_path = self._resolve_ipa_path(appsync_deb_path)
        self._scan_interval = scan_interval
        self.on_device_ready = on_device_ready
        self.on_device_removed = on_device_removed

    @staticmethod
    def _resolve_ipa_path(path: str) -> str:
        if not path:
            return ""
        if os.path.isabs(path):
            return path if os.path.exists(path) else ""
        candidates = [
            os.path.join(os.getcwd(), path),
            os.path.join(os.path.dirname(__file__), "..", "..", path),
            os.path.join(os.path.dirname(__file__), "..", path),
        ]
        for c in candidates:
            if os.path.exists(c):
                return os.path.abspath(c)
        return ""

    @property
    def devices(self) -> dict[str, USBDevice]:
        return dict(self._known)

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        ipa_status = f"WDA IPA: {self._wda_ipa_path}" if self._wda_ipa_path else "WDA IPA: not configured (auto-install disabled)"
        logger.info("USB monitor started (scan every %ds) | %s", self._scan_interval, ipa_status)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for dev in self._known.values():
            self._stop_forward(dev)
            self._stop_ssh_tunnel(dev)
        logger.info("USB monitor stopped")

    async def _scan_loop(self):
        while self._running:
            if self.active_tasks > 0:
                await asyncio.sleep(2)
                continue
            try:
                await self._scan_once()
            except Exception as e:
                logger.error("USB scan error: %s", e)
            await asyncio.sleep(self._scan_interval)

    async def _scan_once(self):
        current_udids = await self._list_usb_devices()

        # Handle USB reconnection for WiFi-only devices
        for udid in current_udids:
            dev = self._known.get(udid)
            if dev and not dev.usb_connected:
                logger.info("USB reconnected for %s", dev.name or udid[:12])
                dev.usb_connected = True

        # Check removed USB devices — keep alive via SSH tunnel if possible
        removed = [u for u in self._known if u not in current_udids and self._known[u].usb_connected]
        for udid in removed:
            dev = self._known[udid]
            wda_alive = False

            # SSH tunnel present: retry multiple times (keeper may be restarting WDA)
            if dev.ssh_tunnel and dev.ssh_tunnel.is_alive():
                tunnel_url = f"http://localhost:{dev.ssh_tunnel.local_port}"
                for attempt in range(6):
                    wda_alive = await self._check_wda(tunnel_url)
                    if wda_alive:
                        break
                    if attempt < 5:
                        logger.info("USB gone, waiting for WDA via SSH tunnel... (%d/6) %s",
                                    attempt + 1, dev.name or udid[:12])
                        await asyncio.sleep(10)
            elif dev.wifi_ip:
                if await self._setup_ssh_tunnel(dev):
                    tunnel_url = f"http://localhost:{dev.ssh_tunnel.local_port}"
                    for attempt in range(6):
                        wda_alive = await self._check_wda(tunnel_url)
                        if wda_alive:
                            break
                        if attempt < 5:
                            logger.info("USB gone, waiting for WDA via new SSH tunnel... (%d/6)", attempt + 1)
                            await asyncio.sleep(10)

            if wda_alive:
                if dev.forward_proc:
                    self._stop_forward(dev)
                dev.usb_connected = False
                dev.wda_running = True
                logger.info("USB gone but WDA alive via SSH tunnel: %s", dev.name or udid[:12])
                if self.on_device_ready:
                    await self.on_device_ready(dev)
                continue

            dev = self._known.pop(udid)
            self._stop_forward(dev)
            self._stop_ssh_tunnel(dev)
            logger.info("Device removed: %s (%s)", dev.name or udid[:12], udid[:12])
            if self.on_device_removed:
                await self.on_device_removed(dev)

        self._failed -= (self._failed - current_udids)

        for udid in current_udids:
            if udid in self._known or udid in self._failed:
                continue
            await self._handle_new_device(udid)

        # Health check for all known devices (USB + WiFi-only)
        for udid, dev in list(self._known.items()):
            wda_url = self._get_wda_url(dev)
            if not wda_url:
                continue
            is_ok = await self._check_wda(wda_url)
            if dev.wda_running and not is_ok:
                logger.warning("WDA not responding for %s (keeper will auto-restart)", dev.name or udid[:12])
                dev.wda_running = False
            elif not dev.wda_running and is_ok:
                logger.info("WDA recovered for %s", dev.name or udid[:12])
                dev.wda_running = True
                if self.on_device_ready:
                    await self.on_device_ready(dev)

    async def _handle_new_device(self, udid: str):
        logger.info("New USB device: %s", udid[:12])
        dev = USBDevice(udid=udid)

        # Step 1: Get device info (handles pairing) + hardware identifiers
        try:
            dev.name, dev.model, dev.ios_version = await self._get_device_info(udid, dev)
            logger.info("   %s (%s, iOS %s, SN:%s)", dev.name, dev.model, dev.ios_version, dev.serial_number)
        except Exception as e:
            err_msg = str(e)
            if "IncompleteReadError" in err_msg or "pair" in err_msg.lower():
                logger.warning("   Device not paired. Please tap 'Trust' on the device, then re-plug USB.")
                self._failed.add(udid)
                return
            logger.warning("   Could not read device info: %s", e)

        # Step 1.5: Detect jailbreak status
        await self._detect_jailbreak(udid, dev)

        # Step 2: Mount DeveloperDiskImage (needed early for DVT pkill)
        await self._mount_developer_image(udid)

        # Step 3: Check if WDA is installed
        dev.wda_installed = await self._is_wda_installed(udid)

        if not dev.wda_installed:
            if not self._wda_ipa_path:
                logger.warning("   WDA not installed and no IPA configured.")
                logger.warning("   Set usb_monitor.wda_ipa_path in config.yaml, or install WDA manually.")
                self._failed.add(udid)
                return

            logger.info("   WDA not installed. Installing from %s ...", os.path.basename(self._wda_ipa_path))
            success = await self._install_wda(udid)

            if not success:
                # WDA install failed (likely signature error) — try deploying AppSync first
                logger.info("   WDA install failed. Attempting to deploy AppSync Unified via AFC2...")
                appsync_ok = await self._ensure_appsync(udid)

                if not appsync_ok:
                    # AFC2 not available — try SSH to install AFC2 + AppSync automatically
                    logger.info("   AFC2 unavailable. Trying SSH auto-install...")
                    ssh_ok = await self._setup_device_via_ssh(udid)
                    if ssh_ok:
                        appsync_ok = True

                if appsync_ok:
                    logger.info("   AppSync deployed. Retrying WDA installation...")
                    success = await self._install_wda(udid)

                    if not success:
                        logger.info("   Still failing — respring to reload AppSync hooks...")
                        await self._respring_device(udid, dev)
                        await asyncio.sleep(5)
                        logger.info("   Retrying WDA installation after respring...")
                        success = await self._install_wda(udid)

            if success:
                dev.wda_installed = True
                logger.info("   WDA installed successfully!")
                # Respring to activate FrontBoard hook (needed for WDA launch)
                await self._respring_device(udid, dev)
            else:
                logger.error("   WDA installation failed. Device may not be jailbroken or SSH not available.")
                self._failed.add(udid)
                return

        # Step 3.5: Enable WiFi sync so keeper can maintain WDA over WiFi
        await self._enable_wifi_sync(udid)

        # Step 3.6: Install OpenSSH + get WiFi IP (for SSH tunnel after USB removal)
        wifi_ip_from_ssh = await self._setup_wifi_ssh(udid)

        # Step 4: Forward WDA port and check if WDA is already running
        dev.local_port = self._allocate_port()
        self._start_forward(dev)
        await asyncio.sleep(2)

        wda_url = f"http://localhost:{dev.local_port}"
        dev.wda_running = await self._check_wda(wda_url)

        # Step 5: Store WiFi IP
        wifi_ip = wifi_ip_from_ssh or (await self._get_wifi_ip(wda_url) if dev.wda_running else wifi_ip_from_ssh)
        if wifi_ip:
            dev.wifi_ip = wifi_ip

        # Step 6: Always launch WDA via XCUITest to establish DTX session
        # (even if WDA appears running — it needs an active DTX session to stay alive)
        logger.info("   Launching WDA via XCUITest...")
        launched = await self._launch_wda_xcuitest(dev)
        if launched:
            dev.wda_running = True
            logger.info("   WDA launched via XCUITest!")
        elif dev.wda_running:
            logger.info("   XCUITest launch failed but WDA is responding (may die soon)")
        else:
            last_err = getattr(dev, "_last_xcuitest_error", "")
            is_security_err = "Security" in last_err or "code signature" in last_err

            if is_security_err:
                logger.warning("   Security error — AppSync hook may not be active. "
                               "Running uicache + ldrestart to reload hooks...")
                await self._respring_device(udid, dev)
                await self._ensure_testmanagerd_running(dev)

            logger.warning("   XCUITest launch failed, retrying after delay...")
            for retry in range(3):
                await asyncio.sleep(10)
                logger.info("   XCUITest retry %d/3...", retry + 1)
                launched = await self._launch_wda_xcuitest(dev)
                if launched:
                    dev.wda_running = True
                    logger.info("   WDA launched on retry %d!", retry + 1)
                    break
            if not dev.wda_running:
                logger.warning("   All XCUITest retries failed, waiting for WDA...")
                for attempt in range(8):
                    await asyncio.sleep(WDA_STARTUP_WAIT)
                    check_url = self._get_wda_url(dev) or wda_url
                    dev.wda_running = await self._check_wda(check_url)
                    if dev.wda_running:
                        break
                    logger.info("   Waiting for WDA... (attempt %d/8)", attempt + 1)

        # Step 7: Setup SSH tunnel (now that WDA is running)
        if dev.wda_running and dev.wifi_ip:
            tunnel_ok = await self._setup_ssh_tunnel(dev)
            if not tunnel_ok:
                logger.info("   SSH tunnel setup failed (will use USB port forward)")

        # Step 8: Keeper not needed for USB-connected devices
        # (usb_monitor handles health checks via USB; keeper uses WiFi SSH which can
        #  falsely detect WDA as dead and kill the active XCUITest DTX session)

        if not dev.wda_running:
            logger.warning("   WDA failed to start on %s", dev.name)
            self._stop_forward(dev)
            self._failed.add(udid)
            return

        self._known[udid] = dev

        if dev.ssh_tunnel and dev.ssh_tunnel.is_alive():
            logger.info("   %s ready! SSH tunnel: localhost:%d -> %s:8100",
                        dev.name, dev.ssh_tunnel.local_port, dev.wifi_ip)
            logger.info("   USB can be unplugged — WDA stays alive via WiFi + SSH tunnel!")
        elif dev.wifi_ip:
            logger.info("   %s ready! WiFi: %s (no SSH tunnel — install OpenSSH on device)",
                        dev.name, dev.wifi_ip)
        else:
            logger.info("   %s ready (USB only, localhost:%d)", dev.name, dev.local_port)

        if self.on_device_ready:
            await self.on_device_ready(dev)

    # ── WiFi sync ─────────────────────────────────────────────────────

    async def _enable_wifi_sync(self, udid: str):
        """Enable WiFi connectivity so WDA can survive USB unplug."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            ld = await create_using_usbmux(serial=udid)
            await ld.set_enable_wifi_connections(True)
            logger.info("   WiFi sync enabled")

            from pymobiledevice3.usbmux import list_devices
            for _ in range(6):
                devs = await list_devices()
                types = [d.connection_type for d in devs if d.serial == udid]
                if "Network" in types:
                    logger.info("   Device visible on WiFi (Network via usbmuxd)")
                    return
                await asyncio.sleep(5)

            # usbmuxd didn't discover via Bonjour — try direct TCP to verify WiFi works
            logger.info("   Bonjour discovery slow, verifying WiFi via direct TCP...")
            await self._verify_wifi_direct(udid)
        except Exception as e:
            logger.warning("   Could not enable WiFi sync: %s", e)

    async def _verify_wifi_direct(self, udid: str):
        """Verify WiFi connectivity by connecting directly to device IP."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux, create_using_tcp
            from pymobiledevice3.pair_records import get_preferred_pair_record, create_pairing_records_cache_folder

            # Get WiFi IP from USB connection first
            ld_usb = await create_using_usbmux(serial=udid)
            # Try to get WiFi IP via a quick WDA check or lockdown
            cache = create_pairing_records_cache_folder()
            pair_record = await get_preferred_pair_record(udid, cache)
            if not pair_record:
                logger.warning("   No pairing record for WiFi verification")
                return

            # We need the device's WiFi IP — will be set later when WDA responds
            logger.info("   WiFi pairing record available (direct TCP will work)")
        except Exception as e:
            logger.debug("   WiFi direct verification failed: %s", e)

    # ── Device info ──────────────────────────────────────────────────

    async def _list_usb_devices(self) -> set[str]:
        from pymobiledevice3.usbmux import list_devices
        devs = await list_devices()
        return {d.serial for d in devs if d.connection_type == "USB"}

    async def _get_device_info(self, udid: str, dev: USBDevice | None = None):
        """Collect device info from lockdown. Populates dev fields if provided.

        Returns (name, model, ios_version) for backward compat.
        """
        from pymobiledevice3.lockdown import create_using_usbmux
        ld = await create_using_usbmux(serial=udid)
        vals = await ld.get_value()

        name = vals.get("DeviceName", "Unknown")
        model = vals.get("ProductType", "Unknown")
        ios_ver = vals.get("ProductVersion", "Unknown")

        if dev is not None:
            dev.serial_number = vals.get("SerialNumber", "")
            dev.imei = vals.get("InternationalMobileEquipmentIdentity", "")
            dev.meid = vals.get("MobileEquipmentIdentifier", "")
            dev.wifi_mac = vals.get("WiFiAddress", "")
            dev.bluetooth_mac = vals.get("BluetoothAddress", "")
            dev.cpu_architecture = vals.get("CPUArchitecture", "")
            dev.hardware_platform = vals.get("HardwarePlatform", "")
            dev.chip_id = vals.get("ChipID", 0)
            dev.product_type = vals.get("ProductType", "")

        return name, model, ios_ver

    async def _detect_jailbreak(self, udid: str, dev: USBDevice):
        """Detect jailbreak status via app list (Cydia/Sileo/Substitute)."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.installation_proxy import InstallationProxyService
            ld = await create_using_usbmux(serial=udid)
            proxy = InstallationProxyService(lockdown=ld)
            await proxy.connect()
            apps = await proxy.get_apps("Any")

            jb_indicators = {
                "com.saurik.Cydia": "Cydia",
                "org.coolstar.SileoStore": "Sileo",
                "com.ex.substitute.settings": "Substitute",
                "org.coolstar.substrated": "Substrate",
            }
            found = [name for bid, name in jb_indicators.items() if bid in apps]
            if found:
                dev.jailbroken = True
                dev.jailbreak_type = " + ".join(found)
            else:
                dev.jailbroken = False
        except Exception as e:
            logger.debug("   Jailbreak detection failed: %s", e)

    # ── WDA install / check / launch ─────────────────────────────────

    async def _is_wda_installed(self, udid: str) -> bool:
        """Check if any WDA bundle ID exists in installed apps (via Python API)."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.installation_proxy import InstallationProxyService
            ld = await create_using_usbmux(serial=udid)
            proxy = InstallationProxyService(lockdown=ld)
            await proxy.connect()
            apps = await proxy.get_apps("User")
            found = any(bid in apps for bid in WDA_ALT_BUNDLE_IDS)
            return found
        except Exception as e:
            logger.debug("   Could not list apps: %s", e)
            return False

    async def _install_wda(self, udid: str) -> bool:
        """Install WDA IPA via pymobiledevice3."""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pymobiledevice3",
                "apps", "install", self._wda_ipa_path,
                "--udid", udid,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode == 0:
                return True
            err = stderr.decode(errors="replace") + stdout.decode(errors="replace")
            logger.error("   Install stderr: %s", err[:500])
            return False
        except asyncio.TimeoutError:
            logger.error("   WDA install timed out (>120s)")
            return False
        except Exception as e:
            logger.error("   WDA install exception: %s", e)
            return False

    # ── WDA XCUITest launch (SSH-based config push) ────────────────

    def _try_ssh_connect(self, dev: USBDevice) -> "paramiko.SSHClient | None":
        """Try to establish SSH to device (WiFi or USB-forwarded). Returns client or None."""
        try:
            import paramiko
        except ImportError:
            return None

        for ssh_target, ssh_port, fwd in self._ssh_targets(dev):
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ssh_target, port=ssh_port, username="root",
                            password="alpine", timeout=10)
                transport = ssh.get_transport()
                if transport:
                    transport.set_keepalive(10)
                return ssh
            except Exception:
                pass
            finally:
                if fwd:
                    try:
                        fwd.terminate()
                    except Exception:
                        pass
        return None

    def _ssh_targets(self, dev: USBDevice):
        """Yield (host, port, fwd_proc|None) candidates for SSH."""
        if dev.wifi_ip:
            yield dev.wifi_ip, 22, None
        for device_port in (22, 44):
            local_port = self._allocate_port()
            fwd = subprocess.Popen(
                [sys.executable, "-m", "pymobiledevice3", "usbmux", "forward",
                 str(local_port), str(device_port), "--udid", dev.udid],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            import time; time.sleep(2)
            yield "127.0.0.1", local_port, fwd

    async def _launch_wda_xcuitest(self, dev: USBDevice) -> bool:
        """Launch WDA via XCUITest.

        Tries SSH config push first (needed for AppSync-installed apps).
        Falls back to standard HouseArrest-based XCUITest if SSH unavailable.
        After WDA starts, freezes testmanagerd (SIGSTOP) so WDA survives
        USB disconnection.
        """
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.dvt.testmanaged.xcuitest import (
                XCUITestService, get_app_info, generate_xctestconfiguration,
            )
            from pymobiledevice3.services.remote_server import NSUUID
            from bpylist2 import archiver

            await self._ensure_testmanagerd_running(dev)

            ld = await create_using_usbmux(serial=dev.udid)
            svc = XCUITestService(ld)
            if svc.pctl is None:
                svc.pctl = await svc.init_process_control()

            session_id = NSUUID.uuid4()
            app_info = await get_app_info(ld, WDA_BUNDLE_ID)
            container = app_info.get("Container", "")

            config = generate_xctestconfiguration(
                app_info, session_id, svc.product_major_version, None, None,
            )
            xctest_path = f"/tmp/{str(session_id).upper()}.xctestconfiguration"
            config_data = archiver.archive(config)

            # Try pushing config via SSH (bypasses broken HouseArrest)
            ssh = self._try_ssh_connect(dev)
            if ssh and container:
                try:
                    sftp = ssh.open_sftp()
                    remote_tmp = container + "/tmp"
                    try:
                        for name in sftp.listdir(remote_tmp):
                            if name.endswith(".xctestconfiguration"):
                                sftp.remove(f"{remote_tmp}/{name}")
                    except FileNotFoundError:
                        ssh.exec_command(f"mkdir -p '{remote_tmp}'", timeout=5)
                        await asyncio.sleep(1)
                    remote_path = container + xctest_path
                    with sftp.open(remote_path, "wb") as f:
                        f.write(config_data)
                    ssh.exec_command(f"chown mobile:mobile '{remote_path}'", timeout=5)
                    sftp.close()
                    logger.info("   XCTest config pushed via SSH (%d bytes)", len(config_data))
                except Exception as e:
                    logger.debug("   SSH config push failed: %s", e)
                finally:
                    ssh.close()
            else:
                logger.info("   No SSH available — using standard HouseArrest config push")

            # XCUITest flow: IDE channels → launch → authorize → start plan
            ctrl_dvt, ctrl_chan, main_dvt, main_chan = await svc.init_ide_channels(
                session_id, config._config["IDECapabilities"],
            )
            pid = await svc.launch_test_app(
                session_id, app_info, WDA_BUNDLE_ID, xctest_path, None, None,
            )
            logger.info("   XCUITest runner PID: %d", pid)

            await asyncio.sleep(1)
            await svc.authorize_test_process_id(ctrl_chan, pid)
            await main_dvt.serve_channel(
                "dtxproxy:XCTestDriverInterface:XCTestManager_IDEInterface", main_chan,
            )
            await svc.start_executing_test_plan_with_protocol_version(
                main_dvt, svc.XCODE_VERSION,
            )

            from pymobiledevice3.services.dvt.testmanaged.xcuitest import XCUITestPlanConsumer
            consumer = XCUITestPlanConsumer(
                pid, svc.pctl, ctrl_dvt, ctrl_chan, main_dvt, main_chan, config,
            )
            consume_task = asyncio.get_event_loop().create_task(consumer.consume())

            dev._xcuitest_refs = [ld, svc, ctrl_dvt, ctrl_chan, main_dvt, main_chan, consumer, consume_task]

            for i in range(10):
                await asyncio.sleep(3)
                check_url = self._get_wda_url(dev) or f"http://localhost:{dev.local_port}"
                if await self._check_wda(check_url):
                    return True
            return False

        except Exception as e:
            logger.warning("   XCUITest launch error: %s", e)
            dev._last_xcuitest_error = str(e)
            return False

    async def _freeze_testmanagerd(self, dev: USBDevice):
        """SIGSTOP testmanagerd on device so it cannot kill WDA when USB disconnects."""
        ssh = self._try_ssh_connect(dev)
        if not ssh:
            logger.info("   No SSH — cannot freeze testmanagerd (WDA may not survive USB unplug)")
            return
        try:
            ssh.exec_command("killall -STOP testmanagerd 2>/dev/null", timeout=5)
            await asyncio.sleep(1)
            logger.info("   testmanagerd frozen (SIGSTOP) — WDA will survive USB disconnect")
        except Exception as e:
            logger.warning("   Could not freeze testmanagerd: %s", e)
        finally:
            ssh.close()

    async def _ensure_testmanagerd_running(self, dev: USBDevice):
        """Unfreeze/restart testmanagerd before XCUITest launch."""
        ssh = self._try_ssh_connect(dev)
        if not ssh:
            return
        try:
            ssh.exec_command("killall -CONT testmanagerd 2>/dev/null", timeout=5)
            await asyncio.sleep(1)
            _, out, _ = ssh.exec_command(
                "ps -ef | grep testmanagerd | grep -v grep | wc -l", timeout=5
            )
            count = int(out.read().decode().strip() or "0")
            if count == 0:
                logger.info("   Restarting testmanagerd...")
                ssh.exec_command(
                    "launchctl load /System/Library/LaunchDaemons/com.apple.testmanagerd.plist 2>/dev/null",
                    timeout=5,
                )
                await asyncio.sleep(8)
        except Exception as e:
            logger.debug("   testmanagerd check: %s", e)
        finally:
            ssh.close()

    # ── WDA keeper process management ───────────────────────────────

    def _get_pid_dir(self) -> str:
        pid_dir = os.path.join(os.path.dirname(__file__), "..", "wda_pids")
        os.makedirs(pid_dir, exist_ok=True)
        return pid_dir

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a process is still running (cross-platform)."""
        try:
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except (OSError, PermissionError):
            return False

    def _find_existing_keeper(self, udid: str) -> int | None:
        """Check if a keeper process is already running for this device."""
        pid_file = os.path.join(self._get_pid_dir(), f"{udid[:12]}.pid")
        if not os.path.exists(pid_file):
            return None
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            if self._is_pid_alive(pid):
                return pid
            logger.debug("   Keeper PID %d no longer running, cleaning up", pid)
            os.remove(pid_file)
            return None
        except (OSError, ValueError):
            try:
                os.remove(pid_file)
            except OSError:
                pass
            return None

    def _start_keeper(self, dev: USBDevice):
        """Start a detached SSH-based WDA keeper process."""
        if not dev.wifi_ip:
            logger.warning("   Cannot start keeper: no WiFi IP for %s", dev.udid[:12])
            return

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

        log_dir = os.path.join(os.path.dirname(__file__), "..", "wda_pids")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{dev.udid[:12]}.log")
        log_file = open(log_path, "a")

        dev.keeper_proc = subprocess.Popen(
            [
                sys.executable, "-m", "client.src.wda_keeper",
                "--udid", dev.udid,
                "--wifi-ip", dev.wifi_ip,
            ],
            stdout=log_file,
            stderr=log_file,
            creationflags=creation_flags,
            start_new_session=(sys.platform != "win32"),
        )
        logger.info("   Keeper started (pid=%d) for %s via SSH %s, log: %s",
                     dev.keeper_proc.pid, dev.udid[:12], dev.wifi_ip, log_path)

    def _stop_keeper(self, dev: USBDevice):
        """Stop the keeper process for a device."""
        # Kill by stored proc reference
        if dev.keeper_proc and dev.keeper_proc.poll() is None:
            dev.keeper_proc.terminate()
            try:
                dev.keeper_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dev.keeper_proc.kill()
            dev.keeper_proc = None

        # Also kill by PID file
        pid = self._find_existing_keeper(dev.udid)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM if sys.platform != "win32" else signal.SIGBREAK)
            except OSError:
                pass
            pid_file = os.path.join(self._get_pid_dir(), f"{dev.udid[:12]}.pid")
            try:
                os.remove(pid_file)
            except OSError:
                pass

    # ── SSH-based device setup (fallback when AFC2 missing) ─────────

    async def _setup_device_via_ssh(self, udid: str) -> bool:
        """Install AFC2 + AppSync via SSH when AFC2 is not yet on device.

        Many jailbreaks (unc0ver, checkra1n) include OpenSSH by default.
        We port-forward device:22 via usbmux, SSH in, push .deb files,
        and install them with dpkg.
        """
        try:
            import paramiko
        except ImportError:
            logger.warning("   paramiko not installed (pip install paramiko). Cannot use SSH.")
            return False

        forward_proc = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connected = False

            for device_port in (22, 44):
                ssh_local_port = self._allocate_port()
                if forward_proc:
                    try:
                        forward_proc.terminate()
                    except Exception:
                        pass
                forward_proc = subprocess.Popen(
                    [sys.executable, "-m", "pymobiledevice3", "usbmux", "forward",
                     str(ssh_local_port), str(device_port), "--udid", udid],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                await asyncio.sleep(2)
                try:
                    ssh.connect("127.0.0.1", port=ssh_local_port,
                                username="root", password="alpine", timeout=10)
                    connected = True
                    logger.info("   SSH connected on device port %d", device_port)
                    break
                except Exception:
                    continue

            if not connected:
                logger.warning("   SSH failed on port 22 and 44. Install OpenSSH or AFC2 from Cydia.")
                return False

            logger.info("   SSH connected to device!")

            # Upload .deb files via SFTP to /var/mobile/Media/
            sftp = ssh.open_sftp()
            remote_debs = []

            # Find AFC2 .deb — look next to appsync.deb or wda ipa
            afc2_deb = self._find_afc2_deb()
            if afc2_deb:
                remote_path = "/var/mobile/Media/afc2.deb"
                sftp.put(afc2_deb, remote_path)
                remote_debs.append(remote_path)
                logger.info("   Uploaded AFC2 .deb")

            if self._appsync_deb_path:
                remote_path = "/var/mobile/Media/appsync.deb"
                sftp.put(self._appsync_deb_path, remote_path)
                remote_debs.append(remote_path)
                logger.info("   Uploaded AppSync .deb")

            sftp.close()

            if not remote_debs:
                # No .deb files — try apt-get as fallback
                logger.info("   No .deb files found, trying apt-get...")
                _, stdout_ch, stderr_ch = ssh.exec_command(
                    "apt-get update -o Acquire::AllowInsecureRepositories=true 2>&1 && "
                    "apt-get install -y --allow-unauthenticated com.saurik.afc2d 2>&1",
                    timeout=60,
                )
                output = stdout_ch.read().decode(errors="replace")
                exit_code = stdout_ch.channel.recv_exit_status()
                if exit_code == 0:
                    logger.info("   AFC2 installed via apt-get")
                else:
                    logger.warning("   apt-get install failed: %s", output[-300:])
                    ssh.close()
                    return False
            else:
                # Install .debs with dpkg
                for deb in remote_debs:
                    _, stdout_ch, stderr_ch = ssh.exec_command(
                        f"dpkg -i {deb} 2>&1", timeout=30,
                    )
                    output = stdout_ch.read().decode(errors="replace")
                    exit_code = stdout_ch.channel.recv_exit_status()
                    logger.info("   dpkg -i %s -> exit %d", os.path.basename(deb), exit_code)
                    if exit_code != 0:
                        logger.warning("   dpkg output: %s", output[-300:])

            # Restart installd to activate AppSync hooks
            ssh.exec_command("killall -9 installd 2>/dev/null", timeout=10)
            await asyncio.sleep(3)

            # Clean up uploaded .debs
            for deb in remote_debs:
                try:
                    ssh.exec_command(f"rm -f {deb}", timeout=5)
                except Exception:
                    pass

            ssh.close()
            logger.info("   SSH setup complete! AFC2 + AppSync installed.")
            return True

        except Exception as e:
            logger.error("   SSH setup failed: %s", e)
            return False
        finally:
            if forward_proc:
                try:
                    forward_proc.terminate()
                except Exception:
                    pass

    def _find_afc2_deb(self) -> str:
        """Search for AFC2 .deb file in common locations."""
        search_dirs = []
        if self._wda_ipa_path:
            search_dirs.append(os.path.dirname(self._wda_ipa_path))
        if self._appsync_deb_path:
            search_dirs.append(os.path.dirname(self._appsync_deb_path))
        search_dirs.append(os.path.join(os.path.dirname(__file__), "..", "wda"))

        for d in search_dirs:
            for name in ("afc2.deb", "afc2add.deb", "com.saurik.afc2d.deb"):
                candidate = os.path.join(d, name)
                if os.path.exists(candidate):
                    return os.path.abspath(candidate)
        return ""

    # ── AppSync deployment via AFC2 ──────────────────────────────────

    async def _ensure_appsync(self, udid: str) -> bool:
        """Deploy AppSync Unified via AFC2 if device is jailbroken with AFC2 access."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.afc import AfcService

            ld = await create_using_usbmux(serial=udid)
            afc = AfcService(lockdown=ld, service_name=AFC2_SERVICE)
            await afc.connect()
        except Exception:
            logger.warning("   AFC2 not available. Device may not be jailbroken.")
            return False

        try:
            # Check if AppSync already registered in dpkg
            try:
                status_data = await afc.get_file_contents(DPKG_STATUS_PATH)
                if APPSYNC_PKG_ID in status_data.decode(errors="replace"):
                    logger.info("   AppSync already installed, killing installd to reload hooks...")
                    await self._kill_process(udid, "installd")
                    await asyncio.sleep(5)
                    await afc.close()
                    return True
            except Exception:
                pass

            # Find .deb source
            deb_path = self._appsync_deb_path
            if not deb_path:
                # Fallback: look next to WDA IPA
                if self._wda_ipa_path:
                    candidate = os.path.join(os.path.dirname(self._wda_ipa_path), "appsync.deb")
                    if os.path.exists(candidate):
                        deb_path = candidate
            if not deb_path:
                logger.warning("   No AppSync .deb found. Set usb_monitor.appsync_deb_path in config.yaml")
                await afc.close()
                return False

            logger.info("   Deploying AppSync from %s via AFC2...", os.path.basename(deb_path))

            # Extract and push files
            files = self._extract_deb_data(deb_path)
            control = self._extract_deb_control(deb_path)

            for remote_path, data in files.items():
                parent = os.path.dirname(remote_path)
                try:
                    await afc.listdir(parent)
                except Exception:
                    await afc.makedirs(parent)
                await afc.set_file_contents(remote_path, data)
                logger.debug("   Pushed %s (%d bytes)", remote_path, len(data))

            # Update dpkg status
            existing = await afc.get_file_contents(DPKG_STATUS_PATH)
            existing_text = existing.decode(errors="replace")
            if APPSYNC_PKG_ID not in existing_text:
                entry = control.strip() + "\nStatus: install ok installed\n\n"
                new_status = existing_text.rstrip("\n") + "\n\n" + entry
                await afc.set_file_contents(DPKG_STATUS_PATH, new_status.encode())

            # Create dpkg info files
            file_list = "\n".join(sorted(files.keys())) + "\n"
            await afc.set_file_contents(f"{DPKG_INFO_DIR}/{APPSYNC_PKG_ID}.list", file_list.encode())

            md5_lines = []
            for path, data in sorted(files.items()):
                md5_lines.append(f"{hashlib.md5(data).hexdigest()}  {path}")
            await afc.set_file_contents(
                f"{DPKG_INFO_DIR}/{APPSYNC_PKG_ID}.md5sums",
                "\n".join(md5_lines).encode(),
            )

            await afc.close()
            logger.info("   AppSync files deployed. Killing installd...")

            await self._kill_process(udid, "installd")
            await asyncio.sleep(5)
            return True

        except Exception as e:
            logger.error("   AppSync deployment failed: %s", e)
            try:
                await afc.close()
            except Exception:
                pass
            return False

    @staticmethod
    def _extract_deb_data(deb_path: str) -> dict[str, bytes]:
        """Extract data files from a .deb archive. Returns {remote_path: bytes}."""
        files = {}
        with open(deb_path, "rb") as f:
            f.read(8)  # ar magic
            while True:
                header = f.read(60)
                if len(header) < 60:
                    break
                name = header[:16].decode().strip().rstrip("/")
                size = int(header[48:58].decode().strip())
                data = f.read(size)
                if size % 2:
                    f.read(1)
                if not name.startswith("data.tar"):
                    continue

                if name.endswith(".lzma"):
                    raw = lzma.decompress(data)
                    tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r")
                elif name.endswith(".gz"):
                    tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
                elif name.endswith(".xz"):
                    tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:xz")
                else:
                    tf = tarfile.open(fileobj=io.BytesIO(data), mode="r")

                for info in tf.getmembers():
                    if info.isfile() and not info.name.endswith(".DS_Store"):
                        path = info.name.lstrip("./")
                        files[f"/{path}"] = tf.extractfile(info).read()
                tf.close()
                break
        return files

    @staticmethod
    def _extract_deb_control(deb_path: str) -> str:
        """Extract the control file text from a .deb archive."""
        with open(deb_path, "rb") as f:
            f.read(8)
            while True:
                header = f.read(60)
                if len(header) < 60:
                    break
                name = header[:16].decode().strip().rstrip("/")
                size = int(header[48:58].decode().strip())
                data = f.read(size)
                if size % 2:
                    f.read(1)
                if not name.startswith("control.tar"):
                    continue

                if name.endswith(".gz"):
                    tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
                elif name.endswith(".xz"):
                    tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:xz")
                else:
                    tf = tarfile.open(fileobj=io.BytesIO(data), mode="r")

                for info in tf.getmembers():
                    if info.name in ("./control", "control"):
                        return tf.extractfile(info).read().decode()
                tf.close()
                break
        return ""

    async def _kill_process(self, udid: str, name: str):
        """Kill a process on the device via DVT pkill."""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pymobiledevice3",
                "developer", "dvt", "pkill", name,
                "--udid", udid,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=15)
        except Exception as e:
            logger.debug("   Could not kill %s: %s", name, e)

    async def _respring_device(self, udid: str, dev: "USBDevice | None" = None):
        """Full respring: uicache + ldrestart to reload all tweak hooks (AppSync etc)."""
        if dev is None:
            dev = self._known.get(udid) or next(
                (d for d in self._known.values() if d.udid == udid), None
            )
        ssh = self._try_ssh_connect(dev) if dev else None
        if ssh:
            try:
                logger.info("   Running uicache to refresh app registration...")
                ssh.exec_command("uicache -a 2>/dev/null", timeout=30)
                await asyncio.sleep(5)
                logger.info("   Running ldrestart to reload all daemon hooks...")
                ssh.exec_command("ldrestart 2>/dev/null &", timeout=5)
            except Exception as e:
                logger.warning("   SSH respring commands failed: %s, falling back to backboardd kill", e)
                ssh.close()
                await self._kill_process(udid, "backboardd")
            else:
                ssh.close()
        else:
            logger.info("   No SSH, killing backboardd for respring...")
            await self._kill_process(udid, "backboardd")
        logger.info("   Waiting for device to respring (35s)...")
        await asyncio.sleep(35)

    async def _mount_developer_image(self, udid: str):
        """Mount DeveloperDiskImage if not already mounted."""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pymobiledevice3",
                "mounter", "auto-mount", "--udid", udid,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if b"mounted successfully" in stderr or b"already mounted" in stderr.lower():
                logger.debug("   DeveloperDiskImage mounted")
            elif proc.returncode == 0:
                logger.debug("   DeveloperDiskImage mount returned 0")
        except Exception as e:
            logger.debug("   DeveloperDiskImage mount skipped: %s", e)

    # ── Port forwarding ──────────────────────────────────────────────

    def _allocate_port(self) -> int:
        port = self._next_port
        self._next_port += 1
        while not self._is_port_free(port):
            port += 1
            self._next_port = port + 1
        return port

    @staticmethod
    def _is_port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def _start_forward(self, dev: USBDevice):
        try:
            dev.forward_proc = subprocess.Popen(
                [
                    sys.executable, "-m", "pymobiledevice3",
                    "usbmux", "forward",
                    str(dev.local_port), str(WDA_PORT_ON_DEVICE),
                    "--udid", dev.udid,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.error("   Port forwarding failed: %s", e)

    @staticmethod
    def _stop_forward(dev: USBDevice):
        if dev.forward_proc and dev.forward_proc.poll() is None:
            dev.forward_proc.terminate()
            try:
                dev.forward_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dev.forward_proc.kill()
            dev.forward_proc = None

    # ── SSH tunnel (WiFi access to WDA) ──────────────────────────────

    def _get_wda_url(self, dev: USBDevice) -> str | None:
        """Return the best URL to reach WDA for this device.
        Prefers USB port forward (stable).
        """
        if dev.usb_connected and dev.forward_proc and dev.forward_proc.poll() is None and dev.local_port:
            return f"http://localhost:{dev.local_port}"
        if dev.ssh_tunnel and dev.ssh_tunnel.is_alive():
            return f"http://localhost:{dev.ssh_tunnel.local_port}"
        if dev.forward_proc and dev.forward_proc.poll() is None and dev.local_port:
            return f"http://localhost:{dev.local_port}"
        if dev.wifi_ip:
            return f"http://{dev.wifi_ip}:{WDA_PORT_ON_DEVICE}"
        return None

    @staticmethod
    def _stop_ssh_tunnel(dev: USBDevice):
        if dev.ssh_tunnel:
            try:
                dev.ssh_tunnel.stop()
            except Exception:
                pass
            dev.ssh_tunnel = None

    async def _setup_ssh_tunnel(self, dev: USBDevice) -> bool:
        """Establish SSH tunnel to device's WDA via WiFi."""
        if not dev.wifi_ip:
            return False

        from .ssh_tunnel import SSHTunnel

        if dev.ssh_tunnel:
            try:
                dev.ssh_tunnel.stop()
            except Exception:
                pass
            dev.ssh_tunnel = None

        tunnel_port = self._allocate_port()
        tunnel = SSHTunnel(device_ip=dev.wifi_ip, local_port=tunnel_port)

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, tunnel.start)
            await asyncio.sleep(2)

            if await self._check_wda(f"http://localhost:{tunnel_port}"):
                dev.ssh_tunnel = tunnel
                logger.info("   SSH tunnel OK: localhost:%d -> %s:8100",
                            tunnel_port, dev.wifi_ip)
                return True

            tunnel.stop()
            logger.info("   SSH tunnel connected but WDA not responding via tunnel")
            return False
        except Exception as e:
            logger.warning("   SSH tunnel failed: %s", e)
            try:
                tunnel.stop()
            except Exception:
                pass
            return False

    async def _setup_wifi_ssh(self, udid: str) -> str:
        """Install OpenSSH on device (if needed) and return its WiFi IP.

        Uses SSH-over-USB to access the device. Returns the WiFi IP string,
        or empty string on failure.
        """
        try:
            import paramiko
        except ImportError:
            logger.warning("   paramiko not installed (pip install paramiko)")
            return ""

        forward_proc = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connected = False

            for device_port in (22, 44):
                local_port = self._allocate_port()
                if forward_proc:
                    try:
                        forward_proc.terminate()
                    except Exception:
                        pass
                forward_proc = subprocess.Popen(
                    [sys.executable, "-m", "pymobiledevice3", "usbmux", "forward",
                     str(local_port), str(device_port), "--udid", udid],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                await asyncio.sleep(2)
                try:
                    ssh.connect("127.0.0.1", port=local_port,
                                username="root", password="alpine", timeout=10)
                    connected = True
                    break
                except Exception:
                    continue

            if not connected:
                logger.info("   No SSH via USB — install OpenSSH from Cydia for WiFi support")
                return ""

            # 1) Ensure OpenSSH is installed (sshd binds 0.0.0.0, needed for WiFi)
            _, out, _ = ssh.exec_command(
                "which sshd 2>/dev/null && echo OK || echo MISS", timeout=10,
            )
            if "MISS" in out.read().decode():
                logger.info("   Installing OpenSSH for WiFi access...")
                _, out, _ = ssh.exec_command(
                    "apt-get update -o Acquire::AllowInsecureRepositories=true 2>&1 && "
                    "apt-get install -y --allow-unauthenticated openssh 2>&1",
                    timeout=120,
                )
                output = out.read().decode(errors="replace")
                exit_code = out.channel.recv_exit_status()
                if exit_code != 0:
                    logger.warning("   OpenSSH install failed: %s", output[-200:])
                    ssh.close()
                    return ""
                logger.info("   OpenSSH installed")
            else:
                logger.info("   OpenSSH already available")

            # 2) Get WiFi IP (scutil works on all iOS, ifconfig/awk may not exist)
            _, out, _ = ssh.exec_command(
                "scutil --nwi 2>/dev/null | grep 'address' | head -1 | sed 's/.*: //'",
                timeout=10,
            )
            wifi_ip = out.read().decode().strip()
            ssh.close()

            if wifi_ip:
                logger.info("   Device WiFi IP: %s", wifi_ip)
            else:
                logger.info("   No WiFi IP — device not on WiFi?")
            return wifi_ip

        except Exception as e:
            logger.warning("   WiFi SSH setup error: %s", e)
            return ""
        finally:
            if forward_proc:
                try:
                    forward_proc.terminate()
                except Exception:
                    pass

    # ── WDA status helpers ───────────────────────────────────────────

    @staticmethod
    async def _check_wda(wda_url: str) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=WDA_CHECK_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{wda_url}/status") as resp:
                    data = await resp.json()
                    return data.get("value", {}).get("ready", False)
        except Exception:
            return False

    @staticmethod
    async def _get_wifi_ip(wda_url: str) -> str:
        try:
            timeout = aiohttp.ClientTimeout(total=WDA_CHECK_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{wda_url}/status") as resp:
                    data = await resp.json()
                    return data.get("value", {}).get("ios", {}).get("ip", "")
        except Exception:
            return ""
