#!/bin/bash
# AI期货分析系统 - 生产环境部署脚本（Nginx + Gunicorn + Systemd）
# 版本：v1.0
# 使用方式：sudo ./deploy-production.sh

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 配置变量
PROJECT_DIR="/var/www/futures_ai"
PROJECT_USER="www-data"
PROJECT_GROUP="www-data"
DOMAIN=""  # 将自动获取或手动输入

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查root权限
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "请使用 sudo 运行此脚本"
        exit 1
    fi
}

# 检测操作系统
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VERSION=$VERSION_ID
    else
        log_error "无法检测操作系统"
        exit 1
    fi
    log_info "检测到操作系统: $OS $VERSION"
}

# 安装系统依赖
install_dependencies() {
    log_info "安装系统依赖..."
    
    case $OS in
        ubuntu|debian)
            apt update
            apt install -y python3 python3-pip python3-venv nginx git curl
            apt install -y build-essential libssl-dev libffi-dev
            
            # 安装 certbot（用于 SSL）
            if ! command -v certbot &> /dev/null; then
                apt install -y certbot python3-certbot-nginx
            fi
            ;;
        centos|rhel|fedora)
            yum update -y
            yum install -y python3 python3-pip nginx git curl
            yum install -y gcc openssl-devel bzip2-devel libffi-devel
            
            # 安装 certbot
            if ! command -v certbot &> /dev/null; then
                yum install -y certbot python3-certbot-nginx
            fi
            ;;
        *)
            log_error "不支持的操作系统: $OS"
            exit 1
            ;;
    esac
    
    log_success "系统依赖安装完成"
}

# 创建项目目录
setup_project_dir() {
    log_info "创建项目目录..."
    
    if [ ! -d "$PROJECT_DIR" ]; then
        mkdir -p $PROJECT_DIR
        log_success "项目目录创建完成: $PROJECT_DIR"
    else
        log_warn "项目目录已存在: $PROJECT_DIR"
        read -p "是否清空并重新部署? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            backup_dir="${PROJECT_DIR}.backup.$(date +%Y%m%d%H%M%S)"
            mv $PROJECT_DIR $backup_dir
            log_info "原项目已备份到: $backup_dir"
            mkdir -p $PROJECT_DIR
        fi
    fi
    
    # 设置权限
    chown -R $PROJECT_USER:$PROJECT_GROUP $PROJECT_DIR
}

# 询问域名
ask_domain() {
    echo
    log_info "qh.ossou.cn"
    echo "----------------------------------------"
    read -p "请输入您的域名 (如: futures.example.com，无则回车): " input_domain
    
    if [ -n "$input_domain" ]; then
        DOMAIN=$input_domain
        log_info "使用域名: $DOMAIN"
    else
        log_warn "未配置域名，将使用 IP 访问"
    fi
}

# 配置 Nginx
setup_nginx() {
    log_info "配置 Nginx..."
    
    # 复制配置文件
    if [ -n "$DOMAIN" ]; then
        # 使用域名配置
        sed "s/server_name _;/server_name $DOMAIN;/g" config/nginx.conf > /etc/nginx/sites-available/futures_ai
    else
        # 使用默认配置
        cp config/nginx.conf /etc/nginx/sites-available/futures_ai
    fi
    
    # 修改项目路径
    sed -i "s|/var/www/futures_ai|$PROJECT_DIR|g" /etc/nginx/sites-available/futures_ai
    
    # 启用站点
    if [ ! -f /etc/nginx/sites-enabled/futures_ai ]; then
        ln -sf /etc/nginx/sites-available/futures_ai /etc/nginx/sites-enabled/
    fi
    
    # 删除默认站点
    if [ -f /etc/nginx/sites-enabled/default ]; then
        rm /etc/nginx/sites-enabled/default
        log_info "已删除默认站点配置"
    fi
    
    # 创建日志目录
    mkdir -p /var/log/nginx
    touch /var/log/nginx/futures_ai_access.log
    touch /var/log/nginx/futures_ai_error.log
    
    # 测试配置
    nginx -t
    if [ $? -ne 0 ]; then
        log_error "Nginx 配置测试失败"
        exit 1
    fi
    
    # 重启 Nginx
    systemctl restart nginx
    systemctl enable nginx
    
    log_success "Nginx 配置完成"
}

