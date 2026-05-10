#!/bin/bash
# AI 期货分析系统 - 本地启动脚本
# 用于本地开发环境快速启动所有服务
# 启动顺序：Redis -> Celery Worker -> Celery Beat -> Flask App

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

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

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 打印头部信息
print_header() {
    echo -e "${CYAN}================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}================================${NC}"
    echo ""
}

# 检查虚拟环境
check_venv() {
    log_info "检查虚拟环境..."
    
    if [ ! -d "venv" ]; then
        log_error "虚拟环境不存在，请先运行部署脚本"
        log_info "运行：bash deploy.sh"
        exit 1
    fi
    
    # 激活虚拟环境
    source venv/bin/activate
    log_success "虚拟环境已激活"
    
    # 加载环境变量
    if [ -f ".env" ]; then
        export $(grep -v '^#' .env | xargs) 2>/dev/null || true
        log_info "环境变量已加载"
    fi
}

# 检查 Redis
check_redis() {
    log_info "检查 Redis 服务..."
    
    if command -v redis-cli &> /dev/null; then
        if redis-cli ping &> /dev/null; then
            log_success "Redis 服务运行正常"
            return 0
        else
            log_warn "Redis 服务未运行，尝试启动..."
            
            # macOS 使用 brew services
            if [[ "$OSTYPE" == "darwin"* ]]; then
                if command -v brew &> /dev/null; then
                    brew services start redis
                    sleep 2
                    if redis-cli ping &> /dev/null; then
                        log_success "Redis 服务已启动"
                        return 0
                    fi
                fi
            fi
            
            # 尝试直接启动 redis-server
            if command -v redis-server &> /dev/null; then
                redis-server --daemonize yes
                sleep 2
                if redis-cli ping &> /dev/null; then
                    log_success "Redis 服务已启动"
                    return 0
                fi
            fi
            
            log_error "无法启动 Redis，请手动安装并启动 Redis"
            log_info "macOS: brew install redis && brew services start redis"
            log_info "Ubuntu: sudo apt install redis-server && sudo systemctl start redis"
            exit 1
        fi
    else
        log_error "未找到 Redis，请先安装 Redis"
        log_info "macOS: brew install redis"
        log_info "Ubuntu: sudo apt install redis-server"
        exit 1
    fi
}

# 启动 Celery Worker
start_celery_worker() {
    log_info "启动 Celery Worker..."
    
    # 检查是否已有 Celery Worker 进程
    if pgrep -f "celery.*worker" > /dev/null; then
        log_warn "检测到已运行的 Celery Worker，先停止..."
        pkill -f "celery.*worker" || true
        sleep 2
    fi
    
    # 使用 solo pool（单进程），避免 macOS 上 prefork + TQSDK asyncio 冲突
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    nohup celery -A celery_app worker --loglevel=info --pool=solo \
        --logfile=logs/celery_worker.log \
        > /dev/null 2>&1 &
    
    sleep 5
    
    # 通过 pgrep 检查进程是否真正运行（nohup 后 $! 不可靠）
    CELERY_WORKER_PID=$(pgrep -f "celery.*worker" | head -1)
    if [ -n "$CELERY_WORKER_PID" ]; then
        log_success "Celery Worker 已启动 (PID: $CELERY_WORKER_PID)"
    else
        log_error "Celery Worker 启动失败，请检查日志：logs/celery_worker.log"
        exit 1
    fi
}

# 启动 Celery Beat
start_celery_beat() {
    log_info "启动 Celery Beat..."
    
    # 检查是否已有 Celery Beat 进程
    if pgrep -f "celery.*beat" > /dev/null; then
        log_warn "检测到已运行的 Celery Beat，先停止..."
        pkill -f "celery.*beat" || true
        sleep 1
    fi
    
    # 清理旧的调度文件（不指定 --schedule，使用默认位置，与服务器一致）
    rm -f celerybeat-schedule celerybeat-schedule.db 2>/dev/null || true

    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    nohup celery -A celery_app beat --loglevel=info \
        > logs/celery_beat.log 2>&1 &
    
    sleep 3
    
    CELERY_BEAT_PID=$(pgrep -f "celery.*beat" | head -1)
    if [ -n "$CELERY_BEAT_PID" ]; then
        log_success "Celery Beat 已启动 (PID: $CELERY_BEAT_PID)"
    else
        log_error "Celery Beat 启动失败，请检查日志：logs/celery_beat.log"
        exit 1
    fi
}

# 检查并释放 5000 端口
check_and_free_port_5000() {
    log_info "检查 5000 端口..."
    
    # macOS 使用 lsof 检查端口
    if command -v lsof &> /dev/null; then
        PID=$(lsof -ti:5000 2>/dev/null | head -1)
        if [ -n "$PID" ]; then
            log_warn "5000 端口被占用 (PID: $PID)，尝试停止..."
            
            # 如果是 python 进程，直接杀死
            if ps -p $PID -o comm= 2>/dev/null | grep -q python; then
                kill -9 $PID 2>/dev/null || true
                sleep 1
                log_success "已停止占用 5000 端口的 Python 进程"
            else
                log_warn "占用 5000 端口的进程不是 Python，请手动处理"
                log_info "运行：lsof -ti:5000 | xargs kill -9"
                return 1
            fi
        fi
    fi
    
    # 备用方案：使用 netstat
    if command -v netstat &> /dev/null; then
        if netstat -an | grep -q "\.5000.*LISTEN"; then
            log_warn "5000 端口仍在监听..."
        fi
    fi
    
    return 0
}

