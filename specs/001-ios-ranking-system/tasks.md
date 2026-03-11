# Tasks: iOS App Ranking System

**Input**: Design documents from `/specs/001-ios-ranking-system/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Server**: `server/src/`, `server/tests/`
- **Client Agent**: `client/src/`, `client/tests/`
- **Admin**: `admin/src/`, `admin/tests/`
- **Shared**: `shared/`

---

## Phase 1: Setup (Project Initialization)

**Purpose**: Create monorepo structure, initialize all sub-projects with dependencies

- [x] T001 Create monorepo directory structure per plan.md (`server/`, `client/`, `admin/`, `shared/`)
- [x] T002 [P] Initialize server Python project with `server/requirements.txt` (fastapi, uvicorn, beanie, pydantic, python-jose, cryptography, passlib, websockets)
- [x] T003 [P] Initialize client Python project with `client/requirements.txt` (Appium-Python-Client, selenium, websockets, pyyaml)
- [x] T004 [P] Initialize admin Vue 3 project with Vite in `admin/` (vue, element-plus, pinia, vue-router, vue-echarts, echarts, monaco-editor-vue3, axios)
- [x] T005 [P] Create shared contract files: `shared/api-contracts/ws-messages.json`, `shared/api-contracts/rest-endpoints.json`, `shared/api-contracts/script-schema.json`
- [x] T006 [P] Create shared constants: `shared/error-codes/codes.json`, `shared/constants/enums.json`
- [x] T007 [P] Create server `.env.example` with MONGODB_URL, JWT_SECRET, AES_KEY, HOST, PORT placeholders in `server/.env.example`
- [x] T008 [P] Create client `config.example.yaml` with server_url, machine_id, devices list placeholders in `client/config.example.yaml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can begin

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T009 Create server config loader with environment variable parsing in `server/src/config.py`
- [x] T010 Create FastAPI application entry point with CORS, error handling, lifespan (MongoDB init) in `server/src/main.py`
- [x] T011 [P] Create User Beanie model with username, hashed_password, role_id, is_active, timestamps in `server/src/models/user.py`
- [x] T012 [P] Create Role Beanie model with name, permissions[], description in `server/src/models/role.py`
- [x] T013 [P] Create Device Beanie model with all fields from data-model.md (device_uid, model, ios_version, status enum, battery, wda_url, companion_id, etc.) in `server/src/models/device.py`
- [x] T014 [P] Create CompanionMachine Beanie model with machine_id, status, managed_device_ids, max_devices in `server/src/models/companion.py`
- [x] T015 [P] Create AppleAccount Beanie model with email, encrypted_password (AES-256), status enum, bound_device_id, pool_group in `server/src/models/apple_account.py`
- [x] T016 [P] Create Script Beanie model with name, current_version, status enum in `server/src/models/script.py`
- [x] T017 [P] Create ScriptVersion Beanie model with script_id, version, steps[] (action/target/params/timeout) in `server/src/models/script.py`
- [x] T018 [P] Create Task Beanie model with task_uid, device_id, script_id, status enum, params, result, timeout, retry fields in `server/src/models/task.py`
- [x] T019 [P] Create Configuration Beanie model with key, value, scope enum, scope_id in `server/src/models/configuration.py`
- [x] T020 [P] Create Strategy Beanie model with script_id, params, phase enum, status, effectiveness_score, execution stats in `server/src/models/strategy.py`
- [x] T021 [P] Create DeviceGroup Beanie model with name, device_ids[], config_overrides in `server/src/models/device_group.py`
- [x] T022 Implement auth service with JWT token generation/validation, password hashing (bcrypt), login logic in `server/src/services/auth_service.py`
- [x] T023 Implement auth REST API endpoints (POST /auth/login, GET /auth/me) in `server/src/api/auth.py`
- [x] T024 Implement AES-256 encryption utility for Apple ID credentials in `server/src/utils/crypto.py`
- [x] T025 Create MongoDB initialization with Beanie document registration and seed data (admin role + default user) in `server/src/db.py`
- [x] T026 [P] Create admin Vue project skeleton: router setup, layout component, Pinia stores structure in `admin/src/main.ts` and `admin/src/router/index.ts`
- [x] T027 [P] Create admin Login page with JWT auth flow in `admin/src/views/Login.vue` and `admin/src/api/auth.ts`
- [x] T028 [P] Create admin API client with axios instance, JWT interceptor, base URL config in `admin/src/api/client.ts`
- [x] T029 [P] Create admin WebSocket client utility with auto-reconnect and event handling in `admin/src/ws/client.ts`
- [x] T030 [P] Create client agent config loader (YAML parsing, server URL, machine_id, device list) in `client/src/config.py`
- [x] T031 Create client agent WebSocket connection manager with JWT auth, auto-reconnect, message routing in `client/src/ws_client.py`
- [x] T032 Create configuration service with scope-based lookup (device > group > global fallback) in `server/src/services/config_service.py`

