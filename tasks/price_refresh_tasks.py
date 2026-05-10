# coding: utf-8
"""
实时价格刷新任务（不花钱的更新）

功能:
1. 每 3 分钟刷新一次价格
2. 只获取价格，不调用 AI
3. 更新到缓存和数据库

成本：￥0
"""

import logging
from datetime import datetime
from typing import Dict, List
import sqlite3
import json

from celery_app import celery_app
from data_layer.quick_price_fetcher import get_fetcher, get_prices_quick

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def refresh_prices_task(self, variety_codes: List[str] = None) -> Dict:
    """
    刷新价格任务（轻量级，不调用 AI）

    Args:
        variety_codes: 品种代码列表，None 则更新全部

    Returns:
        更新结果
    """
    try:
        if variety_codes is None:
            # 使用所有支持的品种
            from data_layer.quick_price_fetcher import EXCHANGE_MAP
            variety_codes = list(EXCHANGE_MAP.keys())

        logger.info(f"[PRICE_REFRESH] 开始更新 {len(variety_codes)} 个品种价格")

        # 批量获取价格
        prices = get_prices_quick(variety_codes)

        success_count = sum(1 for p in prices.values() if p.get("success"))
        failed_count = len(variety_codes) - success_count

        # 保存到数据库（仅更新价格字段）
        saved_count = _save_prices_to_db(prices)

        logger.info(
            f"[PRICE_REFRESH] 完成：成功{success_count}个，"
            f"失败{failed_count}个，保存{saved_count}个"
        )

        return {
            "success": True,
            "total": len(variety_codes),
            "success_count": success_count,
            "failed_count": failed_count,
            "saved_count": saved_count,
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    except Exception as e:
        logger.error(f"[PRICE_REFRESH] 更新失败：{e}")
        return {
            "success": False,
            "error": str(e),
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def _save_prices_to_db(prices: Dict[str, Dict]) -> int:
    """
    保存价格到数据库

    更新 analysis_records 表的最新记录的价格字段
    """
    try:
        conn = sqlite3.connect("futures_analysis.db")
        cursor = conn.cursor()

        saved_count = 0

        for variety_code, data in prices.items():
            if not data.get("success"):
                continue

            price = data.get("price", 0)
            if price <= 0:
                continue

            # 更新最新一条记录的价格和涨跌幅
            cursor.execute(
                """
                UPDATE analysis_records
                SET price = ?,
                    price_change = ?
                WHERE variety_code = ?
                AND id = (
                    SELECT MAX(id) FROM analysis_records
                    WHERE variety_code = ?
                )
            """,
                (
                    price,
                    data.get("change_percent", 0),
                    variety_code,
                    variety_code,
                ),
            )

            saved_count += cursor.rowcount

        conn.commit()
        conn.close()

        return saved_count

    except Exception as e:
        logger.error(f"保存价格到数据库失败：{e}")
        return 0


@celery_app.task
def check_price_alerts_task(
    variety_codes: List[str] = None, threshold: float = 1.0
) -> Dict:
    """
    检查价格异动提醒

    Args:
        variety_codes: 品种代码列表
        threshold: 涨跌幅阈值（%）

    Returns:
        提醒信息
    """
    try:
        from data_layer.quick_price_fetcher import get_fetcher

        fetcher = get_fetcher()
        alerts = []

        if variety_codes is None:
            variety_codes = list(fetcher.__dict__.get("_last_prices", {}).keys())

        for code in variety_codes:
            alert = fetcher.get_price_change_alert(code, threshold)
            if alert:
                alerts.append(alert)

        logger.info(f"[ALERT] 发现 {len(alerts)} 个价格异动")

        return {
            "success": True,
            "alerts": alerts,
            "count": len(alerts),
            "threshold": threshold,
        }

    except Exception as e:
        logger.error(f"检查价格提醒失败：{e}")
        return {"success": False, "error": str(e), "alerts": []}
