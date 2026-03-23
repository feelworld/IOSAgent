from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


class WDAError(Exception):
    """Base WDA error."""


class ElementNotFoundError(WDAError):
    pass


class WDAConnectionError(WDAError):
    pass


class AppCrashError(WDAError):
    pass


class WDADriver:
    """HTTP client wrapping WDA endpoints for iOS device automation."""

    def __init__(self, wda_url: str, device_uid: str) -> None:
        self.wda_url = wda_url.rstrip("/")
        self.device_uid = device_uid
        self._session_id: Optional[str] = None
        self._timeout = aiohttp.ClientTimeout(total=15)

    async def _request(self, method: str, path: str, json: Any = None) -> dict:
        """Make HTTP request to WDA. Each call uses a fresh connection."""
        url = f"{self.wda_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.request(method, url, json=json) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        raise WDAError(f"WDA returned {resp.status}: {data}")
                    return data
        except aiohttp.ClientConnectorError as e:
            raise WDAConnectionError(
                f"Cannot connect to WDA at {self.wda_url}: {e}"
            ) from e
        except asyncio.TimeoutError:
            raise WDAError(f"WDA request timed out after 15s: {method} {path}")
        except aiohttp.ClientError as e:
            raise WDAError(f"WDA request failed ({type(e).__name__}): {e}") from e

    async def create_session(
        self, bundle_id: str = "com.apple.Preferences"
    ) -> str:
        """Create a new WDA session."""
        caps = {}
        if bundle_id:
            caps["bundleId"] = bundle_id
        data = await self._request(
            "POST",
            "/session",
            json={
                "capabilities": {
                    "alwaysMatch": caps,
                }
            },
        )
        self._session_id = data.get("sessionId") or data.get("value", {}).get(
            "sessionId"
        )
        return self._session_id

    async def health_check(self) -> bool:
        """Check if WDA is responsive."""
        try:
            await self._request("GET", "/status")
            return True
        except Exception:
            return False

    async def launch_app(self, bundle_id: str) -> None:
        """Launch an app by bundle ID."""
        await self._request(
            "POST",
            f"/session/{self._session_id}/wda/apps/launch",
            json={"bundleId": bundle_id},
        )

    async def find_element(self, using: str, value: str) -> dict:
        """Find an element. using: 'xpath', 'class name', 'accessibility id', etc."""
        data = await self._request(
            "POST",
            f"/session/{self._session_id}/element",
            json={"using": using, "value": value},
        )
        element = data.get("value", {})
        if not element or "error" in element:
            raise ElementNotFoundError(f"Element not found: {using}={value}")
        return element

    async def tap_element(self, element_id: str) -> None:
        """Tap on an element by its ID."""
        await self._request(
            "POST",
            f"/session/{self._session_id}/element/{element_id}/click",
        )

    async def type_text(self, element_id: str, text: str) -> None:
        """Type text into an element."""
        await self._request(
            "POST",
            f"/session/{self._session_id}/element/{element_id}/value",
            json={"value": list(text)},
        )

    async def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
    ) -> None:
        """Perform a swipe gesture."""
        await self._request(
            "POST",
            f"/session/{self._session_id}/wda/dragfromtoforduration",
            json={
                "fromX": start_x,
                "fromY": start_y,
                "toX": end_x,
                "toY": end_y,
                "duration": duration,
            },
        )

    async def screenshot(self) -> str:
        """Take a screenshot, returns base64 encoded PNG."""
        data = await self._request(
            "GET", f"/session/{self._session_id}/screenshot"
        )
        return data.get("value", "")

    async def get_page_source(self) -> str:
        """Get the current page source XML."""
        data = await self._request(
            "GET", f"/session/{self._session_id}/source"
        )
        return data.get("value", "")

    async def press_home(self) -> None:
        """Press the home button."""
        await self._request("POST", "/wda/homescreen")

    async def get_window_size(self) -> dict:
        """Get the window size."""
        data = await self._request(
            "GET", f"/session/{self._session_id}/window/size"
        )
        return data.get("value", {})

    async def scroll_down(self) -> None:
        """Scroll down on the current view."""
        size = await self.get_window_size()
        w, h = size.get("width", 375), size.get("height", 812)
        await self.swipe(w // 2, h * 3 // 4, w // 2, h // 4, 0.5)

    async def scroll_up(self) -> None:
        """Scroll up on the current view."""
        size = await self.get_window_size()
        w, h = size.get("width", 375), size.get("height", 812)
        await self.swipe(w // 2, h // 4, w // 2, h * 3 // 4, 0.5)
