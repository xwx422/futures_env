#!/bin/bash
# AI期货分析系统 - 云服务器部署脚本（问题排查版）
# 版本：v2.0
# 使用方式：sudo ./deploy-production-cloud.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_DIR="/var/www/futures_ai"
PROJECT_USER="www-data"
PROJECT_GROUP="www-data"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "请使用 sudo 运行此脚本"
        exit 1
    fi
}

check_prerequisites() {
    log_info "检查前置条件..."
    
    if [ ! -f "app.py" ]; then
        log_error "请在项目根目录运行此脚本"
        exit 1
    fi
    
    if [ ! -f "requirements.txt" ]; then
        log_error "requirements.txt 不存在"
        exit 1
    fi
    
    log_success "前置条件检查通过"
}

fix_gunicorn_bind() {
    log_info "修复 Gunicorn 绑定地址..."
    
    if [ -f "config/gunicorn.conf.py" ]; then
        sed -i 's/bind = "127.0.0.1:8000"/bind = "0.0.0.0:8000"/g' config/gunicorn.conf.py
        log_success "Gunicorn 已改为绑定 0.0.0.0:8000"
    else
        log_warn "gunicorn.conf.py 不存在，跳过"
    fi
}

fix_systemd_service() {
    log_info "修复 Systemd 服务配置..."
    
    if [ -f "config/futures-ai.service" ]; then
        sed -i 's/User=www-data/User=root/g' /etc/systemd/system/futures-ai.service 2>/dev/null || true
        sed -i 's/Group=www-data/Group=root/g' /etc/systemd/system/futures-ai.service 2>/dev/null || true
        log_success "Systemd 服务已修复用户权限"
    fi
}

create_logs_directory() {
    log_info "创建日志目录..."
    
    mkdir -p $PROJECT_DIR/logs
    chown -R $PROJECT_USER:$PROJECT_GROUP $PROJECT_DIR/logs 2>/dev/null || true
    chmod -R 755 $PROJECT_DIR/logs
    
    touch $PROJECT_DIR/logs/gunicorn_access.log
    touch $PROJECT_DIR/logs/gunicorn_error.log
    touch $PROJECT_DIR/logs/main.log
    
    log_success "日志目录创建完成"
}

deploy_code() {
    log_info "部署应用代码..."
    
    if [ ! -d "$PROJECT_DIR" ]; then
        mkdir -p $PROJECT_DIR
    fi
    
    if command -v rsync &> /dev/null; then
        rsync -av --exclude='venv' --exclude='.git' --exclude='logs' \
              --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
              --exclude='*.db' . $PROJECT_DIR/
    else
        cp -r *.py $PROJECT_DIR/
        cp -r config data_layer analysis_layer execution_layer routes static templates doc $PROJECT_DIR/ 2>/dev/null || true
        cp requirements.txt .env.example favicon.ico logo.svg $PROJECT_DIR/ 2>/dev/null || true
    fi
    
    chown -R $PROJECT_USER:$PROJECT_GROUP $PROJECT_DIR 2>/dev/null || true
    
    log_success "代码部署完成"
}

fix_nginx_config() {
    log_info "修复 Nginx 配置..."
    
    if [ -f "config/nginx.conf" ]; then
        sed -i 's/server 127.0.0.1:8000;/server 127.0.0.1:8000;/g' config/nginx.conf
        
        mkdir -p /var/log/nginx
        touch /var/log/nginx/futures_ai_access.log
        touch /var/log/nginx/futures_ai_error.log
        
        if [ ! -f /etc/nginx/sites-enabled/futures_ai ]; then
            cp config/nginx.conf /etc/nginx/sites-available/futures_ai
            ln -sf /etc/nginx/sites-available/futures_ai /etc/nginx/sites-enabled/
        fi
        
        if [ -f /etc/nginx/sites-enabled/default ]; then
            rm /etc/nginx/sites-enabled/default
        fi
        
        nginx -t
        systemctl reload nginx
        
        log_success "Nginx 配置已修复"
    fi
}

configure_firewall() {
    log_info "配置防火墙..."
    
    if command -v ufw &> /dev/null; then
        ufw allow 80/tcp
        ufw allow 443/tcp
        ufw allow 22/tcp
        if ! ufw status | grep -q "Status: active"; then
            echo "y" | ufw enable
        fi
        ufw status
        log_success "UFW 防火墙已配置"
    elif command -v firewall-cmd &> /dev/null; then
        firewall-cmd --permanent --add-port=80/tcp
        firewall-cmd --permanent --add-port=443/tcp
        firewall-cmd --reload
        log_success "Firewalld 防火墙已配置"
    else
        log_warn "未检测到支持的防火墙工具，请手动开放 80/443 端口"
    fi
}

check_redis() {
    log_info "检查 Redis 服务..."
    
    if redis-cli ping &>/dev/null; then
        log_success "Redis 已运行"
    else
        log_warn "Redis 未运行，尝试启动..."
        
        if command -v systemctl &> /dev/null; then
            systemctl start redis-server 2>/dev/null || systemctl start redis 2>/dev/null || true
            sleep 2
            
            if redis-cli ping &>/dev/null; then
                log_success "Redis 已启动"
            else
                log_error "Redis 启动失败，请手动启动: sudo systemctl start redis-server"
            fi
        fi
    fi
}

