# Quickstart: iOS App Ranking System

## Prerequisites

- Python 3.11+
- Node.js 18+ & npm
- MongoDB 7.0+ (running locally or remote)
- 至少一台越狱 iPhone（已安装 WebDriverAgent）
- 一台伴生机（Mac/Linux/Windows，与 iPhone 在同一网络）

## 1. Clone & Setup

```bash
git clone <repo-url>
cd IOSAgent
```

## 2. Server Setup

```bash
cd server
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env：设置 MONGODB_URL, JWT_SECRET, AES_KEY 等

# 启动服务端
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Server API docs: `http://localhost:8000/docs`

## 3. Admin Setup

```bash
cd admin
npm install

# 配置 API 地址
cp .env.example .env
# 编辑 .env：设置 VITE_API_URL=http://localhost:8000

# 启动开发服务器
npm run dev
```

Admin panel: `http://localhost:5173`

## 4. Client Agent Setup (on companion machine)

```bash
cd client
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 配置
cp config.example.yaml config.yaml
# 编辑 config.yaml：
#   server_url: wss://localhost:8000/ws/client/companion-001
#   devices:
#     - uid: device-001
#       wda_url: http://192.168.1.101:8100

# 启动客户端 Agent
python src/main.py
```

## 5. Verify End-to-End

1. 打开 Admin panel → 登录（默认 admin/admin）
2. 检查 Dashboard → 设备列表应显示已注册设备
3. 选择一台在线设备 → 创建简单脚本 → 下发执行
4. 观察任务状态变为 running → success
5. 查看执行结果日志

## Quick Validation Checklist

- [ ] MongoDB 连接正常（server 启动无报错）
- [ ] Admin 登录成功，仪表盘加载
- [ ] Client Agent 连接 server，设备出现在列表中
- [ ] 设备状态显示为 "online"
- [ ] 手动下发脚本成功执行并回报结果
