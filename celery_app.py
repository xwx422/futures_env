# celery_app.py
"""
Celery 异步任务队列配置
精简版：只保留核心分析和价格刷新任务
"""

import os
import sys

# 确保项目根目录在 Python 路径中，使 tasks 包能被正确导入
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from celery import Celery
from celery.schedules import crontab
import logging

logger = logging.getLogger(__name__)

# Celery 配置
CELERY_CONFIG = {
    # 消息代理（Redis）
    "broker_url": os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    # 结果后端（Redis）
    "result_backend": os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
    # 序列化配置
    "task_serializer": "json",
    "accept_content": ["json"],
    "result_serializer": "json",
    # 时区配置
    "timezone": "Asia/Shanghai",
    "enable_utc": True,
    # 任务追踪
    "task_track_started": True,
    "task_time_limit": 3600,  # 任务超时 1 小时
    "task_soft_time_limit": 3300,  # 软超时 55 分钟
    # Worker 配置
    "worker_prefetch_multiplier": 1,
    "worker_max_tasks_per_child": 50,
    "worker_pool": "prefork",
    "worker_concurrency": 4,
    # 结果配置
    "result_expires": 86400,
    "result_extended": True,
    # 重试配置
    "task_default_retry_delay": 60,
    "task_max_retries": 3,
    # 定时任务配置（Celery Beat）
    "beat_schedule": {
        # 每 4 小时更新所有品种（主力合约、价格、分析）
        "update-all-varieties-every-4-hours": {
            "task": "tasks.analysis_tasks.update_all_varieties_task",
            "schedule": crontab(minute=0, hour="*/4"),
            "options": {"queue": "default"},
        },
        # 交易日 8:25 更新（早盘前）
        "update-all-varieties-morning": {
            "task": "tasks.analysis_tasks.update_all_varieties_task",
            "schedule": crontab(minute=25, hour=8),
            "options": {"queue": "default"},
        },
        # 交易日 13:00 更新（午盘前）
        "update-all-varieties-afternoon": {
            "task": "tasks.analysis_tasks.update_all_varieties_task",
            "schedule": crontab(minute=0, hour=13),
            "options": {"queue": "default"},
        },
        # 每 3 分钟刷新一次价格（交易日）
        "price-refresh-every-3-minutes": {
            "task": "tasks.price_refresh_tasks.refresh_prices_task",
            "schedule": crontab(minute="*/3"),
            "options": {"queue": "default"},
        },
    },
}

# 创建 Celery 应用
celery_app = Celery("futures_analysis")
celery_app.config_from_object(CELERY_CONFIG)

# 显式导入并注册任务模块
_TASK_MODULES = [
    "tasks.analysis_tasks",
    "tasks.price_refresh_tasks",
]
for mod_name in _TASK_MODULES:
    try:
        __import__(mod_name)
        logger.info(f"[CELERY] 任务模块已加载: {mod_name}")
    except Exception as e:
        logger.warning(f"[CELERY] 任务模块加载失败: {mod_name} - {e}")


# 健康检查任务
@celery_app.task(bind=True)
def health_check(self):
    """Celery 健康检查"""
    return {"status": "ok", "task_id": self.request.id, "worker": self.request.hostname}