reload_systemd() {
    log_info "重载 Systemd 配置..."
    
    systemctl daemon-reload
    
    log_success "Systemd 配置已重载"
}

restart_services() {
    log_info "重启服务..."
    
    # Gunicorn
    systemctl restart futures-ai
    sleep 3
    if systemctl is-active --quiet futures-ai; then
        log_success "futures-ai (Gunicorn) 运行正常"
    else
        log_error "futures-ai 服务启动失败"
        journalctl -u futures-ai -n 20 --no-pager
    fi
    
    # Celery Worker
    systemctl restart futures-ai-celery 2>/dev/null || true
    sleep 2
    if systemctl is-active --quiet futures-ai-celery 2>/dev/null; then
        log_success "futures-ai-celery (Worker) 运行正常"
    else
        log_warn "Celery Worker 未运行或不存在，定时任务可能无法执行"
    fi
    
    # Celery Beat
    systemctl restart futures-ai-beat 2>/dev/null || true
    sleep 2
    if systemctl is-active --quiet futures-ai-beat 2>/dev/null; then
        log_success "futures-ai-beat (定时调度器) 运行正常"
    else
        log_warn "Celery Beat 未运行或不存在，定时任务不会自动触发"
    fi
    
    systemctl restart nginx
    log_success "Nginx 已重启"
}

check_services_status() {
    log_info "检查服务状态..."
    
    echo ""
    echo "=== Gunicorn 服务 ==="
    systemctl status futures-ai --no-pager || true
    echo ""
    
    echo "=== Celery Worker ==="
    systemctl status futures-ai-celery --no-pager || true
    echo ""
    
    echo "=== Celery Beat ==="
    systemctl status futures-ai-beat --no-pager || true
    echo ""
    
    echo "=== 端口监听 ==="
    netstat -tlnp 2>/dev/null | grep -E ":(80|443|8000)" || ss -tlnp | grep -E ":(80|443|8000)" || true
    echo ""
    
    echo "=== Gunicorn 进程 ==="
    ps aux | grep gunicorn | grep -v grep || true
    echo ""
    
    echo "=== Celery 进程 ==="
    ps aux | grep celery | grep -v grep || true
    echo ""
    
    echo "=== Nginx 状态 ==="
    systemctl status nginx --no-pager || true
}

test_connectivity() {
    log_info "测试连接性..."
    
    SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "无法获取IP")
    
    echo ""
    echo "=== 连接测试 ==="
    
    echo "1. 测试本地 Gunicorn (8000端口)..."
    curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ 2>/dev/null || echo "失败"
    
    echo ""
    echo "2. 测试 Nginx (80端口)..."
    curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:80/ 2>/dev/null || echo "失败"
    
    echo ""
    echo "3. 测试外部访问 (http://${SERVER_IP}:80)..."
    curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "http://${SERVER_IP}:80/" 2>/dev/null || echo "失败/超时"
    
    echo ""
    echo "=== Web 访问地址 ==="
    echo "http://${SERVER_IP}"
    echo "http://${SERVER_IP}:80"
}

show_diagnostic_commands() {
    echo ""
    echo "========================================"
    log_success "部署完成！"
    echo "========================================"
    echo ""
    echo "📋 故障排查命令:"
    echo ""
    echo "  # 查看服务状态"
    echo "  systemctl status futures-ai"
    echo "  systemctl status nginx"
    echo ""
    echo "  # 查看应用日志"
    echo "  journalctl -u futures-ai -f"
    echo "  tail -f $PROJECT_DIR/logs/gunicorn_error.log"
    echo "  tail -f /var/log/nginx/futures_ai_error.log"
    echo ""
    echo "  # 检查端口监听"
    echo "  netstat -tlnp | grep -E ':(80|443|8000)'"
    echo ""
    echo "  # 测试本地访问"
    echo "  curl http://127.0.0.1:8000/"
    echo "  curl http://127.0.0.1/"
    echo ""
    echo "  # 云服务器安全组检查"
    echo "  # 登录云平台控制台，确保开放 80 和 443 端口"
    echo ""
}

main() {
    echo "========================================"
    echo "  AI期货分析系统 - 云服务器部署"
    echo "  问题排查版"
    echo "========================================"
    echo ""
    
    check_root
    check_prerequisites
    
    echo ""
    echo "请选择操作:"
    echo "  1) 完整部署（推荐首次使用）"
    echo "  2) 仅修复并重启服务（代码已部署时使用）"
    echo "  3) 仅检查服务状态"
    echo "  4) 运行连接测试"
    echo ""
    read -p "请输入选项 (1-4): " choice
    echo ""
    
    case $choice in
        1)
            fix_gunicorn_bind
            deploy_code
            create_logs_directory
            fix_nginx_config
            configure_firewall
            check_redis
            reload_systemd
            restart_services
            check_services_status
            test_connectivity
            show_diagnostic_commands
            ;;
        2)
            fix_gunicorn_bind
            fix_systemd_service
            create_logs_directory
            fix_nginx_config
            check_redis
            reload_systemd
            restart_services
            check_services_status
            ;;
        3)
            check_services_status
            ;;
        4)
            test_connectivity
            ;;
        *)
            log_error "无效选项"
            exit 1
            ;;
    esac
}

main