**Checkpoint**: Foundation ready — all models defined, auth working, WebSocket infrastructure ready. User story implementation can now begin.

---

## Phase 3: User Story 2 - 客户端设备注册与状态上报 (Priority: P1)

**Goal**: 伴生机启动后自动注册管理的设备，持续心跳上报，服务端维护设备状态，后台实时展示

**Independent Test**: 启动一个 client agent，观察服务端收到 device.register，后台 DeviceList 显示设备为 online，断开后自动标记 offline

### Implementation for User Story 2

- [x] T033 [P] [US2] Implement device_info collector: gather device info via WDA HTTP API (model, iOS version, battery, etc.) in `client/src/device_info.py`
- [x] T034 [P] [US2] Implement heartbeat sender: periodic status aggregation and WebSocket heartbeat message in `client/src/heartbeat.py`
- [x] T035 [US2] Implement client agent main entry: load config → connect WS → register devices → start heartbeat loop in `client/src/main.py`
- [x] T036 [US2] Implement device manager service: register device, update heartbeat, detect offline (timeout checker background task) in `server/src/services/device_manager.py`
- [x] T037 [US2] Implement server WebSocket client handler: accept connection, authenticate, route device.register + heartbeat messages in `server/src/ws/client_handler.py`
- [x] T038 [US2] Implement server WebSocket admin handler: broadcast device status changes, heartbeat batches to subscribed admin clients in `server/src/ws/admin_handler.py`
- [x] T039 [US2] Implement device REST API: GET /devices (list+filter+paginate), GET /devices/{id}, GET /devices/stats in `server/src/api/devices.py`
- [x] T040 [US2] Create admin DeviceList page: device table (Element Plus el-table-v2), status badges, filter by status/group, real-time WS updates in `admin/src/views/DeviceList.vue`
- [x] T041 [US2] Create admin device Pinia store: fetch devices, handle WS device.status_changed events in `admin/src/stores/device.ts`

**Checkpoint**: Devices register, heartbeat flows, admin shows real-time device status. US2 independently testable.

---

## Phase 4: User Story 1 - 后台手动管理设备并下发脚本 (Priority: P1)

**Goal**: 管理员在后台选择设备、选择脚本、下发命令、查看执行结果

**Independent Test**: 在后台选一台在线设备，选已有脚本，点击下发，观察任务状态变化直到 success/failed

### Implementation for User Story 1

