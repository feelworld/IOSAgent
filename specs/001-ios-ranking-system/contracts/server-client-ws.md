# WebSocket Contract: Server ↔ Client (Companion Machine)

**Protocol**: WSS (WebSocket Secure)
**Endpoint**: `wss://<server>/ws/client/{machine_id}`
**Authentication**: JWT token in query param `?token=xxx` on connect

## Message Format

所有消息使用 JSON 格式，顶层结构：

```json
{
  "type": "<message_type>",
  "id": "<uuid>",
  "timestamp": "<ISO8601>",
  "payload": { ... }
}
```

## Server → Client Messages

### `command.dispatch`

下发脚本执行命令到指定设备。

```json
{
  "type": "command.dispatch",
  "id": "cmd-uuid-001",
  "timestamp": "2026-03-07T12:00:00Z",
  "payload": {
    "task_id": "task-uuid-001",
    "device_uid": "device-001",
    "script": {
      "id": "script-001",
      "version": 3,
      "steps": [
        { "action": "launch_app", "target": "com.apple.AppStore", "params": {} },
        { "action": "tap", "target": "//XCUIElementTypeButton[@name='Search']", "params": {} },
        { "action": "type", "target": "//XCUIElementTypeSearchField", "params": { "text": "TargetApp" } },
        { "action": "tap", "target": "//XCUIElementTypeButton[@name='Search']", "params": {} },
        { "action": "wait", "target": "", "params": { "seconds": 3 } },
        { "action": "tap", "target": "//XCUIElementTypeButton[@name='GET']", "params": {} }
      ]
    },
    "params": {
      "target_app": "TargetApp",
      "keyword": "TargetApp"
    },
    "timeout_seconds": 300,
    "retry_on_fail": true,
    "max_retries": 3
  }
}
```

### `command.cancel`

取消正在执行的任务。

```json
{
  "type": "command.cancel",
  "id": "cmd-uuid-002",
  "timestamp": "2026-03-07T12:05:00Z",
  "payload": {
    "task_id": "task-uuid-001",
    "device_uid": "device-001"
  }
}
```

### `config.update`

下发配置更新。

```json
{
  "type": "config.update",
  "id": "cfg-uuid-001",
  "timestamp": "2026-03-07T12:00:00Z",
  "payload": {
    "scope": "device",
    "device_uid": "device-001",
    "configs": {
      "heartbeat_interval": 15,
      "script_timeout": 600
    }
  }
}
```

### `apple_account.switch`

指示设备切换 Apple ID。

```json
{
  "type": "apple_account.switch",
  "id": "acc-uuid-001",
  "timestamp": "2026-03-07T12:00:00Z",
  "payload": {
    "device_uid": "device-001",
    "new_account_id": "account-002",
    "encrypted_credentials": "<AES-256 encrypted>"
  }
}
```

## Client → Server Messages

### `device.register`

伴生机上线时注册其管理的所有设备。

```json
{
  "type": "device.register",
  "id": "reg-uuid-001",
  "timestamp": "2026-03-07T12:00:00Z",
  "payload": {
    "machine_id": "companion-001",
    "devices": [
      {
        "device_uid": "device-001",
        "model": "iPhone 12",
        "ios_version": "15.7",
        "wda_url": "http://192.168.1.101:8100"
      }
    ]
  }
}
```

### `heartbeat`

定期心跳，上报伴生机及其管理设备的状态。

```json
{
  "type": "heartbeat",
  "id": "hb-uuid-001",
  "timestamp": "2026-03-07T12:00:30Z",
  "payload": {
    "machine_id": "companion-001",
    "devices": [
      {
        "device_uid": "device-001",
        "status": "online",
        "battery_level": 85,
        "network_type": "Wi-Fi",
        "appstore_logged_in": true,
        "current_task_id": null
      }
    ]
  }
}
```

### `task.status`

任务状态变更通知。

```json
{
  "type": "task.status",
  "id": "ts-uuid-001",
  "timestamp": "2026-03-07T12:01:00Z",
  "payload": {
    "task_id": "task-uuid-001",
    "device_uid": "device-001",
    "status": "running",
    "progress": 30,
    "current_step": 2,
    "total_steps": 6
  }
}
```

### `task.result`

任务执行结果。

```json
{
  "type": "task.result",
  "id": "tr-uuid-001",
  "timestamp": "2026-03-07T12:05:00Z",
  "payload": {
    "task_id": "task-uuid-001",
    "device_uid": "device-001",
    "status": "success",
    "result": {
      "stdout": "App downloaded successfully",
      "stderr": "",
      "screenshots": ["https://...screenshot1.png"],
      "download_count": 1,
      "duration_seconds": 45
    }
  }
}
```

### `task.error`

任务执行错误。

```json
{
  "type": "task.error",
  "id": "te-uuid-001",
  "timestamp": "2026-03-07T12:05:00Z",
  "payload": {
    "task_id": "task-uuid-001",
    "device_uid": "device-001",
    "status": "failed",
    "error": {
      "code": "APPSTORE_AUTH_REQUIRED",
      "message": "App Store requires password input",
      "step_index": 5,
      "needs_intervention": true
    }
  }
}
```

## Connection Lifecycle

```text
Client connects → auth via JWT → server sends ack
  ↓
Client sends device.register → server records devices
  ↓
Client sends heartbeat (every N seconds, configurable)
  ↓
Server sends command.dispatch when task assigned
  ↓
Client sends task.status / task.result / task.error
  ↓
On disconnect → server marks managed devices offline after timeout
On reconnect → client re-sends device.register + pulls pending commands
```

## Error Codes

| Code | Description |
|------|-------------|
| DEVICE_NOT_FOUND | 设备 UID 无效 |
| WDA_UNREACHABLE | 无法连接设备上的 WDA |
| SCRIPT_PARSE_ERROR | 脚本 JSON 解析失败 |
| STEP_TIMEOUT | 单步执行超时 |
| TASK_TIMEOUT | 整体任务超时 |
| APPSTORE_AUTH_REQUIRED | App Store 需要密码/验证码 |
| APPSTORE_NOT_LOGGED_IN | App Store 未登录 |
| APPLE_ID_BANNED | Apple ID 被封禁 |
| NETWORK_ERROR | 网络错误 |
| UNKNOWN_ERROR | 未知错误 |
