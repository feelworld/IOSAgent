from __future__ import annotations

import asyncio
import logging
import time
import traceback
from typing import Optional

from .wda_driver import WDADriver

logger = logging.getLogger(__name__)


class PythonScriptResult:
    def __init__(self) -> None:
        self.success = False
        self.stdout = ""
        self.stderr = ""
        self.screenshots: list[str] = []
        self.download_count = 0
        self.duration_seconds = 0.0
        self.error_code: Optional[str] = None
        self.error_message: Optional[str] = None


class PythonScriptRunner:
    """Execute raw Python automation scripts that receive a WDA driver and params.

    The Python code must define an ``async def run(driver, params)`` entry point.
    """

    def __init__(self, driver: WDADriver) -> None:
        self.driver = driver
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    async def execute(
        self,
        python_code: str,
        params: dict | None = None,
        global_timeout: int = 300,
    ) -> PythonScriptResult:
        result = PythonScriptResult()
        start_time = time.monotonic()

        try:
            await self.driver.create_session()
        except Exception as e:
            result.error_code = "WDA_UNREACHABLE"
            result.error_message = str(e)
            return result

        namespace: dict = {
            "driver": self.driver,
            "params": params or {},
            "asyncio": asyncio,
            "logger": logging.getLogger("python_script"),
            "result": result,
        }

        try:
            exec(compile(python_code, "<remote_script>", "exec"), namespace)

            run_fn = namespace.get("run")
            if run_fn is None or not asyncio.iscoroutinefunction(run_fn):
                raise ValueError(
                    "Python script must define 'async def run(driver, params)'"
                )

            await asyncio.wait_for(
                run_fn(self.driver, params or {}),
                timeout=global_timeout,
            )

            result.success = True
            if not result.stdout:
                result.stdout = "Python script executed successfully"

        except asyncio.TimeoutError:
            result.error_code = "TASK_TIMEOUT"
            result.error_message = f"Script timed out after {global_timeout}s"
        except asyncio.CancelledError:
            result.error_code = "CANCELLED"
            result.error_message = "Script execution was cancelled"
        except Exception as e:
            result.error_code = "SCRIPT_ERROR"
            result.error_message = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        finally:
            result.duration_seconds = round(time.monotonic() - start_time, 2)

        if not result.success:
            try:
                screenshot = await self.driver.screenshot()
                if screenshot:
                    result.screenshots.append(screenshot)
            except Exception:
                pass

        return result