- [x] T042 [US1] Implement command dispatcher service: create task, dispatch via WS to correct companion machine, handle ack in `server/src/services/command_dispatcher.py`
- [x] T043 [US1] Implement task scheduler service: batch dispatch to multiple devices, command queue per device, expired command cleanup in `server/src/services/task_scheduler.py`
- [x] T044 [US1] Implement server WS: handle task.status + task.result + task.error messages from client, update Task model in `server/src/ws/client_handler.py` (extend)
- [x] T045 [US1] Implement task REST API: POST /tasks/dispatch, GET /tasks (list+filter), GET /tasks/{id}, POST /tasks/{id}/cancel, GET /tasks/stats in `server/src/api/tasks.py`
- [x] T046 [US1] Implement server → admin WS push: task.updated + task.completed events in `server/src/ws/admin_handler.py` (extend)
- [x] T047 [US1] Implement client command executor: receive command.dispatch → route to device → track execution → send task.status updates in `client/src/command_executor.py`
- [x] T048 [US1] Create admin TaskMonitor page: task list table, status badges, filter by device/status/source, real-time updates, cancel button in `admin/src/views/TaskMonitor.vue`
- [x] T049 [US1] Add task dispatch dialog to DeviceList: select script, set params, dispatch to selected devices in `admin/src/views/DeviceList.vue` (extend)
- [x] T050 [US1] Create admin task Pinia store: fetch tasks, handle WS task.updated events in `admin/src/stores/task.ts`
- [x] T051 [US1] Implement device group REST API: GET/POST/PUT/DELETE /groups, POST /groups/{id}/devices in `server/src/api/device_groups.py`
- [x] T052 [US1] Implement Apple Account REST API: GET/POST /apple-accounts, POST bind/unbind in `server/src/api/apple_accounts.py`
- [x] T053 [US1] Implement Apple Account auto-switch service: detect banned status → find backup from pool → trigger switch command in `server/src/services/apple_account_service.py`

**Checkpoint**: Full manual management loop working: select device → dispatch script → view result. US1 independently testable.

---

## Phase 5: User Story 3 - 客户端执行远端脚本 (Priority: P1)

**Goal**: 客户端接收脚本命令后通过 WDA 执行自动化操作，上报进度和结果

**Independent Test**: 服务端下发一个"打开 App Store 搜索关键词"脚本到一台在线设备，设备正确执行并回报 success

### Implementation for User Story 3

- [x] T054 [US3] Implement WDA driver: HTTP client wrapping WDA endpoints (launch app, find element, tap, type, swipe, wait, screenshot) in `client/src/wda_driver.py`
- [x] T055 [US3] Implement script runner: parse JSON steps → translate to WDA driver calls → execute sequentially with per-step timeout → collect results in `client/src/script_runner.py`
- [x] T056 [US3] Integrate script runner with command executor: receive command.dispatch → call script_runner → send task.status progress → send task.result/task.error in `client/src/command_executor.py` (extend)
- [x] T057 [US3] Implement script timeout enforcement: global task timeout watchdog, force-kill on timeout, report timeout status in `client/src/script_runner.py` (extend)
- [x] T058 [US3] Handle WDA error scenarios: element not found, app crash, WDA disconnect, App Store auth popup detection in `client/src/wda_driver.py` (extend)
- [x] T059 [US3] Implement command cancel handling: receive command.cancel → stop running script → cleanup → report cancelled status in `client/src/command_executor.py` (extend)

**Checkpoint**: Client can execute full automation scripts via WDA and report results. US3 independently testable.

---

## Phase 6: User Story 4 - 刷榜脚本管理与发布 (Priority: P2)

**Goal**: 管理员通过后台表单编辑器创建、编辑脚本，管理版本，发布和回滚

**Independent Test**: 后台创建脚本 → 定义 JSON 步骤 → 发布 v1 → 修改发布 v2 → 回滚到 v1

### Implementation for User Story 4

- [x] T060 [US4] Implement script manager service: create script, create version, publish, rollback, list versions in `server/src/services/script_manager.py`
- [x] T061 [US4] Implement script REST API: GET/POST /scripts, PUT /scripts/{id}, POST publish, POST rollback, GET /scripts/{id}/versions in `server/src/api/scripts.py`
- [x] T062 [US4] Create admin ScriptEditor page: script list, form-based step editor (add/remove/reorder steps), JSON preview (Monaco editor), version history panel in `admin/src/views/ScriptEditor.vue`
- [x] T063 [US4] Create script step form component: action type selector, target input, params editor, timeout setting per step in `admin/src/components/ScriptStepForm.vue`
- [x] T064 [US4] Create admin script Pinia store: CRUD operations, version management in `admin/src/stores/script.ts`
- [x] T065 [US4] Validate script JSON schema on save: ensure all steps have required action field, valid action types in `server/src/services/script_manager.py` (extend)
- [x] T065b [US4] Implement gray release for script publishing: publish to selected device subset first, verify results, then promote to full release in `server/src/services/script_manager.py` (extend) and `server/src/api/scripts.py` (add POST /scripts/{id}/gray-release)

