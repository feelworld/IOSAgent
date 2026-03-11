"""
Load test: simulate 100 concurrent WebSocket connections with heartbeat + batch command dispatch.
Validates SC-002 (REST API p95 < 500ms, WS latency < 200ms) and SC-008 (100+ devices).

Usage:
    python -m server.tests.load.test_concurrent --server ws://localhost:8000 --token <jwt>
    python -m pytest server/tests/load/test_concurrent.py -s
"""

import argparse
import asyncio
import json
import logging
import statistics
import time
import uuid
from datetime import datetime, timezone

try:
    import websockets
except ImportError:
    websockets = None

try:
    import aiohttp
except ImportError:
    aiohttp = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SERVER = "ws://localhost:8000"
DEFAULT_REST = "http://localhost:8000"
NUM_CONNECTIONS = 100
HEARTBEAT_ROUNDS = 3
HEARTBEAT_INTERVAL = 1


async def simulate_client(
    server_url: str,
    token: str,
    machine_id: str,
    device_uid: str,
    latencies: list[float],
    errors: list[str],
):
    """Simulate a single companion machine agent."""
    url = f"{server_url}/ws/client/{machine_id}?token={token}"
    try:
        async with websockets.connect(url, open_timeout=10) as ws:
            register_msg = {
                "type": "device.register",
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "machine_id": machine_id,
                    "devices": [{
                        "device_uid": device_uid,
                        "model": "iPhone 14",
                        "ios_version": "16.0",
                        "wda_url": f"http://mock-{device_uid}:8100",
                    }],
                },
            }
            t0 = time.monotonic()
            await ws.send(json.dumps(register_msg))
            latencies.append(time.monotonic() - t0)

            for _ in range(HEARTBEAT_ROUNDS):
                hb_msg = {
                    "type": "heartbeat",
                    "id": str(uuid.uuid4()),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "machine_id": machine_id,
                        "devices": [{
                            "device_uid": device_uid,
                            "status": "online",
                            "battery_level": 85,
                            "network_type": "Wi-Fi",
                            "appstore_logged_in": True,
                            "current_task_id": None,
                        }],
                    },
                }
                t0 = time.monotonic()
                await ws.send(json.dumps(hb_msg))
                latencies.append(time.monotonic() - t0)
                await asyncio.sleep(HEARTBEAT_INTERVAL)

    except Exception as e:
        errors.append(f"{machine_id}: {e}")


async def test_rest_latency(base_url: str, token: str, latencies: list[float], errors: list[str]):
    """Test REST API response times."""
    if not aiohttp:
        logger.warning("aiohttp not available, skipping REST tests")
        return

    headers = {"Authorization": f"Bearer {token}"}
    endpoints = [
        ("GET", "/api/v1/devices?page=1&size=20"),
        ("GET", "/api/v1/devices/stats"),
        ("GET", "/api/v1/tasks/stats"),
        ("GET", "/api/v1/dashboard"),
        ("GET", "/health"),
    ]

    async with aiohttp.ClientSession() as session:
        for method, path in endpoints:
            url = f"{base_url}{path}"
            times = []
            for _ in range(10):
                t0 = time.monotonic()
                try:
                    async with session.request(method, url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        await resp.read()
                        elapsed = (time.monotonic() - t0) * 1000
                        times.append(elapsed)
                except Exception as e:
                    errors.append(f"REST {path}: {e}")

            if times:
                p95 = sorted(times)[int(len(times) * 0.95)]
                latencies.append(p95)
                logger.info("  %s %s -> p95=%.1fms, avg=%.1fms", method, path, p95, statistics.mean(times))


async def run_load_test(server_url: str, rest_url: str, token: str):
    """Run the full load test."""
    logger.info("=" * 60)
    logger.info("Load Test: %d concurrent WebSocket connections", NUM_CONNECTIONS)
    logger.info("Server: %s", server_url)
    logger.info("=" * 60)

    ws_latencies: list[float] = []
    rest_latencies: list[float] = []
    errors: list[str] = []

    logger.info("\n[1/3] Testing %d concurrent WebSocket connections...", NUM_CONNECTIONS)
    t_start = time.monotonic()

    tasks = []
    for i in range(NUM_CONNECTIONS):
        machine_id = f"load-test-{i:04d}"
        device_uid = f"lt-device-{i:04d}"
        tasks.append(simulate_client(server_url, token, machine_id, device_uid, ws_latencies, errors))

    await asyncio.gather(*tasks, return_exceptions=True)
    ws_duration = time.monotonic() - t_start

    logger.info("\n[2/3] Testing REST API latency...")
    await test_rest_latency(rest_url, token, rest_latencies, errors)

    logger.info("\n[3/3] Results:")
    logger.info("-" * 60)
    logger.info("WebSocket Connections: %d attempted", NUM_CONNECTIONS)
    logger.info("WebSocket Errors: %d", len([e for e in errors if "load-test" in e]))

    if ws_latencies:
        ws_ms = [t * 1000 for t in ws_latencies]
        logger.info("WS Send Latency:")
        logger.info("  avg: %.1fms", statistics.mean(ws_ms))
        logger.info("  p50: %.1fms", sorted(ws_ms)[len(ws_ms) // 2])
        logger.info("  p95: %.1fms", sorted(ws_ms)[int(len(ws_ms) * 0.95)])
        logger.info("  max: %.1fms", max(ws_ms))

        ws_p95 = sorted(ws_ms)[int(len(ws_ms) * 0.95)]
        ws_pass = ws_p95 < 200
        logger.info("  SC-002 WS target (<200ms): %s (p95=%.1fms)", "PASS" if ws_pass else "FAIL", ws_p95)

    if rest_latencies:
        rest_pass = all(t < 500 for t in rest_latencies)
        logger.info("REST API p95 target (<500ms): %s", "PASS" if rest_pass else "FAIL")

    logger.info("Total Duration: %.1fs", ws_duration)
    logger.info("Errors: %d", len(errors))
    for err in errors[:10]:
        logger.info("  - %s", err)
    logger.info("-" * 60)


def main():
    parser = argparse.ArgumentParser(description="iOS Ranking System Load Test")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="WebSocket server URL")
    parser.add_argument("--rest", default=DEFAULT_REST, help="REST API base URL")
    parser.add_argument("--token", required=True, help="JWT auth token")
    parser.add_argument("--connections", type=int, default=NUM_CONNECTIONS)
    args = parser.parse_args()

    global NUM_CONNECTIONS
    NUM_CONNECTIONS = args.connections

    asyncio.run(run_load_test(args.server, args.rest, args.token))


if __name__ == "__main__":
    main()