# 配置 SSL
setup_ssl() {
    if [ -z "$DOMAIN" ]; then
        log_warn "未配置域名，跳过 SSL 配置"
        return
    fi
    
    log_info "配置 SSL 证书..."
    
    read -p "是否申请 Let's Encrypt SSL 证书? (Y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        # 申请证书
        certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN
        
        if [ $? -eq 0 ]; then
            log_success "SSL 证书申请成功"
            
            # 设置自动续期
            systemctl enable certbot.timer
            systemctl start certbot.timer
            log_info "已启用证书自动续期"
        else
            log_error "SSL 证书申请失败"
            log_warn "请检查域名解析是否正确"
        fi
    else
        log_warn "跳过 SSL 配置"
    fi
}

# 配置防火墙
setup_firewall() {
    log_info "配置防火墙..."
    
    if command -v ufw &> /dev/null; then
        # Ubuntu/Debian
        ufw allow 'Nginx Full'
        ufw allow OpenSSH
        
        # 检查ufw是否已启用
        if ! ufw status | grep -q "Status: active"; then
            log_info "启用 UFW 防火墙..."
            echo "y" | ufw enable
        fi
        
        ufw status
        log_success "防火墙配置完成"
    elif command -v firewall-cmd &> /dev/null; then
        # CentOS/RHEL
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --reload
        log_success "防火墙配置完成"
    else
        log_warn "未检测到支持的防火墙工具"
    fi
}

# 配置 systemd 服务
setup_systemd() {
    log_info "配置 Systemd 服务..."
    
    # 复制 Gunicorn 服务文件
    cp config/futures-ai.service /etc/systemd/system/
    
    # 修改项目路径
    sed -i "s|/var/www/futures_ai|$PROJECT_DIR|g" /etc/systemd/system/futures-ai.service
    
    # 创建 Celery Worker 服务
    VENV_DIR="${PROJECT_DIR}/venv"
    CELERY_BIN="${VENV_DIR}/bin/celery"
    
    cat > /etc/systemd/system/futures-ai-celery.service << EOF
[Unit]
Description=Celery Worker for futures-ai
After=network.target

[Service]
Type=simple
User=${PROJECT_USER}
Group=${PROJECT_GROUP}
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${VENV_DIR}/bin:/usr/bin:/bin"
Environment="PYTHONPATH=${PROJECT_DIR}"
ExecStart=${CELERY_BIN} -A celery_app worker --loglevel=info --pool=solo
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=futures-ai-celery

[Install]
WantedBy=multi-user.target
EOF
    
    # 创建 Celery Beat 服务
    cat > /etc/systemd/system/futures-ai-beat.service << EOF
[Unit]
Description=Celery Beat for futures-ai
After=network.target futures-ai-celery.service

[Service]
Type=simple
User=${PROJECT_USER}
Group=${PROJECT_GROUP}
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${VENV_DIR}/bin:/usr/bin:/bin"
Environment="PYTHONPATH=${PROJECT_DIR}"
ExecStart=${CELERY_BIN} -A celery_app beat --loglevel=info
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=futures-ai-beat

[Install]
WantedBy=multi-user.target
EOF
    
    # 重新加载 systemd
    systemctl daemon-reload
    
    # 启用所有服务
    systemctl enable futures-ai
    systemctl enable futures-ai-celery
    systemctl enable futures-ai-beat
    
    log_success "Systemd 服务配置完成（Gunicorn + Celery Worker + Celery Beat）"
}

