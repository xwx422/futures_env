#!/bin/bash
# Celery Worker 启动脚本
export PYTHONPATH=/var/www/futures_ai:$PYTHONPATH
export C_FORCE_ROOT=true
cd /var/www/futures_ai
source /var/www/futures_ai/venv/bin/activate
exec celery -A celery_app worker --loglevel=info --pool=solo
