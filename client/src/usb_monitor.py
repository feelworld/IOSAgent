"""
USB Device Monitor — auto-detect iOS devices, ensure WDA is running,
discover WiFi IP, and dynamically register them with the server.
"""
import asyncio
import json
import logging
import socket
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

WDA_BUNDLE_ID = "com.facebook.WebDriverAgentRunner.xctrunner"
WDA_PORT_ON_DEVICE = 8100
USB_SCAN_INTERVAL = 5
WDA_STARTUP_WAIT = 8
WDA_CHECK_TIMEOUT = 5
LOCAL_PORT_BASE = 8200  # auto-assigned local ports start here


@dataclass
class USBDevice:
    udid: str
    name: str = ""
    model: str = ""
    ios_version: str = ""
    wifi_ip: str = ""
    local_port: int = 0
    wda_running: bool = False
    registered: bool = False
    forward_proc: subprocess.Popen | None = field(default=None, repr=False)


class USBMonitor:
    """Watches for USB-connected iOS devices and auto-provisions them."""

    def __init__(self, on_device_ready=None, on_device_removed=None):
        self._known: dict[str, USBDevice] = {}
        self._next_port = LOCAL_PORT_BASE
        self._running = False
        self._task: asyncio.Task | None = None
        self.on_device_ready = on_device_ready
        self.on_device_removed = on_device_removed

    @property
    def devices(self) -> dict[str, USBDevice]:
        return dict(self._known)

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        logger.info("USB monitor started (scan every %ds)", USB_SCAN_INTERVAL)

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
            await asyncio.sleep(USB_SCAN_INTERVAL)

    async def _scan_once(self):
        current_udids = await self._list_usb_devices()

        # Detect removed devices
        removed = [u for u in self._known if u not in current_udids]
        for udid in removed:
            dev = self._known.pop(udid)
            self._stop_forward(dev)
            logger.info("📴 USB device removed: %s (%s)", dev.name or udid[:12], udid[:12])
            if self.on_device_removed:
                await self.on_device_removed(dev)

        # Process current devices
        for udid in current_udids:
            if udid in self._known:
                continue
            await self._handle_new_device(udid)

    async def _handle_new_device(self, udid: str):
        logger.info("🔌 New USB device detected: %s", udid[:12])
        dev = USBDevice(udid=udid)

        # Step 1: Get device info via lockdown
        try:
            dev.name, dev.model, dev.ios_version = await self._get_device_info(udid)
            logger.info("  Device: %s (%s, iOS %s)", dev.name, dev.model, dev.ios_version)
        except Exception as e:
            logger.warning("  Could not read device info: %s", e)

        # Step 2: Allocate local port and start USB forwarding
        dev.local_port = self._allocate_port()
        self._start_forward(dev)
        await asyncio.sleep(2)

        # Step 3: Check if WDA is running
        wda_url = f"http://localhost:{dev.local_port}"
        dev.wda_running = await self._check_wda(wda_url)

        if not dev.wda_running:
            logger.info("  WDA not responding, trying to launch...")
            await self._try_launch_wda(udid)
            await asyncio.sleep(WDA_STARTUP_WAIT)
            dev.wda_running = await self._check_wda(wda_url)

        if not dev.wda_running:
            logger.warning("  ⚠️  WDA is NOT running on %s. Please install WDA via TrollStore and start it manually.", dev.name)
            logger.warning("     After WDA is started, re-plug the device or restart the client.")
            self._stop_forward(dev)
            return

        # Step 4: Get WiFi IP from WDA
        dev.wifi_ip = await self._get_wifi_ip(wda_url)
        if not dev.wifi_ip:
            logger.warning("  ⚠️  Could not get WiFi IP for %s. Using USB forwarding only.", dev.name)

        self._known[udid] = dev

        if dev.wifi_ip:
            logger.info("  ✅ %s ready! WiFi IP: %s", dev.name, dev.wifi_ip)
            logger.info("     WDA accessible at: http://%s:%d", dev.wifi_ip, WDA_PORT_ON_DEVICE)
            logger.info("     📱 You can now unplug the USB cable!")
        else:
            logger.info("  ✅ %s ready via USB forwarding (localhost:%d)", dev.name, dev.local_port)

        if self.on_device_ready:
            await self.on_device_ready(dev)

    # ── pymobiledevice3 helpers ──────────────────────────────────────

    async def _list_usb_devices(self) -> set[str]:
        from pymobiledevice3.usbmux import list_devices
        devs = await list_devices()
        return {d.serial for d in devs if d.connection_type == "USB"}

    async def _get_device_info(self, udid: str) -> tuple[str, str, str]:
        from pymobiledevice3.lockdown import create_using_usbmux
        ld = await create_using_usbmux(serial=udid)
        info = ld.short_info
        name = info.get("DeviceName", "Unknown")
        model = info.get("ProductType", "Unknown")
        ios_ver = info.get("ProductVersion", "Unknown")
        return name, model, ios_ver

    async def _try_launch_wda(self, udid: str):
        """Attempt to launch WDA app on device."""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pymobiledevice3",
                "developer", "dvt", "launch", WDA_BUNDLE_ID,
                "--udid", udid,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=15)
        except Exception as e:
            logger.debug("  Launch WDA via dvt failed (expected on some devices): %s", e)

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
            logger.debug("  Port forwarding: localhost:%d -> device:%d (pid=%d)",
                         dev.local_port, WDA_PORT_ON_DEVICE, dev.forward_proc.pid)
        except Exception as e:
            logger.error("  Failed to start port forwarding: %s", e)

    @staticmethod
    def _stop_forward(dev: USBDevice):
        if dev.forward_proc and dev.forward_proc.poll() is None:
            dev.forward_proc.terminate()
            try:
                dev.forward_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dev.forward_proc.kill()
            dev.forward_proc = None

    # ── WDA helpers ──────────────────────────────────────────────────

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
