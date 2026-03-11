from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Optional

from .wda_driver import (
    ElementNotFoundError,
    WDAConnectionError,
    WDADriver,
    WDAError,
)

logger = logging.getLogger(__name__)


class ScriptTimeoutError(Exception):
    pass


class StepTimeoutError(Exception):
    pass


class ScriptResult:
    def __init__(self) -> None:
        self.success = False
        self.stdout = ""
        self.stderr = ""
        self.screenshots: list[str] = []
        self.download_count = 0
        self.duration_seconds = 0.0
        self.steps_completed = 0
        self.total_steps = 0
        self.error_code: Optional[str] = None
        self.error_message: Optional[str] = None
        self.failed_step_index: Optional[int] = None


class ScriptRunner:
    """Execute JSON automation scripts via WDA driver."""

    def __init__(self, driver: WDADriver) -> None:
        self.driver = driver
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    async def execute(
        self,
        steps: list[dict],
        params: dict | None = None,
        global_timeout: int = 300,
        progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> ScriptResult:
        """Execute a list of script steps."""
        result = ScriptResult()
        result.total_steps = len(steps)
        start_time = time.monotonic()
        self._cancelled = False

        try:
            await self.driver.create_session()
        except Exception as e:
            result.error_code = "WDA_UNREACHABLE"
            result.error_message = str(e)
            return result

        try:
            for i, step in enumerate(steps):
                if self._cancelled:
                    result.error_code = "CANCELLED"
                    result.error_message = "Script execution was cancelled"
                    return result

                elapsed = time.monotonic() - start_time
                if elapsed > global_timeout:
                    raise ScriptTimeoutError(
                        f"Global timeout ({global_timeout}s) exceeded at step {i}"
                    )

                step_timeout = step.get("timeout", 30)
                action = step.get("action", "")
                target = step.get("target", "")
                step_params = step.get("params", {})

                if params:
                    target = self._substitute(target, params)
                    step_params = {
                        k: self._substitute(v, params) if isinstance(v, str) else v
                        for k, v in step_params.items()
                    }

                try:
                    await asyncio.wait_for(
                        self._execute_step(action, target, step_params),
                        timeout=step_timeout,
                    )
                except asyncio.TimeoutError:
                    raise StepTimeoutError(
                        f"Step {i} ({action}) timed out after {step_timeout}s"
                    )

                result.steps_completed = i + 1
                if progress_callback:
                    await progress_callback(i + 1, len(steps))

            result.success = True
            result.stdout = f"All {len(steps)} steps completed successfully"

        except ScriptTimeoutError as e:
            result.error_code = "TASK_TIMEOUT"
            result.error_message = str(e)
        except StepTimeoutError as e:
            result.error_code = "STEP_TIMEOUT"
            result.error_message = str(e)
            result.failed_step_index = result.steps_completed
        except ElementNotFoundError as e:
            result.error_code = "ELEMENT_NOT_FOUND"
            result.error_message = str(e)
            result.failed_step_index = result.steps_completed
        except WDAConnectionError as e:
            result.error_code = "WDA_UNREACHABLE"
            result.error_message = str(e)
        except WDAError as e:
            result.error_code = "WDA_ERROR"
            result.error_message = str(e)
            result.failed_step_index = result.steps_completed
        except Exception as e:
            result.error_code = "UNKNOWN_ERROR"
            result.error_message = str(e)
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

    async def _execute_step(
        self, action: str, target: str, params: dict
    ) -> None:
        """Execute a single script step."""
        if action == "launch_app":
            bundle_id = params.get("bundle_id") or target
            await self.driver.launch_app(bundle_id)

        elif action == "tap":
            element = await self.driver.find_element("xpath", target)
            elem_id = element.get("ELEMENT") or element.get(
                "element-6066-11e4-a52e-4f735466cecf"
            )
            await self.driver.tap_element(elem_id)

        elif action == "type":
            element = await self.driver.find_element("xpath", target)
            elem_id = element.get("ELEMENT") or element.get(
                "element-6066-11e4-a52e-4f735466cecf"
            )
            text = params.get("text", "")
            await self.driver.type_text(elem_id, text)

        elif action == "swipe":
            direction = params.get("direction", "up")
            if direction == "up":
                await self.driver.scroll_down()
            elif direction == "down":
                await self.driver.scroll_up()

        elif action == "wait":
            seconds = params.get("seconds", 1)
            await asyncio.sleep(seconds)

        elif action == "screenshot":
            await self.driver.screenshot()

        elif action == "back":
            size = await self.driver.get_window_size()
            h = size.get("height", 812)
            await self.driver.swipe(
                5, h // 2, size.get("width", 375) // 2, h // 2, 0.3
            )

        elif action == "home":
            await self.driver.press_home()

        elif action == "scroll":
            direction = params.get("direction", "down")
            if direction == "down":
                await self.driver.scroll_down()
            else:
                await self.driver.scroll_up()

        elif action == "find_element":
            await self.driver.find_element("xpath", target)

        elif action == "assert_exists":
            await self.driver.find_element("xpath", target)

        elif action == "assert_not_exists":
            try:
                await self.driver.find_element("xpath", target)
                raise WDAError(
                    f"Element should not exist but was found: {target}"
                )
            except ElementNotFoundError:
                pass

        elif action == "search":
            element = await self.driver.find_element("xpath", target)
            elem_id = element.get("ELEMENT") or element.get(
                "element-6066-11e4-a52e-4f735466cecf"
            )
            await self.driver.type_text(elem_id, params.get("text", ""))

        else:
            logger.warning("Unknown action: %s", action)

    @staticmethod
    def _substitute(text: str, params: dict) -> str:
        """Replace {{key}} placeholders with param values."""
        for key, value in params.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
        return text
