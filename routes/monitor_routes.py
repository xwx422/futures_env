# routes/monitor_routes.py
"""
监控和统计路由
提供API成本、性能监控接口
"""

from flask import Blueprint, jsonify, request, session, redirect, url_for
from functools import wraps
from utils.api_cost_monitor import get_api_stats, get_cost_monitor, print_cost_report
import logging

logger = logging.getLogger(__name__)

monitor_bp = Blueprint("monitor", __name__, url_prefix="/api/monitor")


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


@monitor_bp.route("/api-cost", methods=["GET"])
@login_required
def get_api_cost_stats():
    """
    获取API调用成本统计

    返回：
    {
        "total_api_calls": 100,
        "cache_hits": 50,
        "cache_hit_rate": 0.5,
        "total_cost_usd": 0.5,
        "total_cost_cny": 3.6,
        "saved_cost_usd": 0.3,
        "saved_cost_cny": 2.16,
        "savings_rate": 0.6
    }
    """
    try:
        # 检查权限（仅管理员）
        if session.get("role") != "admin":
            return jsonify({"success": False, "error": "权限不足"}), 403

        stats = get_api_stats()

        return jsonify({"success": True, "data": stats})

    except Exception as e:
        logger.error(f"[API] 获取API成本统计失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@monitor_bp.route("/api-cost/daily", methods=["GET"])
@login_required
def get_daily_cost_report():
    """
    获取每日API成本报告

    Query参数：
    - days: 天数（默认7天）
    """
    try:
        if session.get("role") != "admin":
            return jsonify({"success": False, "error": "权限不足"}), 403

        days = request.args.get("days", 7, type=int)

        monitor = get_cost_monitor()
        report = monitor.get_daily_report(days)

        return jsonify({"success": True, "days": days, "data": report})

    except Exception as e:
        logger.error(f"[API] 获取每日成本报告失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@monitor_bp.route("/api-cost/report", methods=["GET"])
@login_required
def get_cost_report_text():
    """
    获取文本格式的成本报告
    """
    try:
        if session.get("role") != "admin":
            return jsonify({"success": False, "error": "权限不足"}), 403

        monitor = get_cost_monitor()
        report_text = monitor.generate_cost_report()

        return jsonify({"success": True, "report": report_text})

    except Exception as e:
        logger.error(f"[API] 生成成本报告失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@monitor_bp.route("/cache-stats", methods=["GET"])
@login_required
def get_cache_statistics():
    """
    获取缓存统计信息
    """
    try:
        if session.get("role") != "admin":
            return jsonify({"success": False, "error": "权限不足"}), 403

        from utils.cache_utils import CacheStats

        stats = CacheStats.get_stats()

        return jsonify({"success": True, "data": stats})

    except Exception as e:
        logger.error(f"[API] 获取缓存统计失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
