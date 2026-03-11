# WebSocket Contract: Server → Admin (Real-time Push)

**Protocol**: WSS
**Endpoint**: `wss://<server>/ws/admin`
**Authentication**: JWT token in query param `?token=xxx`

## Purpose

后台通过此 WebSocket 连接接收服务端的实时推送，用于：
- 设备状态变更通知
- 任务状态实时更新
- 仪表盘数据刷新
- 系统告警

## Message Format

```json
{
  "type": "<event_type>",
  "timestamp": "<ISO8601>",
  "payload": { ... }
}
```

## Event Types

### `device.status_changed`

设备状态变更。

```json
{
  "type": "device.status_changed",
  "timestamp": "2026-03-07T12:00:30Z",
  "payload": {
    "device_uid": "device-001",
    "old_status": "online",
    "new_status": "busy",
    "battery_level": 80,
    "current_task_id": "task-001"
  }
}
```

### `device.heartbeat`

设备心跳更新（批量推送，降低频率）。

```json
{
  "type": "device.heartbeat",
  "timestamp": "2026-03-07T12:00:30Z",
  "payload": {
    "devices": [
      { "device_uid": "device-001", "battery_level": 85, "status": "online" },
      { "device_uid": "device-002", "battery_level": 72, "status": "busy" }
    ]
  }
}
```

### `task.updated`

任务状态更新。

```json
{
  "type": "task.updated",
  "timestamp": "2026-03-07T12:01:00Z",
  "payload": {
    "task_id": "task-001",
    "device_uid": "device-001",
    "status": "running",
    "progress": 50
  }
}
```

### `task.completed`

任务完成（成功或失败）。

```json
{
  "type": "task.completed",
  "timestamp": "2026-03-07T12:05:00Z",
  "payload": {
    "task_id": "task-001",
    "device_uid": "device-001",
    "status": "success",
    "download_count": 1,
    "duration_seconds": 45
  }
}
```

### `dashboard.stats`

仪表盘数据周期性推送（每 10 秒）。

```json
{
  "type": "dashboard.stats",
  "timestamp": "2026-03-07T12:00:10Z",
  "payload": {
    "devices_online": 92,
    "devices_total": 105,
    "tasks_running": 8,
    "tasks_success_today": 280,
    "downloads_today": 250
  }
}
```

### `alert`

系统告警。

```json
{
  "type": "alert",
  "timestamp": "2026-03-07T12:00:00Z",
  "payload": {
    "level": "warning",
    "code": "APPLE_ID_BANNED",
    "message": "Apple ID xxx@icloud.com 已被封禁",
    "device_uid": "device-001",
    "action_taken": "auto_switched_to_backup"
  }
}
```

### `strategy.effectiveness_changed`

策略效果变化通知。

```json
{
  "type": "strategy.effectiveness_changed",
  "timestamp": "2026-03-07T12:00:00Z",
  "payload": {
    "strategy_id": "strategy-001",
    "phase": "execute",
    "old_score": 0.85,
    "new_score": 0.6,
    "alert": "效果显著下降，建议检查"
  }
}
```

## Admin → Server Messages

后台可通过 WebSocket 发送订阅控制：

### `subscribe`

```json
{
  "type": "subscribe",
  "payload": {
    "channels": ["device.status_changed", "task.updated", "dashboard.stats", "alert"]
  }
}
```

### `unsubscribe`

```json
{
  "type": "unsubscribe",
  "payload": {
    "channels": ["device.heartbeat"]
  }
}
```