# 创建日志目录
setup_logs() {
    log_info "创建日志目录..."
    
    mkdir -p $PROJECT_DIR/logs
    chown -R $PROJECT_USER:$PROJECT_GROUP $PROJECT_DIR/logs
    
    # 创建必要的日志文件
    touch $PROJECT_DIR/logs/gunicorn_access.log
    touch $PROJECT_DIR/logs/gunicorn_error.log
    chown -R $PROJECT_USER:$PROJECT_GROUP $PROJECT_DIR/logs
    
    log_success "日志目录创建完成"
}

# 部署应用代码
deploy_code() {
    log_info "部署应用代码..."
    
    # 检查当前目录是否是项目根目录
    if [ ! -f "app.py" ] || [ ! -f "main.py" ]; then
        log_error "请在项目根目录运行此脚本"
        exit 1
    fi
    
    # 复制代码到项目目录
    log_info "复制项目文件..."
    
    # 使用 rsync 或 cp 复制文件
    if command -v rsync &> /dev/null; then
        rsync -av --exclude='venv' --exclude='.git' --exclude='logs' --exclude='__pycache__' \
              --exclude='*.pyc' --exclude='.DS_Store' --exclude='.ruff_cache' \
              . $PROJECT_DIR/
    else
        # 使用 cp 复制
        cp -r *.py $PROJECT_DIR/
        cp -r config data_layer analysis_layer execution_layer routes static templates doc $PROJECT_DIR/ 2>/dev/null || true
        cp requirements.txt .env.example favicon.ico logo.svg $PROJECT_DIR/ 2>/dev/null || true
    fi
    
    # 设置权限
    chown -R $PROJECT_USER:$PROJECT_GROUP $PROJECT_DIR
    
    log_success "代码部署完成"
}

# 安装 Python 依赖
install_python_deps() {
    log_info "安装 Python 依赖..."
    
    # 创建虚拟环境
    if [ ! -d "$PROJECT_DIR/venv" ]; then
        python3 -m venv $PROJECT_DIR/venv
        log_success "虚拟环境创建完成"
    fi
    
    # 安装依赖
    $PROJECT_DIR/venv/bin/pip install --upgrade pip -q
    $PROJECT_DIR/venv/bin/pip install -r $PROJECT_DIR/requirements.txt -q
    $PROJECT_DIR/venv/bin/pip install gunicorn -q
    
    log_success "Python 依赖安装完成"
}

