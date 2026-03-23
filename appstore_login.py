"""
App Store 智能登录脚本 (状态机模式)
根据 iOS 版本自动选择登录流程:
  - iOS 14.x: 系统弹窗式登录 (Apple ID + 密码同屏, 点"登录")
  - iOS 15+:  全屏登录页 (先输邮箱点继续, 再输密码点继续)

远程下发时, params 由系统自动注入:
    - apple_id / apple_password: 账号密码
    - ios_version: 设备 iOS 版本 (如 "14.2", "16.1")

error_code 约定:
    - APPLE_ID_BANNED: 账号被封/禁用, 触发服务端自动切换
"""
import asyncio
import logging

logger = logging.getLogger("appstore_login")

BANNED_KEYWORDS = [
    "已被禁用", "has been disabled",
    "已被锁定", "has been locked",
    "无法登录", "cannot sign in",
    "此 Apple ID 已被停用", "This Apple ID has been disabled",
]


# ─── Helpers ──────────────────────────────────────────────────

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
        return await driver.find_element(using, value)
    except Exception:
        return None


async def find_elements(driver, using, value):
    try:
        data = await driver._request(
            "POST", f"/session/{driver._session_id}/elements",
            json={"using": using, "value": value},
        )
        return data.get("value", [])
    except Exception:
        return []


async def tap_element(driver, elem):
    eid = elem.get("ELEMENT") or list(elem.values())[0]
    await driver.tap_element(eid)
    return eid


async def type_into(driver, elem, text):
    eid = elem.get("ELEMENT") or list(elem.values())[0]
    await driver.tap_element(eid)
    await asyncio.sleep(0.3)
    await driver.type_text(eid, text)


async def clear_and_type(driver, elem, text):
    """Clear field then type text."""
    eid = elem.get("ELEMENT") or list(elem.values())[0]
    await driver.tap_element(eid)
    await asyncio.sleep(0.3)
    try:
        await driver._request(
            "POST", f"/session/{driver._session_id}/element/{eid}/clear",
        )
    except Exception:
        pass
    await asyncio.sleep(0.2)
    await driver.type_text(eid, text)


async def check_banned(driver):
    try:
        source = await driver.get_page_source()
        for kw in BANNED_KEYWORDS:
            if kw in source:
                return True
    except Exception:
        pass
    return False


async def get_source_safe(driver):
    try:
        return await driver.get_page_source()
    except Exception:
        return ""


def parse_major_version(version_str):
    """'14.2' -> 14, '15.1.1' -> 15, '' -> 0"""
    try:
        return int(version_str.split(".")[0])
    except (ValueError, IndexError):
        return 0


# ─── iOS 14.x Login Flow (Alert-style dialog) ─────────────────