**Checkpoint**: Script CRUD + version management + publish/rollback + gray release fully working. US4 independently testable.

---

## Phase 7: User Story 5 - 智能管理：探索阶段 (Priority: P2)

**Goal**: 管理员手动触发探索，系统自动分配策略组合到不同设备，收集结果，分析有效性

**Independent Test**: 触发探索 → 5 台设备各自执行不同策略 → 一轮完成后查看效果分析报告

### Implementation for User Story 5

- [x] T066 [US5] Implement strategy engine - explore: generate strategy combinations from script + param variations, assign to devices, track execution in `server/src/services/strategy_engine.py`
- [x] T067 [US5] Implement explore session management: start session, create strategies, dispatch tasks with source=explore, collect results in `server/src/services/strategy_engine.py` (extend)
- [x] T068 [US5] Implement effectiveness analysis: aggregate task results per strategy, calculate download count totals, rank strategies by effectiveness_score in `server/src/services/strategy_engine.py` (extend)
- [x] T069 [US5] Implement strategy REST API: POST /strategies/explore/start, POST stop, GET analysis, GET /strategies list in `server/src/api/strategies.py`
- [x] T070 [US5] Create admin StrategyManager page - explore tab: configure device count + rounds + param variations, start/stop explore, view analysis results in `admin/src/views/StrategyManager.vue`
- [x] T071 [US5] Create admin strategy Pinia store: explore session management, analysis data in `admin/src/stores/strategy.ts`
- [x] T072 [US5] Create explore analysis chart component: ECharts bar/line charts comparing strategy effectiveness scores in `admin/src/components/ExploreAnalysis.vue`

**Checkpoint**: Explore session runs, strategies tested, effectiveness analysis available. US5 independently testable.

---

## Phase 8: User Story 6 - 智能管理：实施阶段 (Priority: P3)

**Goal**: 将探索阶段发现的有效策略批量推送到所有设备，持续监控效果

**Independent Test**: 选择有效策略 → 启动实施 → 10 台设备执行 → 仪表盘显示进度和成功率

### Implementation for User Story 6

- [x] T073 [US6] Implement strategy engine - execute: batch assign effective strategies to all available devices based on device criteria in `server/src/services/strategy_engine.py` (extend)
- [x] T074 [US6] Implement effectiveness monitor: background task tracking download count trends, detect effectiveness decline, trigger alert in `server/src/services/strategy_engine.py` (extend)
- [x] T075 [US6] Implement strategy execute REST API: POST /strategies/execute/start, monitor endpoint in `server/src/api/strategies.py` (extend)
- [x] T076 [US6] Implement server → admin WS push: strategy.effectiveness_changed + alert events in `server/src/ws/admin_handler.py` (extend)
- [x] T077 [US6] Create admin StrategyManager page - execute tab: select strategies, start batch execution, monitor progress, effectiveness trend chart in `admin/src/views/StrategyManager.vue` (extend)
- [x] T078 [US6] Create admin Dashboard page: device stats, task stats, download counters, active strategies, alert list (ECharts + real-time WS data) in `admin/src/views/Dashboard.vue`
- [x] T079 [US6] Create dashboard Pinia store: aggregate stats from WS dashboard.stats events in `admin/src/stores/dashboard.ts`

**Checkpoint**: Effective strategies deployed at scale, monitoring and alerts working. US6 independently testable.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Configuration management UI, security hardening, documentation

