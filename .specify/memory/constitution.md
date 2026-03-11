<!--
  Sync Impact Report
  ==================
  Version change: N/A → 1.0.0 (Initial creation)
  
  Added principles:
    - I. Three-Tier Architecture Separation
    - II. Command-Driven Communication
    - III. Script Safety & Isolation
    - IV. Real-Time Status Reporting
    - V. Configuration-First Management
    - VI. Security & Resilience
  
  Added sections:
    - Core Principles (6 principles)
    - System Architecture Constraints
    - Development Workflow
    - Governance
  
  Removed sections: N/A (initial creation)
  
  Templates requiring updates:
    - .specify/templates/plan-template.md ✅ compatible (no changes needed)
    - .specify/templates/spec-template.md ✅ compatible (no changes needed)
    - .specify/templates/tasks-template.md ✅ compatible (mobile path convention already present)
    - .specify/templates/checklist-template.md ✅ compatible
    - .specify/templates/agent-file-template.md ✅ compatible
  
  Follow-up TODOs: None
-->

# IOSAgent Constitution

## Core Principles

### I. Three-Tier Architecture Separation

系统 MUST 严格划分为三个独立层级：**服务端（Server）**、**客户端（Client Agent，运行在伴生机上）**、**后台（Admin）**。

- 服务端负责调度和控制所有客户端，是唯一的指令下发中心
- 客户端是运行在伴生机（Companion Machine）上的 Python Agent，通过 HTTP 控制越狱 iOS 设备上的 WDA（WebDriverAgent），MUST NOT 自主发起业务动作，只响应服务端指令
- iOS 设备仅运行 WDA，不直接与服务端通信，由伴生机代理管理
- 后台负责管理配置、发布脚本、监控设备状态，MUST NOT 直接向客户端下发指令
- 数据流向：后台 → 服务端 → 伴生机 Agent → iOS 设备（WDA），iOS 设备 → 伴生机 Agent → 服务端 → 后台
- 三层之间通过明确定义的 API 契约通信，禁止跨层直接访问

### II. Command-Driven Communication

客户端的所有行为 MUST 由服务端指令驱动。

- 服务端向客户端下发结构化命令（含命令类型、参数、超时设置）
- 客户端接收命令后执行，完成后 MUST 回报执行结果（成功/失败/异常详情）
- 命令 MUST 具备唯一标识，支持追踪和幂等重试
- 服务端 MUST 维护每个客户端的命令队列和执行状态

### III. Script Safety & Isolation

远端下发的脚本 MUST 在受控环境中执行。

- 脚本由后台发布，经服务端分发到客户端
- 客户端执行脚本时 MUST 有超时机制，防止无限挂起
- 脚本执行结果（stdout/stderr/exit code）MUST 完整上报
- 脚本版本 MUST 可追溯，支持回滚到上一个已知可用版本
- 脚本更新 MUST 支持灰度发布（先部分设备验证，再全量推送）

### IV. Real-Time Status Reporting

客户端 MUST 持续向服务端上报设备状态。

- 上报内容包括但不限于：设备在线状态、电量、网络状况、当前执行任务、App Store 登录状态
- 心跳间隔 MUST 可配置（由后台设定）
- 服务端 MUST 在心跳超时后将设备标记为离线
- 后台 MUST 能实时查看所有设备的聚合状态面板

### V. Configuration-First Management

所有客户端行为参数 MUST 由后台配置驱动，MUST NOT 硬编码在客户端中。

- 配置包括：任务调度策略、心跳间隔、重试次数、脚本版本、目标 App 信息等
- 配置变更 MUST 通过服务端实时下发到客户端，无需客户端重启
- 后台 MUST 支持按设备/设备组/全局三个维度管理配置
- 配置变更 MUST 有审计日志

### VI. Security & Resilience

系统 MUST 具备安全防护和容错能力。

- 服务端与客户端之间的通信 MUST 加密（TLS/HTTPS）
- 客户端身份 MUST 经过服务端认证（设备指纹 + Token）
- 客户端 MUST 能在网络断连后自动重连并恢复任务状态
- 服务端 MUST 能处理客户端异常退出、脚本崩溃等故障场景
- 敏感数据（Apple ID 凭据等）MUST 加密存储，MUST NOT 明文传输或记录在日志中

## System Architecture Constraints

### Technology Stack

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 服务端 | Python | 负责设备调度、命令下发、状态管理 |
| 客户端 Agent | Python (伴生机) + WDA (iOS 设备) | 伴生机通过 HTTP 控制越狱设备上的 WDA |
| 后台 | Vue.js | Web 管理界面，实时数据展示 |
| 通信协议 | WebSocket + REST | 服务端-客户端使用 WebSocket，后台-服务端使用 REST + WebSocket |
| 数据库 | MongoDB | 存储设备状态、任务记录、脚本配置等 |

### Monorepo Structure

```text
IOSAgent/
├── server/              # 服务端（Python FastAPI）
│   ├── src/
│   └── tests/
├── client/              # 伴生机 Agent（Python，控制 iOS 设备上的 WDA）
│   ├── src/
│   └── tests/
├── admin/               # 后台管理（Vue.js）
│   ├── src/
│   └── tests/
├── shared/              # 共享定义
│   ├── api-contracts/   # API 契约（接口定义、数据模型）
│   ├── error-codes/     # 统一错误码
│   └── constants/       # 共享常量
└── docs/                # 项目文档
```

### Non-Negotiable Constraints

- 每个层级 MUST 可独立部署和升级
- `shared/` 中的契约定义是三层间的 Single Source of Truth
- 服务端 MUST 可实时下发新版本脚本到伴生机 Agent，无需重启 Agent 即可执行
- 后台操作 MUST 有操作审计日志
- 系统 MUST 支持同时管理至少 100 台设备

## Development Workflow

### API-First Development

1. 在 `shared/api-contracts/` 中定义接口契约
2. 服务端根据契约实现 API
3. 客户端根据契约实现调用
4. 后台根据契约实现管理功能

### Branch Strategy

- `main`：稳定发布版本
- `dev`：开发集成分支
- `feature/*`：功能分支
- `hotfix/*`：紧急修复分支

### Quality Gates

- 所有 API 变更 MUST 先更新 `shared/api-contracts/`
- 服务端和后台代码 MUST 通过自动化测试
- 客户端脚本 MUST 在测试设备上验证后再全量发布
- 配置变更 MUST 经过 review 后生效

## Governance

- 本 Constitution 是项目的最高规范文件，所有开发实践 MUST 与其保持一致
- 修改 Constitution MUST 提交变更说明，经团队 review 后合并
- 每次修改 MUST 更新版本号（遵循语义化版本：MAJOR.MINOR.PATCH）
- 所有 PR/Code Review MUST 验证是否符合 Constitution 中的原则
- 运行时开发指引参见 `docs/` 目录下的具体文档

**Version**: 1.1.0 | **Ratified**: 2026-03-07 | **Last Amended**: 2026-03-07
