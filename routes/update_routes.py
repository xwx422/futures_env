# routes/update_routes.py（优化版）
"""
更新数据路由模块
提供 API 接口触发数据分析任务（使用Celery异步处理）
"""

from flask import Blueprint, request, jsonify, session
import logging
from datetime import datetime
import sqlite3

logger = logging.getLogger(__name__)

# 创建蓝图
update_bp = Blueprint("update", __name__)


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect("futures_analysis.db")
    conn.row_factory = sqlite3.Row
    return conn


@update_bp.route("/update_data", methods=["POST"])
def update_data():
    """
    触发数据分析接口

    使用Celery异步执行数据分析任务，立即返回启动状态
    """
    try:
        # 检查登录状态
        if "username" not in session:
            return jsonify({"success": False, "error": "请先登录"}), 401

        # 检查是否为管理员
        if session.get("role") != "admin":
            return jsonify({"success": False, "error": "只有管理员可以执行此操作"}), 403

        username = session["username"]

        # 导入Celery任务
        from tasks.analysis_tasks import update_all_varieties_task

        # 启动Celery异步任务
        task_result = update_all_varieties_task.delay(username=username)

        logger.info(
            f"数据分析Celery任务已启动，任务ID: {task_result.id}, 用户: {username}"
        )

        return jsonify(
            {
                "success": True,
                "message": "数据分析已启动，请稍后查看结果",
                "task_id": task_result.id,
                "timestamp": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logger.exception(f"启动分析失败: {e}")
        return jsonify({"success": False, "error": f"更新失败: {str(e)}"}), 500


@update_bp.route("/get_latest_update_time")
def get_latest_update_time():
    """
    获取最新数据分析时间

    查询数据库中最新记录的 run_time
    """
    try:
        if "username" not in session:
            return jsonify({"success": False, "error": "请先登录"}), 401

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT run_time FROM analysis_records
            ORDER BY run_time DESC LIMIT 1
        """)
        latest = cursor.fetchone()
        conn.close()

        return jsonify(
            {"success": True, "latest_time": latest[0] if latest else "暂无数据"}
        )

    except Exception as e:
        logger.exception(f"获取更新时间失败: {e}")
        return jsonify({"success": False, "error": f"获取时间失败: {str(e)}"}), 500


@update_bp.route("/update_logs")
def get_update_logs():
    """
    获取数据更新日志列表

    用于管理后台查看更新历史
    """
    try:
        if "username" not in session:
            return jsonify({"success": False, "error": "请先登录"}), 401

        if session.get("role") != "admin":
            return jsonify({"success": False, "error": "无权访问"}), 403

        # 获取查询参数
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        offset = (page - 1) * per_page

        conn = get_db_connection()
        cursor = conn.cursor()

        # 查询总数
        cursor.execute("SELECT COUNT(*) as total FROM update_logs")
        total = cursor.fetchone()["total"]

        # 查询日志数据
        cursor.execute(
            """
            SELECT * FROM update_logs
            ORDER BY update_time DESC
            LIMIT ? OFFSET ?
        """,
            (per_page, offset),
        )

        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify(
            {
                "success": True,
                "data": logs,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": (total + per_page - 1) // per_page,
            }
        )

    except Exception as e:
        logger.exception(f"获取更新日志失败: {e}")
        return jsonify({"success": False, "error": f"获取日志失败: {str(e)}"}), 500


def register_update_routes(app):
    """注册更新相关路由到 Flask 应用"""
    app.register_blueprint(update_bp, url_prefix="/api")
    logger.info("更新路由已注册")
