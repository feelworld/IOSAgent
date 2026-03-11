import json
import logging

from fastapi import WebSocket, WebSocketDisconnect, Query

from server.src.services.auth_service import decode_token

logger = logging.getLogger(__name__)

admin_connections: dict[WebSocket, set[str]] = {}

DEFAULT_CHANNELS = {
    "device.status_changed",
    "device.heartbeat",
    "task.updated",
    "task.completed",
    "dashboard.stats",
    "alert",
}


async def admin_ws_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket endpoint for admin dashboard clients."""
    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    await websocket.accept()
    admin_connections[websocket] = set(DEFAULT_CHANNELS)
    logger.info(f"Admin client connected (total: {len(admin_connections)})")

    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type")

            if msg_type == "subscribe":
                channels = message.get("payload", {}).get("channels", [])
                admin_connections[websocket].update(channels)
            elif msg_type == "unsubscribe":
                channels = message.get("payload", {}).get("channels", [])
                admin_connections[websocket].difference_update(channels)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Admin WS error: {e}")
    finally:
        admin_connections.pop(websocket, None)
        logger.info(
            f"Admin client disconnected (remaining: {len(admin_connections)})"
        )


async def broadcast_to_admins(message: dict):
    """Broadcast a message to all subscribed admin clients."""
    msg_type = message.get("type", "")
    disconnected: list[WebSocket] = []
    for ws, channels in admin_connections.items():
        if msg_type in channels:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
    for ws in disconnected:
        admin_connections.pop(ws, None)
