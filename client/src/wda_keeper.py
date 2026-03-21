"""
WDA keeper — monitors WDA health via SSH and restarts via XCUITest if needed.

Runs as a detached process, one per device. Responsibilities:
  1. Monitor WDA health via SSH direct-tcpip to localhost:8100
  2. If WDA dies and USB is available, restart via XCUITest
  3. If only WiFi available, keep monitoring until USB is reconnected

Usage:
    python -m client.src.wda_keeper --udid <UDID> --wifi-ip <IP>
"""
import argparse
import asyncio
import logging
import os
import signal
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WDA-KEEPER %(process)d] %(message)s",
)
logger = logging.getLogger("wda_keeper")

WDA_BUNDLE_ID = "com.facebook.WebDriverAgentRunner.xctrunner"
WDA_PORT = 8100
HEALTH_CHECK_INTERVAL = 30
RECONNECT_DELAY = 15

SSH_USER = "root"
SSH_PASS = "alpine"
SSH_PORT = 22


class WDAKeeper:
    """Monitor WDA health via SSH; restart via XCUITest when USB is available."""

    def __init__(self, udid: str, wifi_ip: str):
        self.udid = udid
        self.wifi_ip = wifi_ip
        self._ssh = None

    def _connect_ssh(self):
        import paramiko
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(
            self.wifi_ip, port=SSH_PORT,
            username=SSH_USER, password=SSH_PASS,
            timeout=15, banner_timeout=15,
        )
        transport = self._ssh.get_transport()
        if transport:
            transport.set_keepalive(10)
        logger.info("SSH connected to %s (keepalive=10s)", self.wifi_ip)

    def _ensure_ssh(self):
        if not self._ssh:
            self._connect_ssh()
            return
        t = self._ssh.get_transport()
        if not t or not t.is_active():
            self._connect_ssh()

    def is_wda_healthy(self) -> bool:
        """Check WDA HTTP health through SSH direct-tcpip channel."""
        try:
            self._ensure_ssh()
            transport = self._ssh.get_transport()
            chan = transport.open_channel(
                "direct-tcpip", ("localhost", WDA_PORT), ("127.0.0.1", 0),
            )
            chan.sendall(b"GET /status HTTP/1.0\r\nHost: localhost\r\n\r\n")
            chan.settimeout(8)
            time.sleep(1)
            data = b""
            try:
                while True:
                    chunk = chan.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except Exception:
                pass
            chan.close()
            return b"200" in data and (b'"ready"' in data or b'"state"' in data)
        except Exception:
            return False

    def _unfreeze_testmanagerd(self):
        """Resume testmanagerd (SIGCONT) before XCUITest launch."""
        try:
            self._ensure_ssh()
            self._ssh.exec_command("killall -CONT testmanagerd 2>/dev/null", timeout=5)
            time.sleep(1)
            _, out, _ = self._ssh.exec_command(
                "ps -ef | grep testmanagerd | grep -v grep | wc -l", timeout=5,
            )
            count = int(out.read().decode().strip() or "0")
            if count == 0:
                logger.info("Restarting testmanagerd...")
                self._ssh.exec_command(
                    "launchctl load /System/Library/LaunchDaemons/com.apple.testmanagerd.plist 2>/dev/null",
                    timeout=5,
                )
                time.sleep(3)
            logger.info("testmanagerd unfrozen/running")
        except Exception as e:
            logger.warning("Could not unfreeze testmanagerd: %s", e)

    def _freeze_testmanagerd(self):
        """SIGSTOP testmanagerd so WDA survives USB disconnection."""
        try:
            self._ensure_ssh()
            self._ssh.exec_command("killall -STOP testmanagerd 2>/dev/null", timeout=5)
            time.sleep(1)
            logger.info("testmanagerd frozen (SIGSTOP)")
        except Exception as e:
            logger.warning("Could not freeze testmanagerd: %s", e)

    async def restart_wda_via_xcuitest(self) -> bool:
        """Restart WDA using XCUITest (requires USB connection).

        Unfreezes testmanagerd first, starts WDA, then re-freezes it
        so WDA survives USB disconnection.
        """
        try:
            import paramiko
            from pymobiledevice3.usbmux import list_devices
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.dvt.testmanaged.xcuitest import (
                XCUITestService, XCUITestPlanConsumer,
                get_app_info, generate_xctestconfiguration,
            )
            from pymobiledevice3.services.remote_server import NSUUID
            from bpylist2 import archiver

            devices = await list_devices()
            usb_match = [d for d in devices if d.serial == self.udid and d.connection_type == "USB"]
            if not usb_match:
                return False
            logger.info("USB detected — restarting WDA via XCUITest")

            self._unfreeze_testmanagerd()

            ld = await create_using_usbmux(serial=self.udid)
            svc = XCUITestService(ld)
            if svc.pctl is None:
                svc.pctl = await svc.init_process_control()

            session_id = NSUUID.uuid4()
            app_info = await get_app_info(ld, WDA_BUNDLE_ID)
            container = app_info.get("Container", "")
            if not container:
                logger.warning("WDA has no data container")
                return False

            config = generate_xctestconfiguration(
                app_info, session_id, svc.product_major_version, None, None,
            )
            xctest_path = f"/tmp/{str(session_id).upper()}.xctestconfiguration"
            config_data = archiver.archive(config)

            self._ensure_ssh()
            sftp = self._ssh.open_sftp()
            remote_tmp = container + "/tmp"
            try:
                for name in sftp.listdir(remote_tmp):
                    if name.endswith(".xctestconfiguration"):
                        sftp.remove(f"{remote_tmp}/{name}")
            except FileNotFoundError:
                self._ssh.exec_command(f"mkdir -p '{remote_tmp}'", timeout=5)
                await asyncio.sleep(1)

            remote_path = container + xctest_path
            with sftp.open(remote_path, "wb") as f:
                f.write(config_data)
            self._ssh.exec_command(f"chown mobile:mobile '{remote_path}'", timeout=5)
            sftp.close()

            ctrl_dvt, ctrl_chan, main_dvt, main_chan = await svc.init_ide_channels(
                session_id, config._config["IDECapabilities"],
            )
            pid = await svc.launch_test_app(
                session_id, app_info, WDA_BUNDLE_ID, xctest_path, None, None,
            )
            logger.info("XCUITest runner PID: %d", pid)

            await asyncio.sleep(1)
            await svc.authorize_test_process_id(ctrl_chan, pid)
            await main_dvt.serve_channel(
                "dtxproxy:XCTestDriverInterface:XCTestManager_IDEInterface", main_chan,
            )
            await svc.start_executing_test_plan_with_protocol_version(
                main_dvt, svc.XCODE_VERSION,
            )

            consumer = XCUITestPlanConsumer(
                pid, svc.pctl, ctrl_dvt, ctrl_chan, main_dvt, main_chan, config,
            )
            asyncio.get_event_loop().create_task(consumer.consume())

            for _ in range(10):
                await asyncio.sleep(3)
                if self.is_wda_healthy():
                    logger.info("WDA restarted successfully")
                    self._freeze_testmanagerd()
                    return True
            return False

        except Exception as e:
            logger.warning("XCUITest restart failed: %s", e)
            return False


