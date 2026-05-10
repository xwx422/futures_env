# routes/market_data_routes.py
"""
市场数据API路由
为TradingView K线图提供数据接口
"""

from flask import Blueprint, jsonify, request, session, redirect, url_for
from functools import wraps
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

from data_layer.fetch_market import EXCHANGE_MAP, get_tq_api, cleanup_tq_api
from data_layer.technical_indicators import TechnicalIndicators, FuturesIndicators
from utils.cache_utils import cache_market_data, get_cache_key
from utils.market_calendar import get_next_update_info
from config.cache_config import cache

logger = logging.getLogger(__name__)

market_data_bp = Blueprint("market_data", __name__, url_prefix="/api/market")


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


@market_data_bp.route("/<variety_code>/klines", methods=["GET"])
@login_required
def get_klines(variety_code):
    """
    获取K线数据（TradingView格式）

    Query参数：
    - timeframe: 时间周期 (5m, 30m, 1h, 1d) 默认1d
    - limit: 数据条数 默认500
    - from: 开始时间戳
    - to: 结束时间戳

    返回：
    {
        "success": true,
        "data": [
            {"time": 1704067200, "open": 3500, "high": 3600, "low": 3480, "close": 3550, "volume": 15000},
            ...
        ]
    }
    """
    try:
        # 参数验证
        if variety_code not in EXCHANGE_MAP:
            return jsonify(
                {"success": False, "error": f"不支持的品种代码: {variety_code}"}
            ), 400

        # 获取参数
        timeframe = request.args.get("timeframe", "1d")
        limit = request.args.get("limit", 500, type=int)
        from_ts = request.args.get("from", type=int)
        to_ts = request.args.get("to", type=int)

        # 缓存键
        cache_key = get_cache_key("klines", variety_code, timeframe, limit)

        # 尝试从缓存获取
        cached_data = cache.get(cache_key)
        if cached_data:
            return jsonify({"success": True, "data": cached_data, "cached": True})

        # 转换时间周期为秒
        timeframe_seconds = {
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
        }.get(timeframe, 86400)

        # 获取数据
        api = get_tq_api()
        main_symbol = f"KQ.m@{EXCHANGE_MAP[variety_code]}"

        klines = api.get_kline_serial(
            main_symbol, duration_seconds=timeframe_seconds, data_length=limit
        )

        df = pd.DataFrame(klines)
        df = df[df["datetime"] > 0].copy()

        if len(df) == 0:
            return jsonify({"success": False, "error": "无数据"}), 404

        # 转换时间格式
        df["time"] = pd.to_datetime(df["datetime"]).astype("int64") // 10**9

        # 构建返回数据
        data = []
        for _, row in df.iterrows():
            data.append(
                {
                    "time": int(row["time"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]) if "volume" in row else 0,
                }
            )

        # 缓存结果（5分钟）
        cache.set(cache_key, data, timeout=300)

        return jsonify({"success": True, "data": data, "count": len(data)})

    except Exception as e:
        logger.error(f"[API] 获取K线数据失败 {variety_code}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cleanup_tq_api()


@market_data_bp.route("/<variety_code>/indicators", methods=["GET"])
@login_required
def get_indicators(variety_code):
    """
    获取技术指标数据

    Query参数：
    - indicators: 指标列表，逗号分隔 (ma,ema,macd,rsi,bollinger)
    - timeframe: 时间周期 默认1d

    返回：
    {
        "success": true,
        "data": {
            "ma": [{"time": 1704067200, "value": 3500}, ...],
            "macd": [{"time": 1704067200, "macd": 10, "signal": 5, "histogram": 5}, ...]
        }
    }
    """
    try:
        if variety_code not in EXCHANGE_MAP:
            return jsonify(
                {"success": False, "error": f"不支持的品种代码: {variety_code}"}
            ), 400

        # 获取参数
        indicators = request.args.get("indicators", "ma,macd,rsi").split(",")
        timeframe = request.args.get("timeframe", "1d")

        # 缓存键
        cache_key = get_cache_key(
            "indicators", variety_code, timeframe, ",".join(indicators)
        )
        cached_data = cache.get(cache_key)
        if cached_data:
            return jsonify({"success": True, "data": cached_data, "cached": True})

        # 获取K线数据
        timeframe_seconds = {
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
        }.get(timeframe, 86400)

        api = get_tq_api()
        main_symbol = f"KQ.m@{EXCHANGE_MAP[variety_code]}"

        klines = api.get_kline_serial(
            main_symbol, duration_seconds=timeframe_seconds, data_length=200
        )

        df = pd.DataFrame(klines)
        df = df[df["datetime"] > 0].copy()
        df["time"] = pd.to_datetime(df["datetime"]).astype("int64") // 10**9

        if len(df) < 30:
            return jsonify({"success": False, "error": "数据不足"}), 400

        # 计算指标
        result = {}

        if "ma" in indicators or "sma" in indicators:
            # 简单移动平均线
            for period in [5, 10, 20, 30, 60]:
                if len(df) >= period:
                    df[f"ma{period}"] = df["close"].rolling(window=period).mean()
                    result[f"ma{period}"] = [
                        {
                            "time": int(row["time"]),
                            "value": round(row[f"ma{period}"], 2),
                        }
                        for _, row in df.iterrows()
                        if not pd.isna(row[f"ma{period}"])
                    ]

        if "ema" in indicators:
            # 指数移动平均线
            for period in [12, 26]:
                if len(df) >= period:
                    df[f"ema{period}"] = df["close"].ewm(span=period).mean()
                    result[f"ema{period}"] = [
                        {
                            "time": int(row["time"]),
                            "value": round(row[f"ema{period}"], 2),
                        }
                        for _, row in df.iterrows()
                        if not pd.isna(row[f"ema{period}"])
                    ]

        if "macd" in indicators:
            # MACD
            ema12 = df["close"].ewm(span=12).mean()
            ema26 = df["close"].ewm(span=26).mean()
            df["macd"] = ema12 - ema26
            df["macd_signal"] = df["macd"].ewm(span=9).mean()
            df["macd_histogram"] = df["macd"] - df["macd_signal"]

            result["macd"] = [
                {
                    "time": int(row["time"]),
                    "macd": round(row["macd"], 4),
                    "signal": round(row["macd_signal"], 4),
                    "histogram": round(row["macd_histogram"], 4),
                }
                for _, row in df.iterrows()
                if not pd.isna(row["macd"])
            ]

        if "rsi" in indicators:
            # RSI
            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df["rsi"] = 100 - (100 / (1 + rs))

            result["rsi"] = [
                {"time": int(row["time"]), "value": round(row["rsi"], 2)}
                for _, row in df.iterrows()
                if not pd.isna(row["rsi"])
            ]

        if "bollinger" in indicators or "boll" in indicators:
            # 布林带
            df["bb_middle"] = df["close"].rolling(window=20).mean()
            bb_std = df["close"].rolling(window=20).std()
            df["bb_upper"] = df["bb_middle"] + (bb_std * 2)
            df["bb_lower"] = df["bb_middle"] - (bb_std * 2)

            result["bollinger"] = {
                "upper": [
                    {"time": int(row["time"]), "value": round(row["bb_upper"], 2)}
                    for _, row in df.iterrows()
                    if not pd.isna(row["bb_upper"])
                ],
                "middle": [
                    {"time": int(row["time"]), "value": round(row["bb_middle"], 2)}
                    for _, row in df.iterrows()
                    if not pd.isna(row["bb_middle"])
                ],
                "lower": [
                    {"time": int(row["time"]), "value": round(row["bb_lower"], 2)}
                    for _, row in df.iterrows()
                    if not pd.isna(row["bb_lower"])
                ],
            }

        if "volume" in indicators or "vol" in indicators:
            # 成交量
            result["volume"] = [
                {"time": int(row["time"]), "value": float(row["volume"])}
                for _, row in df.iterrows()
            ]

        # 缓存结果（5分钟）
        cache.set(cache_key, result, timeout=300)

        return jsonify({"success": True, "data": result, "count": len(df)})

    except Exception as e:
        logger.error(f"[API] 获取技术指标失败 {variety_code}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cleanup_tq_api()


@market_data_bp.route("/<variety_code>/config", methods=["GET"])
@login_required
def get_chart_config(variety_code):
    """
    获取图表配置信息

    返回品种的名称、价格精度等信息
    """
    try:
        if variety_code not in EXCHANGE_MAP:
            return jsonify(
                {"success": False, "error": f"不支持的品种代码: {variety_code}"}
            ), 400

        # 品种配置映射
        variety_config = {
            "RB": {"name": "螺纹钢", "price_scale": 0, "min_move": 1},
            "MA": {"name": "甲醇", "price_scale": 0, "min_move": 1},
            "SA": {"name": "纯碱", "price_scale": 0, "min_move": 1},
            "BU": {"name": "沥青", "price_scale": 0, "min_move": 1},
            "C": {"name": "玉米", "price_scale": 0, "min_move": 1},
            "CS": {"name": "玉米淀粉", "price_scale": 0, "min_move": 1},
            "JD": {"name": "鸡蛋", "price_scale": 0, "min_move": 1},
            "M": {"name": "豆粕", "price_scale": 0, "min_move": 1},
            "RM": {"name": "菜粕", "price_scale": 0, "min_move": 1},
            "SR": {"name": "白糖", "price_scale": 0, "min_move": 1},
            "V": {"name": "PVC", "price_scale": 0, "min_move": 1},
            "FG": {"name": "玻璃", "price_scale": 0, "min_move": 1},
        }

        config = variety_config.get(
            variety_code, {"name": variety_code, "price_scale": 0, "min_move": 1}
        )

        config["symbol"] = variety_code
        config["exchange"] = EXCHANGE_MAP[variety_code].split(".")[0]

        return jsonify({"success": True, "data": config})

    except Exception as e:
        logger.error(f"[API] 获取图表配置失败 {variety_code}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@market_data_bp.route("/timeframes", methods=["GET"])
@login_required
def get_supported_timeframes():
    """
    获取支持的时间周期列表
    """
    timeframes = [
        {"value": "15m", "label": "15分钟", "seconds": 900},
        {"value": "30m", "label": "30分钟", "seconds": 1800},
        {"value": "1h", "label": "1小时", "seconds": 3600},
        {"value": "1d", "label": "日线", "seconds": 86400},
        {"value": "1w", "label": "周线", "seconds": 604800},
    ]

    return jsonify({"success": True, "data": timeframes})


@market_data_bp.route("/next-update", methods=["GET"])
@login_required
def get_next_update():
    """
    获取下次数据更新时间
    
    考虑节假日和周末，返回下次自动更新的时间
    
    返回：
    {
        "success": true,
        "data": {
            "next_update_time": "2026-02-10 08:30:00",
            "next_update_desc": "明天 上午8:30",
            "countdown": "5小时30分钟",
            "is_trading_day": true,
            "is_updating": false,
            "current_time": "2026-02-09 23:31:00"
        }
    }
    """
    try:
        info = get_next_update_info()
        return jsonify({"success": True, "data": info})
    except Exception as e:
        logger.error(f"[API] 获取下次更新时间失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
