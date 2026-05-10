#!/bin/bash
# start_celery.sh
# 启动 Celery 异步任务队列

# 切换到脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================"
echo "启动 Celery 异步任务队列"
echo "工作目录：$(pwd)"
echo "================================"

# 激活虚拟环境
source venv/bin/activate

# 添加项目根目录到 Python 路径
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

# 启动 Worker（solo 单进程模式，避免 macOS 上 prefork + TQSDK asyncio 冲突）
echo "启动 Celery Worker..."
celery -A celery_app worker \
    --loglevel=info \
    --pool=solo \
    -n worker@%h \
    --logfile=logs/celery_worker.log &

WORKER_PID=$!

# 启动 Celery Beat（定时任务调度器）
echo "启动 Celery Beat 定时任务调度器..."
celery -A celery_app beat \
    --loglevel=info \
    --schedule=logs/celerybeat-schedule \
    --logfile=logs/celery_beat.log &

BEAT_PID=$!

# 启动 Flower 监控（可选）
echo "启动 Flower 监控界面..."
FLOWER_UNAUTHENTICATED_API=1 celery -A celery_app flower \
    --port=5555 \
    --loglevel=info &

FLOWER_PID=$!

echo ""
echo "================================"
echo "Celery 已启动"
echo "Worker PID: $WORKER_PID"
echo "Beat PID: $BEAT_PID"
echo "Flower PID: $FLOWER_PID"
echo "Flower 监控：http://localhost:5555"
echo "================================"
echo ""
echo "查看 Worker 日志：tail -f logs/celery_worker.log"
echo "查看 Beat 日志：tail -f logs/celery_beat.log"
echo "停止服务：kill $WORKER_PID $BEAT_PID $FLOWER_PID"
