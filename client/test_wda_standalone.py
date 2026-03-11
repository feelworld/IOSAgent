"""
独立测试脚本：连接越狱 iPhone 上的 WDA，执行 App Store 登录流程。

使用方式：
    1. 确保 iPhone 上 WDA 已启动
    2. 修改下面的 WDA_URL 为你的设备地址
    3. 修改 APPLE_ID 和 APPLE_PASSWORD
    4. 运行: python test_wda_standalone.py

前置条件见下方说明。
"""

import asyncio
import json
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.src.wda_driver import WDADriver, WDAError, ElementNotFoundError
from client.src.script_runner import ScriptRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test")

# ============================================================
# !! 修改这三个值 !!
# ============================================================
WDA_URL = "http://192.168.1.101:8100"  # iPhone 上 WDA 的 HTTP 地址
APPLE_ID = "your_apple_id@icloud.com"  # Apple ID 邮箱
APPLE_PASSWORD = "your_password"        # Apple ID 密码
# ============================================================


async def step1_test_connection():
    """步骤 1: 测试 WDA 是否连通。"""
    logger.info("=" * 50)
    logger.info("步骤 1: 测试 WDA 连接")
    logger.info("=" * 50)

    driver = WDADriver(WDA_URL, "test-device")
    healthy = await driver.health_check()

    if healthy:
        logger.info("WDA 连接成功！")
        data = await driver._request("GET", "/status")
        value = data.get("value", {})
        os_info = value.get("os", {})
        logger.info("  iOS 版本: %s", os_info.get("version", "未知"))
        logger.info("  设备名称: %s", os_info.get("name", "未知"))
        return True
    else:
        logger.error("WDA 连接失败！请检查:")
        logger.error("  1. iPhone 和本机是否在同一局域网")
        logger.error("  2. WDA 是否已在 iPhone 上启动")
        logger.error("  3. WDA_URL 是否正确: %s", WDA_URL)
        return False


async def step2_test_basic_operations():
    """步骤 2: 测试基本操作（创建 session、截图、获取页面源码）。"""
    logger.info("\n" + "=" * 50)
    logger.info("步骤 2: 测试基本操作")
    logger.info("=" * 50)

    driver = WDADriver(WDA_URL, "test-device")

    logger.info("创建 WDA session...")
    session_id = await driver.create_session("com.apple.Preferences")
    logger.info("  Session ID: %s", session_id)

    logger.info("获取窗口尺寸...")
    size = await driver.get_window_size()
    logger.info("  窗口尺寸: %sx%s", size.get("width"), size.get("height"))

    logger.info("截图...")
    screenshot = await driver.screenshot()
    logger.info("  截图数据长度: %d 字符", len(screenshot) if screenshot else 0)

    logger.info("获取页面源码（用于定位元素）...")
    source = await driver.get_page_source()
    source_file = "page_source.xml"
    with open(source_file, "w", encoding="utf-8") as f:
        f.write(source)
    logger.info("  页面源码已保存到: %s (可用浏览器打开查看元素结构)", source_file)

    return True


async def step3_open_appstore():
    """步骤 3: 打开 App Store。"""
    logger.info("\n" + "=" * 50)
    logger.info("步骤 3: 打开 App Store")
    logger.info("=" * 50)

    driver = WDADriver(WDA_URL, "test-device")
    await driver.create_session("com.apple.AppStore")

    logger.info("启动 App Store...")
    await driver.launch_app("com.apple.AppStore")
    logger.info("  App Store 已启动")

    await asyncio.sleep(3)

    source = await driver.get_page_source()
    with open("appstore_source.xml", "w", encoding="utf-8") as f:
        f.write(source)
    logger.info("  App Store 页面源码已保存到: appstore_source.xml")
    logger.info("  请查看 XML 文件确定元素 XPath，用于下一步的登录脚本")

    return True


