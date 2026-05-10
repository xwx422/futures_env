#!/bin/bash
# Celery Beat 启动脚本
export PYTHONPATH=/var/www/futures_ai:$PYTHONPATH
export C_FORCE_ROOT=true
cd /var/www/futures_ai
source /var/www/futures_ai/venv/bin/activate
exec celery -A celery_app beat --loglevel=info