async def login_ios14(driver, apple_id, apple_password):
    """iOS 14 App Store login: system alert with both fields on one screen."""
    logger.info("[iOS14] Opening App Store...")
    try:
        await driver.create_session("com.apple.AppStore")
    except Exception:
        await driver.launch_app("com.apple.AppStore")
    await asyncio.sleep(5)

    for iteration in range(25):
        logger.info("--- [iOS14] Iteration %d ---", iteration + 1)

        if await check_banned(driver):
            raise BannedAccountError(f"Apple ID {apple_id} is banned or disabled")

        source = await get_source_safe(driver)

        # ── Priority 1: Login alert with input fields (must check BEFORE "完成") ──
        text_fields = await find_elements(driver, "class name", "XCUIElementTypeTextField")
        secure_fields = await find_elements(driver, "class name", "XCUIElementTypeSecureTextField")

        if secure_fields:
            logger.info("[iOS14] Login dialog detected (text_fields=%d, secure_fields=%d)",
                        len(text_fields), len(secure_fields))

            if text_fields:
                logger.info("[iOS14] Entering Apple ID: %s", apple_id)
                await clear_and_type(driver, text_fields[0], apple_id)
                await asyncio.sleep(0.5)

            logger.info("[iOS14] Entering password")
            await clear_and_type(driver, secure_fields[0], apple_password)
            await asyncio.sleep(0.5)

            sign_btn = None
            for name in ["登录", "Sign In", "好", "OK"]:
                sign_btn = await has_element(driver, "name", name)
                if sign_btn:
                    break
            if sign_btn:
                logger.info("[iOS14] Tapping login button")
                await tap_element(driver, sign_btn)
            else:
                logger.warning("[iOS14] Login button not found, scanning all buttons...")
                buttons = await find_elements(driver, "class name", "XCUIElementTypeButton")
                for btn in buttons:
                    bid = btn.get("ELEMENT") or list(btn.values())[0]
                    try:
                        a = await driver._request(
                            "GET", f"/session/{driver._session_id}/element/{bid}/attribute/label",
                        )
                        lbl = a.get("value", "")
                        if lbl:
                            logger.info("[iOS14] Button: '%s'", lbl)
                        if lbl in ("登录", "Sign In", "好", "OK"):
                            await driver.tap_element(bid)
                            logger.info("[iOS14] Tapped button: '%s'", lbl)
                            break
                    except Exception:
                        pass

            logger.info("[iOS14] Waiting for login response...")
            await asyncio.sleep(10)
            continue

        # ── Priority 2: Security / 2FA popups ──
        e = await has_element(driver, "name", "不升级")
        if e:
            logger.info("[iOS14] Tapping '不升级'")
            await tap_element(driver, e)
            await asyncio.sleep(3)
            continue

        e = await has_element(driver, "name", "其他选项")
        if e:
            logger.info("[iOS14] Tapping '其他选项'")
            await tap_element(driver, e)
            await asyncio.sleep(3)
            continue

        e = await has_element(driver, "name", "不是")
        if not e:
            e = await has_element(driver, "name", "Don\u2019t Upgrade")
        if e:
            logger.info("[iOS14] Tapping dismiss button")
            await tap_element(driver, e)
            await asyncio.sleep(3)
            continue

        # ── Priority 3: Account page (has "完成" button) ──
        done_btn = await has_element(driver, "name", "完成")
        if done_btn:
            if "退出登录" in source or "Sign Out" in source:
                logger.info("[iOS14] Confirmed logged in (found sign-out), tapping '完成'")
                await tap_element(driver, done_btn)
                return

            has_sign_in = False
            for sign_name in ["AppStore.account.signIn", "登录", "Sign In", "登入"]:
                el = await has_element(driver, "name", sign_name)
                if el:
                    has_sign_in = True
                    logger.info("[iOS14] Account page, tapping sign-in: '%s'", sign_name)
                    await tap_element(driver, el)
                    await asyncio.sleep(5)
                    break

            if not has_sign_in:
                logger.info("[iOS14] Account page, scanning buttons for sign-in...")
                buttons = await find_elements(driver, "class name", "XCUIElementTypeButton")
                for btn in buttons[:15]:
                    bid = btn.get("ELEMENT") or list(btn.values())[0]
                    try:
                        a = await driver._request(
                            "GET", f"/session/{driver._session_id}/element/{bid}/attribute/label",
                        )
                        lbl = a.get("value", "")
                        if lbl:
                            logger.info("[iOS14]   button: '%s'", lbl)
                        if lbl in ("登录", "Sign In", "登入"):
                            has_sign_in = True
                            await driver.tap_element(bid)
                            logger.info("[iOS14] Tapped sign-in: '%s'", lbl)
                            await asyncio.sleep(5)
                            break
                    except Exception:
                        pass

            if not has_sign_in:
                logger.warning("[iOS14] Account page but no sign-in found, source[:400]=%s", source[:400])
                await asyncio.sleep(3)
            continue

        # ── Priority 4: Main page → tap profile icon ──
        if "Today" in source or "今天" in source or "游戏" in source or "Games" in source:
            size = await driver.get_window_size()
            w = size.get("width", 375)
            coords = [(w - 30, 52), (w - 30, 45), (w - 25, 88), (w - 30, 70)]
            cx, cy = coords[iteration % len(coords)]
            logger.info("[iOS14] Main page, tapping profile icon at (%d, %d)", cx, cy)
            await tap_coord(driver, cx, cy)
            await asyncio.sleep(3)
            continue

        # ── Unknown state ──
        logger.warning("[iOS14] Unknown state, source[:400]=%s", source[:400])
        await asyncio.sleep(4)

    logger.info("[iOS14] Max iterations reached")


# ─── iOS 15+ Login Flow (Full-screen pages) ───────────────────

