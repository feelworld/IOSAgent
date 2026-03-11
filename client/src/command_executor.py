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

        for uid, url in devices.items():
            self._drivers[uid] = WDADriver(url, uid)

    async def handle_command_dispatch(self, message: dict) -> None:
        """Handle command.dispatch message from server."""
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

        task = asyncio.create_task(
            self._execute_task(task_id, task_uid, device_uid, script, params, timeout)
        )
        self._running_tasks[task_id] = task

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

    async def _execute_task(
        self,
        task_id: str,
        task_uid: str,
        device_uid: str,
        script: dict,
        params: dict,
        timeout: int,
    ) -> None:
        driver = self._drivers[device_uid]
        script_type = script.get("script_type", "steps")

        try:
            if script_type == "python":
                await self._execute_python_task(
                    task_id, task_uid, device_uid, driver, script, params, timeout
                )
            else:
                await self._execute_steps_task(
                    task_id, task_uid, device_uid, driver, script, params, timeout
                )
        except asyncio.CancelledError:
            await self._send_error(
                task_id, task_uid, device_uid, "CANCELLED", "Task was cancelled"
            )
        except Exception as e:
            await self._send_error(
                task_id, task_uid, device_uid, "UNKNOWN_ERROR", str(e)
            )
        finally:
            self._runners.pop(task_id, None)
            self._running_tasks.pop(task_id, None)

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

    async def _execute_python_task(
        self, task_id: str, task_uid: str, device_uid: str,
        driver: WDADriver, script: dict, params: dict, timeout: int,
    ) -> None:
        python_code = script.get("python_code", "")
        if not python_code:
            await self._send_error(
                task_id, task_uid, device_uid,
                "INVALID_SCRIPT", "No python_code in script",
            )
            return

        await self._send_status(task_id, task_uid, device_uid, "running", 0, 0, 1)

        py_runner = PythonScriptRunner(driver)
        result = await py_runner.execute(python_code, params, timeout)
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
