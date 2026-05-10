#!/bin/bash
# Gunicorn 启动脚本
# 使用 sync worker 避免与 TqSdk 异步代码冲突
export PYTHONPATH=/var/www/futures_ai:$PYTHONPATH
cd /var/www/futures_ai
source /var/www/futures_ai/venv/bin/activate
python -c "from signal_tracker import SignalTracker; print('signal_tracker OK')"
exec gunicorn --workers 4 --worker-class sync --bind 0.0.0.0:8000 app:app
