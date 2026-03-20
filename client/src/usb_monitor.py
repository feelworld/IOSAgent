"""
USB Device Monitor — auto-detect iOS devices, install/start WDA,
discover WiFi IP, and dynamically register them with the server.

Full flow per device:
  1. Detect USB insertion
  2. Pair device (user taps "Trust" on device if needed)
  3. Check if WDA app is installed
  4. If not → install from configured IPA path
  5. Forward WDA port via USB, check if WDA is running
  6. If not running → try to launch WDA
  7. Get WiFi IP from WDA
  8. Register device with server
  9. Notify user: "You can unplug USB now"
"""
import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field

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
    forward_proc: subprocess.Popen | None = field(default=None, repr=False)


class USBMonitor:
    """Watches for USB-connected iOS devices and auto-provisions them."""

    def __init__(
        self,
        wda_ipa_path: str = "",
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        on_device_ready=None,
        on_device_removed=None,
    ):
        self._known: dict[str, USBDevice] = {}
        self._failed: set[str] = set()  # devices that failed provisioning
        self._next_port = LOCAL_PORT_BASE
        self._running = False
        self._task: asyncio.Task | None = None
        self._wda_ipa_path = self._resolve_ipa_path(wda_ipa_path)
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
        logger.info("USB monitor stopped")

    async def _scan_loop(self):
        while self._running:
            try:
                await self._scan_once()
            except Exception as e:
                logger.error("USB scan error: %s", e)
            await asyncio.sleep(self._scan_interval)

    async def _scan_once(self):
        current_udids = await self._list_usb_devices()

        removed = [u for u in self._known if u not in current_udids]
        for udid in removed:
            dev = self._known.pop(udid)
            self._stop_forward(dev)
            logger.info("📴 USB removed: %s (%s)", dev.name or udid[:12], udid[:12])
            if self.on_device_removed:
                await self.on_device_removed(dev)

        # Also clear failed status for unplugged devices so re-plugging retries
        self._failed -= (self._failed - current_udids)

        for udid in current_udids:
            if udid in self._known or udid in self._failed:
                continue
            await self._handle_new_device(udid)

    async def _handle_new_device(self, udid: str):
        logger.info("🔌 New USB device: %s", udid[:12])
        dev = USBDevice(udid=udid)

        # Step 1: Get device info (handles pairing)
        try:
            dev.name, dev.model, dev.ios_version = await self._get_device_info(udid)
            logger.info("   %s (%s, iOS %s)", dev.name, dev.model, dev.ios_version)
        except Exception as e:
            err_msg = str(e)
            if "IncompleteReadError" in err_msg or "pair" in err_msg.lower():
                logger.warning("   ⚠️ Device not paired. Please tap 'Trust' on the device, then re-plug USB.")
                self._failed.add(udid)
                return
            logger.warning("   Could not read device info: %s", e)

        # Step 2: Check if WDA is installed
        dev.wda_installed = await self._is_wda_installed(udid)

        if not dev.wda_installed:
            if self._wda_ipa_path:
                logger.info("   WDA not installed. Installing from %s ...", os.path.basename(self._wda_ipa_path))
                success = await self._install_wda(udid)
                if success:
                    dev.wda_installed = True
                    logger.info("   ✅ WDA installed successfully!")
                else:
                    logger.error("   ❌ WDA installation failed. Ensure device is jailbroken with AppSync Unified.")
                    return
            else:
                logger.warning("   ⚠️ WDA not installed and no IPA configured.")
                logger.warning("      Set usb_monitor.wda_ipa_path in config.yaml, or install WDA manually.")
                self._failed.add(udid)
                return

        # Step 3: Forward WDA port and check if running
        dev.local_port = self._allocate_port()
        self._start_forward(dev)
        await asyncio.sleep(2)

        wda_url = f"http://localhost:{dev.local_port}"
        dev.wda_running = await self._check_wda(wda_url)

        if not dev.wda_running:
            logger.info("   WDA installed but not running. Launching...")
            await self._launch_wda(udid)
            for attempt in range(3):
                await asyncio.sleep(WDA_STARTUP_WAIT)
                dev.wda_running = await self._check_wda(wda_url)
                if dev.wda_running:
                    break
                logger.info("   Waiting for WDA to start... (attempt %d/3)", attempt + 1)

        if not dev.wda_running:
            logger.warning("   ⚠️ WDA failed to start on %s. Please start WDA manually on the device.", dev.name)
            self._stop_forward(dev)
            self._failed.add(udid)
            return

        # Step 4: Get WiFi IP
        dev.wifi_ip = await self._get_wifi_ip(wda_url)

        self._known[udid] = dev

        if dev.wifi_ip:
            logger.info("   ✅ %s ready! WiFi: %s", dev.name, dev.wifi_ip)
            logger.info("      WDA: http://%s:%d", dev.wifi_ip, WDA_PORT_ON_DEVICE)
            logger.info("      📱 You can now unplug the USB cable!")
        else:
            logger.info("   ✅ %s ready (USB only, localhost:%d)", dev.name, dev.local_port)

        if self.on_device_ready:
            await self.on_device_ready(dev)

    # ── Device info ──────────────────────────────────────────────────

    async def _list_usb_devices(self) -> set[str]:
        from pymobiledevice3.usbmux import list_devices
        devs = await list_devices()
        return {d.serial for d in devs if d.connection_type == "USB"}

    async def _get_device_info(self, udid: str) -> tuple[str, str, str]:
        from pymobiledevice3.lockdown import create_using_usbmux
        ld = await create_using_usbmux(serial=udid)
        info = ld.short_info
        return (
            info.get("DeviceName", "Unknown"),
            info.get("ProductType", "Unknown"),
            info.get("ProductVersion", "Unknown"),
        )

    # ── WDA install / check / launch ─────────────────────────────────

    async def _is_wda_installed(self, udid: str) -> bool:
        """Check if any WDA bundle ID exists in installed apps."""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pymobiledevice3",
                "apps", "list", "--udid", udid, "--no-color",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode(errors="replace").lower()
            return any(bid in output for bid in WDA_ALT_BUNDLE_IDS)
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

    async def _launch_wda(self, udid: str):
        """Try multiple methods to launch WDA on the device."""
        for bundle_id in WDA_ALT_BUNDLE_IDS:
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "pymobiledevice3",
                    "developer", "dvt", "launch", bundle_id,
                    "--udid", udid,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=15)
                if proc.returncode == 0:
                    logger.debug("   Launched WDA via: %s", bundle_id)
                    return
            except Exception:
                pass
        logger.debug("   dvt launch failed, WDA may need manual start on device")

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

    # ── WDA status helpers ───────────────────────────────────────────

    @staticmethod
    async def _check_wda(wda_url: str) -> bool:
        try:
            loop = asyncio.get_event_loop()
            def _check():
                r = urllib.request.urlopen(f"{wda_url}/status", timeout=WDA_CHECK_TIMEOUT)
                data = json.loads(r.read())
                return data.get("value", {}).get("ready", False)
            return await loop.run_in_executor(None, _check)
        except Exception:
            return False

    @staticmethod
    async def _get_wifi_ip(wda_url: str) -> str:
        try:
            loop = asyncio.get_event_loop()
            def _get():
                r = urllib.request.urlopen(f"{wda_url}/status", timeout=WDA_CHECK_TIMEOUT)
                data = json.loads(r.read())
                return data.get("value", {}).get("ios", {}).get("ip", "")
            return await loop.run_in_executor(None, _get)
        except Exception:
            return ""