async def step4_run_login_script():
    """步骤 4: 运行 App Store 登录脚本（使用 ScriptRunner）。

    注意：App Store 的登录流程因 iOS 版本不同而差异很大。
    以下 XPath 仅供参考，需要根据你的设备实际页面源码调整。
    先运行 step3 保存 XML，然后根据 XML 中的元素修改 XPath。
    """
    logger.info("\n" + "=" * 50)
    logger.info("步骤 4: 执行 App Store 登录脚本")
    logger.info("=" * 50)

    driver = WDADriver(WDA_URL, "test-device")
    runner = ScriptRunner(driver)

    # App Store 登录脚本
    # !! 重要: 以下 XPath 需要根据你设备上的实际页面结构调整 !!
    # !! 先运行 step3 获取 XML，然后修改这里的 XPath !!
    login_steps = [
        {
            "action": "launch_app",
            "target": "com.apple.AppStore",
            "params": {},
            "timeout": 10,
        },
        {
            "action": "wait",
            "target": "",
            "params": {"seconds": 3},
            "timeout": 5,
        },
        # 点击右上角的用户头像（进入账户页面）
        {
            "action": "tap",
            "target": "//XCUIElementTypeButton[@name='Account']",
            "params": {},
            "timeout": 10,
        },
        {
            "action": "wait",
            "target": "",
            "params": {"seconds": 2},
            "timeout": 5,
        },
        # 如果已登录会显示账户页，如果未登录会显示登录按钮
        # 点击 "登录" 或 "Sign In"
        {
            "action": "tap",
            "target": "//XCUIElementTypeButton[contains(@name,'Sign In') or contains(@name,'登录')]",
            "params": {},
            "timeout": 10,
        },
        {
            "action": "wait",
            "target": "",
            "params": {"seconds": 2},
            "timeout": 5,
        },
        # 输入 Apple ID
        {
            "action": "type",
            "target": "//XCUIElementTypeTextField[@name='Apple ID' or @name='Apple\xa0ID' or contains(@value,'Apple ID')]",
            "params": {"text": "{{apple_id}}"},
            "timeout": 10,
        },
        {
            "action": "wait",
            "target": "",
            "params": {"seconds": 1},
            "timeout": 5,
        },
        # 输入密码
        {
            "action": "type",
            "target": "//XCUIElementTypeSecureTextField",
            "params": {"text": "{{password}}"},
            "timeout": 10,
        },
        {
            "action": "wait",
            "target": "",
            "params": {"seconds": 1},
            "timeout": 5,
        },
        # 点击登录/Sign In 按钮
        {
            "action": "tap",
            "target": "//XCUIElementTypeButton[@name='Sign In' or @name='登录']",
            "params": {},
            "timeout": 10,
        },
        {
            "action": "wait",
            "target": "",
            "params": {"seconds": 5},
            "timeout": 10,
        },
        # 截图确认结果
        {
            "action": "screenshot",
            "target": "",
            "params": {},
            "timeout": 10,
        },
    ]

    async def on_progress(completed, total):
        logger.info("  进度: %d/%d", completed, total)

    result = await runner.execute(
        steps=login_steps,
        params={
            "apple_id": APPLE_ID,
            "password": APPLE_PASSWORD,
        },
        global_timeout=120,
        progress_callback=on_progress,
    )

    logger.info("\n--- 执行结果 ---")
    logger.info("成功: %s", result.success)
    logger.info("完成步骤: %d/%d", result.steps_completed, result.total_steps)
    logger.info("耗时: %.1f 秒", result.duration_seconds)
    if result.error_code:
        logger.error("错误码: %s", result.error_code)
        logger.error("错误信息: %s", result.error_message)
        if result.failed_step_index is not None:
            logger.error("失败步骤: #%d", result.failed_step_index)

    if result.screenshots:
        import base64
        for idx, ss in enumerate(result.screenshots):
            filename = f"screenshot_{idx}.png"
            with open(filename, "wb") as f:
                f.write(base64.b64decode(ss))
            logger.info("截图已保存: %s", filename)

    return result.success


async def main():
    logger.info("iOS App Store 登录自动化测试")
    logger.info("WDA 地址: %s", WDA_URL)
    logger.info("")

    # 按步骤执行，任何一步失败就停止
    if not await step1_test_connection():
        return

    if not await step2_test_basic_operations():
        return

    if not await step3_open_appstore():
        return

    logger.info("\n" + "!" * 50)
    logger.info("接下来将执行登录脚本。")
    logger.info("请先检查 appstore_source.xml 中的元素结构，")
    logger.info("确认 XPath 是否正确，必要时修改脚本中的 XPath。")
    logger.info("!" * 50)

    proceed = input("\n是否继续执行登录脚本？(y/n): ").strip().lower()
    if proceed == "y":
        await step4_run_login_script()
    else:
        logger.info("已跳过登录脚本执行。")

    logger.info("\n测试完成。")


if __name__ == "__main__":
    asyncio.run(main())
