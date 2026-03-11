# REST API Contract: Server ↔ Admin

**Protocol**: HTTPS
**Base URL**: `https://<server>/api/v1`
**Authentication**: Bearer JWT token in `Authorization` header
**Content-Type**: `application/json`

## Response Format

```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

Error response:
```json
{
  "code": 40001,
  "message": "Device not found",
  "data": null
}
```

## Auth Endpoints

### POST /auth/login

```json
Request:  { "username": "admin", "password": "xxx" }
Response: { "access_token": "jwt...", "token_type": "bearer", "expires_in": 86400 }
```

### GET /auth/me

```json
Response: { "id": "...", "username": "admin", "role": "admin", "permissions": ["*"] }
```

## Device Endpoints

### GET /devices

查询设备列表，支持筛选和分页。

```text
Query params: ?status=online&group_id=xxx&page=1&size=20&sort=last_heartbeat:desc
```

```json
Response: {
  "items": [
    {
      "id": "...",
      "device_uid": "device-001",
      "model": "iPhone 12",
      "ios_version": "15.7",
      "status": "online",
      "battery_level": 85,
      "network_type": "Wi-Fi",
      "current_apple_id": { "email": "xxx@icloud.com", "status": "active" },
      "companion": { "machine_id": "companion-001", "name": "Mac-01" },
      "group_names": ["Group A"],
      "current_task_id": null,
      "last_heartbeat": "2026-03-07T12:00:30Z"
    }
  ],
  "total": 105,
  "page": 1,
  "size": 20
}
```

### GET /devices/{id}

获取单个设备详情。

### GET /devices/stats

聚合统计。

```json
Response: {
  "total": 105,
  "online": 92,
  "offline": 8,
  "busy": 3,
  "error": 2,
  "online_rate": 0.876
}
```

## Script Endpoints

### GET /scripts

```text
Query: ?status=published&page=1&size=20
```

### POST /scripts

```json
Request: {
  "name": "App Store 搜索下载",
  "description": "搜索指定关键词并下载目标 App",
  "steps": [
    { "action": "launch_app", "target": "com.apple.AppStore", "params": {} },
    { "action": "tap", "target": "//XCUIElementTypeButton[@name='Search']", "params": {} },
    { "action": "type", "target": "//XCUIElementTypeSearchField", "params": { "text": "{{keyword}}" } },
    { "action": "wait", "target": "", "params": { "seconds": 3 } },
    { "action": "tap", "target": "//XCUIElementTypeButton[@name='GET']", "params": {} }
  ]
}
Response: { "id": "...", "name": "...", "current_version": 1, "status": "draft" }
```

### PUT /scripts/{id}

更新脚本（自动创建新版本）。

### POST /scripts/{id}/publish

发布当前版本。

### POST /scripts/{id}/rollback

```json
Request: { "target_version": 1 }
```

### GET /scripts/{id}/versions

获取版本历史。

## Task Endpoints

### POST /tasks/dispatch

手动下发任务。

```json
Request: {
  "device_ids": ["device-id-1", "device-id-2"],
  "script_id": "script-001",
  "script_version": 3,
  "params": { "keyword": "TargetApp" },
  "timeout_seconds": 300
}
Response: {
  "tasks": [
    { "task_id": "task-001", "device_id": "device-id-1", "status": "pending" },
    { "task_id": "task-002", "device_id": "device-id-2", "status": "pending" }
  ]
}
```

### GET /tasks

```text
Query: ?status=running&device_id=xxx&source=manual&page=1&size=20&sort=created_at:desc
```

### GET /tasks/{id}

获取任务详情（含执行结果）。

### POST /tasks/{id}/cancel

取消任务。

### GET /tasks/stats

```json
Response: {
  "total": 1520,
  "pending": 12,
  "running": 8,
  "success": 1350,
  "failed": 120,
  "timeout": 30,
  "success_rate": 0.888
}
```

## Strategy Endpoints

### POST /strategies/explore/start

启动探索阶段。

```json
Request: {
  "script_id": "script-001",
  "device_count": 10,
  "rounds": 5,
  "param_variations": [
    { "keyword": "TargetApp" },
    { "keyword": "target app best" },
    { "keyword": "target application" }
  ]
}
Response: {
  "explore_session_id": "session-001",
  "strategies_created": 3,
  "devices_assigned": 10
}
```

### POST /strategies/explore/{session_id}/stop

停止探索。

### GET /strategies/explore/{session_id}/analysis

获取探索分析结果。

```json
Response: {
  "session_id": "session-001",
  "total_executions": 50,
  "strategies": [
    {
      "id": "strategy-001",
      "params": { "keyword": "TargetApp" },
      "executions": 20,
      "success_rate": 0.9,
      "total_downloads": 18,
      "effectiveness_score": 0.9
    }
  ],
  "recommended_strategies": ["strategy-001"]
}
```

### POST /strategies/execute/start

启动实施阶段。

```json
Request: {
  "strategy_ids": ["strategy-001"],
  "device_ids": [] 
}
```

空 `device_ids` 表示分配到所有可用设备。

### GET /strategies

```text
Query: ?phase=explore&status=active
```

## Configuration Endpoints

### GET /configs

```text
Query: ?scope=global  or  ?scope=device&scope_id=xxx
```

### PUT /configs

```json
Request: {
  "key": "heartbeat_interval",
  "value": 15,
  "scope": "device",
  "scope_id": "device-id-001"
}
```

## Device Group Endpoints

### GET /groups
### POST /groups
### PUT /groups/{id}
### DELETE /groups/{id}
### POST /groups/{id}/devices

添加设备到组。

```json
Request: { "device_ids": ["device-001", "device-002"] }
```

## Apple Account Endpoints

### GET /apple-accounts
### POST /apple-accounts

```json
Request: { "email": "xxx@icloud.com", "password": "xxx", "pool_group": "pool-a" }
```

密码在传输后由服务端 AES-256 加密存储。

### POST /apple-accounts/{id}/bind

```json
Request: { "device_id": "device-001", "is_primary": true }
```

### POST /apple-accounts/{id}/unbind

## Dashboard Endpoint

### GET /dashboard

```json
Response: {
  "devices": { "total": 105, "online": 92, "offline": 8, "busy": 3, "error": 2 },
  "tasks_today": { "total": 320, "success": 280, "failed": 30, "running": 10 },
  "strategies": { "active_explore": 2, "active_execute": 1 },
  "downloads_today": 250,
  "downloads_total": 12500
}
```
