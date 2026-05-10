# config/cache_config.py
"""
Redis缓存配置模块
提供Flask-Caching和原生Redis客户端配置
"""

import os
from flask_caching import Cache
import redis

# Redis连接配置
REDIS_CONFIG = {
    "host": os.getenv("REDIS_HOST", "localhost"),
    "port": int(os.getenv("REDIS_PORT", 6379)),
    "db": int(os.getenv("REDIS_DB", 0)),
    "password": os.getenv("REDIS_PASSWORD", None),
    "decode_responses": True,
}

# Flask-Caching配置
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_REDIS_HOST": REDIS_CONFIG["host"],
    "CACHE_REDIS_PORT": REDIS_CONFIG["port"],
    "CACHE_REDIS_DB": REDIS_CONFIG["db"],
    "CACHE_REDIS_PASSWORD": REDIS_CONFIG["password"],
    "CACHE_DEFAULT_TIMEOUT": 300,  # 默认缓存5分钟
    "CACHE_KEY_PREFIX": "futures:",  # 键前缀
    "CACHE_OPTIONS": {
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
        "retry_on_timeout": True,
    },
}

# 缓存超时配置（秒）
CACHE_TIMEOUTS = {
    "market_data": 300,  # 行情数据：5分钟
    "technical_indicators": 900,  # 技术指标：15分钟
    "ai_analysis": 1800,  # AI分析结果：30分钟
    "user_session": 3600,  # 用户会话：1小时
    "homepage_stats": 600,  # 首页统计：10分钟
    "variety_list": 300,  # 品种列表：5分钟
    "analysis_history": 1800,  # 分析历史：30分钟
}

# 创建缓存实例
cache = Cache(config=CACHE_CONFIG)

# 创建原生Redis客户端
redis_client = redis.Redis(**REDIS_CONFIG)


def init_cache(app):
    """初始化缓存"""
    cache.init_app(app)
    return cache


def get_cache_key(prefix, *args, **kwargs):
    """
    生成缓存键

    示例：
        get_cache_key('market', '螺纹钢', timeframe='1d')
        # 返回：futures:market:螺纹钢:1d
    """
    key_parts = [prefix]
    key_parts.extend([str(arg) for arg in args])
    key_parts.extend([f"{k}={v}" for k, v in sorted(kwargs.items())])
    return ":".join(key_parts)


def invalidate_cache_pattern(pattern):
    """
    批量清除匹配模式的缓存

    示例：
        invalidate_cache_pattern('futures:market:*')
    """
    try:
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)
            return len(keys)
        return 0
    except Exception as e:
        print(f"清除缓存失败: {e}")
        return 0


def cache_with_timeout(timeout_key):
    """
    装饰器：使用配置中的超时时间

    示例：
        @cache_with_timeout('market_data')
        def get_market_data(variety_code):
            ...
    """
    timeout = CACHE_TIMEOUTS.get(timeout_key, 300)
    return cache.cached(timeout=timeout)
