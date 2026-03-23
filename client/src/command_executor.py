from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from .python_script_runner import PythonScriptRunner
from .script_runner import ScriptRunner
from .wda_driver import WDADriver

logger = logging.getLogger(__name__)

BATCH_WINDOW_SECONDS = 3.0


SESSION_KEEPALIVE_INTERVAL = 60.0


class CommandExecutor:
    """Receives commands from server, executes via script runner, reports results."""

    def __init__(
        self,
        devices: dict[str, str],
        send_fn: Callable[[dict], Awaitable[None]],
    ) -> None:
        self.devices = devices
        self.send_fn = send_fn
        self._drivers: dict[str, WDADriver] = {}
        self._runners: dict[str, ScriptRunner] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self.usb_monitor = None
        self._pending_batch: list[dict] = []
        self._batch_timer: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None

        for uid, url in devices.items():
            self._drivers[uid] = WDADriver(url, uid)

    def add_device(self, device_uid: str, wda_url: str) -> None:
        """Dynamically register a new device (e.g. USB-detected)."""
        self.devices[device_uid] = wda_url
        self._drivers[device_uid] = WDADriver(wda_url, device_uid)
        logger.info("CommandExecutor: added device %s -> %s", device_uid, wda_url)
        asyncio.ensure_future(self._precreate_session(device_uid))

    def update_device_url(self, device_uid: str, wda_url: str) -> None:
        """Update WDA URL for an existing device (e.g. after WDA restart)."""
        self.devices[device_uid] = wda_url
        self._drivers[device_uid] = WDADriver(wda_url, device_uid)
        asyncio.ensure_future(self._precreate_session(device_uid))

    async def _precreate_session(self, device_uid: str) -> None:
        """Pre-create a WDA session so it's ready when a script arrives."""
        driver = self._drivers.get(device_uid)
        if not driver:
            return
        for attempt in range(5):
            try:
                await driver.create_session("")
                logger.info("Pre-created WDA session for %s (attempt %d)",
                            device_uid, attempt + 1)
                break
            except Exception as e:
                logger.warning("Pre-create session failed for %s (attempt %d/5): %s",
                               device_uid, attempt + 1, e)
                if attempt < 4:
                    await asyncio.sleep(3)

        if not self._keepalive_task or self._keepalive_task.done():
            self._keepalive_task = asyncio.create_task(self._session_keepalive_loop())

    async def _session_keepalive_loop(self) -> None:
        """Periodically touch WDA to keep sessions alive."""
        while True:
            await asyncio.sleep(SESSION_KEEPALIVE_INTERVAL)
            for uid, driver in list(self._drivers.items()):
                if not driver._session_id:
                    continue
                try:
                    await driver.health_check()
                except Exception:
                    logger.warning("Session keepalive failed for %s, recreating...", uid)
                    try:
                        await driver.create_session("")
                        logger.info("Session recreated for %s", uid)
                    except Exception as e:
                        logger.error("Session recreate failed for %s: %s", uid, e)

    async def handle_command_dispatch(self, message: dict) -> None:
        """Queue incoming tasks and flush after a short batch window."""
        payload = message.get("payload", message)
        task_id = payload.get("task_id")
        task_uid = payload.get("task_uid", task_id)
        device_uid = payload.get("device_uid")
        script = payload.get("script", {})
        params = payload.get("params", {})
        timeout = payload.get("timeout_seconds", 300)

        if device_uid not in self._drivers:
            await self._send_error(
                task_id, task_uid, device_uid,
                "DEVICE_NOT_FOUND",
                f"Device {device_uid} not managed by this agent",
            )
            return

        self._pending_batch.append({
            "task_id": task_id, "task_uid": task_uid,
            "device_uid": device_uid, "script": script,
            "params": params, "timeout": timeout,
        })
        logger.info("Queued task %s for device %s (batch size=%d)",
                     task_id, device_uid, len(self._pending_batch))

        if self._batch_timer and not self._batch_timer.done():
            self._batch_timer.cancel()
        self._batch_timer = asyncio.create_task(self._flush_batch())

    async def _flush_batch(self) -> None:
        """Wait for batch window, then process all queued tasks."""
        await asyncio.sleep(BATCH_WINDOW_SECONDS)
        batch = list(self._pending_batch)
        self._pending_batch.clear()
        if not batch:
            return

        logger.info("=== Flushing batch of %d task(s) ===", len(batch))

        python_tasks = [t for t in batch if t["script"].get("script_type") == "python"]
        other_tasks = [t for t in batch if t["script"].get("script_type") != "python"]

        for t in other_tasks:
            task = asyncio.create_task(
                self._execute_task_single(t)
            )
            self._running_tasks[t["task_id"]] = task

        if python_tasks:
            task = asyncio.create_task(
                self._execute_python_batch(python_tasks)
            )
            for t in python_tasks:
                self._running_tasks[t["task_id"]] = task

    async def _execute_python_batch(self, tasks: list[dict]) -> None:
        """Run all scripts simultaneously. Sessions should already exist from pre-creation."""
        if self.usb_monitor:
            self.usb_monitor.active_tasks += len(tasks)

        try:
            # Ensure sessions exist (fast if pre-created, retry if expired)
            session_ok: dict[str, bool] = {}
            for t in tasks:
                device_uid = t["device_uid"]
                driver = self._drivers[device_uid]
                if driver._session_id:
                    ok = await driver.health_check()
                    if ok:
                        logger.info("Reusing pre-created session for %s", device_uid)
                        session_ok[t["task_id"]] = True
                        continue
                    logger.warning("Pre-created session stale for %s, recreating", device_uid)

                ok = False
                for attempt in range(3):
                    try:
                        await driver.create_session("")
                        logger.info("WDA session created for %s (attempt %d)",
                                    device_uid, attempt + 1)
                        ok = True
                        break
                    except Exception as e:
                        logger.warning("Session creation failed for %s (%d/3): %s",
                                       device_uid, attempt + 1, e)
                        if attempt < 2:
                            await asyncio.sleep(2)
                session_ok[t["task_id"]] = ok

            # Run all scripts concurrently
            async def _run_one(t: dict) -> None:
                tid = t["task_id"]
                tuid = t["task_uid"]
                duid = t["device_uid"]
                driver = self._drivers[duid]
                try:
                    if not session_ok.get(tid):
                        await self._send_error(
                            tid, tuid, duid,
                            "WDA_UNREACHABLE", "Could not create WDA session",
                        )
                        return
                    logger.info("Starting script execution for %s", duid)
                    await self._send_status(tid, tuid, duid, "running", 0, 0, 1)
                    py_runner = PythonScriptRunner(driver)
                    result = await py_runner.execute(
                        t["script"].get("python_code", ""), t["params"], t["timeout"],
                    )
                    await self._report_result(tid, tuid, duid, result)
                except asyncio.CancelledError:
                    await self._send_error(tid, tuid, duid, "CANCELLED", "Task was cancelled")
                except Exception as e:
                    await self._send_error(tid, tuid, duid, "UNKNOWN_ERROR", str(e))

            logger.info("=== Launching %d script(s) simultaneously ===", len(tasks))
            await asyncio.gather(*[_run_one(t) for t in tasks])

        finally:
            if self.usb_monitor:
                self.usb_monitor.active_tasks = max(
                    0, self.usb_monitor.active_tasks - len(tasks)
                )
            for t in tasks:
                self._runners.pop(t["task_id"], None)
                self._running_tasks.pop(t["task_id"], None)

    async def handle_command_cancel(self, message: dict) -> None:
        """Handle command.cancel message from server."""
        payload = message.get("payload", message)
        task_id = payload.get("task_id")
        runner = self._runners.get(task_id)
        if runner:
            runner.cancel()
            logger.info("Cancellation requested for task %s", task_id)

        atask = self._running_tasks.get(task_id)
        if atask and not atask.done():
            atask.cancel()

    async def _execute_task_single(self, t: dict) -> None:
        """Execute a single non-python task with standard lifecycle."""
        tid, tuid, duid = t["task_id"], t["task_uid"], t["device_uid"]
        driver = self._drivers[duid]
        if self.usb_monitor:
            self.usb_monitor.active_tasks += 1
        try:
            await self._execute_steps_task(
                tid, tuid, duid, driver, t["script"], t["params"], t["timeout"]
            )
        except asyncio.CancelledError:
            await self._send_error(tid, tuid, duid, "CANCELLED", "Task was cancelled")
        except Exception as e:
            await self._send_error(tid, tuid, duid, "UNKNOWN_ERROR", str(e))
        finally:
            if self.usb_monitor:
                self.usb_monitor.active_tasks = max(0, self.usb_monitor.active_tasks - 1)
            self._runners.pop(tid, None)
            self._running_tasks.pop(tid, None)

    async def _execute_steps_task(
        self, task_id: str, task_uid: str, device_uid: str,
        driver: WDADriver, script: dict, params: dict, timeout: int,
    ) -> None:
        runner = ScriptRunner(driver)
        self._runners[task_id] = runner
        steps = script.get("steps", [])

        await self._send_status(task_id, task_uid, device_uid, "running", 0, 0, len(steps))

        async def on_progress(completed: int, total: int) -> None:
            progress = int(completed / total * 100) if total > 0 else 0
            await self._send_status(
                task_id, task_uid, device_uid, "running", progress, completed, total
            )

        result = await runner.execute(steps, params, timeout, on_progress)
        await self._report_result(task_id, task_uid, device_uid, result)

    async def _report_result(
        self, task_id: str, task_uid: str, device_uid: str, result,
    ) -> None:
        if result.success:
            await self._send_result(
                task_id, task_uid, device_uid, "success",
                {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "screenshots": result.screenshots,
                    "download_count": getattr(result, "download_count", 0),
                    "duration_seconds": result.duration_seconds,
                },
            )
        else:
            await self._send_error(
                task_id, task_uid, device_uid,
                result.error_code or "UNKNOWN_ERROR",
                result.error_message or "Unknown error",
                getattr(result, "failed_step_index", None),
            )

    async def _send_status(
        self, task_id: str, task_uid: str, device_uid: str,
        status: str, progress: int, current_step: int, total_steps: int,
    ) -> None:
        await self.send_fn({
            "type": "task.status",
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "task_id": task_id,
                "task_uid": task_uid,
                "device_uid": device_uid,
                "status": status,
                "progress": progress,
                "current_step": current_step,
                "total_steps": total_steps,
            },
        })

    async def _send_result(
        self, task_id: str, task_uid: str, device_uid: str,
        status: str, result: dict,
    ) -> None:
        await self.send_fn({
            "type": "task.result",
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "task_id": task_id,
                "task_uid": task_uid,
                "device_uid": device_uid,
                "status": status,
                "result": result,
            },
        })

    async def _send_error(
        self, task_id: str, task_uid: str, device_uid: str,
        code: str, message: str, step_index: int | None = None,
    ) -> None:
        needs_intervention = code in (
            "APPSTORE_AUTH_REQUIRED",
            "APPLE_ID_BANNED",
        )
        await self.send_fn({
            "type": "task.error",
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "task_id": task_id,
                "task_uid": task_uid,
                "device_uid": device_uid,
                "status": "failed",
                "error": {
                    "code": code,
                    "message": message,
                    "step_index": step_index,
                    "needs_intervention": needs_intervention,
                },
            },
        })
