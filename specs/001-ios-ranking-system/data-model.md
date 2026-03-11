# Data Model: iOS App Ranking System

**Branch**: `001-ios-ranking-system` | **Date**: 2026-03-07
**Storage**: MongoDB 7.0+ via Beanie ODM

## Entity Overview

```text
User ──────── Role (1:N)
Device ─┬──── DeviceGroup (N:N)
        ├──── AppleAccount (1:N, 主账号+备用池)
        └──── Task (1:N)
Script ─┬──── ScriptVersion (1:N)
        └──── Strategy (1:N)
Task ───┬──── Device (N:1)
        └──── ScriptVersion (N:1)
Strategy ──── Script (N:1)
Configuration ── scope: device | device_group | global
```

## Entities

### Device

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | MongoDB 自动生成 | PK |
| device_uid | string | 设备唯一标识（UDID 或设备指纹） | unique, indexed |
| name | string | 设备别名 | optional |
| model | string | 设备型号（如 iPhone 12） | required |
| ios_version | string | iOS 系统版本 | required |
| status | enum | online / offline / busy / error / maintenance | indexed, default: offline |
| battery_level | int | 电量百分比 (0-100) | |
| network_type | string | Wi-Fi / Cellular / None | |
| wda_url | string | WDA 访问地址（http://ip:8100） | required |
| companion_id | string | 所属伴生机标识 | indexed |
| current_apple_id | ObjectId | 当前绑定的 Apple ID 账号 | ref: AppleAccount |
| group_ids | ObjectId[] | 所属设备组列表 | ref: DeviceGroup[] |
| current_task_id | ObjectId | 当前执行的任务 | ref: Task, nullable |
| last_heartbeat | datetime | 最后心跳时间 | indexed |
| registered_at | datetime | 注册时间 | |
| metadata | object | 扩展信息（屏幕分辨率、存储等） | |

**State transitions**:
```text
(new) → offline → online → busy → online
                      ↓         ↓
                   error → maintenance → online
                      ↓
                   offline (heartbeat timeout)
```

### AppleAccount

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| email | string | Apple ID 邮箱 | unique, indexed |
| encrypted_password | string | AES-256 加密密码 | required |
| status | enum | active / banned / suspended / unknown | indexed |
| bound_device_id | ObjectId | 当前绑定设备 | ref: Device, nullable |
| is_primary | boolean | 是否为该设备的主账号 | default: false |
| pool_group | string | 备用账号池分组标识 | indexed |
| last_used_at | datetime | 最后使用时间 | |
| banned_at | datetime | 封禁时间 | nullable |
| created_at | datetime | 录入时间 | |

### Script

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| name | string | 脚本名称 | required, indexed |
| description | string | 脚本描述 | optional |
| current_version | int | 当前生效版本号 | required |
| status | enum | draft / published / deprecated | indexed |
| created_by | ObjectId | 创建者 | ref: User |
| created_at | datetime | 创建时间 | |
| updated_at | datetime | 最后修改时间 | |

### ScriptVersion

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| script_id | ObjectId | 所属脚本 | ref: Script, indexed |
| version | int | 版本号（递增） | required |
| steps | object[] | JSON 结构化操作步骤 | required |
| steps[].action | string | 操作类型（tap/swipe/type/wait/search/scroll/launch_app 等） | required |
| steps[].target | string | 操作目标（元素 xpath/id/name） | required for interactive actions |
| steps[].params | object | 操作参数（text/duration/direction 等） | optional |
| steps[].timeout | int | 单步超时（秒） | default: 30 |
| changelog | string | 版本变更说明 | optional |
| published_at | datetime | 发布时间 | nullable |
| created_at | datetime | 创建时间 | |

### Task

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| task_uid | string | 任务唯一标识（UUID） | unique, indexed |
| device_id | ObjectId | 执行设备 | ref: Device, indexed |
| script_id | ObjectId | 关联脚本 | ref: Script |
| script_version | int | 执行的脚本版本号 | required |
| strategy_id | ObjectId | 关联策略（智能管理时） | ref: Strategy, nullable |
| status | enum | pending / dispatched / running / success / failed / timeout / cancelled | indexed |
| params | object | 脚本参数（目标 App 名称等） | |
| result | object | 执行结果详情 | nullable |
| result.stdout | string | 标准输出 | |
| result.stderr | string | 错误输出 | |
| result.screenshots | string[] | 截图 URL 列表 | |
| result.download_count | int | 本次执行产生的下载数 | |
| error_message | string | 错误信息 | nullable |
| dispatched_at | datetime | 下发时间 | |
| started_at | datetime | 开始执行时间 | nullable |
| completed_at | datetime | 完成时间 | nullable |
| timeout_seconds | int | 超时设置（秒） | default: 300 |
| retry_count | int | 已重试次数 | default: 0 |
| max_retries | int | 最大重试次数 | default: 3 |
| source | enum | manual / explore / execute | 任务来源 |
| created_at | datetime | 创建时间 | |

