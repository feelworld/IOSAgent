# Research: iOS App Ranking System

**Branch**: `001-ios-ranking-system` | **Date**: 2026-03-07

## R1: Python 服务端框架选型

**Decision**: FastAPI + Uvicorn

**Rationale**: FastAPI 基于 ASGI 原生支持 WebSocket，同一应用可同时服务 REST API（后台）和 WebSocket（客户端设备）。配合 Uvicorn + uvloop 性能优秀，Pydantic v2 提供自动校验和 OpenAPI 文档生成。

**Alternatives considered**:
- Django Channels：需 Redis 做多进程协调，与 Motor/PyMongo Async 集成有事件循环冲突风险，整体偏重
- Tornado：长连接性能好但生态不如 FastAPI，缺少 Pydantic 等现代工具
- aiohttp：需手写路由、校验、文档，无 OpenAPI 自动生成，开发效率低

**Key dependencies**:
```text
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
pydantic>=2.0.0
```

**MongoDB 驱动说明**: Motor 计划 2026 年 5 月后进入维护期，推荐使用 PyMongo Async（`AsyncMongoClient`），API 与 Motor 类似，迁移成本低。若需跨实例 WebSocket 广播，可加 Redis Pub/Sub。

---

## R2: 客户端架构（Appium + WDA）

**Decision**: 伴生机架构（Companion Machine）

**Rationale**: Python 客户端运行在伴生机（Mac/Linux/Windows）上，通过 HTTP 控制越狱 iPhone 上预装的 WebDriverAgent。越狱设备上 Python 版本过旧（多为 2.7/3.7），依赖链难以满足 Appium-Python-Client 5.x 的要求（需 Python 3.9+ 和 Selenium 4.26+），且手机资源有限不适合长期运行自动化客户端。

**Architecture**:
```text
服务端 (FastAPI)
    │ WebSocket
    ▼
伴生机 N 台 (Python Client)
    │ HTTP (http://<device_ip>:8100)
    ▼
iOS 设备 (仅运行 WDA)
```

- 每台伴生机负责 10-20 台 iOS 设备
- 设备通过 Wi-Fi 暴露 WDA 端口（8100）
- 伴生机通过 WebSocket 连接服务端接收命令，通过 HTTP 连接设备上的 WDA 执行操作

**Alternatives considered**:
- Python 直接跑在 iPhone 上：Python 版本受限、依赖不全、手机资源紧张
- 完整 Appium Server 部署：多了一层中间代理，对越狱设备直连 WDA 不必要
- 直连 WDA 库（wdapy）：更轻量但功能有限，Appium-Python-Client 生态更成熟

**Key dependencies**:
```text
Appium-Python-Client>=5.1.1
selenium>=4.26.0,<5.0
```

**Key constraints**:
- 每台 iOS 设备 MUST 预装并启动 WDA
- 设备与伴生机 MUST 在同一网络（Wi-Fi）或使用 USB 端口转发
- iOS 17+ 设备需移除 WDA 中 XC* framework
- 大规模部署需要多台伴生机分担设备连接

---

## R3: Vue 3 后台管理框架选型

**Decision**: Vue 3 + Element Plus

**Rationale**: Element Plus 的 Table V2 虚拟表格天然适合 100+ 设备列表，组件库齐全（表单、表格、布局），国内生态和文档完善，维护活跃，适合企业级后台管理系统。

**Alternatives considered**:
- Ant Design Vue：维护更新变慢
- Vuetify 3：偏 Material 风格，包体较大
- Naive UI：生态和模板较少，复杂表格场景性能有反馈

**Recommended stack**:

| 用途 | 选型 |
|------|------|
| 框架 | Vue 3 (Composition API) |
| UI 库 | Element Plus |
| 状态管理 | Pinia |
| 图表 | vue-echarts + ECharts |
| 脚本编辑器 | monaco-editor-vue3 |
| WebSocket | 原生 WebSocket |
| 构建工具 | Vite |
| 路由 | Vue Router 4 |

**Key dependencies**:
```text
vue@^3.4.x
element-plus@^2.8.x
pinia@^2.1.x
vue-router@^4.x
vue-echarts@^7.x
echarts@^5.x
monaco-editor-vue3@^1.x
vite@^5.x
```

---

## R4: MongoDB ODM 选型

**Decision**: Beanie ODM（基于 PyMongo Async / Motor）

**Rationale**: Beanie 是 Python 的异步 MongoDB ODM，基于 Pydantic v2 模型定义，与 FastAPI 天然集成。支持文档验证、查询构建器、迁移工具。比直接使用 PyMongo Async 更有结构性，比 MongoEngine 更适合异步场景。

**Alternatives considered**:
- 直接 PyMongo Async：灵活但缺乏模型定义和验证，代码维护性差
- MongoEngine：不支持原生异步，与 FastAPI 配合需额外封装
- ODMantic：功能不如 Beanie 成熟

**Key dependencies**:
```text
beanie>=1.26.0
```

---

## R5: 安全通信方案

**Decision**: WSS (WebSocket Secure) + HTTPS + JWT

**Rationale**: 服务端与伴生机之间使用 WSS 加密 WebSocket 通信，后台与服务端之间使用 HTTPS REST API。身份认证使用 JWT Token，设备认证额外使用设备指纹（Device Fingerprint）作为辅助验证。Apple ID 凭据使用 AES-256 加密存储在 MongoDB 中。

**Key dependencies**:
```text
python-jose[cryptography]>=3.3.0   # JWT
cryptography>=43.0.0               # AES-256 加密
passlib[bcrypt]>=1.7.4             # 密码哈希
```