async def run_keeper(udid: str, wifi_ip: str):
    keeper = WDAKeeper(udid, wifi_ip)
    consecutive_failures = 0

    while True:
        try:
            if keeper.is_wda_healthy():
                if consecutive_failures > 0:
                    logger.info("WDA recovered on %s", udid[:12])
                consecutive_failures = 0
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                continue

            consecutive_failures += 1
            logger.warning("WDA not healthy on %s (check %d)", udid[:12], consecutive_failures)

            if await keeper.restart_wda_via_xcuitest():
                consecutive_failures = 0
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                continue

            logger.info("No USB — monitoring only, will retry in %ds", HEALTH_CHECK_INTERVAL)
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)

        except Exception as e:
            consecutive_failures += 1
            logger.warning("Keeper error: %s (attempt %d)", e, consecutive_failures)
            keeper._ssh = None
            delay = min(RECONNECT_DELAY * consecutive_failures, 120)
            await asyncio.sleep(delay)


def write_pid_file(udid: str) -> str:
    pid_dir = os.path.join(os.path.dirname(__file__), "..", "wda_pids")
    os.makedirs(pid_dir, exist_ok=True)
    pid_file = os.path.join(pid_dir, f"{udid[:12]}.pid")
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))
    return pid_file


def main():
    parser = argparse.ArgumentParser(description="WDA Keeper")
    parser.add_argument("--udid", required=True)
    parser.add_argument("--wifi-ip", required=True)
    args = parser.parse_args()

    pid_file = write_pid_file(args.udid)
    logger.info("Keeper started (pid=%d) for %s via %s",
                os.getpid(), args.udid[:12], args.wifi_ip)

    loop = asyncio.new_event_loop()

    def _shutdown():
        for t in asyncio.all_tasks(loop):
            t.cancel()

    try:
        if sys.platform != "win32":
            loop.add_signal_handler(signal.SIGTERM, _shutdown)
        loop.run_until_complete(run_keeper(args.udid, args.wifi_ip))
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
        try:
            os.remove(pid_file)
        except OSError:
            pass
        logger.info("Keeper stopped")


if __name__ == "__main__":
    main()
