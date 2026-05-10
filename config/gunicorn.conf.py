# AI期货分析系统 - Gunicorn 配置文件
# 使用方式：gunicorn -c config/gunicorn.conf.py app:app

import multiprocessing
import os

# 项目根目录
project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 服务器套接字
bind = "0.0.0.0:8000"

# 工作进程数 (CPU 核心数 * 2 + 1)
workers = multiprocessing.cpu_count() * 2 + 1

# 工作模式
worker_class = "sync"

# 每个工作进程的最大并发请求数
max_requests = 1000
max_requests_jitter = 50

# 超时时间
timeout = 120
keepalive = 5
graceful_timeout = 30

# 工作进程名称
proc_name = "futures_ai"

# 进程管理
daemon = False
pidfile = os.path.join(project_dir, "logs", "gunicorn.pid")

# 日志配置
accesslog = os.path.join(project_dir, "logs", "gunicorn_access.log")
errorlog = os.path.join(project_dir, "logs", "gunicorn_error.log")
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 预加载应用（节省内存）
preload_app = True

# 用户和组（生产环境使用）
# user = "www-data"
# group = "www-data"

# 安全设置
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# 重载配置（开发环境使用）
# reload = True
# reload_engine = "auto"

# 启动时钩子
def on_starting(server):
    """启动前执行"""
    pass

def on_reload(server):
    """重载配置时执行"""
    pass

def when_ready(server):
    """工作进程启动后执行"""
    pass

def worker_int(worker):
    """工作进程中断时执行"""
    pass

def worker_abort(worker):
    """工作进程异常终止时执行"""
    pass