# 配置环境变量
setup_environment() {
    log_info "配置环境变量..."
    
    cd $PROJECT_DIR
    
    if [ -f ".env" ]; then
        log_warn ".env 文件已存在"
    else
        if [ -f ".env.example" ]; then
            cp .env.example .env
            
            # 生成随机 SECRET_KEY
            SECRET_KEY=$($PROJECT_DIR/venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
            sed -i "s/your-secret-key-here/$SECRET_KEY/g" .env
            
            log_success ".env 文件已创建"
        fi
    fi
    
    chmod 600 .env
    chown $PROJECT_USER:$PROJECT_GROUP .env
}

# 初始化数据库
init_database() {
    log_info "初始化数据库..."
    
    cd $PROJECT_DIR
    
    if [ -f "futures_analysis.db" ]; then
        log_warn "数据库已存在"
        read -p "是否重新初始化? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            mv futures_analysis.db "futures_analysis.db.backup.$(date +%Y%m%d%H%M%S)"
            $PROJECT_DIR/venv/bin/python init_db.py
        fi
    else
        $PROJECT_DIR/venv/bin/python init_db.py
    fi
    
    # 设置数据库权限
    chown $PROJECT_USER:$PROJECT_GROUP futures_analysis.db 2>/dev/null || true
    chmod 666 futures_analysis.db 2>/dev/null || true
    
    log_success "数据库初始化完成"
}

# 启动服务
start_services() {
    log_info "启动服务..."
    
    # 启动 Gunicorn
    systemctl start futures-ai
    sleep 2
    
    if systemctl is-active --quiet futures-ai; then
        log_success "futures-ai (Gunicorn) 启动成功"
    else
        log_error "futures-ai 服务启动失败"
        systemctl status futures-ai
        exit 1
    fi
    
    # 启动 Celery Worker
    systemctl start futures-ai-celery
    sleep 2
    if systemctl is-active --quiet futures-ai-celery; then
        log_success "futures-ai-celery (Worker) 启动成功"
    else
        log_warn "Celery Worker 启动失败，定时任务可能无法执行"
    fi
    
    # 启动 Celery Beat
    systemctl start futures-ai-beat
    sleep 2
    if systemctl is-active --quiet futures-ai-beat; then
        log_success "futures-ai-beat (定时调度器) 启动成功"
    else
        log_warn "Celery Beat 启动失败，定时任务不会自动触发"
    fi
    
    # 重启 Nginx
    systemctl restart nginx
    
    log_success "所有服务已启动"
}

# 显示部署信息
show_summary() {
    echo
    echo "========================================"
    log_success "生产环境部署完成！"
    echo "========================================"
    echo
    echo "📁 项目目录: $PROJECT_DIR"
    echo "🌐 访问地址: http://${DOMAIN:-$(curl -s ifconfig.me || echo 'your-server-ip')}"
    if [ -n "$DOMAIN" ]; then
        echo "🔒 HTTPS: https://$DOMAIN"
    fi
    echo
    echo "📋 服务管理命令:"
    echo "  systemctl status futures-ai          # Web 服务状态"
    echo "  systemctl status futures-ai-celery   # Celery Worker 状态"
    echo "  systemctl status futures-ai-beat     # Celery Beat 状态"
    echo "  systemctl restart futures-ai         # 重启 Web"
    echo "  systemctl restart futures-ai-celery  # 重启 Worker"
    echo "  systemctl restart futures-ai-beat    # 重启 Beat"
    echo
    echo "🌐 Nginx 管理命令:"
    echo "  nginx -t                       # 测试配置"
    echo "  systemctl reload nginx         # 重载配置"
    echo
    echo "📜 日志查看:"
    echo "  tail -f $PROJECT_DIR/logs/gunicorn_error.log"
    echo "  tail -f /var/log/nginx/futures_ai_error.log"
    echo "  journalctl -u futures-ai -f"
    echo "  journalctl -u futures-ai-celery -f"
    echo "  journalctl -u futures-ai-beat -f"
    echo
    echo "⚙️  配置文件:"
    echo "  Nginx: /etc/nginx/sites-available/futures_ai"
    echo "  Systemd: /etc/systemd/system/futures-ai.service"
    echo "  Systemd Celery: /etc/systemd/system/futures-ai-celery.service"
    echo "  Systemd Beat: /etc/systemd/system/futures-ai-beat.service"
    echo "  环境变量: $PROJECT_DIR/.env"
    echo
    echo "⚠️  重要提示:"
    log_warn "请编辑 $PROJECT_DIR/.env 文件，配置天勤账号 (TQSDK_AUTH)"
    log_warn "默认管理员账号: admin / admin123"
    echo "  Celery Beat 已配置 10 个定时任务，启动后全自动运行，无需手动干预"
    echo
}

# 主函数
main() {
    echo "========================================"
    echo "  AI期货分析系统 - 生产环境部署"
    echo "  Nginx + Gunicorn + Systemd"
    echo "========================================"
    echo
    
    # 检查root权限
    check_root
    
    # 检测操作系统
    detect_os
    
    # 询问域名
    ask_domain
    
    # 执行部署步骤
    install_dependencies
    setup_project_dir
    deploy_code
    setup_logs
    install_python_deps
    setup_environment
    init_database
    setup_nginx
    setup_ssl
    setup_firewall
    setup_systemd
    start_services
    
    # 显示部署信息
    show_summary
}

# 运行主函数
main