- [x] T080 [P] Create admin ConfigPanel page: view/edit global, group, device configs with scope selector in `admin/src/views/ConfigPanel.vue`
- [x] T081 [P] Implement config REST API: GET/PUT /configs with scope-based filtering in `server/src/api/config.py`
- [x] T082 [P] Implement dashboard REST API: GET /dashboard aggregate endpoint in `server/src/api/dashboard.py`
- [x] T083 [P] Add audit logging middleware: log all admin API operations (who, what, when) to MongoDB in `server/src/middleware/audit.py`
- [x] T084 [P] Implement configuration push to client: send config.update message via WS when config changes in `server/src/services/config_service.py` (extend)
- [x] T085 [P] Handle config.update on client side: receive and apply config changes (heartbeat interval, timeouts) without restart in `client/src/ws_client.py` (extend)
- [x] T086 [P] Add HTTPS/WSS TLS configuration to server in `server/src/config.py` (extend)
- [x] T087 Run quickstart.md validation: verify end-to-end setup per `specs/001-ios-ranking-system/quickstart.md`
- [x] T088 Code cleanup, consistent error handling across all API endpoints, logging standardization
- [x] T089 [P] Implement server health check endpoint (GET /health) with MongoDB connectivity check in `server/src/api/health.py`
- [x] T090 Create load test script: simulate 100 concurrent WebSocket connections with heartbeat + batch command dispatch, validate SC-002 and SC-008 targets in `server/tests/load/test_concurrent.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US2 (Phase 3)**: Depends on Foundational — device registration is foundation for US1
- **US1 (Phase 4)**: Depends on Foundational + US2 (needs registered devices to dispatch to)
- **US3 (Phase 5)**: Depends on Foundational + US2 (needs WS connection + device) — can parallel with US1
- **US4 (Phase 6)**: Depends on Foundational only — can parallel with US1/US2/US3
- **US5 (Phase 7)**: Depends on US1 + US3 + US4 (needs dispatch + execution + script management)
- **US6 (Phase 8)**: Depends on US5 (needs explore results)
- **Polish (Phase 9)**: Depends on all desired stories being complete

### User Story Dependencies

```text
Phase 1 (Setup)
    │
Phase 2 (Foundational)
    │
    ├──→ Phase 3 (US2: Device Registration) ──→ Phase 4 (US1: Manual Dispatch)
    │                                                │
    ├──→ Phase 5 (US3: Script Execution) ←───────────┘ (US1 triggers US3)
    │
    ├──→ Phase 6 (US4: Script Management) ────────────┐
    │                                                  │
    └──→ [US1 + US3 + US4 complete] ──→ Phase 7 (US5: Explore)
                                            │
                                       Phase 8 (US6: Execute)
                                            │
                                       Phase 9 (Polish)
```

### Parallel Opportunities

Within each phase, tasks marked [P] can run in parallel:

```text
Phase 1: T002, T003, T004, T005, T006, T007, T008 — all parallel
Phase 2: T011-T021 (all models) — all parallel; T026-T031 (all skeletons) — all parallel
Phase 3: T033, T034 — parallel (different client files)
Phase 4: T051, T052 — parallel (different API files); T048, T049, T050 — parallel (different admin files)
Phase 5: T054, T055 — sequential (driver before runner)
Phase 6: T062, T063, T064 — parallel (different admin files)
Phase 9: T080-T086 — all parallel
```

### Cross-Story Parallelism

After Foundational completes:
- **US2 + US4**: Can proceed in parallel (different subsystems)
- **US3**: Can start once WS infrastructure is in place (from Foundational)
- **US1**: Needs US2 devices, but admin UI tasks can start in parallel

---

## Implementation Strategy

### MVP First (US2 + US1 + US3)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US2 (Device Registration)
4. Complete Phase 4: US1 (Manual Dispatch)
5. Complete Phase 5: US3 (Script Execution)
6. **STOP and VALIDATE**: End-to-end test: admin → dispatch script → device executes → result visible
7. Deploy/demo if ready — this is the MVP

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. + US2 → Devices visible in admin (Demo 1)
3. + US1 + US3 → Manual dispatch working (Demo 2 — **MVP!**)
4. + US4 → Full script management (Demo 3)
5. + US5 → Smart exploration (Demo 4)
6. + US6 → Full smart management (Demo 5 — **Complete System**)
7. + Polish → Production ready

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Client agent = Python on companion machine, NOT on iPhone
- Models are in Foundational because multiple stories share them
