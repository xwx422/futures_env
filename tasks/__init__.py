# tasks package
# Celery tasks module

from .analysis_tasks import (
    analyze_variety_task,
    batch_analyze_task,
    update_all_varieties_task,
)