# 启动 Flask 应用
start_flask_app() {
    log_info "启动 Flask 应用..."
    
    # 检查并释放 5000 端口
    check_and_free_port_5000
    
    # 检查是否已有 Flask/Gunicorn 进程
    if pgrep -f "python.*app.py" > /dev/null; then
        log_warn "检测到已运行的 Flask 应用，先停止..."
        pkill -f "python.*app.py" || true
        sleep 2
    fi
    
    # 再次检查端口是否可用
    if command -v lsof &> /dev/null; then
        PID=$(lsof -ti:5000 2>/dev/null | head -1)
        if [ -n "$PID" ]; then
            log_error "5000 端口仍被占用，无法启动 Flask 应用"
            log_info "请手动释放端口：lsof -ti:5000 | xargs kill -9"
            exit 1
        fi
    fi
    
    # 启动 Flask 应用（前台运行，方便查看日志）
    log_info "Flask 应用启动中..."
    log_info "访问地址：http://localhost:5000"
    log_info "按 Ctrl+C 停止服务"
    echo ""
    
    # 运行 Flask 应用（前台，确保使用 venv）
    venv/bin/python app.py
}

# 停止所有服务
stop_all() {
    log_info "停止所有服务..."
    
    # 停止 Flask
    pkill -f "python.*app.py" 2>/dev/null || true
    
    # 停止 Celery Beat
    pkill -f "celery.*beat" 2>/dev/null || true
    
    # 停止 Celery Worker
    pkill -f "celery.*worker" 2>/dev/null || true
    
    log_success "所有服务已停止"
}

# 显示服务状态
show_status() {
    echo ""
    print_header "服务状态"
    
    # Redis 状态
    if command -v redis-cli &> /dev/null && redis-cli ping &> /dev/null; then
        log_success "Redis: 运行中"
    else
        log_error "Redis: 未运行"
    fi
    
    # Celery Worker 状态
    if pgrep -f "celery.*worker" > /dev/null; then
        log_success "Celery Worker: 运行中 (PID: $(pgrep -f 'celery.*worker' | head -1))"
    else
        log_error "Celery Worker: 未运行"
    fi
    
    # Celery Beat 状态
    if pgrep -f "celery.*beat" > /dev/null; then
        log_success "Celery Beat: 运行中 (PID: $(pgrep -f 'celery.*beat' | head -1))"
    else
        log_error "Celery Beat: 未运行"
    fi
    
    # Flask 应用状态
    if pgrep -f "python.*app.py" > /dev/null; then
        log_success "Flask App: 运行中 (PID: $(pgrep -f 'python.*app.py' | head -1))"
    else
        log_error "Flask App: 未运行"
    fi
    
    echo ""
}

# 显示使用说明
show_usage() {
    echo "用法：$0 [选项]"
    echo ""
    echo "选项:"
    echo "  start       启动所有服务（默认）"
    echo "  stop        停止所有服务"
    echo "  restart     重启所有服务"
    echo "  status      显示服务状态"
    echo "  worker      只启动 Celery Worker"
    echo "  beat        只启动 Celery Beat"
    echo "  celery      启动 Celery Worker + Beat (用于后台分析任务)"
    echo "  app         只启动 Flask 应用"
    echo "  help        显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0          启动所有服务"
    echo "  $0 stop     停止所有服务"
    echo "  $0 status   查看服务状态"
    echo ""
}

# 主函数
main() {
    # 创建日志目录
    mkdir -p logs
    
    case "${1:-start}" in
        start)
            print_header "AI 期货分析系统 - 本地启动"
            check_venv
            check_redis
            start_celery_worker
            start_celery_beat
            show_status
            log_info "所有后台服务已启动，现在启动 Flask 应用..."
            echo ""
            start_flask_app
            ;;
        
        stop)
            print_header "AI 期货分析系统 - 停止服务"
            stop_all
            ;;
        
        restart)
            print_header "AI 期货分析系统 - 重启服务"
            stop_all
            sleep 2
            check_venv
            check_redis
            start_celery_worker
            start_celery_beat
            show_status
            log_info "所有后台服务已重启，现在启动 Flask 应用..."
            echo ""
            start_flask_app
            ;;
        
        status)
            show_status
            ;;
        
        worker)
            check_venv
            check_redis
            start_celery_worker
            show_status
            ;;
        
        beat)
            check_venv
            check_redis
            start_celery_beat
            show_status
            ;;
        
        app)
            check_venv
            start_flask_app
            ;;

        celery)
            print_header "AI 期货分析系统 - 启动 Celery"
            check_venv
            check_redis
            start_celery_worker
            start_celery_beat
            show_status
            log_success "Celery Worker + Beat 已启动，可以执行后台分析任务"
            ;;  
        
        help|--help|-h)
            show_usage
            ;;
        
        *)
            log_error "未知选项：$1"
            show_usage
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@"