async def login_ios15(driver, apple_id, apple_password):
    """iOS 15+ App Store login: full-screen Apple ID sign-in pages."""
    logger.info("[iOS15+] Opening App Store...")
    try:
        await driver.create_session("com.apple.AppStore")
    except Exception:
        await driver.launch_app("com.apple.AppStore")
    await asyncio.sleep(5)

    for iteration in range(25):
        logger.info("--- [iOS15+] Iteration %d ---", iteration + 1)

        if await check_banned(driver):
            raise BannedAccountError(f"Apple ID {apple_id} is banned or disabled")

        source = await get_source_safe(driver)

        # Already logged in
        e = await has_element(driver, "name", "完成")
        if e:
            sign_in = await has_element(driver, "name", "AppStore.account.signIn")
            if not sign_in:
                logger.info("[iOS15+] Already logged in, tapping '完成'")
                await tap_element(driver, e)
                return

        # Security popup
        e = await has_element(driver, "name", "不升级")
        if e:
            logger.info("[iOS15+] Tapping '不升级'")
            await tap_element(driver, e)
            await asyncio.sleep(3)
            continue

        # 2FA options
        e = await has_element(driver, "name", "其他选项")
        if e:
            logger.info("[iOS15+] Tapping '其他选项'")
            await tap_element(driver, e)
            await asyncio.sleep(3)
            continue

        # Password page (separate from email)
        secure = await has_element(driver, "class name", "XCUIElementTypeSecureTextField")
        if secure:
            email_field = await has_element(driver, "name", "username-field")
            if not email_field:
                logger.info("[iOS15+] Password page, entering password")
                await type_into(driver, secure, apple_password)
                await asyncio.sleep(1)
                cont = await has_element(driver, "name", "continue-button")
                if cont:
                    await tap_element(driver, cont)
                logger.info("[iOS15+] Waiting for response...")
                await asyncio.sleep(10)
                continue

        # Email page
        email_field = await has_element(driver, "name", "username-field")
        if email_field:
            logger.info("[iOS15+] Email page, entering Apple ID: %s", apple_id)
            await type_into(driver, email_field, apple_id)
            await asyncio.sleep(1)
            cont = await has_element(driver, "name", "continue-button")
            if cont:
                await tap_element(driver, cont)
            await asyncio.sleep(5)
            continue

        # Account popup
        sign_in = await has_element(driver, "name", "AppStore.account.signIn")
        if sign_in:
            logger.info("[iOS15+] Tapping sign-in button")
            await tap_element(driver, sign_in)
            await asyncio.sleep(4)
            continue

        # Main page
        btn = await has_element(driver, "accessibility id", "AppStore.accountButton")
        if not btn:
            btn = await has_element(driver, "name", "Account")
        if btn:
            logger.info("[iOS15+] Tapping account button")
            await tap_element(driver, btn)
            await asyncio.sleep(3)
            continue

        if "Today" in source or "今天" in source or "游戏" in source:
            size = await driver.get_window_size()
            w = size.get("width", 375)
            logger.info("[iOS15+] Main page, tapping profile icon")
            await tap_coord(driver, w - 30, 52)
            await asyncio.sleep(3)
            continue

        # Loading or continue button
        e = await has_element(driver, "name", "continue-button")
        if e:
            logger.info("[iOS15+] Loading/continue...")
            await asyncio.sleep(5)
            continue

        logger.warning("[iOS15+] Unknown state, source[:300]=%s", source[:300])
        await asyncio.sleep(4)

    logger.info("[iOS15+] Max iterations reached")


# ─── Entry Point ──────────────────────────────────────────────

async def run(driver, params):
    """Entry point for remote execution via PythonScriptRunner."""
    apple_id = params.get("apple_id", "")
    apple_password = params.get("apple_password", "")
    ios_version = params.get("ios_version", "")

    if not apple_id or not apple_password:
        raise RuntimeError("Missing apple_id or apple_password in params")

    major = parse_major_version(ios_version)
    logger.info("Device iOS version: %s (major=%d), Apple ID: %s", ios_version, major, apple_id)

    if major <= 14:
        await login_ios14(driver, apple_id, apple_password)
    else:
        await login_ios15(driver, apple_id, apple_password)

    logger.info("Login flow completed for %s", apple_id)


class BannedAccountError(Exception):
    """Raised when the Apple ID is banned/disabled. error_code = APPLE_ID_BANNED"""
    pass


if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from client.src.wda_driver import WDADriver

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    async def main():
        driver = WDADriver("http://localhost:8100", "test")
        if not await driver.health_check():
            logger.error("WDA not reachable!")
            return
        await driver.create_session("")
        await run(driver, {
            "apple_id": "test@example.com",
            "apple_password": "test123",
            "ios_version": "14.2",
        })

    asyncio.run(main())
