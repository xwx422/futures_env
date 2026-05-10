# coding: utf-8
"""
实时价格路由模块

提供不花钱的实时价格查询接口
"""

from flask import Blueprint, jsonify, session, request
import logging
from datetime import datetime
import time
import threading

from data_layer.quick_price_fetcher import get_fetcher, get_prices_quick

logger = logging.getLogger(__name__)

price_bp = Blueprint("price", __name__, url_prefix="/api/price")

# 内存缓存（2 秒过期）
_price_cache = {
    'data': None,
    'timestamp': 0,
    'lock': threading.Lock()
}


@price_bp.route("/refresh", methods=["POST"])
def refresh_prices():
    """
    手动刷新价格（轻量级，不调用 AI）
    
    返回：
    {
        "success": true,
        "data": {
            "RB": {"price": 3850.5, "change_percent": 0.40, ...},
            ...
        },
        "update_time": "2026-02-22 14:30:25"
    }
    """
    try:
        # 异步刷新任务（不需要登录，任何人都可以刷新）
        from tasks.price_refresh_tasks import refresh_prices_task
        task = refresh_prices_task.delay()

        return jsonify({
            "success": True,
            "message": "价格刷新已启动",
            "task_id": task.id
        })

    except Exception as e:
        logger.error(f"刷新价格失败：{e}")
        return jsonify({"success": False, "error": str(e)}), 500


