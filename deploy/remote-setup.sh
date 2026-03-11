#!/usr/bin/env bash
#
# IOSAgent EC2 首次部署脚本
# 由 deploy.ps1 自动上传并执行，不要手动运行
#
set -euo pipefail

GIT_REPO="${1:?Usage: remote-setup.sh <git_repo_url> [branch] [install_dir]}"
BRANCH="${2:-main}"
INSTALL_DIR="${3:-/home/ubuntu/IOSAgent}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════╗"
echo "║     IOSAgent - EC2 First-Time Setup            ║"
echo "╚════════════════════════════════════════════════╝"
echo -e "${NC}"

# ─── 1. System update ───────────────────────────────────────────────────
info "Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
ok "System updated"

# ─── 2. Install Docker ──────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    info "Installing Docker..."
    apt-get install -y -qq ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
      | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
    usermod -aG docker ubuntu
    ok "Docker installed: $(docker --version)"
else
    ok "Docker already installed: $(docker --version)"
fi

# ─── 3. Install Node.js ─────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    info "Installing Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y -qq nodejs
    ok "Node.js installed: $(node --version)"
else
    ok "Node.js already installed: $(node --version)"
fi

# ─── 4. Install Git ─────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    info "Installing Git..."
    apt-get install -y -qq git
fi
ok "Git: $(git --version)"

# ─── 5. Configure firewall ──────────────────────────────────────────────
info "Configuring firewall..."
ufw allow 22/tcp  >/dev/null 2>&1 || true
ufw allow 80/tcp  >/dev/null 2>&1 || true
ufw allow 443/tcp >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true
ok "Firewall configured (22, 80, 443)"

# ─── 6. Clone repository ────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Repository exists, pulling latest..."
    cd "$INSTALL_DIR"
    git fetch origin
    git reset --hard "origin/$BRANCH"
    ok "Repository updated"
else
    info "Cloning repository..."
    git clone --branch "$BRANCH" "$GIT_REPO" "$INSTALL_DIR"
    ok "Repository cloned to $INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# ─── 7. Generate secrets ────────────────────────────────────────────────
ENV_FILE="$INSTALL_DIR/server/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    info "Generating server/.env with secure secrets..."
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
    ok "server/.env created with random secrets"
else
    ok "server/.env already exists, keeping current secrets"
fi

# ─── 8. Build frontend ──────────────────────────────────────────────────
info "Building admin frontend..."
cd "$INSTALL_DIR/admin"
npm install --silent 2>&1 | tail -1
npm run build 2>&1 | tail -5
cd "$INSTALL_DIR"

if [[ -d "admin/dist" ]]; then
    ok "Frontend built: admin/dist/"
else
    err "Frontend build failed"
fi

# ─── 9. Start services ──────────────────────────────────────────────────
info "Building and starting Docker containers..."
docker compose down --remove-orphans 2>/dev/null || true
docker compose up -d --build

info "Waiting for services to start..."
for i in $(seq 1 15); do
    if curl -sf http://localhost/health >/dev/null 2>&1; then
        ok "Health check passed"
        break
    fi
    if [[ $i -eq 15 ]]; then
        warn "Health check timeout - check: docker compose logs"
    fi
    sleep 4
done

# ─── 10. Copy update script ─────────────────────────────────────────────
cp /tmp/remote-update.sh "$INSTALL_DIR/deploy/remote-update.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/deploy/remote-update.sh" 2>/dev/null || true

# ─── Done ────────────────────────────────────────────────────────────────
PUBLIC_IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "$HOSTNAME")

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Deployment Complete!                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Admin URL:     ${GREEN}http://${PUBLIC_IP}/${NC}"
echo -e "  API URL:       ${GREEN}http://${PUBLIC_IP}/api/v1/${NC}"
echo -e "  Health:        ${GREEN}http://${PUBLIC_IP}/health${NC}"
echo ""
echo -e "  Default login: admin / admin123 ${YELLOW}(change after first login!)${NC}"
echo ""
echo -e "  Client Agent config (on your Windows PC):"
echo -e "    server_url:      ${CYAN}ws://${PUBLIC_IP}/ws/client${NC}"
echo -e "    server_http_url: ${CYAN}http://${PUBLIC_IP}${NC}"
echo ""
docker compose ps
echo ""
