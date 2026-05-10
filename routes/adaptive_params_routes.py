# routes/adaptive_params_routes.py
"""
自适应参数优化API路由
提供市场状态识别、自适应参数生成、参数对比等接口
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required
import logging

from analysis_layer.adaptive_params import (
    AdaptiveParamOptimizer,
    get_adaptive_params,
    analyze_market_state,
    compare_params,
)

logger = logging.getLogger(__name__)

# 创建蓝图
adaptive_bp = Blueprint("adaptive", __name__)


@adaptive_bp.route("/api/adaptive/market-state/<variety_code>", methods=["GET"])
@login_required
def get_market_state(variety_code):
    """
    获取品种当前市场状态

    Path参数:
    - variety_code: 品种代码（如 RB）

    Query参数:
    - lookback_days: 回看天数（默认20）

    Returns:
    {
        "success": true,
        "data": {
            "variety_code": "RB",
            "market_state": "strong_trend",
            "state_description": "强趋势市场，适合顺势交易",
            "adx_current": 45.2,
            "adx_trend": "rising",
            "volatility_pct": 0.025,
            "volatility_state": "normal",
            "confidence": 0.9
        }
    }
    """
    try:
        lookback_days = request.args.get("lookback_days", 20, type=int)

        optimizer = AdaptiveParamOptimizer()
        state, info = optimizer.detect_market_state(variety_code.upper(), lookback_days)

        # 获取状态描述
        state_descriptions = {
            "strong_trend": "强趋势市场，适合顺势交易",
            "normal_trend": "正常趋势市场，标准操作",
            "weak_trend": "弱趋势市场，谨慎操作",
            "sideways": "震荡市场，高抛低吸",
        }

        return jsonify(
            {
                "success": True,
                "data": {
                    "variety_code": variety_code.upper(),
                    "market_state": state.value,
                    "state_description": state_descriptions.get(state.value, ""),
                    "adx_current": info.get("adx_current"),
                    "adx_trend": info.get("adx_trend"),
                    "volatility_pct": info.get("volatility_pct"),
                    "volatility_state": info.get("volatility_state"),
                    "confidence": info.get("confidence"),
                },
            }
        )

    except Exception as e:
        logger.error(f"获取市场状态失败 {variety_code}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@adaptive_bp.route("/api/adaptive/params/<variety_code>", methods=["GET"])
@login_required
def get_adaptive_parameters(variety_code):
    """
    获取品种的自适应参数

    Path参数:
    - variety_code: 品种代码

    Returns:
    {
        "success": true,
        "data": {
            "variety_code": "RB",
            "market_state": "strong_trend",
            "state_description": "强趋势市场，适合顺势交易",
            "parameters": {
                "position_pct": 0.45,
                "position_multiplier": 1.5,
                "stop_loss_atr_multiple": 1.2,
                "stop_loss_pct": 0.015,
                "take_profit_atr_multiple": 3.6,
                "take_profit_pct": 0.08,
                "max_position_pct": 0.15,
                "max_daily_loss_pct": 0.025,
                "min_risk_reward_ratio": 1.5,
                "trailing_stop_enabled": true,
                "trailing_stop_trigger": 0.03,
                "hold_period_preference": "medium",
                "min_confidence": "中",
                "require_trend_alignment": true
            },
            "generated_at": "2026-02-09T14:30:00"
        }
    }
    """
    try:
        params = get_adaptive_params(variety_code.upper())

        return jsonify(
            {
                "success": True,
                "data": {
                    "variety_code": variety_code.upper(),
                    "market_state": params.market_state.value,
                    "state_description": params.state_description,
                    "parameters": {
                        "position_pct": params.position_pct,
                        "position_multiplier": params.position_multiplier,
                        "stop_loss_atr_multiple": params.stop_loss_atr_multiple,
                        "stop_loss_pct": params.stop_loss_pct,
                        "take_profit_atr_multiple": params.take_profit_atr_multiple,
                        "take_profit_pct": params.take_profit_pct,
                        "max_position_pct": params.max_position_pct,
                        "max_daily_loss_pct": params.max_daily_loss_pct,
                        "min_risk_reward_ratio": params.min_risk_reward_ratio,
                        "trailing_stop_enabled": params.trailing_stop_enabled,
                        "trailing_stop_trigger": params.trailing_stop_trigger,
                        "hold_period_preference": params.hold_period_preference,
                        "min_confidence": params.min_confidence,
                        "require_trend_alignment": params.require_trend_alignment,
                    },
                    "generated_at": params.generated_at.isoformat(),
                },
            }
        )

    except Exception as e:
        logger.error(f"获取自适应参数失败 {variety_code}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@adaptive_bp.route("/api/adaptive/compare/<variety_code>", methods=["GET"])
@login_required
def compare_parameters(variety_code):
    """
    对比固定参数和自适应参数

    Path参数:
    - variety_code: 品种代码

    Returns:
    {
        "success": true,
        "data": {
            "variety_code": "RB",
            "market_state": "strong_trend",
            "state_info": {...},
            "base_params": {
                "position_pct": 0.3,
                "stop_loss_atr_multiple": 1.5,
                ...
            },
            "adaptive_params": {...},
            "differences": {
                "position_pct": "150%",
                "stop_loss_adjustment": "tightened",
                "take_profit_adjustment": "expanded"
            }
        }
    }
    """
    try:
        comparison = compare_params(variety_code.upper())

        return jsonify({"success": True, "data": comparison})

    except Exception as e:
        logger.error(f"对比参数失败 {variety_code}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@adaptive_bp.route(
    "/api/adaptive/market-state-distribution/<variety_code>", methods=["GET"]
)
@login_required
def get_market_state_distribution(variety_code):
    """
    获取品种市场状态分布统计

    Path参数:
    - variety_code: 品种代码

    Query参数:
    - days: 统计天数（默认90）

    Returns:
    {
        "success": true,
        "data": {
            "variety_code": "RB",
            "days": 90,
            "distribution": {
                "strong_trend": {"count": 25, "percentage": 27.8},
                "normal_trend": {"count": 35, "percentage": 38.9},
                "weak_trend": {"count": 15, "percentage": 16.7},
                "sideways": {"count": 15, "percentage": 16.7}
            }
        }
    }
    """
    try:
        days = request.args.get("days", 90, type=int)

        optimizer = AdaptiveParamOptimizer()
        distribution = optimizer.get_market_state_distribution(
            variety_code.upper(), days
        )

        return jsonify(
            {
                "success": True,
                "data": {
                    "variety_code": variety_code.upper(),
                    "days": days,
                    "distribution": distribution,
                },
            }
        )

    except Exception as e:
        logger.error(f"获取市场状态分布失败 {variety_code}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@adaptive_bp.route("/api/adaptive/all-varieties", methods=["GET"])
@login_required
def get_all_adaptive_params():
    """
    批量获取所有品种的自适应参数

    Query参数:
    - varieties: 品种列表，逗号分隔（默认配置中的所有品种）

    Returns:
    {
        "success": true,
        "data": [
            {
                "variety_code": "RB",
                "market_state": "strong_trend",
                "parameters": {...}
            },
            ...
        ]
    }
    """
    try:
        varieties_str = request.args.get(
            "varieties", "RB,BU,MA,JD,C,CS,SA,FG,V,M,RM,SR"
        )
        varieties = [v.strip().upper() for v in varieties_str.split(",")]

        results = []
        for variety in varieties:
            try:
                params = get_adaptive_params(variety)
                results.append(
                    {
                        "variety_code": variety,
                        "market_state": params.market_state.value,
                        "state_description": params.state_description,
                        "position_pct": params.position_pct,
                        "position_multiplier": params.position_multiplier,
                        "stop_loss_atr_multiple": params.stop_loss_atr_multiple,
                        "take_profit_atr_multiple": params.take_profit_atr_multiple,
                        "hold_period_preference": params.hold_period_preference,
                        "min_confidence": params.min_confidence,
                    }
                )
            except Exception as e:
                logger.warning(f"获取 {variety} 参数失败: {e}")
                continue

        return jsonify({"success": True, "data": results, "count": len(results)})

    except Exception as e:
        logger.error(f"批量获取自适应参数失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@adaptive_bp.route("/api/adaptive/optimize", methods=["POST"])
@login_required
def optimize_parameters():
    """
    触发参数优化（通过回测）

    Request Body:
    {
        "variety_code": "RB",
        "market_state": "strong_trend",
        "test_period_days": 90
    }

    Returns:
    {
        "success": true,
        "data": {
            "variety_code": "RB",
            "market_state": "strong_trend",
            "test_period_days": 90,
            "optimized_params": {...},
            "estimated_improvement": "15-25%",
            "confidence": "medium"
        }
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"success": False, "error": "缺少请求数据"}), 400

        variety_code = data.get("variety_code", "").upper()
        market_state_str = data.get("market_state", "normal_trend")
        test_period_days = data.get("test_period_days", 90)

        if not variety_code:
            return jsonify({"success": False, "error": "缺少variety_code参数"}), 400

        # 转换市场状态字符串
        from analysis_layer.adaptive_params import MarketState

        try:
            market_state = MarketState(market_state_str)
        except ValueError:
            return jsonify(
                {"success": False, "error": f"无效的市场状态: {market_state_str}"}
            ), 400

        # 执行优化
        optimizer = AdaptiveParamOptimizer()
        result = optimizer.optimize_params_by_backtest(
            variety_code, market_state, test_period_days
        )

        if not result:
            return jsonify({"success": False, "error": "参数优化失败，数据不足"}), 404

        return jsonify({"success": True, "data": result})

    except Exception as e:
        logger.error(f"参数优化失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def register_adaptive_routes(app):
    """注册自适应参数路由"""
    app.register_blueprint(adaptive_bp)
    logger.info("✅ 自适应参数路由已注册")
