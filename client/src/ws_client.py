from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from .config import AgentConfig

logger = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class AgentWSClient:
    """WebSocket client that connects to the server, authenticates,
    registers devices, maintains a heartbeat, and routes incoming messages."""

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._ws: ClientConnection | None = None
        self._handlers: dict[str, MessageHandler] = {}
        self._running = False
        self._receive_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._reconnect_attempts = 0

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._ws.close_code is None

    @property
    def machine_id(self) -> str:
        return self._config.machine_id

    def register_handler(self, msg_type: str, handler: MessageHandler) -> None:
        self._handlers[msg_type] = handler

    async def connect(self, token: str) -> None:
        """Connect to the server WebSocket endpoint and start the receive loop.

        Registration and heartbeat are handled externally by main.py to avoid
        duplicate messages with conflicting formats.
        """
        self._running = True
        self._token = token
        url = f"{self._config.server_url}/{self._config.machine_id}?token={token}"
        logger.info("Connecting to %s", self._config.server_url)
        try:
            self._ws = await websockets.connect(url)
            self._reconnect_attempts = 0
            logger.info("WebSocket connected")

            self._receive_task = asyncio.create_task(self._receive_loop())
        except Exception:
            logger.exception("Failed to connect")
            if self._running:
                asyncio.create_task(self._reconnect_loop())

    async def disconnect(self) -> None:
        """Gracefully close the connection and cancel background tasks."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._receive_task:
            self._receive_task.cancel()
            self._receive_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("Disconnected")

    async def send_message(self, message: dict[str, Any]) -> None:
        if not self.is_connected:
            raise ConnectionError("WebSocket is not connected")
        payload = json.dumps(message)
        await self._ws.send(payload)  # type: ignore[union-attr]
        logger.debug("Sent: %s", message.get("type", "unknown"))

    async def _register_devices(self) -> None:
        for dev in self._config.devices:
            await self.send_message({
                "type": "device.register",
                "device_uid": dev.device_uid,
                "wda_url": dev.wda_url,
                "name": dev.name,
            })
        logger.info("Registered %d device(s)", len(self._config.devices))

    async def _heartbeat_loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self._config.heartbeat_interval)
                if self.is_connected:
                    await self.send_message({
                        "type": "heartbeat",
                        "machine_id": self._config.machine_id,
                        "timestamp": time.time(),
                    })
        except asyncio.CancelledError:
            pass

    async def _receive_loop(self) -> None:
        try:
            while self._running and self._ws:
                raw = await self._ws.recv()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message, ignoring")
                    continue

                msg_type = message.get("type", "")
                logger.debug("Received: %s", msg_type)
                handler = self._handlers.get(msg_type)
                if handler:
                    try:
                        await handler(message)
                    except Exception:
                        logger.exception("Handler error for %s", msg_type)
                else:
                    logger.warning("No handler for message type: %s", msg_type)
        except websockets.ConnectionClosed:
            logger.warning("Connection closed by server")
        except asyncio.CancelledError:
            return

        if self._running:
            asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        max_attempts = self._config.max_reconnect_attempts
        while self._running:
            if max_attempts > 0 and self._reconnect_attempts >= max_attempts:
                logger.error(
                    "Max reconnect attempts (%d) reached, giving up", max_attempts
                )
                self._running = False
                return

            self._reconnect_attempts += 1
            logger.info(
                "Reconnect attempt %d (max=%s)",
                self._reconnect_attempts,
                max_attempts or "unlimited",
            )
            await asyncio.sleep(self._config.reconnect_interval)
            try:
                await self.connect(self._token)
                return
            except Exception:
                logger.exception("Reconnect attempt %d failed", self._reconnect_attempts)
