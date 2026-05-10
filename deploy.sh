#!/bin/bash
# AI期货分析系统 - 一键部署脚本
# 支持：Ubuntu/Debian/CentOS/macOS
# 版本：v1.0

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

# 检查命令是否存在
check_command() {
    if ! command -v $1 &> /dev/null; then
        return 1
    fi
    return 0
}

# 检测操作系统
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if [ -f /etc/os-release ]; then
            . /etc/os-release
            OS=$ID
        else
            OS="linux"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
    else
        OS="unknown"
    fi
    log_info "检测到操作系统: $OS"
}

# 安装系统依赖
install_system_deps() {
    log_info "安装系统依赖..."
    
    case $OS in
        ubuntu|debian)
            sudo apt update
            sudo apt install -y python3 python3-pip python3-venv git curl
            ;;
        centos|rhel|fedora)
            sudo yum update -y
            sudo yum install -y python3 python3-pip git curl
            ;;
        macos)
            if ! check_command brew; then
                log_error "请先安装 Homebrew: https://brew.sh"
                exit 1
            fi
            brew install python3 git curl
            ;;
        *)
            log_warn "未知操作系统，请手动安装 Python 3.9+ 和 git"
            ;;
    esac
    
    log_success "系统依赖安装完成"
}

# 检查Python版本
check_python() {
    log_info "检查 Python 版本..."
    
    if check_command python3; then
        PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
        log_info "Python 版本: $PYTHON_VERSION"
        
        # 检查版本是否 >= 3.9
        REQUIRED_VERSION="3.9"
        if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then 
            log_success "Python 版本符合要求"
        else
            log_error "Python 版本过低，需要 3.9+"
            exit 1
        fi
    else
        log_error "未找到 Python3，请先安装"
        exit 1
    fi
}

# 创建虚拟环境
setup_venv() {
    log_info "创建 Python 虚拟环境..."
    
    if [ -d "venv" ]; then
        log_warn "虚拟环境已存在，跳过创建"
    else
        python3 -m venv venv
        log_success "虚拟环境创建完成"
    fi
    
    # 激活虚拟环境
    source venv/bin/activate
    log_success "虚拟环境已激活"
}

# 安装Python依赖
install_deps() {
    log_info "安装 Python 依赖..."
    
    pip install --upgrade pip -q
    
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt -q
        log_success "依赖安装完成"
    else
        log_error "未找到 requirements.txt 文件"
        exit 1
    fi
}

# 配置环境变量
setup_env() {
    log_info "配置环境变量..."
    
    if [ -f ".env" ]; then
        log_warn ".env 文件已存在，跳过配置"
        log_info "如需修改配置，请编辑 .env 文件"
    else
        if [ -f ".env.example" ]; then
            cp .env.example .env
            
            # 生成随机SECRET_KEY
            SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
            
            # 更新SECRET_KEY
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s/your-secret-key-here/$SECRET_KEY/g" .env
            else
                sed -i "s/your-secret-key-here/$SECRET_KEY/g" .env
            fi
            
            log_success ".env 文件已创建"
            log_warn "请编辑 .env 文件，配置以下必填项："
            log_warn "  - TQSDK_AUTH（天勤账号）"
            log_warn "  - DEEPSEEK_API_KEY（可选）"
        else
            log_warn "未找到 .env.example，创建默认 .env 文件"
            SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
            cat > .env << EOF
# API配置
TQSDK_AUTH=xwx422,xuwenxing
DEEPSEEK_API_KEY=sk-33d512ee692d4d6f9a00d5cb249c424d

# Flask配置
SECRET_KEY=$SECRET_KEY
DEBUG=false
LOG_LEVEL=INFO
EOF
        fi
    fi
    
    # 设置文件权限
    chmod 600 .env
}

# 初始化数据库
init_database() {
    log_info "初始化数据库..."
    
    if [ -f "futures_analysis.db" ]; then
        log_warn "数据库已存在，跳过初始化"
        read -p "是否重新初始化数据库？(y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            mv futures_analysis.db "futures_analysis.db.backup.$(date +%Y%m%d%H%M%S)"
            python init_db.py
            log_success "数据库重新初始化完成"
        fi
    else
        python init_db.py
        log_success "数据库初始化完成"
    fi
}

# 创建日志目录
setup_logs() {
    log_info "创建日志目录..."
    mkdir -p logs
    log_success "日志目录创建完成"
}

# 创建启动脚本
create_start_scripts() {
    log_info "创建启动脚本..."
    
    # Web服务启动脚本
    cat > start_web.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
echo "启动 Web 服务..."
echo "访问地址: http://localhost:5000"
python app.py
EOF
    chmod +x start_web.sh
    
    # 数据分析启动脚本
    cat > start_analysis.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
echo "执行数据分析..."
python main.py
EOF
    chmod +x start_analysis.sh
    
    log_success "启动脚本创建完成"
}

# 显示部署信息
show_info() {
    echo
    echo "========================================"
    log_success "部署完成！"
    echo "========================================"
    echo
    echo "📁 项目目录: $(pwd)"
    echo "🐍 Python: $(python3 --version)"
    echo "🗄️  数据库: $(pwd)/futures_analysis.db"
    echo
    echo "🔧 常用命令:"
    echo "  ./start_web.sh       # 启动 Web 服务"
    echo "  ./start_analysis.sh  # 执行数据分析"
    echo
    echo "⚙️  配置文件:"
    echo "  .env                 # 环境变量配置"
    echo
    echo "📖 文档:"
    echo "  doc/01_系统架构与功能说明.md"
    echo "  doc/02_升级更新变更内容记录.md"
    echo "  doc/03_安装部署文档.md"
    echo
    echo "⚠️  重要提示:"
    log_warn "请编辑 .env 文件配置天勤账号 (TQSDK_AUTH)"
    echo
    echo "🚀 快速开始:"
    echo "  1. 编辑 .env 文件，配置 API 密钥"
    echo "  2. 运行 ./start_web.sh 启动服务"
    echo "  3. 访问 http://localhost:5000"
    echo "  4. 默认账号: admin / admin123"
    echo
}

# 主函数
main() {
    echo "========================================"
    echo "  AI期货分析系统 - 一键部署脚本"
    echo "========================================"
    echo
    
    # 检查是否在项目根目录
    if [ ! -f "app.py" ] || [ ! -f "main.py" ]; then
        log_error "请在项目根目录运行此脚本"
        exit 1
    fi
    
    # 检测操作系统
    detect_os
    
    # 安装系统依赖
    read -p "是否安装系统依赖? (Y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        install_system_deps
    fi
    
    # 检查Python
    check_python
    
    # 创建虚拟环境
    setup_venv
    
    # 安装依赖
    install_deps
    
    # 配置环境变量
    setup_env
    
    # 初始化数据库
    init_database
    
    # 创建日志目录
    setup_logs
    
    # 创建启动脚本
    create_start_scripts
    
    # 显示信息
    show_info
}

# 运行主函数
main
