"""
Divergence Monitoring Routes
API endpoints for real-time divergence signal monitoring
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

divergence_bp = Blueprint("divergence", __name__, url_prefix="/api/divergence")


@divergence_bp.route("/detect", methods=["POST"])
def detect_divergences():
    """
    API: 检测品种的背离信号

    Request Body:
        {
            "varieties": ["RB", "HC", "CU"],
            "timeframe": "daily"
        }

    Returns:
        JSON: 检测到的背离信号
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"success": False, "error": "请求数据为空"}), 400

        varieties = data.get("varieties", [])
        timeframe = data.get("timeframe", "daily")

        if not varieties:
            return jsonify({"success": False, "error": "请指定品种列表"}), 400

        from analysis_layer.divergence_monitor import DivergenceDetector

        detector = DivergenceDetector()
        all_divergences = []

        for variety in varieties:
            divergences = detector.detect_divergences(variety, timeframe)
            all_divergences.extend(divergences)

        divergence_list = []
        for div in all_divergences:
            divergence_list.append(
                {
                    "variety_code": div.variety_code,
                    "timeframe": div.timeframe,
                    "divergence_type": div.divergence_type,
                    "strength": div.strength,
                    "current_price": div.current_price,
                    "current_indicator": round(div.current_indicator, 2),
                    "price_pivots": {
                        "pivot_1": {
                            "index": div.price_pivot_1.index,
                            "price": div.price_pivot_1.price,
                            "is_high": div.price_pivot_1.is_high,
                        },
                        "pivot_2": {
                            "index": div.price_pivot_2.index,
                            "price": div.price_pivot_2.price,
                            "is_high": div.price_pivot_2.is_high,
                        },
                    },
                    "indicator_pivots": {
                        "pivot_1": {
                            "index": div.indicator_pivot_1.index,
                            "value": round(div.indicator_pivot_1.indicator_value, 2),
                        },
                        "pivot_2": {
                            "index": div.indicator_pivot_2.index,
                            "value": round(div.indicator_pivot_2.indicator_value, 2),
                        },
                    },
                    "timestamp": div.timestamp,
                }
            )

        return jsonify(
            {
                "success": True,
                "varieties_processed": len(varieties),
                "total_divergences": len(divergence_list),
                "strong_divergences": len(
                    [d for d in divergence_list if d["strength"] >= 0.7]
                ),
                "moderate_divergences": len(
                    [d for d in divergence_list if 0.5 <= d["strength"] < 0.7]
                ),
                "weak_divergences": len(
                    [d for d in divergence_list if d["strength"] < 0.5]
                ),
                "divergences": divergence_list,
            }
        )

    except Exception as e:
        logger.exception(f"[DIVERGENCE_API] 背离检测失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@divergence_bp.route("/active", methods=["GET"])
def get_active_divergences():
    """
    API: 获取活跃的背离信号

    Query Parameters:
        varieties: 逗号分隔的品种代码列表（可选）

    Returns:
        JSON: 活跃背离信号列表
    """
    try:
        varieties_param = request.args.get("varieties", "")
        if varieties_param:
            varieties = [v.strip() for v in varieties_param.split(",") if v.strip()]
        else:
            varieties = None

        from analysis_layer.divergence_monitor import DivergenceDetector

        detector = DivergenceDetector()
        result = detector.get_active_divergences(varieties)

        return jsonify(
            {
                "success": True,
                **result,
            }
        )

    except Exception as e:
        logger.exception(f"[DIVERGENCE_API] 获取活跃背离失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@divergence_bp.route("/history/<variety_code>", methods=["GET"])
def get_divergence_history(variety_code: str):
    """
    API: 获取品种的历史背离分析

    Args:
        variety_code: 品种代码

    Query Parameters:
        days: 分析天数（默认30）

    Returns:
        JSON: 历史背离分析结果
    """
    try:
        days = request.args.get("days", "30")
        try:
            days = int(days)
        except ValueError:
            days = 30

        from analysis_layer.divergence_monitor import DivergenceDetector

        detector = DivergenceDetector()
        history = detector.analyze_divergence_history(variety_code, days)

        return jsonify(
            {
                "success": True,
                **history,
            }
        )

    except Exception as e:
        logger.exception(f"[DIVERGENCE_API] 获取背离历史失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@divergence_bp.route("/run-monitor", methods=["POST"])
def run_divergence_monitor():
    """
    API: 运行背离监控任务

    Request Body:
        {
            "varieties": ["RB", "HC", "CU"]
        }

    Returns:
        JSON: 监控任务结果
    """
    try:
        data = request.get_json()

        varieties = data.get("varieties") if data else None

        from analysis_layer.divergence_monitor import run_divergence_detection_task

        result = run_divergence_detection_task(varieties)

        return jsonify(result)

    except Exception as e:
        logger.exception(f"[DIVERGENCE_API] 运行背离监控失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@divergence_bp.route("/summary", methods=["GET"])
def get_divergence_summary():
    """
    API: 获取全市场背离信号摘要

    Returns:
        JSON: 背离信号摘要
    """
    try:
        from analysis_layer.divergence_monitor import DivergenceDetector

        detector = DivergenceDetector()

        conn = sqlite3.connect("futures_analysis.db")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT DISTINCT variety_code FROM variety_info WHERE is_active = 1 LIMIT 20"
        )
        varieties = [row[0] for row in cursor.fetchall()]

        conn.close()

        all_divergences = []
        for variety in varieties:
            divergences = detector.detect_divergences(variety, "daily")
            for div in divergences:
                all_divergences.append(
                    {
                        "variety_code": div.variety_code,
                        "type": div.divergence_type,
                        "strength": div.strength,
                        "current_price": div.current_price,
                    }
                )

        summary = {
            "total_signals": len(all_divergences),
            "bullish_divergences": len(
                [d for d in all_divergences if "bullish" in d["type"]]
            ),
            "bearish_divergences": len(
                [d for d in all_divergences if "bearish" in d["type"]]
            ),
            "regular_divergences": len(
                [d for d in all_divergences if "regular" in d["type"]]
            ),
            "hidden_divergences": len(
                [d for d in all_divergences if "hidden" in d["type"]]
            ),
            "strong_signals": [d for d in all_divergences if d["strength"] >= 0.7],
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        return jsonify(
            {
                "success": True,
                "summary": summary,
            }
        )

    except Exception as e:
        logger.exception(f"[DIVERGENCE_API] 获取背离摘要失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@divergence_bp.route("/alert", methods=["GET"])
def get_divergence_alerts():
    """
    API: 获取需要关注的背离警报

    Query Parameters:
        min_strength: 最小强度阈值（默认0.7）

    Returns:
        JSON: 背离警报列表
    """
    try:
        min_strength = request.args.get("min_strength", "0.7")
        try:
            min_strength = float(min_strength)
        except ValueError:
            min_strength = 0.7

        from analysis_layer.divergence_monitor import DivergenceDetector

        detector = DivergenceDetector()

        conn = sqlite3.connect("futures_analysis.db")
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT variety_code, timeframe, divergence_type, strength,
                   timestamp, current_price, current_indicator
            FROM active_divergences
            WHERE strength >= ?
            ORDER BY strength DESC, timestamp DESC
            LIMIT 50
            """,
            (min_strength,),
        )

        alerts = []
        for row in cursor.fetchall():
            alerts.append(
                {
                    "variety_code": row[0],
                    "timeframe": row[1],
                    "divergence_type": row[2],
                    "strength": row[3],
                    "timestamp": row[4],
                    "current_price": row[5],
                    "current_indicator": round(row[6], 2) if row[6] else 0,
                    "alert_level": "high" if row[3] >= 0.8 else "medium",
                }
            )

        conn.close()

        return jsonify(
            {
                "success": True,
                "alert_count": len(alerts),
                "alerts": alerts,
            }
        )

    except Exception as e:
        logger.exception(f"[DIVERGENCE_API] 获取背离警报失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
