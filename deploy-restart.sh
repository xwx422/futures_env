#!/bin/bash
#
# AI 期货分析系统 - 一键更新部署重启脚本（完整版）
#
# 适用环境：Nginx + Gunicorn + Systemd + Cron + Celery (Worker + Beat)
# 项目路径：/var/www/futures_ai
# 使用方法：sudo bash deploy-restart.sh
#
# 重启的服务包括:
#   - Gunicorn (Web 服务)
#   - Celery Worker (异步任务)
#   - Celery Beat (定时任务调度器)
#   - Nginx (反向代理)
#   - Cron (系统定时任务)
#
# 定时任务说明:
#   - 自动回测：每日 23:30 运行，回测最近 7 天数据
#   - 周度报告：每周日 23:00 运行，回测最近 30 天数据
#   - 数据更新：每 4 小时更新所有品种数据
#   - 价格刷新：每 3 分钟刷新实时价格
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 项目配置
PROJECT_NAME="futures-ai"
PROJECT_DIR="/var/www/futures_ai"
VENV_DIR="${PROJECT_DIR}/venv"
SYSTEMD_SERVICE="${PROJECT_NAME}.service"
CELERY_SERVICE="${PROJECT_NAME}-celery.service"
CELERY_BEAT_SERVICE="${PROJECT_NAME}-beat.service"
NGINX_SERVICE="nginx"
CRON_SERVICE="cron"
BACKUP_DIR="${PROJECT_DIR}/backups"
LOG_DIR="${PROJECT_DIR}/logs"

# 定时任务脚本
SCHEDULE_RUNNER="${PROJECT_DIR}/schedule_runner.sh"
BACKTEST_CRON="${PROJECT_DIR}/setup_backtest_cron.sh"
RUN_BACKTEST="${PROJECT_DIR}/run_backtest_with_calendar.sh"

# 日志文件
DEPLOY_LOG="${LOG_DIR}/deploy_$(date +%Y%m%d_%H%M%S).log"

# 打印函数
print_header() {
    echo -e "${CYAN}================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}================================${NC}"
    echo ""
}

