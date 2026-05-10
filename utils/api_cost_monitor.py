# utils/api_cost_monitor.py
"""
API调用成本监控工具
跟踪API调用量、成本统计和优化效果
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List
from dataclasses import dataclass, asdict
from collections import defaultdict
import logging

try:
    from utils.cache_utils import redis_client

    REDIS_AVAILABLE = True
except:
    REDIS_AVAILABLE = False
    redis_client = None

logger = logging.getLogger(__name__)


@dataclass
class APICallRecord:
    """API调用记录"""

    timestamp: str
    api_name: str
    variety_code: str
    success: bool
    cost_time: float
    is_cached: bool = False
    batch_size: int = 1


class APICostMonitor:
    """
    API成本监控器

    功能：
    1. 记录每次API调用
    2. 统计API调用量和成本
    3. 计算缓存命中率和成本节省
    4. 生成成本报告
    """

    # DeepSeek API定价（每1000 tokens）
    API_PRICING = {
        "deepseek-chat": {
            "input": 0.001,  # 输入：$0.001/1K tokens
            "output": 0.002,  # 输出：$0.002/1K tokens
        }
    }

    # 估算平均token消耗
    AVG_TOKENS_PER_CALL = {
        "single": {"input": 800, "output": 200},  # 单品种
        "batch": {"input": 2000, "output": 500},  # 批量（3个品种）
    }

    def __init__(self):
        self.stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "batch_calls": 0,
            "single_calls": 0,
            "failed_calls": 0,
            "total_cost_usd": 0.0,
            "saved_cost_usd": 0.0,
        }
        self.daily_stats = defaultdict(lambda: {"calls": 0, "cost": 0.0, "saved": 0.0})

    def record_api_call(
        self,
        api_name: str,
        variety_code: str,
        success: bool = True,
        cost_time: float = 0,
        is_cached: bool = False,
        batch_size: int = 1,
    ):
        """
        记录API调用

        Args:
            api_name: API名称（如 deepseek-chat）
            variety_code: 品种代码
            success: 是否成功
            cost_time: 耗时（秒）
            is_cached: 是否命中缓存
            batch_size: 批量大小（1表示单品种）
        """
        record = APICallRecord(
            timestamp=datetime.now().isoformat(),
            api_name=api_name,
            variety_code=variety_code,
            success=success,
            cost_time=cost_time,
            is_cached=is_cached,
            batch_size=batch_size,
        )

        # 更新统计
        if is_cached:
            self.stats["cache_hits"] += 1
        elif batch_size > 1:
            self.stats["batch_calls"] += 1
        else:
            self.stats["single_calls"] += 1

        if success and not is_cached:
            self.stats["total_calls"] += 1

            # 计算成本
            if batch_size > 1:
                tokens = self.AVG_TOKENS_PER_CALL["batch"]
                # 批量调用成本按品种分摊
                cost_per_variety = self._calculate_cost(api_name, tokens) / batch_size
                actual_cost = cost_per_variety * batch_size

                # 计算节省（相比单品种调用）
                single_cost = self._calculate_cost(
                    api_name, self.AVG_TOKENS_PER_CALL["single"]
                )
                saved_cost = (single_cost * batch_size) - actual_cost
            else:
                tokens = self.AVG_TOKENS_PER_CALL["single"]
                actual_cost = self._calculate_cost(api_name, tokens)
                saved_cost = 0

            self.stats["total_cost_usd"] += actual_cost
            self.stats["saved_cost_usd"] += saved_cost

            # 更新每日统计
            today = datetime.now().strftime("%Y-%m-%d")
            self.daily_stats[today]["calls"] += 1
            self.daily_stats[today]["cost"] += actual_cost
            self.daily_stats[today]["saved"] += saved_cost

        if not success:
            self.stats["failed_calls"] += 1

        # 记录到Redis（如果可用）
        if REDIS_AVAILABLE and redis_client:
            self._save_to_redis(record)

        logger.debug(f"[API Monitor] {api_name} - {variety_code} - Cached: {is_cached}")

    def _calculate_cost(self, api_name: str, tokens: Dict) -> float:
        """计算API调用成本"""
        pricing = self.API_PRICING.get(api_name, self.API_PRICING["deepseek-chat"])

        input_cost = (tokens["input"] / 1000) * pricing["input"]
        output_cost = (tokens["output"] / 1000) * pricing["output"]

        return input_cost + output_cost

    def _save_to_redis(self, record: APICallRecord):
        """保存记录到Redis"""
        try:
            key = f"api_stats:{datetime.now().strftime('%Y-%m-%d')}"
            record_json = json.dumps(asdict(record))
            redis_client.lpush(key, record_json)
            redis_client.expire(key, 86400 * 30)  # 保留30天
        except Exception as e:
            logger.warning(f"保存API统计到Redis失败: {e}")

    def get_stats(self) -> Dict:
        """获取统计信息"""
        total_requests = self.stats["total_calls"] + self.stats["cache_hits"]

        return {
            "total_api_calls": self.stats["total_calls"],
            "cache_hits": self.stats["cache_hits"],
            "cache_hit_rate": self.stats["cache_hits"] / max(total_requests, 1),
            "batch_calls": self.stats["batch_calls"],
            "single_calls": self.stats["single_calls"],
            "failed_calls": self.stats["failed_calls"],
            "total_cost_usd": round(self.stats["total_cost_usd"], 4),
            "total_cost_cny": round(self.stats["total_cost_usd"] * 7.2, 2),  # 按7.2汇率
            "saved_cost_usd": round(self.stats["saved_cost_usd"], 4),
            "saved_cost_cny": round(self.stats["saved_cost_usd"] * 7.2, 2),
            "savings_rate": self.stats["saved_cost_usd"]
            / max(self.stats["total_cost_usd"] + self.stats["saved_cost_usd"], 0.001),
        }

    def get_daily_report(self, days: int = 7) -> List[Dict]:
        """获取每日报告"""
        report = []
        today = datetime.now()

        for i in range(days):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            stats = self.daily_stats.get(date, {"calls": 0, "cost": 0.0, "saved": 0.0})

            report.append(
                {
                    "date": date,
                    "calls": stats["calls"],
                    "cost_usd": round(stats["cost"], 4),
                    "cost_cny": round(stats["cost"] * 7.2, 2),
                    "saved_usd": round(stats["saved"], 4),
                    "saved_cny": round(stats["saved"] * 7.2, 2),
                }
            )

        return report

    def generate_cost_report(self) -> str:
        """生成成本报告文本"""
        stats = self.get_stats()
        daily = self.get_daily_report(7)

        report = []
        report.append("=" * 50)
        report.append("API调用成本报告")
        report.append("=" * 50)
        report.append("")
        report.append(f"统计时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        report.append("【总体统计】")
        report.append(f"  API调用次数: {stats['total_api_calls']}")
        report.append(f"  缓存命中次数: {stats['cache_hits']}")
        report.append(f"  缓存命中率: {stats['cache_hit_rate']:.1%}")
        report.append(f"  批量调用: {stats['batch_calls']}")
        report.append(f"  单品种调用: {stats['single_calls']}")
        report.append(f"  失败次数: {stats['failed_calls']}")
        report.append("")
        report.append("【成本分析】")
        report.append(
            f"  实际成本: ${stats['total_cost_usd']:.4f} (¥{stats['total_cost_cny']:.2f})"
        )
        report.append(
            f"  节省成本: ${stats['saved_cost_usd']:.4f} (¥{stats['saved_cost_cny']:.2f})"
        )
        report.append(f"  节省比例: {stats['savings_rate']:.1%}")
        report.append("")
        report.append("【近7日趋势】")
        for day in daily:
            report.append(
                f"  {day['date']}: {day['calls']}次调用, "
                f"¥{day['cost_cny']:.2f}, 节省¥{day['saved_cny']:.2f}"
            )
        report.append("")
        report.append("=" * 50)

        return "\n".join(report)

    def reset_stats(self):
        """重置统计（谨慎使用）"""
        self.stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "batch_calls": 0,
            "single_calls": 0,
            "failed_calls": 0,
            "total_cost_usd": 0.0,
            "saved_cost_usd": 0.0,
        }
        self.daily_stats.clear()


# 全局监控器实例
_cost_monitor = None


def get_cost_monitor() -> APICostMonitor:
    """获取全局成本监控器实例"""
    global _cost_monitor
    if _cost_monitor is None:
        _cost_monitor = APICostMonitor()
    return _cost_monitor


def record_api_call(api_name: str, variety_code: str, **kwargs):
    """
    便捷的API调用记录函数

    示例:
        record_api_call('deepseek-chat', '螺纹钢', success=True, is_cached=False)
    """
    monitor = get_cost_monitor()
    monitor.record_api_call(api_name, variety_code, **kwargs)


def get_api_stats() -> Dict:
    """获取API统计信息"""
    return get_cost_monitor().get_stats()


def print_cost_report():
    """打印成本报告"""
    print(get_cost_monitor().generate_cost_report())
