#!/bin/bash
#
# 创建 systemd 服务文件脚本
# 用于创建 Gunicorn、Celery Worker、Celery Beat 服务
#

set -e

# 配置
PROJECT_NAME="futures-ai"

# 自动检测项目目录（使用当前目录）
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 检测虚拟环境
if [ -d "${PROJECT_DIR}/venv" ]; then
    VENV_DIR="${PROJECT_DIR}/venv"
elif [ -d "${PROJECT_DIR}/.venv" ]; then
    VENV_DIR="${PROJECT_DIR}/.venv"
elif command -v python3 &> /dev/null; then
    VENV_DIR=""  # 使用系统 Python
else
    echo "错误：未找到虚拟环境或 Python3"
    exit 1
fi

# 检测用户
if [ -n "$SUDO_USER" ]; then
    USER="$SUDO_USER"
else
    USER="$(whoami)"
fi
GROUP="$USER"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

echo "========================================"
echo "systemd 服务配置脚本"
echo "========================================"
echo ""
echo "项目目录：$PROJECT_DIR"
echo "虚拟环境：${VENV_DIR:-使用系统 Python}"
echo "运行用户：$USER"
echo ""

# 创建 Gunicorn 服务
print_info "创建 Gunicorn 服务..."
if [ -n "$VENV_DIR" ]; then
    PYTHON_BIN="${VENV_DIR}/bin/python3"
    GUNICORN_BIN="${VENV_DIR}/bin/gunicorn"
else
    PYTHON_BIN="/usr/bin/python3"
    GUNICORN_BIN="/usr/local/bin/gunicorn"
    # 如果 gunicorn 不存在，使用 python3 -m gunicorn
    if [ ! -f "$GUNICORN_BIN" ]; then
        GUNICORN_BIN="python3 -m gunicorn"
    fi
fi

cat > /etc/systemd/system/${PROJECT_NAME}.service << EOF
[Unit]
Description=Gunicorn instance to serve ${PROJECT_NAME}
After=network.target

[Service]
User=${USER}
Group=${GROUP}
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${VENV_DIR:-/usr/local/bin}:${VENV_DIR:-/usr/local/bin}:/usr/bin:/bin"
Environment="PYTHONPATH=${PROJECT_DIR}"
ExecStart=${GUNICORN_BIN} -c config/gunicorn.conf.py app:app
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${PROJECT_NAME}-gunicorn

[Install]
WantedBy=multi-user.target
EOF
print_success "Gunicorn 服务已创建"

# 创建 Celery Worker 服务
print_info "创建 Celery Worker 服务..."
if [ -n "$VENV_DIR" ]; then
    CELERY_BIN="${VENV_DIR}/bin/celery"
else
    CELERY_BIN="/usr/local/bin/celery"
    if [ ! -f "$CELERY_BIN" ]; then
        CELERY_BIN="python3 -m celery"
    fi
fi

cat > /etc/systemd/system/${PROJECT_NAME}-celery.service << EOF
[Unit]
Description=Celery Worker for ${PROJECT_NAME}
After=network.target

[Service]
Type=simple
User=${USER}
Group=${GROUP}
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${VENV_DIR:-/usr/local/bin}:${VENV_DIR:-/usr/local/bin}:/usr/bin:/bin"
Environment="PYTHONPATH=${PROJECT_DIR}"
ExecStart=${CELERY_BIN} -A celery_app worker --loglevel=info --pool=solo
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${PROJECT_NAME}-celery

[Install]
WantedBy=multi-user.target
EOF
print_success "Celery Worker 服务已创建"

# 创建 Celery Beat 服务
print_info "创建 Celery Beat 服务..."
cat > /etc/systemd/system/${PROJECT_NAME}-beat.service << EOF
[Unit]
Description=Celery Beat for ${PROJECT_NAME}
After=network.target ${PROJECT_NAME}-celery.service

[Service]
Type=simple
User=${USER}
Group=${GROUP}
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${VENV_DIR:-/usr/local/bin}:${VENV_DIR:-/usr/local/bin}:/usr/bin:/bin"
Environment="PYTHONPATH=${PROJECT_DIR}"
ExecStart=${CELERY_BIN} -A celery_app beat --loglevel=info
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${PROJECT_NAME}-beat

[Install]
WantedBy=multi-user.target
EOF
print_success "Celery Beat 服务已创建"

# 重新加载 systemd
print_info "重新加载 systemd 配置..."
sudo systemctl daemon-reload
print_success "systemd 配置已重载"

# 启用服务
print_info "启用服务..."
sudo systemctl enable ${PROJECT_NAME}.service 2>/dev/null || true
sudo systemctl enable ${PROJECT_NAME}-celery.service 2>/dev/null || true
sudo systemctl enable ${PROJECT_NAME}-beat.service 2>/dev/null || true
print_success "服务已启用"

# 显示状态
echo ""
print_info "服务状态:"
echo ""
echo "启动服务："
echo "  sudo systemctl start ${PROJECT_NAME}"
echo "  sudo systemctl start ${PROJECT_NAME}-celery"
echo "  sudo systemctl start ${PROJECT_NAME}-beat"
echo ""
echo "查看状态："
echo "  sudo systemctl status ${PROJECT_NAME}"
echo "  sudo systemctl status ${PROJECT_NAME}-celery"
echo "  sudo systemctl status ${PROJECT_NAME}-beat"
echo ""
echo "查看日志："
echo "  sudo journalctl -u ${PROJECT_NAME} -f"
echo "  sudo journalctl -u ${PROJECT_NAME}-celery -f"
echo "  sudo journalctl -u ${PROJECT_NAME}-beat -f"
echo ""
echo "或者直接运行（测试用）："
echo "  cd ${PROJECT_DIR}"
echo "  celery -A celery_app worker --loglevel=info"
echo ""

print_success "systemd 服务配置完成！"