print_step() {
    echo -e "${YELLOW}[$1]${NC} $2"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# 检查是否在项目目录
check_project_dir() {
    print_step "0" "检查项目目录"
    if [ ! -d "$PROJECT_DIR" ]; then
        print_error "项目目录不存在：$PROJECT_DIR"
        exit 1
    fi
    cd "$PROJECT_DIR"
    print_success "项目目录检查通过"
}

# 创建备份
create_backup() {
    print_step "1" "创建备份"
    
    # 创建备份目录
    mkdir -p "$BACKUP_DIR"
    
    # 生成备份文件名
    BACKUP_NAME="backup_$(date +%Y%m%d_%H%M%S)"
    BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"
    mkdir -p "$BACKUP_PATH"
    
    # 备份数据库
    if [ -f "${PROJECT_DIR}/futures_analysis.db" ]; then
        cp "${PROJECT_DIR}/futures_analysis.db" "$BACKUP_PATH/"
        print_success "数据库已备份"
    fi
    
    # 备份配置文件
    if [ -f "${PROJECT_DIR}/.env" ]; then
        cp "${PROJECT_DIR}/.env" "$BACKUP_PATH/"
        print_success ".env 已备份"
    fi
    
    if [ -f "${PROJECT_DIR}/config.yaml" ]; then
        cp "${PROJECT_DIR}/config.yaml" "$BACKUP_PATH/"
        print_success "config.yaml 已备份"
    fi
    
    # 备份 crontab
    crontab -l > "$BACKUP_PATH/crontab_backup.txt" 2>/dev/null || true
    print_success "crontab 已备份"
    
    print_info "备份位置：$BACKUP_PATH"
}

# 停止服务
stop_services() {
    print_step "2" "停止服务"

    # 停止 Gunicorn
    print_info "停止 Gunicorn..."
    sudo systemctl stop "$SYSTEMD_SERVICE" 2>/dev/null || true
    pkill -f "gunicorn.*app:app" 2>/dev/null || true
    pkill -f "gunicorn" 2>/dev/null || true
    sleep 2
    print_success "Gunicorn 已停止"

    # 停止 Celery Worker
    print_info "停止 Celery Worker..."
    sudo systemctl stop "$CELERY_SERVICE" 2>/dev/null || true
    pkill -f "celery.*worker" 2>/dev/null || true
    sleep 1
    print_success "Celery Worker 已停止"

    # 停止 Celery Beat
    print_info "停止 Celery Beat..."
    sudo systemctl stop "$CELERY_BEAT_SERVICE" 2>/dev/null || true
    pkill -f "celery.*beat" 2>/dev/null || true
    sleep 1
    print_success "Celery Beat 已停止"

    # 停止 Nginx
    print_info "停止 Nginx..."
    sudo systemctl stop "$NGINX_SERVICE" 2>/dev/null || true
    sleep 1
    print_success "Nginx 已停止"

    # 停止 Redis（可选，如无权限则跳过）
    print_info "检查 Redis..."
    if command -v redis-cli &> /dev/null; then
        if redis-cli ping &> /dev/null 2>&1; then
            print_success "Redis 运行正常（无需重启）"
        else
            print_warning "Redis 未运行，请手动启动"
        fi
    fi
}

# 清理缓存和临时文件
clean_cache() {
    print_step "3" "清理缓存和临时文件"
    
    # 清理 Python 缓存
    print_info "清理 Python 缓存..."
    find "$PROJECT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$PROJECT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    find "$PROJECT_DIR" -type f -name "*.pyo" -delete 2>/dev/null || true
    find "$PROJECT_DIR" -type f -name "*.pyd" -delete 2>/dev/null || true
    print_success "Python 缓存已清理"
    
    # 清理日志文件（保留最近 7 天）
    print_info "清理旧日志文件..."
    if [ -d "$LOG_DIR" ]; then
        find "$LOG_DIR" -type f -name "*.log" -mtime +7 -delete 2>/dev/null || true
        find "$LOG_DIR" -type f -name "*.log.*" -mtime +7 -delete 2>/dev/null || true
    fi
    print_success "旧日志已清理（保留 7 天）"
    
    # 清理 Celery Beat 调度文件
    print_info "清理 Celery Beat 调度文件..."
    rm -f "${LOG_DIR}/celerybeat-schedule" 2>/dev/null || true
    rm -f "${LOG_DIR}/celerybeat-schedule.db" 2>/dev/null || true
    rm -f "${PROJECT_DIR}/celerybeat-schedule" 2>/dev/null || true
    rm -f "${PROJECT_DIR}/celerybeat-schedule.db" 2>/dev/null || true
    rm -f "${PROJECT_DIR}/celerybeat-schedule*" 2>/dev/null || true
    print_success "Celery Beat 调度文件已清理"

    # 清理 Gunicorn Socket
    print_info "清理 Gunicorn Socket..."
    rm -f "${PROJECT_DIR}/gunicorn.sock" 2>/dev/null || true
    print_success "Gunicorn Socket 已清理"

    # 清理系统临时文件
    print_info "清理系统临时文件..."
    rm -rf /tmp/futures_* 2>/dev/null || true
    rm -rf /tmp/celery_* 2>/dev/null || true
    print_success "系统临时文件已清理"
    
    # 清理 Redis 缓存键（可选）
    print_info "清理 Redis 过期任务键..."
    if command -v redis-cli &> /dev/null; then
        redis-cli KEYS "celery-task-meta-*" 2>/dev/null | xargs redis-cli DEL 2>/dev/null || true
        print_success "Redis 过期任务键已清理"
    fi
}

# 重启定时任务
restart_cron_jobs() {
    print_step "4" "重启定时任务"

    # 先执行数据库迁移（确保新字段存在）
    print_info "检查数据库结构..."
    cd "$PROJECT_DIR"
    if [ -f "${VENV_DIR}/bin/python" ]; then
        ${VENV_DIR}/bin/python init_db.py 2>/dev/null && print_success "数据库结构检查完成" || print_warning "数据库迁移失败（不影响启动，应用启动时会重试）"
    fi

    # 检查 crontab 是否存在
    if crontab -l 2>/dev/null | grep -q "$SCHEDULE_RUNNER"; then
        print_info "检测到数据更新定时任务"
        print_info "重启 schedule_runner.sh..."

        # 确保脚本可执行
        chmod +x "$SCHEDULE_RUNNER" 2>/dev/null || true

        # 重启 cron 服务
        sudo systemctl restart "$CRON_SERVICE" 2>/dev/null || true
        print_success "数据更新定时任务已重启"
    else
        print_info "未检测到数据更新定时任务，正在创建..."
        
        # 创建定时任务（仅交易日：周一到周五）
        (crontab -l 2>/dev/null || true; cat << 'CRONEOF'
# 数据更新定时任务（仅交易日）
30 8 * * 1-5 cd /var/www/futures_ai && /var/www/futures_ai/schedule_runner.sh >> /var/www/futures_ai/logs/schedule_runner.log 2>&1
20 10 * * 1-5 cd /var/www/futures_ai && /var/www/futures_ai/schedule_runner.sh >> /var/www/futures_ai/logs/schedule_runner.log 2>&1
0 13 * * 1-5 cd /var/www/futures_ai && /var/www/futures_ai/schedule_runner.sh >> /var/www/futures_ai/logs/schedule_runner.log 2>&1
0 14 * * 1-5 cd /var/www/futures_ai && /var/www/futures_ai/schedule_runner.sh >> /var/www/futures_ai/logs/schedule_runner.log 2>&1
30 20 * * 1-5 cd /var/www/futures_ai && /var/www/futures_ai/schedule_runner.sh >> /var/www/futures_ai/logs/schedule_runner.log 2>&1
0 22 * * 1-5 cd /var/www/futures_ai && /var/www/futures_ai/schedule_runner.sh >> /var/www/futures_ai/logs/schedule_runner.log 2>&1
CRONEOF
) | crontab -
        
        chmod +x "$SCHEDULE_RUNNER" 2>/dev/null || true
        print_success "数据更新定时任务已创建"
    fi

    # 检查回测定时任务
    if crontab -l 2>/dev/null | grep -q "$RUN_BACKTEST"; then
        print_info "检测到自动回测定时任务"
        print_info "确保回测脚本可执行..."

        # 确保脚本可执行
        chmod +x "$RUN_BACKTEST" 2>/dev/null || true
        chmod +x "$BACKTEST_CRON" 2>/dev/null || true

        print_success "自动回测定时任务已检查"
    else
        print_info "未检测到自动回测定时任务（可选）"
    fi

    # 重启 cron 服务
    print_info "重启 Cron 服务..."
    sudo systemctl restart "$CRON_SERVICE" 2>/dev/null || sudo service cron restart 2>/dev/null || true
    print_success "Cron 服务已重启"
    
    # 显示当前 crontab 配置
    print_info "当前 crontab 配置:"
    crontab -l 2>/dev/null | grep -E "(schedule_runner|backtest|futures)" || print_info "无相关定时任务"
}

# 启动服务
start_services() {
    print_step "5" "启动服务"
    
    # 检查 systemd 服务文件是否存在（任意一个缺失都需要重新创建）
    print_info "检查 systemd 服务配置..."
    if [ ! -f "/etc/systemd/system/$SYSTEMD_SERVICE" ] || [ ! -f "/etc/systemd/system/$CELERY_SERVICE" ] || [ ! -f "/etc/systemd/system/$CELERY_BEAT_SERVICE" ]; then
        print_warning "Systemd 服务文件不完整，创建全部服务..."
        sudo bash "${PROJECT_DIR}/setup_systemd_services.sh"
    fi

    # 重新加载 Systemd 配置
    print_info "重新加载 Systemd 配置..."
    sudo systemctl daemon-reload
    print_success "Systemd 配置已重载"

    # 启动 Nginx
    print_info "启动 Nginx..."
    sudo systemctl start "$NGINX_SERVICE"
    print_success "Nginx 已启动"

    # 启动 Gunicorn
    print_info "启动 Gunicorn..."
    sudo systemctl start "$SYSTEMD_SERVICE"
    sleep 2
    print_success "Gunicorn 已启动"

    # 启动 Celery Worker
    print_info "启动 Celery Worker..."
    sudo systemctl start "$CELERY_SERVICE"
    sleep 2
    print_success "Celery Worker 已启动"

    # 启动 Celery Beat（重要：自动回测依赖此服务）
    print_info "启动 Celery Beat..."
    sudo systemctl start "$CELERY_BEAT_SERVICE"
    sleep 2
    print_success "Celery Beat 已启动"
    
    # 显示 Celery Beat 定时任务配置
    print_info "Celery Beat 定时任务:"
    if [ -f "${PROJECT_DIR}/celery_app.py" ]; then
        cd "$PROJECT_DIR"
        ${VENV_DIR}/bin/python -c "
from celery_app import celery_app
tasks = list(celery_app.conf.beat_schedule.keys())
print(f'   已加载 {len(tasks)} 个定时任务:')
for name in tasks:
    task = celery_app.conf.beat_schedule[name]
    schedule = task.get('schedule', 'unknown')
    print(f'      - {name}: {schedule}')
" 2>/dev/null || print_info "   无法读取 Celery 配置"
    fi
    
    # 显示 Cron 定时任务配置
    print_info "Cron 定时任务:"
    cron_count=$(crontab -l 2>/dev/null | grep -c "schedule_runner" || echo "0")
    if [ "$cron_count" -gt 0 ]; then
        crontab -l 2>/dev/null | grep "schedule_runner" | while read line; do
            echo "   - $line"
        done
    else
        print_info "   未配置（deploy-restart.sh 会在检测不到时自动创建）"
    fi
}

# 验证服务状态
verify_services() {
    print_step "6" "验证服务状态"

    # 检查 Gunicorn
    if sudo systemctl is-active --quiet "$SYSTEMD_SERVICE"; then
        print_success "Gunicorn 运行正常"
    else
        print_error "Gunicorn 启动失败"
        sudo systemctl status "$SYSTEMD_SERVICE" --no-pager | head -10
    fi

    # 检查 Celery Worker
    if sudo systemctl is-active --quiet "$CELERY_SERVICE"; then
        print_success "Celery Worker 运行正常"
    else
        print_error "Celery Worker 启动失败"
        sudo systemctl status "$CELERY_SERVICE" --no-pager | head -10
    fi

    # 检查 Celery Beat
    if sudo systemctl is-active --quiet "$CELERY_BEAT_SERVICE"; then
        print_success "Celery Beat 运行正常"
    else
        print_error "Celery Beat 启动失败"
        sudo systemctl status "$CELERY_BEAT_SERVICE" --no-pager | head -10
    fi

    # 检查 Nginx
    if sudo systemctl is-active --quiet "$NGINX_SERVICE"; then
        print_success "Nginx 运行正常"
    else
        print_error "Nginx 启动失败"
        sudo systemctl status "$NGINX_SERVICE" --no-pager | head -10
    fi

    # 检查 Cron
    if sudo systemctl is-active --quiet "$CRON_SERVICE"; then
        print_success "Cron 运行正常"
    else
        print_warning "Cron 未运行（如无定时任务可忽略）"
    fi

    # 检查端口
    print_info "检查端口监听..."
    sleep 3
    if command -v netstat &> /dev/null; then
        netstat -tlnp 2>/dev/null | grep -E ":(80|443|8000)" || print_info "端口检查完成"
    elif command -v ss &> /dev/null; then
        ss -tlnp 2>/dev/null | grep -E ":(80|443|8000)" || print_info "端口检查完成"
    fi
    
    # 检查数据库连接
    print_info "检查数据库连接..."
    if [ -f "${PROJECT_DIR}/futures_analysis.db" ]; then
        db_tables=$(sqlite3 "${PROJECT_DIR}/futures_analysis.db" ".tables" 2>/dev/null | wc -w)
        if [ "$db_tables" -gt 0 ]; then
            print_success "数据库连接正常（$db_tables 个表）"
        else
            print_warning "数据库表数量为 0"
        fi
    else
        print_warning "数据库文件不存在"
    fi
}

# 测试 API
test_api() {
    print_step "7" "测试 API"

    # 测试首页
    print_info "测试首页..."
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ | grep -q "200\|302"; then
        print_success "首页访问正常"
    else
        print_error "首页访问失败"
    fi

    # 测试价格 API
    print_info "测试价格 API..."
    API_RESULT=$(curl -s "http://localhost:8000/api/price/current" 2>/dev/null)
    if echo "$API_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('success') else 1)" 2>/dev/null; then
        print_success "价格 API 正常"
    else
        print_error "价格 API 异常"
    fi

    
    # 测试数据库连接
    print_info "测试数据库查询..."
    if [ -f "${PROJECT_DIR}/futures_analysis.db" ]; then
        count=$(sqlite3 "${PROJECT_DIR}/futures_analysis.db" "SELECT COUNT(*) FROM analysis_records;" 2>/dev/null)
        if [ "$count" -gt 0 ]; then
            print_success "数据库有 $count 条分析记录"
        else
            print_warning "数据库无分析记录"
        fi
    fi
}

# 显示服务状态
show_status() {
    print_header "服务状态"

    echo "Gunicorn:"
    sudo systemctl status "$SYSTEMD_SERVICE" --no-pager -l | head -10
    echo ""

    echo "Celery Worker:"
    sudo systemctl status "$CELERY_SERVICE" --no-pager -l | head -10
    echo ""

    echo "Celery Beat:"
    sudo systemctl status "$CELERY_BEAT_SERVICE" --no-pager -l | head -10
    echo ""

    echo "Nginx:"
    sudo systemctl status "$NGINX_SERVICE" --no-pager -l | head -10
    echo ""

    echo "Cron:"
    sudo systemctl status "$CRON_SERVICE" --no-pager -l | head -10
    echo ""
}

# 显示业务状态
show_business_status() {
    print_header "业务状态"
    
    if [ -f "${PROJECT_DIR}/futures_analysis.db" ]; then
        cd "$PROJECT_DIR"
        
        
        # 数据更新统计
        print_info "数据更新统计:"
        sqlite3 futures_analysis.db "SELECT COUNT(*) as count FROM update_logs WHERE DATE(update_time) = DATE('now');" 2>/dev/null && echo "   今日更新次数" || echo "   无数据"
        
        # 最新分析时间
        print_info "最新分析时间:"
        sqlite3 futures_analysis.db "SELECT MAX(run_time) FROM analysis_records;" 2>/dev/null || echo "   无数据"
    fi
}

# 显示日志
show_logs() {
    print_header "最近日志"
    
    print_info "Gunicorn 最近日志:"
    sudo journalctl -u "$SYSTEMD_SERVICE" --no-pager -n 5
    echo ""
    
    print_info "Celery Worker 最近日志:"
    sudo journalctl -u "$CELERY_SERVICE" --no-pager -n 5
    echo ""
    
    print_info "Celery Beat 最近日志:"
    sudo journalctl -u "$CELERY_BEAT_SERVICE" --no-pager -n 5
    echo ""
    
    print_info "Cron 最近日志:"
    sudo journalctl -u "$CRON_SERVICE" --no-pager -n 5
    echo ""
}

# 显示定时任务
show_cron() {
    print_header "定时任务"
    
    print_info "当前 crontab:"
    crontab -l 2>/dev/null | grep -E "(schedule_runner|backtest|futures)" || print_info "无相关定时任务"
    echo ""
}

# 主函数
main() {
    print_header "AI 期货分析系统 - 一键更新部署重启（完整版）"

    echo "项目目录：$PROJECT_DIR"
    echo "部署时间：$(date '+%Y-%m-%d %H:%M:%S')"
    echo "日志文件：$DEPLOY_LOG"
    echo ""

    # 创建日志目录
    mkdir -p "$LOG_DIR"

    # 执行部署步骤
    check_project_dir
    create_backup
    stop_services
    clean_cache
    restart_cron_jobs
    start_services
    verify_services
    test_api

    # 显示状态
    echo ""
    show_status
    
    # 显示业务状态
    show_business_status

    # 显示日志
    show_logs

    # 显示定时任务
    show_cron

    # 完成提示
    print_header "部署完成"
    print_success "所有服务已重启"
    print_info "部署日志：$DEPLOY_LOG"
    print_info "备份位置：$BACKUP_PATH"
    echo ""
    print_info "如需回滚，请执行:"
    echo "  sudo systemctl stop $SYSTEMD_SERVICE $CELERY_SERVICE $CELERY_BEAT_SERVICE"
    echo "  cp $BACKUP_PATH/* $PROJECT_DIR/"
    echo "  sudo systemctl start $SYSTEMD_SERVICE $CELERY_SERVICE $CELERY_BEAT_SERVICE"
    echo ""
    print_info "下次清理时间：7 天后（自动清理旧日志）"
    echo ""
    echo ""
}

# 执行主函数
main "$@"
