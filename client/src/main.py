import asyncio
import logging
import signal
import uuid
from datetime import datetime, timezone

import aiohttp

from client.src.command_executor import CommandExecutor
from client.src.config import AgentConfig, DeviceConfig, load_config
from client.src.device_info import collect_device_info
from client.src.heartbeat import HeartbeatSender
from client.src.usb_monitor import USBMonitor, USBDevice, WDA_PORT_ON_DEVICE
from client.src.ws_client import AgentWSClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agent")


async def obtain_token(config: AgentConfig) -> str:
    """Login to the server via HTTP and return a JWT access token."""
    url = f"{config.server_http_url}/api/v1/auth/login"
    payload = {"username": config.auth.username, "password": config.auth.password}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Login failed (HTTP {resp.status}): {body}")
            data = await resp.json()
            token = data.get("access_token") or data.get("data", {}).get("access_token")
            if not token:
                raise RuntimeError(f"No access_token in login response: {data}")
            return token


async def main():
    config = load_config()
    logger.info(
        "Agent starting: machine_id=%s, static_devices=%d",
        config.machine_id,
        len(config.devices),
    )

    ws_client = AgentWSClient(config)
    device_map: dict[str, str] = {}
    executor: CommandExecutor | None = None

    heartbeat = HeartbeatSender(
        machine_id=config.machine_id,
        devices=list(config.devices),
        send_fn=ws_client.send_message,
        interval=config.heartbeat_interval,
    )

    async def register_devices(devices_info: list[dict]):
        """Send device.register message to server."""
        if not devices_info:
            return
        msg = {
            "type": "device.register",
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "machine_id": config.machine_id,
                "devices": devices_info,
            },
        }
        await ws_client.send_message(msg)

    # ── Callback: USB device becomes ready ───────────────────────────
    async def on_usb_device_ready(usb_dev: USBDevice):
        device_uid = usb_dev.udid[:12]
        if usb_dev.wifi_ip:
            wda_url = f"http://{usb_dev.wifi_ip}:{WDA_PORT_ON_DEVICE}"
        else:
            wda_url = f"http://localhost:{usb_dev.local_port}"

        device_map[device_uid] = wda_url
        if executor:
            executor.devices[device_uid] = wda_url

        heartbeat.add_device(DeviceConfig(
            device_uid=device_uid, wda_url=wda_url, name=usb_dev.name,
        ))

        info = await collect_device_info(wda_url, device_uid)
        await register_devices([{
            "device_uid": device_uid,
            "model": info.model or usb_dev.model,
            "ios_version": info.ios_version or usb_dev.ios_version,
            "wda_url": wda_url,
        }])
        logger.info("✅ Auto-registered device: %s -> %s", device_uid, wda_url)

    # ── Callback: USB device removed ─────────────────────────────────
    async def on_usb_device_removed(usb_dev: USBDevice):
        device_uid = usb_dev.udid[:12]
        if usb_dev.wifi_ip:
            wifi_url = f"http://{usb_dev.wifi_ip}:{WDA_PORT_ON_DEVICE}"
            logger.info("📴 USB unplugged for %s, switching to WiFi: %s", device_uid, wifi_url)
            device_map[device_uid] = wifi_url
            if executor:
                executor.devices[device_uid] = wifi_url
        else:
            logger.warning("📴 USB removed for %s with no WiFi IP — device will go offline", device_uid)

    usb_monitor = USBMonitor(
        on_device_ready=on_usb_device_ready,
        on_device_removed=on_usb_device_removed,
    )

    token = await obtain_token(config)
    logger.info("Obtained JWT token from server")

    try:
        await ws_client.connect(token)

        # Register statically-configured devices
        static_info = []
        for dev in config.devices:
            info = await collect_device_info(dev.wda_url, dev.device_uid)
            static_info.append({
                "device_uid": info.device_uid,
                "model": info.model,
                "ios_version": info.ios_version,
                "wda_url": dev.wda_url,
            })
            device_map[dev.device_uid] = dev.wda_url

        if static_info:
            await register_devices(static_info)
            logger.info("Registered %d static device(s)", len(static_info))

        await heartbeat.start()

        executor = CommandExecutor(device_map, ws_client.send_message)
        ws_client.register_handler("command.dispatch", executor.handle_command_dispatch)
        ws_client.register_handler("command.cancel", executor.handle_command_cancel)
        logger.info("CommandExecutor ready for %d device(s)", len(device_map))

        # Start USB auto-detection
        await usb_monitor.start()

        async def handle_config_update(message: dict) -> None:
            payload = message.get("payload", {})
            configs: dict = payload.get("configs", {})
            if not configs:
                return
            logger.info("Config update received: %s", list(configs.keys()))
            if "heartbeat_interval" in configs:
                new_interval = int(configs["heartbeat_interval"])
                heartbeat.update_interval(new_interval)

        ws_client.register_handler("config.update", handle_config_update)

        stop_event = asyncio.Event()

        def _signal_handler():
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass

        await stop_event.wait()

    except KeyboardInterrupt:
        pass
    finally:
        await usb_monitor.stop()
        await heartbeat.stop()
        await ws_client.disconnect()
        logger.info("Agent shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
