# Implementation Plan: iOS App Ranking System

**Branch**: `001-ios-ranking-system` | **Date**: 2026-03-07 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-ios-ranking-system/spec.md`

## Summary

构建一个三层架构的 iOS 刷榜系统：Python 服务端通过 WebSocket 管理和调度越狱 iOS 设备，Vue.js 后台提供管理界面（手动管理 + 智能管理），客户端通过 Appium+WebDriverAgent 在设备上执行自动化操作脚本。数据存储使用 MongoDB。智能管理支持探索阶段（随机策略测试）和实施阶段（有效策略批量推送），以目标 App 下载量增量衡量策略效果。

## Technical Context

**Language/Version**: Python 3.11+ (Server + Client Agent), TypeScript (Admin Vue.js)
**Primary Dependencies**: FastAPI, Uvicorn, Beanie ODM (MongoDB), Vue 3, Element Plus, Appium-Python-Client 5.x, WebDriverAgent
**Storage**: MongoDB 7.0+ (via PyMongo Async / Beanie)
**Testing**: pytest (Server + Client), Vitest (Admin)
**Target Platform**: Linux server (服务端), Web browser (后台), 伴生机 Mac/Linux (客户端 Agent), iOS 14+ jailbroken (WDA)
**Project Type**: Distributed system (web-service + companion-machine-agents + web-admin + on-device-WDA)
**Performance Goals**: 同时管理 100+ 台设备，命令下发延迟 <1s，心跳处理 <100ms
**Constraints**: 设备必须越狱并预装 WDA，伴生机与设备须同网络，Apple ID 凭据 AES-256 加密存储
**Scale/Scope**: 100+ 台设备，5-10 台伴生机，4 个子系统，11 个核心实体（含 ScriptVersion、CompanionMachine），21 个功能需求

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Three-Tier Architecture Separation | ✅ PASS | server/ / client/ / admin/ 独立部署，通过 shared/ API 契约通信 |
| II. Command-Driven Communication | ✅ PASS | WebSocket 下发结构化命令（含 UUID、类型、参数、超时），客户端只响应不自主 |
| III. Script Safety & Isolation | ✅ PASS | 脚本有超时机制、版本追溯、灰度发布支持 |
| IV. Real-Time Status Reporting | ✅ PASS | WebSocket 心跳上报，间隔可配置，超时标记离线 |
| V. Configuration-First Management | ✅ PASS | 配置存储在 MongoDB，通过服务端实时下发，支持设备/组/全局三维度 |
| VI. Security & Resilience | ✅ PASS | WSS/HTTPS 加密通信，设备指纹+Token 认证，Apple ID 加密存储，断连自动重连 |

**Gate Result**: ALL PASS — 可进入 Phase 0

## Project Structure

### Documentation (this feature)

```text
specs/001-ios-ranking-system/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── server-client-ws.md    # 服务端-客户端 WebSocket 协议
│   ├── server-admin-rest.md   # 服务端-后台 REST API
│   └── server-admin-ws.md     # 服务端-后台 WebSocket 实时推送
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
server/
├── src/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置加载
│   ├── models/              # MongoDB 数据模型 (Beanie ODM)
│   │   ├── device.py
│   │   ├── script.py
│   │   ├── task.py
│   │   ├── strategy.py
│   │   ├── apple_account.py
│   │   ├── user.py
│   │   └── configuration.py
│   ├── services/            # 业务逻辑
│   │   ├── device_manager.py
│   │   ├── command_dispatcher.py
│   │   ├── script_manager.py
│   │   ├── task_scheduler.py
│   │   ├── strategy_engine.py
│   │   └── auth_service.py
│   ├── api/                 # REST API 路由
│   │   ├── devices.py
│   │   ├── scripts.py
│   │   ├── tasks.py
│   │   ├── strategies.py
│   │   ├── config.py
│   │   └── auth.py
│   └── ws/                  # WebSocket 处理
│       ├── client_handler.py    # 客户端连接管理
│       └── admin_handler.py     # 后台实时推送
└── tests/
    ├── unit/
    ├── integration/
    └── contract/

client/                          # 伴生机 Agent（Python，运行在 Mac/Linux 上）
├── src/
│   ├── main.py              # Agent 入口（每台伴生机运行一个实例）
│   ├── config.py            # 本地配置（管理的设备列表、服务端地址等）
│   ├── ws_client.py         # 与服务端的 WebSocket 连接
│   ├── command_executor.py  # 命令执行调度（分发到对应设备）
│   ├── wda_driver.py        # WDA HTTP 操作封装（连接设备上的 WDA）
│   ├── heartbeat.py         # 心跳与状态上报（聚合所管理设备的状态）
│   ├── device_info.py       # 远程设备信息采集（通过 WDA 接口）
│   └── script_runner.py     # JSON 脚本解析与执行（翻译为 WDA 操作序列）
└── tests/

admin/
├── src/
│   ├── main.ts
│   ├── api/                 # REST API 调用封装
│   ├── ws/                  # WebSocket 实时数据
│   ├── views/               # 页面
│   │   ├── Dashboard.vue        # 仪表盘
│   │   ├── DeviceList.vue       # 设备管理
│   │   ├── ScriptEditor.vue     # 脚本编辑器
│   │   ├── TaskMonitor.vue      # 任务监控
│   │   ├── StrategyManager.vue  # 智能管理
│   │   ├── ConfigPanel.vue      # 配置管理
│   │   └── Login.vue            # 登录
│   ├── components/          # 通用组件
│   └── stores/              # Pinia 状态管理
└── tests/

shared/
├── api-contracts/           # API 契约定义 (JSON Schema)
│   ├── ws-messages.json     # WebSocket 消息格式
│   ├── rest-endpoints.json  # REST API 端点
│   └── script-schema.json   # 脚本 JSON 格式定义
├── error-codes/
│   └── codes.json           # 统一错误码
└── constants/
    └── enums.json           # 共享枚举值
```

**Structure Decision**: 采用 Monorepo 结构（server + client + admin + shared），与 Constitution 的三层架构原则一致。client 采用 Python（Appium-Python-Client），运行在伴生机（Companion Machine）上，通过 HTTP 控制越狱 iPhone 上的 WDA。每台伴生机管理 10-20 台 iOS 设备。共享契约放在 shared/ 目录作为 Single Source of Truth。

## Complexity Tracking

> 无 Constitution 违规，无需记录。
