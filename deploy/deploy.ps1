#Requires -Version 5.1
<#
.SYNOPSIS
    IOSAgent 远程部署主控脚本 (Windows PowerShell)
.DESCRIPTION
    从本地 Windows PC 通过 SSH 操作远程 EC2 服务器，完成部署/更新/排障。
.PARAMETER Action
    deploy  - 首次完整部署（安装 Docker、克隆代码、启动服务）
    update  - 智能更新（git pull + 按需重建）
    status  - 查看服务状态
    logs    - 查看实时日志
    restart - 重启所有服务
    ssh     - 直接登录远程服务器
    doctor  - 自动排障诊断
.EXAMPLE
    .\deploy.ps1 deploy -GitRepo "https://github.com/yourname/IOSAgent.git"
    .\deploy.ps1 update
    .\deploy.ps1 status
    .\deploy.ps1 ssh
    .\deploy.ps1 doctor
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("deploy", "update", "status", "logs", "restart", "ssh", "doctor")]
    [string]$Action = "status",

    [string]$GitRepo = "",
    [string]$Branch = "main"
)

# ─── Config ──────────────────────────────────────────────────────────────
$EC2_IP       = "13.215.194.223"
$EC2_USER     = "ubuntu"
$PEM_FILE     = "C:\Users\xiong\Downloads\ios ranking system.pem"
$REMOTE_DIR   = "/home/ubuntu/IOSAgent"
$SSH_OPTS     = @("-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "-i", $PEM_FILE)

function Write-Header($msg) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

function Invoke-Remote {
    param([string]$Command, [switch]$Interactive)
    if ($Interactive) {
        ssh @SSH_OPTS "$EC2_USER@$EC2_IP" -t $Command
    } else {
        ssh @SSH_OPTS "$EC2_USER@$EC2_IP" $Command
    }
}

function Test-Connection {
    Write-Host "Testing SSH connection..." -ForegroundColor Yellow
    $result = ssh @SSH_OPTS -o ConnectTimeout=5 "$EC2_USER@$EC2_IP" "echo ok" 2>&1
    if ($result -match "ok") {
        Write-Host "  SSH connected!" -ForegroundColor Green
        return $true
    } else {
        Write-Host "  SSH connection FAILED!" -ForegroundColor Red
        Write-Host "  Check: PEM file exists, EC2 security group allows port 22, instance is running" -ForegroundColor Yellow
        return $false
    }
}

# ─── Actions ─────────────────────────────────────────────────────────────

function Do-Deploy {
    if (-not $GitRepo) {
        Write-Host "ERROR: -GitRepo is required for first deploy" -ForegroundColor Red
        Write-Host 'Example: .\deploy.ps1 deploy -GitRepo "https://github.com/yourname/IOSAgent.git"' -ForegroundColor Yellow
        return
    }

    Write-Header "Full Deploy to EC2 ($EC2_IP)"

    # Upload setup script
    Write-Host "`nUploading setup scripts..." -ForegroundColor Yellow
    scp @SSH_OPTS "deploy/remote-setup.sh" "deploy/remote-update.sh" "${EC2_USER}@${EC2_IP}:/tmp/"

    # Run remote setup
    Write-Host "`nRunning remote setup..." -ForegroundColor Yellow
    Invoke-Remote "chmod +x /tmp/remote-setup.sh && sudo /tmp/remote-setup.sh '$GitRepo' '$Branch' '$REMOTE_DIR'" -Interactive
}

function Do-Update {
    Write-Header "Smart Update ($EC2_IP)"

    # Upload latest update script first
    scp @SSH_OPTS "deploy/remote-update.sh" "${EC2_USER}@${EC2_IP}:/tmp/"

    Invoke-Remote "chmod +x /tmp/remote-update.sh && cd $REMOTE_DIR && sudo /tmp/remote-update.sh" -Interactive
}

function Do-Status {
    Write-Header "Service Status ($EC2_IP)"
    Invoke-Remote @"
cd $REMOTE_DIR 2>/dev/null && echo '--- Docker Containers ---' && docker compose ps 2>/dev/null;
echo ''; echo '--- Disk Usage ---'; df -h / | tail -1;
echo ''; echo '--- Memory ---'; free -h | head -2;
echo ''; echo '--- Health Check ---';
curl -sf http://localhost/health 2>/dev/null && echo ' API: OK' || echo ' API: FAILED';
curl -sf http://localhost/ 2>/dev/null | head -1 | grep -q 'html' && echo ' Frontend: OK' || echo ' Frontend: FAILED';
echo ''; echo '--- Recent Logs (last 5) ---'; docker compose logs --tail=5 server 2>/dev/null
"@
}

function Do-Logs {
    Write-Header "Live Logs ($EC2_IP)"
    Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
    Invoke-Remote "cd $REMOTE_DIR && docker compose logs -f --tail=50" -Interactive
}

function Do-Restart {
    Write-Header "Restart Services ($EC2_IP)"
    Invoke-Remote "cd $REMOTE_DIR && docker compose restart && docker compose ps"
}

function Do-SSH {
    Write-Header "SSH to $EC2_IP"
    ssh @SSH_OPTS -t "$EC2_USER@$EC2_IP" "cd $REMOTE_DIR 2>/dev/null; exec bash"
}

function Do-Doctor {
    Write-Header "Auto Diagnostics ($EC2_IP)"
    Invoke-Remote @"
echo '====== System ======';
echo 'Uptime:'; uptime;
echo ''; echo 'Disk:'; df -h / | tail -1;
echo ''; echo 'Memory:'; free -h | head -2;
echo ''; echo '====== Docker ======';
docker info --format '{{.ServerVersion}}' 2>/dev/null && echo 'Docker: OK' || echo 'Docker: NOT INSTALLED';
echo '';
cd $REMOTE_DIR 2>/dev/null || { echo 'Project dir NOT FOUND: $REMOTE_DIR'; exit 1; };
echo '====== Containers ======';
docker compose ps 2>/dev/null;
echo '';
echo '====== Container Health ======';
for svc in mongodb server nginx; do
    state=`docker compose ps --format json 2>/dev/null | python3 -c "import sys,json; [print(json.loads(l).get('State','?')) for l in sys.stdin if json.loads(l).get('Service')=='\$svc']" 2>/dev/null || echo 'unknown'`;
    echo "  \$svc: \$state";
done;
echo '';
echo '====== Network Check ======';
curl -sf http://localhost/health >/dev/null 2>&1 && echo '  Health endpoint: OK' || echo '  Health endpoint: FAILED';
curl -sf http://localhost/ >/dev/null 2>&1 && echo '  Frontend: OK' || echo '  Frontend: FAILED';
echo '';
echo '====== Recent Errors ======';
docker compose logs --tail=20 server 2>/dev/null | grep -iE 'error|exception|traceback|failed' | tail -10;
echo '';
echo '====== MongoDB ======';
docker compose exec -T mongodb mongosh --eval 'db.adminCommand("ping")' 2>/dev/null | tail -1;
echo '';
echo '====== Firewall ======';
sudo ufw status 2>/dev/null | head -5;
echo '';
echo '====== Done ======'
"@
}

# ─── Main ────────────────────────────────────────────────────────────────

if (-not (Test-Path $PEM_FILE)) {
    Write-Host "ERROR: PEM file not found: $PEM_FILE" -ForegroundColor Red
    exit 1
}

if (-not (Test-Connection)) { exit 1 }

switch ($Action) {
    "deploy"  { Do-Deploy }
    "update"  { Do-Update }
    "status"  { Do-Status }
    "logs"    { Do-Logs }
    "restart" { Do-Restart }
    "ssh"     { Do-SSH }
    "doctor"  { Do-Doctor }
}
