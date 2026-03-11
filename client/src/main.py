import asyncio
import logging
import signal
import uuid
from datetime import datetime, timezone

import aiohttp

from client.src.command_executor import CommandExecutor
from client.src.config import AgentConfig, load_config
from client.src.device_info import collect_device_info
from client.src.heartbeat import HeartbeatSender
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
        "Agent starting: machine_id=%s, devices=%d",
        config.machine_id,
        len(config.devices),
    )

    ws_client = AgentWSClient(config)
    heartbeat = HeartbeatSender(
        machine_id=config.machine_id,
        devices=config.devices,
        send_fn=ws_client.send_message,
        interval=config.heartbeat_interval,
    )

    token = await obtain_token(config)
    logger.info("Obtained JWT token from server")

    try:
        await ws_client.connect(token)

        devices_info = []
        for dev in config.devices:
            info = await collect_device_info(dev.wda_url, dev.device_uid)
            devices_info.append({
                "device_uid": info.device_uid,
                "model": info.model,
                "ios_version": info.ios_version,
                "wda_url": dev.wda_url,
            })

        register_msg = {
            "type": "device.register",
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "machine_id": config.machine_id,
                "devices": devices_info,
            },
        }
        await ws_client.send_message(register_msg)
        logger.info("Registered %d devices", len(devices_info))

        await heartbeat.start()

        # Build device_uid -> wda_url mapping for command execution
        device_map = {dev.device_uid: dev.wda_url for dev in config.devices}
        executor = CommandExecutor(device_map, ws_client.send_message)
        ws_client.register_handler("command.dispatch", executor.handle_command_dispatch)
        ws_client.register_handler("command.cancel", executor.handle_command_cancel)
        logger.info("CommandExecutor ready for %d device(s)", len(device_map))

        async def handle_config_update(message: dict) -> None:
            payload = message.get("payload", {})
            configs: dict = payload.get("configs", {})
            if not configs:
                logger.warning("config.update received with empty configs")
                return

            logger.info("Config update received: %s", list(configs.keys()))

            if "heartbeat_interval" in configs:
                new_interval = int(configs["heartbeat_interval"])
                heartbeat.update_interval(new_interval)
                logger.info("heartbeat_interval updated to %d", new_interval)

            for key, value in configs.items():
                if key != "heartbeat_interval":
                    logger.info("Config changed: %s = %s", key, value)

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
        await heartbeat.stop()
        await ws_client.disconnect()
        logger.info("Agent shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
