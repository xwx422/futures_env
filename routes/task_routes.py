# routes/task_routes.py
"""
任务管理路由
提供异步任务的查询和管理接口
"""

from flask import Blueprint, jsonify, request, session, redirect, url_for
from functools import wraps
from celery.result import AsyncResult, GroupResult
from celery_app import celery_app
from tasks.analysis_tasks import (
    analyze_variety_task,
    batch_analyze_task,
    update_all_varieties_task,
)
import logging

logger = logging.getLogger(__name__)

task_bp = Blueprint("tasks", __name__, url_prefix="/api/tasks")


def login_required(f):
    """登录验证装饰器"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            if request.is_json:
                return jsonify({"success": False, "error": "未登录"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


@task_bp.route("/analyze/start", methods=["POST"])
@login_required
def start_analysis():
    """
    启动异步分析任务

    请求体：
    {
        "varieties": ["RB", "MA", "SA"],  // 品种列表
        "batch_mode": true  // 是否批量模式
    }
    """
    try:
        data = request.get_json()
        varieties = data.get("varieties", [])
        batch_mode = data.get("batch_mode", True)

        if not varieties:
            return jsonify({"success": False, "error": "请提供要分析的品种列表"}), 400

        # 验证品种代码
        from data_layer.fetch_market import EXCHANGE_MAP

        invalid_varieties = [v for v in varieties if v not in EXCHANGE_MAP]
        if invalid_varieties:
            return jsonify(
                {"success": False, "error": f"无效的品种代码: {invalid_varieties}"}
            ), 400

        # 启动任务
        if batch_mode and len(varieties) > 1:
            # 批量模式
            result = batch_analyze_task.delay(varieties, session.get("username"))
            task_id = result.id
            task_type = "batch"
        else:
            # 单个品种模式
            if len(varieties) == 1:
                result = analyze_variety_task.delay(
                    varieties[0], session.get("username")
                )
                task_id = result.id
                task_type = "single"
            else:
                # 多个单任务
                tasks = [
                    analyze_variety_task.delay(v, session.get("username"))
                    for v in varieties
                ]
                task_id = [t.id for t in tasks]
                task_type = "multiple"

        logger.info(f"[API] 用户 {session.get('username')} 启动分析任务: {varieties}")

        return jsonify(
            {
                "success": True,
                "task_id": task_id,
                "task_type": task_type,
                "total_varieties": len(varieties),
                "varieties": varieties,
                "status": "started",
                "message": "分析任务已启动，请使用任务ID查询进度",
            }
        )

    except Exception as e:
        logger.error(f"[API] 启动分析任务失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@task_bp.route("/<task_id>/status", methods=["GET"])
@login_required
def get_task_status(task_id):
    """
    获取单个任务状态

    返回：
    {
        "task_id": "xxx",
        "state": "PENDING/PROGRESS/SUCCESS/FAILURE",
        "progress": {"current": 3, "total": 6, "step": "AI深度研判"},
        "result": {...},  // 成功时返回
        "error": "..."  // 失败时返回
    }
    """
    try:
        task = AsyncResult(task_id, app=celery_app)

        response = {
            "task_id": task_id,
            "state": task.state,
        }

        if task.state == "PENDING":
            response["message"] = "任务等待中"

        elif task.state == "PROGRESS":
            response["progress"] = task.info
            response["message"] = f"正在执行: {task.info.get('step', '处理中')}"

        elif task.state == "SUCCESS":
            response["result"] = task.result
            response["message"] = "任务已完成"

        elif task.state == "FAILURE":
            response["error"] = str(task.info)
            response["message"] = "任务执行失败"

        else:
            response["message"] = f"未知状态: {task.state}"

        return jsonify(response)

    except Exception as e:
        logger.error(f"[API] 获取任务状态失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@task_bp.route("/batch/<group_id>/status", methods=["GET"])
@login_required
def get_batch_status(group_id):
    """
    获取批量任务组状态

    返回：
    {
        "group_id": "xxx",
        "total": 12,
        "completed": 8,
        "failed": 1,
        "pending": 3,
        "progress_percent": 66.7,
        "results": [...]
    }
    """
    try:
        result = GroupResult.restore(group_id, app=celery_app)

        if not result:
            return jsonify({"success": False, "error": "任务组不存在或已过期"}), 404

        # 统计任务状态
        total = len(result)
        completed = sum(1 for r in result.results if r.ready())
        successful = sum(1 for r in result.results if r.successful())
        failed = sum(1 for r in result.results if r.failed())
        pending = total - completed

        # 获取已完成的结果
        results = []
        for r in result.results:
            if r.ready():
                if r.successful():
                    results.append({"status": "success", "result": r.result})
                else:
                    results.append({"status": "failed", "error": str(r.result)})
            else:
                results.append({"status": "pending", "task_id": r.id})

        return jsonify(
            {
                "group_id": group_id,
                "total": total,
                "completed": completed,
                "successful": successful,
                "failed": failed,
                "pending": pending,
                "progress_percent": round((completed / total * 100), 1)
                if total > 0
                else 0,
                "is_ready": result.ready(),
                "is_successful": result.successful(),
                "results": results,
            }
        )

    except Exception as e:
        logger.error(f"[API] 获取批量任务状态失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@task_bp.route("/<task_id>/revoke", methods=["POST"])
@login_required
def revoke_task(task_id):
    """
    取消正在执行的任务

    需要管理员权限
    """
    try:
        # 检查权限
        if session.get("role") != "admin":
            return jsonify({"success": False, "error": "权限不足"}), 403

        task = AsyncResult(task_id, app=celery_app)

        if task.state in ["PENDING", "PROGRESS"]:
            task.revoke(terminate=True)
            logger.info(f"[API] 任务 {task_id} 已被用户 {session.get('username')} 取消")
            return jsonify({"success": True, "message": "任务已取消"})
        else:
            return jsonify(
                {"success": False, "error": f"任务状态为 {task.state}，无法取消"}
            ), 400

    except Exception as e:
        logger.error(f"[API] 取消任务失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@task_bp.route("/active", methods=["GET"])
@login_required
def list_active_tasks():
    """
    列出当前活跃的任务

    需要管理员权限
    """
    try:
        # 检查权限
        if session.get("role") != "admin":
            return jsonify({"success": False, "error": "权限不足"}), 403

        # 使用 inspect 获取活跃任务
        inspect = celery_app.control.inspect()

        active_tasks = inspect.active()
        scheduled_tasks = inspect.scheduled()
        reserved_tasks = inspect.reserved()

        tasks_info = {
            "active": active_tasks,
            "scheduled": scheduled_tasks,
            "reserved": reserved_tasks,
        }

        return jsonify({"success": True, "tasks": tasks_info})

    except Exception as e:
        logger.error(f"[API] 获取活跃任务列表失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@task_bp.route("/update-all", methods=["POST"])
@login_required
def update_all_varieties():
    """
    更新所有品种（管理员功能）
    """
    try:
        # 检查权限
        if session.get("role") != "admin":
            return jsonify({"success": False, "error": "权限不足"}), 403

        # 启动全品种更新任务
        result = update_all_varieties_task.delay(session.get("username"))

        logger.info(f"[API] 管理员 {session.get('username')} 启动全品种更新")

        return jsonify(
            {
                "success": True,
                "task_id": result.id,
                "task_type": "update_all",
                "status": "started",
                "message": "全品种更新任务已启动",
            }
        )

    except Exception as e:
        logger.error(f"[API] 启动全品种更新失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