**State transitions**:
```text
pending → dispatched → running → success
                          ↓        ↓
                       timeout   failed
                          ↓        ↓
                       (retry if retry_count < max_retries → pending)
                       cancelled (manual stop)
```

### Strategy

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| name | string | 策略名称 | required |
| script_id | ObjectId | 关联脚本 | ref: Script, indexed |
| script_version | int | 使用的脚本版本 | required |
| params | object | 脚本参数配置 | required |
| device_criteria | object | 适用设备条件（型号、系统版本等） | |
| phase | enum | explore / execute | indexed |
| status | enum | active / paused / completed / abandoned | indexed |
| effectiveness_score | float | 效果评分（基于下载量增量） | default: 0.0 |
| total_executions | int | 总执行次数 | default: 0 |
| successful_executions | int | 成功执行次数 | default: 0 |
| total_downloads | int | 累计产生下载量 | default: 0 |
| explore_session_id | string | 探索会话标识 | nullable, indexed |
| created_at | datetime | 创建时间 | |
| updated_at | datetime | 最后更新时间 | |

### DeviceGroup

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| name | string | 组名 | unique, required |
| description | string | 描述 | optional |
| device_ids | ObjectId[] | 设备列表 | ref: Device[] |
| config_overrides | object | 组级配置覆盖 | |
| created_at | datetime | 创建时间 | |

### User

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| username | string | 用户名 | unique, required |
| hashed_password | string | bcrypt 哈希密码 | required |
| role_id | ObjectId | 角色 | ref: Role |
| is_active | boolean | 是否启用 | default: true |
| last_login_at | datetime | 最后登录时间 | nullable |
| created_at | datetime | 创建时间 | |

### Role

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| name | string | 角色名 | unique, required |
| permissions | string[] | 权限标识列表 | default: ["*"] for admin |
| description | string | 角色描述 | optional |
| created_at | datetime | 创建时间 | |

初始数据：创建 `admin` 角色，permissions 为 `["*"]`（全部权限）。

### Configuration

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| key | string | 配置键名 | required |
| value | any | 配置值 | required |
| scope | enum | global / device_group / device | required, indexed |
| scope_id | ObjectId | 作用对象ID（设备或设备组） | nullable, indexed |
| description | string | 配置说明 | optional |
| updated_by | ObjectId | 最后修改者 | ref: User |
| updated_at | datetime | 最后修改时间 | |

**预置配置项**:
| key | default | description |
|-----|---------|-------------|
| heartbeat_interval | 30 | 心跳间隔（秒） |
| heartbeat_timeout | 90 | 心跳超时判定离线（秒） |
| script_timeout | 300 | 脚本默认超时（秒） |
| max_retries | 3 | 命令最大重试次数 |
| command_expire_seconds | 3600 | 离线命令过期时间（秒） |

### CompanionMachine（伴生机）

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| _id | ObjectId | PK | |
| machine_id | string | 伴生机唯一标识 | unique, indexed |
| name | string | 伴生机名称 | optional |
| ip_address | string | IP 地址 | |
| status | enum | online / offline | indexed |
| managed_device_ids | ObjectId[] | 管理的设备列表 | ref: Device[] |
| max_devices | int | 最大管理设备数 | default: 20 |
| last_heartbeat | datetime | 最后心跳 | |
| registered_at | datetime | 注册时间 | |

## Indexes

```text
Device: { device_uid: 1 } unique
Device: { status: 1, last_heartbeat: -1 }
Device: { companion_id: 1 }
AppleAccount: { email: 1 } unique
AppleAccount: { status: 1, pool_group: 1 }
Task: { task_uid: 1 } unique
Task: { device_id: 1, status: 1 }
Task: { strategy_id: 1 }
Task: { created_at: -1 }
Strategy: { phase: 1, status: 1 }
Strategy: { explore_session_id: 1 }
Configuration: { key: 1, scope: 1, scope_id: 1 } unique
CompanionMachine: { machine_id: 1 } unique
```
