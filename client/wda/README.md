# WDA IPA

This directory contains WDA (WebDriverAgent) IPA and AppSync Unified .deb for automatic deployment.

## Files
- `WebDriverAgent-v5.3.0.ipa` — WDA compiled with SDK 16.2 (Xcode 14), compatible with iOS 12.0+
- `appsync.deb` — AppSync Unified, auto-deployed via AFC2 for unsigned IPA installation

## Version Compatibility
| WDA Version | SDK   | Compatible iOS |
|-------------|-------|---------------|
| v5.3.0      | 16.2  | 12.0 ~ 16.x  |
| v11.4.1     | 18.5  | 15.0+ only    |

**Important**: Newer WDA versions (v7+) are compiled with iOS 17/18 SDK and will crash on iOS 14.x devices.

## How it works
1. Device plugged in via USB → client detects automatically
2. If AppSync not installed → deploys via AFC2 + kills installd
3. Installs WDA IPA → launches via XCUITestService with AFC2 bypass
4. WDA ready → user can unplug USB, device connects via WiFi
