# utils/cache_utils.py
"""
缓存工具函数
提供便捷的缓存操作接口
"""

import json
import hashlib
import pickle
from functools import wraps
from config.cache_config import redis_client, get_cache_key

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


def cache_get(key):
    """从缓存获取数据"""
    try:
        value = redis_client.get(key)
        if value is None:
            return None

        # 如果 value 已经是字符串，尝试 JSON 解析
        if isinstance(value, str):
            try:
                return json.loads(value)
            except:
                return value

        # 如果 value 是 bytes
        if isinstance(value, bytes):
            # 先尝试 pickle
            try:
                return pickle.loads(value)
            except:
                pass

            # 再尝试 json（先解码为字符串）
            try:
                return json.loads(value.decode("utf-8"))
            except:
                pass

        # 其他类型直接返回
        return value
    except Exception as e:
        print(f"[CACHE ERROR] 获取失败: {e}")
        return None

        # 如果 value 已经是字符串，直接返回
        if isinstance(value, str):
            return value

        # 如果 value 是 bytes，尝试反序列化
        if isinstance(value, bytes):
            # 先尝试 pickle
            try:
                return pickle.loads(value)
            except:
                pass

            # 再尝试 json
            try:
                return json.loads(value.decode("utf-8"))
            except:
                pass

            # 最后尝试直接解码为字符串
            try:
                return value.decode("utf-8")
            except:
                pass

        # 其他类型直接返回
        return value
    except Exception as e:
        print(f"[CACHE ERROR] 获取失败: {e}")
        return None


def cache_set(key, value, timeout=300):
    """设置缓存数据（使用json序列化）"""
    try:
        # 统一使用 JSON 序列化（避免 pickle 兼容性问题）
        serialized = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        redis_client.setex(key, timeout, serialized)
    except Exception as e:
        print(f"[CACHE ERROR] 设置失败: {e}")


def cache_delete(key):
    """删除缓存"""
    try:
        redis_client.delete(key)
    except Exception as e:
        print(f"[CACHE ERROR] 删除失败: {e}")


def cache_analysis_result(timeout=1800):
    """
    装饰器：缓存分析结果

    Args:
        timeout: 缓存超时时间（秒），默认30分钟
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = f"analysis:{func.__name__}:{hashlib.md5(str(args).encode()).hexdigest()}"

            # 尝试从缓存获取
            cached_result = cache_get(cache_key)
            if cached_result is not None:
                print(f"[CACHE HIT] {cache_key}")
                return cached_result

            # 执行函数
            result = func(*args, **kwargs)

            # 存入缓存
            cache_set(cache_key, result, timeout=timeout)
            print(f"[CACHE SET] {cache_key}")

            return result

        return wrapper

    return decorator


def cache_market_data(timeout=300):
    """
    装饰器：缓存行情数据

    Args:
        timeout: 缓存超时时间（秒），默认5分钟
    """

    def decorator(func):
        @wraps(func)
        def wrapper(variety_code, *args, **kwargs):
            cache_key = get_cache_key("market", variety_code, *args, **kwargs)

            # 尝试从缓存获取
            cached_result = cache_get(cache_key)
            if cached_result is not None:
                return cached_result

            # 执行函数
            result = func(variety_code, *args, **kwargs)

            # 存入缓存
            if result:
                cache_set(cache_key, result, timeout=timeout)

            return result

        return wrapper

    return decorator


def cache_technical_indicators(timeout=900):
    """
    装饰器：缓存技术指标

    Args:
        timeout: 缓存超时时间（秒），默认15分钟
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = get_cache_key("tech", func.__name__, *args, **kwargs)

            cached_result = cache_get(cache_key)
            if cached_result is not None:
                return cached_result

            result = func(*args, **kwargs)

            if result:
                cache_set(cache_key, result, timeout=timeout)

            return result

        return wrapper

    return decorator


def invalidate_market_cache(variety_code):
    """
    清除指定品种的所有行情缓存

    Args:
        variety_code: 品种代码
    """
    pattern = f"futures:market:*{variety_code}*"
    keys = redis_client.keys(pattern)
    if keys:
        redis_client.delete(*keys)
        print(f"[CACHE INVALIDATE] 清除 {len(keys)} 个缓存键")


def invalidate_analysis_cache(variety_code=None):
    """
    清除分析结果缓存

    Args:
        variety_code: 品种代码，None则清除所有
    """
    if variety_code:
        pattern = f"futures:analysis:*{variety_code}*"
    else:
        pattern = "futures:analysis:*"

    keys = redis_client.keys(pattern)
    if keys:
        redis_client.delete(*keys)


def get_or_set_cache(key, func, timeout=300, *args, **kwargs):
    """
    获取缓存，如果不存在则执行函数并缓存结果

    Args:
        key: 缓存键
        func: 数据获取函数
        timeout: 缓存超时
        *args, **kwargs: 传递给func的参数

    Returns:
        缓存值或函数返回值
    """
    cached = cache_get(key)
    if cached is not None:
        return cached

    result = func(*args, **kwargs)
    if result:
        cache_set(key, result, timeout=timeout)

    return result


def cache_ai_result(variety_code, tech_hash, result, timeout=1800):
    """
    缓存AI分析结果（使用技术参数指纹）

    Args:
        variety_code: 品种代码
        tech_hash: 技术指标参数哈希
        result: AI分析结果
        timeout: 缓存超时（秒）
    """
    cache_key = f"futures:ai:{variety_code}:{tech_hash}"
    cache_set(cache_key, result, timeout=timeout)


def get_cached_ai_result(variety_code, tech_hash):
    """
    获取缓存的AI分析结果

    Args:
        variety_code: 品种代码
        tech_hash: 技术指标参数哈希

    Returns:
        缓存的结果或None
    """
    cache_key = f"futures:ai:{variety_code}:{tech_hash}"
    return cache_get(cache_key)


def generate_tech_hash(tech_indicators):
    """
    生成技术指标指纹

    Args:
        tech_indicators: 技术指标字典

    Returns:
        MD5哈希字符串
    """
    # 取关键指标值
    key_values = {
        "macd": tech_indicators.get("macd", {}).get("macd_signal"),
        "rsi": round(tech_indicators.get("rsi", {}).get("rsi_value", 0)),
        "adx": round(tech_indicators.get("adx", {}).get("adx_value", 0)),
    }

    hash_str = json.dumps(key_values, sort_keys=True)
    return hashlib.md5(hash_str.encode()).hexdigest()[:8]


class CacheStats:
    """缓存统计信息"""

    @staticmethod
    def get_stats():
        """获取缓存统计"""
        try:
            info = redis_client.info()
            return {
                "used_memory": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "total_keys": len(redis_client.keys("futures:*")),
                "hit_rate": info.get("keyspace_hits", 0)
                / max(info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0), 1),
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def clear_all_cache():
        """清除所有缓存（危险操作）"""
        keys = redis_client.keys("futures:*")
        if keys:
            redis_client.delete(*keys)
            return len(keys)
        return 0
