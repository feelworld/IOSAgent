#!/usr/bin/env bash
#
# IOSAgent 智能更新脚本
# 根据 git diff 判断变更范围，只重建需要更新的部分
#
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

PROJECT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
BRANCH="${2:-001-ios-ranking-system}"
cd "$PROJECT_DIR"

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════╗"
echo "║         IOSAgent - Smart Update                ║"
echo "╚════════════════════════════════════════════════╝"
echo -e "${NC}"

# ─── 1. Git pull ─────────────────────────────────────────────────────────
OLD_HEAD=$(git rev-parse HEAD)
info "Current commit: $(git log -1 --format='%h %s')"
info "Pulling latest changes..."

git fetch origin
git reset --hard "origin/$BRANCH"

NEW_HEAD=$(git rev-parse HEAD)
info "Updated to:     $(git log -1 --format='%h %s')"

if [[ "$OLD_HEAD" == "$NEW_HEAD" ]]; then
    ok "Already up to date, no changes to deploy"
    echo ""
    docker compose ps
    exit 0
fi

# ─── 2. Analyze changes ─────────────────────────────────────────────────
info "Analyzing changed files..."
CHANGED=$(git diff --name-only "$OLD_HEAD" "$NEW_HEAD")
echo "$CHANGED" | head -20
TOTAL=$(echo "$CHANGED" | wc -l)
[[ $TOTAL -gt 20 ]] && echo "  ... and $((TOTAL - 20)) more files"

REBUILD_SERVER=false
REBUILD_FRONTEND=false
REBUILD_NGINX=false
RESTART_ONLY=false

while IFS= read -r file; do
    case "$file" in
        server/*|Dockerfile.server)
            REBUILD_SERVER=true ;;
        admin/*|Dockerfile.admin)
            REBUILD_FRONTEND=true ;;
        nginx/*|docker-compose.yml)
            REBUILD_NGINX=true ;;
        deploy/*|.gitignore|.dockerignore|README*)
            RESTART_ONLY=true ;;
        *)
            REBUILD_SERVER=true ;;
    esac
done <<< "$CHANGED"

echo ""
info "Change analysis:"
echo -e "  Server (Python):   $(if $REBUILD_SERVER; then echo -e "${YELLOW}CHANGED${NC}"; else echo -e "${GREEN}no change${NC}"; fi)"
echo -e "  Frontend (Vue):    $(if $REBUILD_FRONTEND; then echo -e "${YELLOW}CHANGED${NC}"; else echo -e "${GREEN}no change${NC}"; fi)"
echo -e "  Nginx config:      $(if $REBUILD_NGINX; then echo -e "${YELLOW}CHANGED${NC}"; else echo -e "${GREEN}no change${NC}"; fi)"
echo ""

# ─── 3. Rebuild what's needed ────────────────────────────────────────────

if $REBUILD_FRONTEND; then
    info "Rebuilding frontend..."
    cd "$PROJECT_DIR/admin"
    npm install --silent 2>&1 | tail -1
    npm run build 2>&1 | tail -3
    cd "$PROJECT_DIR"
    ok "Frontend rebuilt"
fi

if $REBUILD_SERVER; then
    info "Rebuilding server container..."
    docker compose build --no-cache server
    docker compose up -d server
    ok "Server container rebuilt and restarted"
elif $REBUILD_NGINX; then
    info "Restarting nginx with new config..."
    docker compose up -d --force-recreate nginx
    ok "Nginx restarted"
elif $REBUILD_FRONTEND; then
    info "Restarting nginx to serve new frontend..."
    docker compose restart nginx
    ok "Nginx restarted with new frontend"
fi

if $REBUILD_SERVER || $REBUILD_NGINX; then
    docker compose up -d
fi

# ─── 4. Health check ────────────────────────────────────────────────────
info "Running health check..."
sleep 5
for i in $(seq 1 10); do
    if curl -sf http://localhost/health >/dev/null 2>&1; then
        ok "Health check passed"
        break
    fi
    [[ $i -eq 10 ]] && warn "Health check timeout"
    sleep 3
done

# ─── 5. Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}Update complete!${NC}"
echo -e "  Commits: ${CYAN}$(git log --oneline "$OLD_HEAD".."$NEW_HEAD" | wc -l)${NC} new commit(s)"
echo ""
git log --oneline "$OLD_HEAD".."$NEW_HEAD" | head -10
echo ""
docker compose ps
echo ""
