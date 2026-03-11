"""
App Store 智能登录脚本 (状态机模式)
根据当前页面状态自动判断下一步操作，不会重启 App Store。

可作为独立脚本运行，也可通过远程下发（PythonScriptRunner）执行。

独立运行:
    1. 修改下方 APPLE_ID 和 APPLE_PASSWORD
    2. 确保 WDA 在 iPad 上运行，且端口转发已开启
    3. 运行: python appstore_login.py

远程下发时, params 应包含:
    - apple_id: Apple ID 邮箱
    - apple_password: Apple ID 密码
"""
import asyncio
import base64
import logging

logger = logging.getLogger("appstore_login")

WDA_URL = "http://localhost:8100"
APPLE_ID = "jwkhjbfer661@outlook.com"
APPLE_PASSWORD = "Hlzhx1212"


async def save_screenshot(driver, filename):
    screenshot_b64 = await driver.screenshot()
    with open(filename, "wb") as f:
        f.write(base64.b64decode(screenshot_b64))
    logger.info("Screenshot: %s", filename)


async def tap_coord(driver, x, y):
    actions = {
        "actions": [{
            "type": "pointer", "id": "finger1",
            "parameters": {"pointerType": "touch"},
            "actions": [
                {"type": "pointerMove", "duration": 0, "x": x, "y": y},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": 100},
                {"type": "pointerUp", "button": 0},
            ],
        }]
    }
    await driver._request("POST", f"/session/{driver._session_id}/actions", json=actions)


async def has_element(driver, using, value):
    try:
        elem = await driver.find_element(using, value)
        return elem
    except Exception:
        return None


async def tap_element(driver, elem):
    eid = elem.get("ELEMENT") or list(elem.values())[0]
    await driver.tap_element(eid)
    return eid


async def type_into(driver, elem, text):
    eid = elem.get("ELEMENT") or list(elem.values())[0]
    await driver.tap_element(eid)
    await asyncio.sleep(0.3)
    await driver.type_text(eid, text)


async def detect_state(driver):
    """Detect current page state by checking for key elements."""

    e = await has_element(driver, "name", "不升级")
    if e:
        return "security_popup", e

    e = await has_element(driver, "name", "其他选项")
    if e:
        return "2fa_options", e

    e = await has_element(driver, "class name", "XCUIElementTypeSecureTextField")
    if e:
        return "password_screen", e

    e = await has_element(driver, "name", "username-field")
    if e:
        return "email_screen", e

    e = await has_element(driver, "name", "完成")
    if e:
        sign_in = await has_element(driver, "name", "AppStore.account.signIn")
        if sign_in:
            return "account_popup", sign_in
        return "logged_in", e

    e = await has_element(driver, "name", "AppStore.account.signIn")
    if e:
        return "account_popup", e

    e = await has_element(driver, "name", "AppStore.accountButton")
    if e:
        return "main_page", e

    e = await has_element(driver, "name", "continue-button")
    if e:
        return "loading", e

    return "unknown", None


async def run(driver, params):
    """Entry point for remote execution via PythonScriptRunner.

    Args:
        driver: WDADriver instance (session already created by runner)
        params: dict with optional keys 'apple_id' and 'apple_password'
    """
    apple_id = params.get("apple_id", APPLE_ID)
    apple_password = params.get("apple_password", APPLE_PASSWORD)

    logger.info("Starting App Store login for %s", apple_id)

    source = await driver.get_page_source()
    if "com.apple.AppStore" not in source and "AppStore" not in source:
        logger.info("App Store not in foreground, launching...")
        await driver.launch_app("com.apple.AppStore")
        await asyncio.sleep(3)

    MAX_ITERATIONS = 15
    for iteration in range(MAX_ITERATIONS):
        logger.info("=" * 50)
        logger.info("Iteration %d: Detecting state...", iteration + 1)

        state, elem = await detect_state(driver)
        logger.info("Current state: %s", state)

        if state == "main_page":
            logger.info("Action: Tap account button")
            await tap_element(driver, elem)
            await asyncio.sleep(3)

        elif state == "account_popup":
            logger.info("Action: Tap 'Sign in with Apple Account'")
            await tap_element(driver, elem)
            await asyncio.sleep(4)

        elif state == "email_screen":
            logger.info("Action: Enter Apple ID and tap Continue")
            await type_into(driver, elem, apple_id)
            await asyncio.sleep(1)
            cont = await has_element(driver, "name", "continue-button")
            if cont:
                await tap_element(driver, cont)
            await asyncio.sleep(5)

        elif state == "password_screen":
            logger.info("Action: Enter password and tap Continue")
            await type_into(driver, elem, apple_password)
            await asyncio.sleep(1)
            cont = await has_element(driver, "name", "continue-button")
            if cont:
                await tap_element(driver, cont)
            logger.info("Waiting for server response...")
            await asyncio.sleep(10)

        elif state == "2fa_options":
            logger.info("Action: Tap '其他选项'")
            await tap_element(driver, elem)
            await asyncio.sleep(5)

        elif state == "security_popup":
            logger.info("Action: Tap '不升级'")
            await tap_element(driver, elem)
            await asyncio.sleep(5)

        elif state == "logged_in":
            logger.info("Action: Already logged in! Tap '完成' to dismiss")
            await tap_element(driver, elem)
            await asyncio.sleep(2)
            logger.info("Login successful!")
            return

        elif state == "loading":
            logger.info("Page is loading, waiting...")
            await asyncio.sleep(5)

        elif state == "unknown":
            logger.warning("Unknown state, waiting...")
            source = await driver.get_page_source()
            if "AppStore.account.signIn" not in source and "username-field" not in source:
                logger.info("Might be logged in already!")
                return
            await asyncio.sleep(3)

    logger.info("Reached max iterations, login flow finished")


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from client.src.wda_driver import WDADriver

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    async def main():
        driver = WDADriver(WDA_URL, "test-ipad")
        if not await driver.health_check():
            logger.error("WDA not reachable! Check port forwarding.")
            return

        logger.info("Connecting to current screen...")
        try:
            data = await driver._request("POST", "/session", json={
                "capabilities": {"alwaysMatch": {}}
            })
            driver._session_id = data.get("sessionId") or data.get("value", {}).get("sessionId")
        except Exception:
            driver._session_id = await driver.create_session("com.apple.AppStore")
        logger.info("Session: %s", driver._session_id)

        await run(driver, {"apple_id": APPLE_ID, "apple_password": APPLE_PASSWORD})

        await save_screenshot(driver, "final_result.png")
        logger.info("Done! Check final_result.png")

    asyncio.run(main())