@price_bp.route("/current")
def get_current_prices():
    """
    获取当前价格（带缓存 + 休市降级，减少 TqSdk 调用频率）

    优化策略：
    1. 缓存 2 秒，避免频繁调用 TqSdk
    2. 休市期间返回缓存，不调用 TqSdk（节省 60-70% 调用）
    3. 免费账号限制：约 60-120 次/分钟
    4. 优化后：交易日 30 次/分钟，休市日 0 次

    参数:
    - varieties: 品种代码，逗号分隔（可选，默认全部）

    返回：
    {
        "success": true,
        "data": {
            "RB": {
                "price": 3850.5,
                "change": 15.5,
                "change_percent": 0.40,
                "update_time": "2026-02-22 14:30:25"
            },
            ...
        },
        "market_status": {
            "is_trading": true,
            "session": "下午",
            "reason": "下午交易时段"
        },
        "update_time": "2026-02-22 14:30:25"
    }
    """
    try:
        # 检查交易时段
        from utils.market_calendar import calendar
        market_status = calendar.is_trading_time()
        
        # 休市期间，使用长缓存策略
        if not market_status['is_trading']:
            # 检查是否有缓存（休市期间缓存 5 分钟）
            with _price_cache['lock']:
                if _price_cache['data'] and (time.time() - _price_cache['timestamp']) < 300:
                    logger.debug(f"休市期间使用缓存价格：{market_status['session']}")
                    result = _price_cache['data'].copy()
                    result['market_status'] = market_status
                    return jsonify(result)
        
        # 交易时段或缓存过期，检查短期缓存（2 秒）
        with _price_cache['lock']:
            if _price_cache['data'] and (time.time() - _price_cache['timestamp']) < 2:
                logger.debug(f"使用缓存价格，剩余有效期：{2 - (time.time() - _price_cache['timestamp']):.1f}秒")
                result = _price_cache['data'].copy()
                result['market_status'] = market_status
                return jsonify(result)

        # 休市期间且无缓存，返回空数据
        if not market_status['is_trading']:
            logger.info(f"休市期间无缓存：{market_status['session']} - {market_status['reason']}")
            return jsonify({
                "success": True,
                "data": {},
                "market_status": market_status,
                "message": f"休市中：{market_status['reason']}，{market_status['next_session']}",
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

        # 交易时段，获取新数据
        varieties_param = request.args.get("varieties")
        variety_codes = None
        if varieties_param:
            variety_codes = [v.strip().upper() for v in varieties_param.split(",")]

        # 创建新的价格获取器实例，确保获取实时数据
        from data_layer.quick_price_fetcher import QuickPriceFetcher
        fetcher = QuickPriceFetcher()
        
        try:
            prices = fetcher.get_multi_prices(variety_codes)
        except Exception as e:
            logger.error(f"获取价格异常：{e}")
            prices = {}
        finally:
            try:
                fetcher.close()  # 确保关闭连接
            except:
                pass

        # 过滤失败的数据
        success_prices = {k: v for k, v in prices.items() if v.get("success")}

        result = {
            "success": True,
            "data": success_prices,
            "market_status": market_status,
            "count": len(success_prices),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # 更新缓存
        with _price_cache['lock']:
            _price_cache['data'] = result
            _price_cache['timestamp'] = time.time()

        logger.info(f"获取实时价格：{len(success_prices)}个品种，{market_status['session']}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"获取价格失败：{e}")
        return jsonify({"success": False, "error": str(e)}), 500


@price_bp.route("/<variety_code>")
def get_single_price(variety_code: str):
    """
    获取单个品种价格
    
    返回：
    {
        "success": true,
        "data": {
            "variety_code": "RB",
            "variety_name": "螺纹钢",
            "price": 3850.5,
            "change": 15.5,
            "change_percent": 0.40,
            ...
        }
    }
    """
    try:
        from data_layer.quick_price_fetcher import get_price_single
        
        data = get_price_single(variety_code.upper())
        
        if data.get("success"):
            return jsonify({
                "success": True,
                "data": data,
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        else:
            return jsonify({
                "success": False,
                "error": data.get("error", "获取失败")
            }), 400
            
    except Exception as e:
        logger.error(f"获取价格失败 {variety_code}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@price_bp.route("/alert")
def get_price_alerts():
    """
    获取价格异动提醒
    
    参数:
    - threshold: 涨跌幅阈值（%，默认 1.0）
    
    返回：
    {
        "success": true,
        "alerts": [
            {
                "variety_code": "RB",
                "variety_name": "螺纹钢",
                "price": 3850.5,
                "change_percent": 1.52,
                "alert_type": "上涨",
                "message": "螺纹钢 上涨 1.52%，现价 3850.50"
            },
            ...
        ],
        "count": 2
    }
    """
    try:
        threshold = request.args.get("threshold", 1.0, type=float)
        
        from tasks.price_refresh_tasks import check_price_alerts_task
        
        # 同步检查（数据量小）
        fetcher = get_fetcher()
        alerts = []
        
        # 使用所有支持的品种
        from data_layer.quick_price_fetcher import EXCHANGE_MAP
        for code in EXCHANGE_MAP.keys():
            alert = fetcher.get_price_change_alert(code, threshold)
            if alert:
                alerts.append(alert)
        
        return jsonify({
            "success": True,
            "alerts": alerts,
            "count": len(alerts),
            "threshold": threshold
        })
        
    except Exception as e:
        logger.error(f"获取价格提醒失败：{e}")
        return jsonify({"success": False, "error": str(e)}), 500


@price_bp.route("/stats")
def get_price_stats():
    """
    获取价格统计信息
    
    返回：
    {
        "success": true,
        "stats": {
            "gainers": [{"code": "RB", "change_percent": 1.52}, ...],  # 上涨
            "losers": [{"code": "MA", "change_percent": -0.85}, ...],  # 下跌
            "unchanged": [...],  # 平盘
            "most_active": [{"code": "RB", "volume": 125000}, ...]  # 最活跃
        }
    }
    """
    try:
        prices = get_prices_quick()
        
        gainers = []
        losers = []
        unchanged = []
        active = []
        
        for code, data in prices.items():
            if not data.get("success") or data.get("price", 0) <= 0:
                continue
            
            change_pct = data.get("change_percent", 0)
            volume = data.get("volume", 0)
            
            item = {
                "code": code,
                "name": data.get("variety_name", code),
                "price": data.get("price", 0),
                "change_percent": change_pct
            }
            
            if change_pct > 0.5:
                gainers.append(item)
            elif change_pct < -0.5:
                losers.append(item)
            else:
                unchanged.append(item)
            
            if volume > 0:
                active.append({**item, "volume": volume})
        
        # 排序
        gainers.sort(key=lambda x: x["change_percent"], reverse=True)
        losers.sort(key=lambda x: x["change_percent"])
        active.sort(key=lambda x: x["volume"], reverse=True)
        
        return jsonify({
            "success": True,
            "stats": {
                "gainers": gainers[:5],  # 前 5 名
                "losers": losers[:5],
                "unchanged": unchanged[:5],
                "most_active": active[:5]
            },
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    except Exception as e:
        logger.error(f"获取价格统计失败：{e}")
        return jsonify({"success": False, "error": str(e)}), 500


def register_price_routes(app):
    """注册价格路由"""
    app.register_blueprint(price_bp)
    logger.info("实时价格路由已注册")
