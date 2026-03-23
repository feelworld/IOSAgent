"""
App Store 自动化脚本 (模块化)
通过 action 参数路由到不同功能:
  - login:           登录 Apple ID
  - search_download: 搜索并下载指定 App
  - full_flow:       登录 + 搜索下载 (串联)

params 由系统自动注入:
    - action: 执行动作
    - apple_id / apple_password: 账号密码 (login / full_flow 需要)
    - app_name: 要搜索下载的 App 名称 (search_download / full_flow 需要)
    - ios_version: 设备 iOS 版本
    - device_uid: 设备 UID

error_code 约定:
    - APPLE_ID_BANNED: 账号被封/禁用, 触发服务端自动切换
"""
import asyncio
import logging

logger = logging.getLogger("appstore_agent")

BANNED_KEYWORDS = [
    "已被禁用", "has been disabled",
    "已被锁定", "has been locked",
    "无法登录", "cannot sign in",
    "此 Apple ID 已被停用", "This Apple ID has been disabled",
]


class BannedAccountError(Exception):
    """Raised when the Apple ID is banned/disabled. error_code = APPLE_ID_BANNED"""
    pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  通用工具函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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


async def tap_element(driver, elem, timeout=8):
    eid = elem.get("ELEMENT") or list(elem.values())[0]
    try:
        await asyncio.wait_for(driver.tap_element(eid), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("tap_element: timed out after %ds, skipping", timeout)
        return eid
    except Exception as e:
        err_str = str(e).lower()
        if "stale" in err_str or "not present" in err_str:
            logger.warning("tap_element: stale element (already gone), skipping")
            return eid
        raise
    return eid


async def type_into(driver, elem, text):
    eid = elem.get("ELEMENT") or list(elem.values())[0]
    await driver.tap_element(eid)
    await asyncio.sleep(0.3)
    await driver.type_text(eid, text)


async def clear_and_type(driver, elem, text):
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
    try:
        return int(version_str.split(".")[0])
    except (ValueError, IndexError):
        return 0


async def ensure_appstore_foreground(driver, tag):
    """Make sure App Store is in the foreground."""
    try:
        await driver.create_session("com.apple.AppStore")
    except Exception:
        try:
            await driver.launch_app("com.apple.AppStore")
        except Exception:
            pass
    await asyncio.sleep(3)


async def dismiss_popups(driver, tag):
    """Try to dismiss any system popup. Returns True if a popup was found."""
    popup_buttons = [
        "同意并继续", "Agree & Continue", "Agree and Continue",
        "不添加号码并继续",
        "不是居住在中国大陆的中国公民？",
        "不升级", "Don\u2019t Upgrade",
        "不是", "Not Now",
        "其他选项", "Other Options",
        "继续", "Continue",
        "好", "OK",
    ]
    for btn_name in popup_buttons:
        e = await has_element(driver, "name", btn_name)
        if e:
            logger.info("%s Dismissing popup: '%s'", tag, btn_name)
            await tap_element(driver, e)
            await asyncio.sleep(4)
            return True
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Action: login — 登录 Apple ID
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def do_login(driver, params):
    """Login to App Store with Apple ID."""
    apple_id = params.get("apple_id", "")
    apple_password = params.get("apple_password", "")
    ios_version = params.get("ios_version", "")
    device_uid = params.get("device_uid", "")

    if not apple_id or not apple_password:
        raise RuntimeError("Missing apple_id or apple_password in params")

    major = parse_major_version(ios_version)
    logger.info("[%s] Login: iOS %s (major=%d), Apple ID: %s", device_uid, ios_version, major, apple_id)

    if major <= 14:
        await _login_ios14(driver, apple_id, apple_password, device_uid=device_uid)
    else:
        await _login_ios15(driver, apple_id, apple_password, device_uid=device_uid)

    logger.info("[%s] Login completed for %s", device_uid, apple_id)


async def _login_ios14(driver, apple_id, apple_password, device_uid=""):
    tag = f"[iOS14][{device_uid}]"
    logger.info("%s Opening App Store...", tag)
    await ensure_appstore_foreground(driver, tag)
    await asyncio.sleep(2)

    login_submitted = False
    login_count = 0
    for iteration in range(25):
        logger.info("--- %s Iteration %d ---", tag, iteration + 1)
        try:
            result = await _ios14_iteration(driver, apple_id, apple_password, iteration, tag, login_submitted)
            if result == "done":
                return
            if result == "login_submitted":
                login_submitted = True
                login_count += 1
                if login_count >= 3:
                    logger.warning("%s Submitted login %d times but keeps looping", tag, login_count)
                    raise BannedAccountError(f"Apple ID {apple_id} requires verification (login loop)")
            else:
                login_submitted = False
        except BannedAccountError:
            raise
        except Exception as exc:
            exc_str = str(exc).lower()
            if "stale" in exc_str or "not present" in exc_str:
                logger.info("%s stale element, continuing...", tag)
                await asyncio.sleep(3)
            else:
                logger.warning("%s Iteration %d error: %s, recovering...", tag, iteration + 1, exc)
                login_submitted = False
                await ensure_appstore_foreground(driver, tag)
    logger.info("%s Max iterations reached", tag)


async def _ios14_iteration(driver, apple_id, apple_password, iteration, tag="[iOS14]", login_submitted=False):
    """Single iteration of iOS14 login loop."""

    # ── Priority 0: Quick popup dismiss ──
    if await dismiss_popups(driver, tag):
        return

    source = await get_source_safe(driver)

    if not source or len(source) < 50:
        logger.warning("%s Empty page source, re-activating App Store...", tag)
        await ensure_appstore_foreground(driver, tag)
        return

    app_indicators = ["Today", "今天", "游戏", "Games", "完成", "登录",
                      "Sign In", "AppStore", "XCUIElementTypeTextField",
                      "XCUIElementTypeSecureTextField", "退出登录"]
    if not any(kw in source for kw in app_indicators):
        logger.info("%s App Store not in foreground, re-activating...", tag)
        await ensure_appstore_foreground(driver, tag)
        return

    if await check_banned(driver):
        raise BannedAccountError(f"Apple ID {apple_id} is banned or disabled")

    # ── Priority 1: Login alert with input fields ──
    text_fields = await find_elements(driver, "class name", "XCUIElementTypeTextField")
    secure_fields = await find_elements(driver, "class name", "XCUIElementTypeSecureTextField")

    is_login_alert = False
    if secure_fields:
        cancel_btn = await has_element(driver, "name", "取消")
        if not cancel_btn:
            cancel_btn = await has_element(driver, "name", "Cancel")
        login_btn = await has_element(driver, "name", "登录")
        if not login_btn:
            login_btn = await has_element(driver, "name", "Sign In")
        if cancel_btn or login_btn:
            is_login_alert = True
        else:
            logger.info("%s Found fields but no Cancel/Login btn → NOT login dialog", tag)

    if is_login_alert:
        if login_submitted:
            logger.info("%s Login already submitted, waiting...", tag)
            await asyncio.sleep(8)
            return

        logger.info("%s Login dialog (text=%d, secure=%d)", tag, len(text_fields), len(secure_fields))

        if text_fields:
            logger.info("%s Entering Apple ID: %s", tag, apple_id)
            await clear_and_type(driver, text_fields[0], apple_id)
            await asyncio.sleep(0.5)

        logger.info("%s Entering password", tag)
        await clear_and_type(driver, secure_fields[0], apple_password)
        await asyncio.sleep(0.5)

        sign_btn = None
        for name in ["登录", "Sign In", "好", "OK"]:
            sign_btn = await has_element(driver, "name", name)
            if sign_btn:
                break
        if sign_btn:
            logger.info("%s Tapping login button", tag)
            await tap_element(driver, sign_btn)
        else:
            buttons = await find_elements(driver, "class name", "XCUIElementTypeButton")
            for btn in buttons:
                bid = btn.get("ELEMENT") or list(btn.values())[0]
                try:
                    a = await driver._request(
                        "GET", f"/session/{driver._session_id}/element/{bid}/attribute/label",
                    )
                    lbl = a.get("value", "")
                    if lbl in ("登录", "Sign In", "好", "OK"):
                        await driver.tap_element(bid)
                        break
                except Exception:
                    pass

        logger.info("%s Waiting for login response (15s)...", tag)
        await asyncio.sleep(15)
        return "login_submitted"

    # ── Priority 2: Security / 2FA popups ──
    for btn_name in ["不升级", "其他选项", "不是", "Don\u2019t Upgrade"]:
        e = await has_element(driver, "name", btn_name)
        if e:
            logger.info("%s Tapping '%s'", tag, btn_name)
            await tap_element(driver, e)
            await asyncio.sleep(3)
            return

    # ── Priority 3: Account page ──
    done_btn = await has_element(driver, "name", "完成")
    if done_btn:
        if "退出登录" in source or "Sign Out" in source:
            if apple_id.lower() in source.lower():
                logger.info("%s Target account %s already logged in", tag, apple_id)
                await tap_element(driver, done_btn)
                return "done"
            else:
                logger.info("%s Different account, signing out...", tag)
                sign_out = await has_element(driver, "name", "退出登录")
                if not sign_out:
                    sign_out = await has_element(driver, "name", "Sign Out")
                if sign_out:
                    logger.info("%s Scrolling to find sign-out...", tag)
                    try:
                        size = await driver.get_window_size()
                        w, h = size.get("width", 375), size.get("height", 667)
                        await tap_coord(driver, w // 2, h - 50)
                        await asyncio.sleep(1)
                    except Exception:
                        pass
                    sign_out = await has_element(driver, "name", "退出登录")
                    if not sign_out:
                        sign_out = await has_element(driver, "name", "Sign Out")

                if sign_out:
                    logger.info("%s Tapping sign-out", tag)
                    await tap_element(driver, sign_out)
                    await asyncio.sleep(3)
                    confirm = await has_element(driver, "name", "退出登录")
                    if not confirm:
                        confirm = await has_element(driver, "name", "Sign Out")
                    if confirm:
                        logger.info("%s Confirming sign-out", tag)
                        await tap_element(driver, confirm)
                    await asyncio.sleep(5)
                else:
                    size = await driver.get_window_size()
                    w, h = size.get("width", 375), size.get("height", 667)
                    actions = {"actions": [{"type": "pointer", "id": "finger1",
                        "parameters": {"pointerType": "touch"}, "actions": [
                            {"type": "pointerMove", "duration": 0, "x": w // 2, "y": h * 3 // 4},
                            {"type": "pointerDown", "button": 0},
                            {"type": "pointerMove", "duration": 500, "x": w // 2, "y": h // 4},
                            {"type": "pointerUp", "button": 0},
                        ]}]}
                    await driver._request("POST", f"/session/{driver._session_id}/actions", json=actions)
                    await asyncio.sleep(2)
                return

        has_sign_in = False
        for sign_name in ["AppStore.account.signIn", "登录", "Sign In", "登入"]:
            el = await has_element(driver, "name", sign_name)
            if el:
                has_sign_in = True
                logger.info("%s Account page, tapping sign-in: '%s'", tag, sign_name)
                await tap_element(driver, el)
                await asyncio.sleep(5)
                break

        if not has_sign_in:
            buttons = await find_elements(driver, "class name", "XCUIElementTypeButton")
            for btn in buttons[:15]:
                bid = btn.get("ELEMENT") or list(btn.values())[0]
                try:
                    a = await driver._request(
                        "GET", f"/session/{driver._session_id}/element/{bid}/attribute/label",
                    )
                    lbl = a.get("value", "")
                    if lbl in ("登录", "Sign In", "登入"):
                        await driver.tap_element(bid)
                        has_sign_in = True
                        await asyncio.sleep(5)
                        break
                except Exception:
                    pass

        if not has_sign_in:
            logger.warning("%s Account page, no sign-in found", tag)
            await asyncio.sleep(3)
        return

    # ── Priority 4: Main page → tap profile icon ──
    if "Today" in source or "今天" in source or "游戏" in source or "Games" in source:
        size = await driver.get_window_size()
        w = size.get("width", 375)
        coords = [(w - 30, 52), (w - 30, 45), (w - 25, 88), (w - 30, 70)]
        cx, cy = coords[iteration % len(coords)]
        logger.info("%s Main page, tapping profile icon at (%d, %d)", tag, cx, cy)
        await tap_coord(driver, cx, cy)
        await asyncio.sleep(3)
        return

    logger.warning("%s Unknown state", tag)
    await asyncio.sleep(4)


async def _login_ios15(driver, apple_id, apple_password, device_uid=""):
    tag = f"[iOS15][{device_uid}]"
    logger.info("%s Opening App Store...", tag)
    await ensure_appstore_foreground(driver, tag)
    await asyncio.sleep(2)

    for iteration in range(25):
        logger.info("--- %s Iteration %d ---", tag, iteration + 1)

        if await check_banned(driver):
            raise BannedAccountError(f"Apple ID {apple_id} is banned or disabled")

        source = await get_source_safe(driver)

        e = await has_element(driver, "name", "完成")
        if e:
            sign_in = await has_element(driver, "name", "AppStore.account.signIn")
            if not sign_in:
                logger.info("%s Already logged in, tapping '完成'", tag)
                await tap_element(driver, e)
                return

        for btn_name in ["不升级", "其他选项", "Don\u2019t Upgrade", "不是"]:
            e = await has_element(driver, "name", btn_name)
            if e:
                logger.info("%s Tapping '%s'", tag, btn_name)
                await tap_element(driver, e)
                await asyncio.sleep(3)
                break
        else:
            secure = await has_element(driver, "class name", "XCUIElementTypeSecureTextField")
            if secure:
                email_field = await has_element(driver, "name", "username-field")
                if not email_field:
                    logger.info("%s Password page, entering password", tag)
                    await type_into(driver, secure, apple_password)
                    await asyncio.sleep(1)
                    cont = await has_element(driver, "name", "continue-button")
                    if cont:
                        await tap_element(driver, cont)
                    await asyncio.sleep(10)
                    continue

            email_field = await has_element(driver, "name", "username-field")
            if email_field:
                logger.info("%s Email page, entering Apple ID: %s", tag, apple_id)
                await type_into(driver, email_field, apple_id)
                await asyncio.sleep(1)
                cont = await has_element(driver, "name", "continue-button")
                if cont:
                    await tap_element(driver, cont)
                await asyncio.sleep(5)
                continue

            sign_in = await has_element(driver, "name", "AppStore.account.signIn")
            if sign_in:
                logger.info("%s Tapping sign-in", tag)
                await tap_element(driver, sign_in)
                await asyncio.sleep(4)
                continue

            btn = await has_element(driver, "accessibility id", "AppStore.accountButton")
            if not btn:
                btn = await has_element(driver, "name", "Account")
            if btn:
                logger.info("%s Tapping account button", tag)
                await tap_element(driver, btn)
                await asyncio.sleep(3)
                continue

            if "Today" in source or "今天" in source or "游戏" in source:
                size = await driver.get_window_size()
                w = size.get("width", 375)
                await tap_coord(driver, w - 30, 52)
                await asyncio.sleep(3)
                continue

            logger.warning("%s Unknown state", tag)
            await asyncio.sleep(4)

    logger.info("%s Max iterations reached", tag)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Action: search_download — 搜索并下载 App
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def do_search_download(driver, params):
    """Search for an app in App Store and download it."""
    app_name = params.get("app_name", "")
    device_uid = params.get("device_uid", "")
    tag = f"[Search][{device_uid}]"

    if not app_name:
        raise RuntimeError("Missing app_name in params")

    logger.info("%s Searching for app: '%s'", tag, app_name)

    await ensure_appstore_foreground(driver, tag)
    await asyncio.sleep(2)

    # Step 1: Navigate to Search tab
    search_tab = await has_element(driver, "name", "搜索")
    if not search_tab:
        search_tab = await has_element(driver, "name", "Search")
    if search_tab:
        logger.info("%s Tapping Search tab", tag)
        await tap_element(driver, search_tab)
        await asyncio.sleep(2)
    else:
        logger.warning("%s Search tab not found, trying bottom tab bar", tag)
        size = await driver.get_window_size()
        w, h = size.get("width", 375), size.get("height", 667)
        await tap_coord(driver, w * 4 // 5, h - 25)
        await asyncio.sleep(2)

    # Step 2: Tap search field
    search_field = await has_element(driver, "name", "搜索")
    if not search_field:
        search_field = await has_element(driver, "name", "Search")
    search_fields = await find_elements(driver, "class name", "XCUIElementTypeSearchField")
    if search_fields:
        search_field = search_fields[0]

    if search_field:
        logger.info("%s Tapping search field", tag)
        await tap_element(driver, search_field)
        await asyncio.sleep(1)
    else:
        logger.warning("%s Search field not found, tapping top area", tag)
        size = await driver.get_window_size()
        w = size.get("width", 375)
        await tap_coord(driver, w // 2, 110)
        await asyncio.sleep(1)

    # Step 3: Clear existing text and type app name
    search_fields = await find_elements(driver, "class name", "XCUIElementTypeSearchField")
    if search_fields:
        logger.info("%s Typing app name: '%s'", tag, app_name)
        await clear_and_type(driver, search_fields[0], app_name)
        await asyncio.sleep(1)
    else:
        logger.warning("%s No search field to type into", tag)
        return

    # Step 4: Press keyboard Search key (send \n to trigger search)
    search_fields = await find_elements(driver, "class name", "XCUIElementTypeSearchField")
    if search_fields:
        sf_id = search_fields[0].get("ELEMENT") or list(search_fields[0].values())[0]
        logger.info("%s Sending Enter key to trigger keyboard search", tag)
        try:
            await driver.type_text(sf_id, "\n")
        except Exception:
            logger.warning("%s Enter key failed, trying keyboard button", tag)
            keyboards = await find_elements(driver, "class name", "XCUIElementTypeKeyboard")
            if keyboards:
                btns = await find_elements(driver, "class name", "XCUIElementTypeButton")
                for btn in btns:
                    bid = btn.get("ELEMENT") or list(btn.values())[0]
                    try:
                        a = await driver._request(
                            "GET", f"/session/{driver._session_id}/element/{bid}/attribute/label",
                        )
                        lbl = a.get("value", "")
                        if lbl in ("搜索", "search", "Search"):
                            logger.info("%s Found keyboard search button: '%s'", tag, lbl)
                            await driver.tap_element(bid)
                            break
                    except Exception:
                        pass
    await asyncio.sleep(5)

    # Step 5: Dismiss any popups
    await dismiss_popups(driver, tag)

    # Step 6: Find the app in search results and tap GET/下载
    logger.info("%s Looking for download button...", tag)
    for attempt in range(3):
        get_btn = await has_element(driver, "name", "获取")
        if not get_btn:
            get_btn = await has_element(driver, "name", "GET")
        if not get_btn:
            get_btn = await has_element(driver, "name", "iCloud")
        if not get_btn:
            get_btn = await has_element(driver, "name", "打开")
            if get_btn:
                logger.info("%s App already installed (打开/Open found)", tag)
                return
            get_btn = await has_element(driver, "name", "Open")
            if get_btn:
                logger.info("%s App already installed (Open found)", tag)
                return

        if get_btn:
            logger.info("%s Tapping download button", tag)
            await tap_element(driver, get_btn)
            await asyncio.sleep(3)

            # Handle "Install" confirmation or Apple ID password prompt
            install_btn = await has_element(driver, "name", "安装")
            if not install_btn:
                install_btn = await has_element(driver, "name", "Install")
            if install_btn:
                logger.info("%s Confirming install", tag)
                await tap_element(driver, install_btn)
                await asyncio.sleep(2)

            await dismiss_popups(driver, tag)

            # Wait for download to complete
            logger.info("%s Waiting for download to complete...", tag)
            for wait_round in range(30):
                await asyncio.sleep(5)
                open_btn = await has_element(driver, "name", "打开")
                if not open_btn:
                    open_btn = await has_element(driver, "name", "Open")
                if open_btn:
                    logger.info("%s Download complete!", tag)
                    return

                await dismiss_popups(driver, tag)

                source = await get_source_safe(driver)
                if "打开" in source or "Open" in source or "OPEN" in source:
                    logger.info("%s Download complete (detected in source)", tag)
                    return

            logger.warning("%s Download may still be in progress after timeout", tag)
            return

        logger.info("%s Download button not found, attempt %d, scrolling...", tag, attempt + 1)
        size = await driver.get_window_size()
        w, h = size.get("width", 375), size.get("height", 667)
        actions = {"actions": [{"type": "pointer", "id": "finger1",
            "parameters": {"pointerType": "touch"}, "actions": [
                {"type": "pointerMove", "duration": 0, "x": w // 2, "y": h * 2 // 3},
                {"type": "pointerDown", "button": 0},
                {"type": "pointerMove", "duration": 500, "x": w // 2, "y": h // 3},
                {"type": "pointerUp", "button": 0},
            ]}]}
        await driver._request("POST", f"/session/{driver._session_id}/actions", json=actions)
        await asyncio.sleep(3)

    logger.warning("%s Could not find download button for '%s'", tag, app_name)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  统一入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ACTION_MAP = {
    "login": do_login,
    "search_download": do_search_download,
}


async def run(driver, params):
    """Unified entry point. Routes to action handler based on params['action']."""
    action = params.get("action", "login")
    device_uid = params.get("device_uid", "")

    logger.info("[%s] Action: %s", device_uid, action)

    if action == "full_flow":
        await do_login(driver, params)
        await do_search_download(driver, params)
        logger.info("[%s] Full flow completed", device_uid)
    elif action in ACTION_MAP:
        await ACTION_MAP[action](driver, params)
        logger.info("[%s] Action '%s' completed", device_uid, action)
    else:
        raise RuntimeError(f"Unknown action: {action}")
