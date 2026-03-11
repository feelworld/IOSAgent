#!/usr/bin/env bash
#
# IOSAgent 一键部署脚本
# 在 Ubuntu 22.04 EC2 实例上运行：chmod +x deploy.sh && sudo ./deploy.sh
#
set -euo pipefail

# ─── Colors ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ─── Pre-checks ─────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && err "请以 root 运行: sudo ./deploy.sh"

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
info "项目目录: $PROJECT_DIR"

# ─── 1. Install Docker ──────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    info "安装 Docker..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
      > /etc/apt/sources-list.d/docker.list 2>/dev/null || \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
      | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
    ok "Docker 安装完成"
else
    ok "Docker 已安装: $(docker --version)"
fi

# ─── 2. Install Node.js (for building frontend) ─────────────────────────
if ! command -v node &>/dev/null; then
    info "安装 Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y -qq nodejs
    ok "Node.js 安装完成: $(node --version)"
else
    ok "Node.js 已安装: $(node --version)"
fi

# ─── 3. Configure firewall ──────────────────────────────────────────────
if command -v ufw &>/dev/null; then
    info "配置防火墙..."
    ufw allow 22/tcp   >/dev/null 2>&1 || true
    ufw allow 80/tcp   >/dev/null 2>&1 || true
    ufw allow 443/tcp  >/dev/null 2>&1 || true
    ufw --force enable  >/dev/null 2>&1 || true
    ok "防火墙配置完成 (22, 80, 443)"
fi

# ─── 4. Generate secrets ────────────────────────────────────────────────
ENV_FILE="$PROJECT_DIR/server/.env"
if [[ ! -f "$ENV_FILE" ]] || grep -q "change-me\|dev-secret" "$ENV_FILE" 2>/dev/null; then
    info "生成安全密钥..."
    JWT_SECRET=$(openssl rand -hex 32)
    AES_KEY=$(openssl rand -hex 16)

    cat > "$ENV_FILE" <<EOF
MONGODB_URL=mongodb://mongodb:27017/ios_ranking
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24
AES_KEY=${AES_KEY}
HOST=0.0.0.0
PORT=8000
DEBUG=false
SSL_ENABLED=false
SSL_CERTFILE=
SSL_KEYFILE=
EOF
    ok "server/.env 已生成（含随机 JWT_SECRET 和 AES_KEY）"
else
    ok "server/.env 已存在，跳过生成"
fi

# ─── 5. Build frontend ──────────────────────────────────────────────────
info "构建 Admin 前端..."
cd "$PROJECT_DIR/admin"
npm install --silent 2>&1 | tail -1
npm run build 2>&1 | tail -3
cd "$PROJECT_DIR"
if [[ -d "$PROJECT_DIR/admin/dist" ]]; then
    ok "前端构建完成: admin/dist/"
else
    err "前端构建失败，admin/dist/ 不存在"
fi

# ─── 6. Build and start containers ──────────────────────────────────────
info "构建并启动 Docker 容器..."
docker compose down --remove-orphans 2>/dev/null || true
docker compose up -d --build

info "等待服务启动..."
sleep 10

# Health check
for i in $(seq 1 12); do
    if curl -sf http://localhost/health >/dev/null 2>&1; then
        ok "服务健康检查通过"
        break
    fi
    if [[ $i -eq 12 ]]; then
        warn "健康检查超时，请检查 docker compose logs"
    fi
    sleep 5
done

# ─── 7. SSL setup (optional) ────────────────────────────────────────────
echo ""
echo -e "${CYAN}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  部署完成!${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════${NC}"
echo ""

PUBLIC_IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "YOUR_SERVER_IP")

echo -e "  管理后台:  ${GREEN}http://${PUBLIC_IP}/${NC}"
echo -e "  API 地址:  ${GREEN}http://${PUBLIC_IP}/api/v1/${NC}"
echo -e "  健康检查:  ${GREEN}http://${PUBLIC_IP}/health${NC}"
echo ""
echo -e "  默认账号:  admin"
echo -e "  默认密码:  admin123 ${YELLOW}(请登录后立即修改!)${NC}"
echo ""
echo -e "  本地 Client Agent 配置:"
echo -e "    server_url:      ${CYAN}ws://${PUBLIC_IP}/ws/client${NC}"
echo -e "    server_http_url: ${CYAN}http://${PUBLIC_IP}${NC}"
echo ""

# Ask about SSL
read -rp "是否配置 SSL 证书 (需要域名)? [y/N]: " SETUP_SSL
if [[ "${SETUP_SSL,,}" == "y" ]]; then
    read -rp "请输入域名 (例: ios.example.com): " DOMAIN
    if [[ -z "$DOMAIN" ]]; then
        warn "未输入域名，跳过 SSL 配置"
    else
        read -rp "请输入邮箱 (用于 Let's Encrypt): " EMAIL

        info "为 ${DOMAIN} 申请 SSL 证书..."
        mkdir -p certbot/conf certbot/www

        # Add certbot challenge location to nginx
        cat > "$PROJECT_DIR/nginx/nginx.conf" <<'NGINX_EOF'
upstream backend {
    server server:8000;
}

server {
    listen 80;
    server_name DOMAIN_PLACEHOLDER;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name DOMAIN_PLACEHOLDER;

    ssl_certificate /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 20m;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    location /ws/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    location /health {
        proxy_pass http://backend;
        proxy_set_header Host $host;
    }
}
NGINX_EOF
        sed -i "s/DOMAIN_PLACEHOLDER/${DOMAIN}/g" "$PROJECT_DIR/nginx/nginx.conf"

        # Get certificate
        docker compose run --rm certbot certonly \
            --webroot -w /var/www/certbot \
            --email "$EMAIL" --agree-tos --no-eff-email \
            -d "$DOMAIN" || warn "证书申请失败，请检查域名 DNS"

        docker compose restart nginx
        ok "SSL 配置完成!"
        echo ""
        echo -e "  管理后台:  ${GREEN}https://${DOMAIN}/${NC}"
        echo -e "  本地 Client Agent 配置:"
        echo -e "    server_url:      ${CYAN}wss://${DOMAIN}/ws/client${NC}"
        echo -e "    server_http_url: ${CYAN}https://${DOMAIN}${NC}"
    fi
fi

echo ""
echo -e "${CYAN}常用命令:${NC}"
echo "  查看日志:    docker compose logs -f"
echo "  重启服务:    docker compose restart"
echo "  停止服务:    docker compose down"
echo "  更新部署:    git pull && docker compose up -d --build"
echo ""
