# tasks/analysis_tasks.py
"""
分析任务定义
包含所有异步分析任务
"""

import logging
from typing import Dict, List
import os
import threading
import time

from data_layer.fetch_market import get_market_summary, cleanup_tq_api
from analysis_layer.batch_deepseek_agent import (
    BatchAIAnalyzer,
    analyze_varieties_with_cost_optimization,
)
from analysis_layer.trend_filter import filter_signal, get_trend_summary
from execution_layer.risk_manager import FuturesRiskManager
from execution_layer.generate_card import get_atr_value, calculate_adaptive_stop
from utils.cache_utils import invalidate_market_cache
from celery.exceptions import SoftTimeLimitExceeded

logger = logging.getLogger(__name__)

from celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, soft_time_limit=300)
def analyze_variety_task(self, variety_code: str, username: str = None) -> Dict:
    """
    分析单个品种的任务（支持成本优化）

    Args:
        variety_code: 品种代码
        username: 操作用户名（用于日志）

    Returns:
        分析结果字典
    """
    try:
        logger.info(f"[TASK] 开始分析品种: {variety_code}, 用户: {username}")

        self.update_state(
            state="PROGRESS", meta={"current": 1, "total": 5, "step": "获取行情数据"}
        )

        market_data = get_market_summary(variety_code, use_cache=True)
        if not market_data.get("success"):
            error_msg = market_data.get("fund_data", {}).get(
                "reason", "获取市场数据失败"
            )
            logger.error(f"[TASK] 品种 {variety_code} 获取市场数据失败: {error_msg}")
            return {"success": False, "variety_code": variety_code, "error": error_msg}

        self.update_state(
            state="PROGRESS", meta={"current": 2, "total": 5, "step": "AI深度研判"}
        )

        try:
            analyzer = BatchAIAnalyzer(batch_size=1, use_cache=True)
            variety_data = {
                "variety_code": variety_code,
                "variety_name": market_data.get("variety_name", variety_code),
                "market_data": market_data,
            }
            ai_results = analyzer.analyze_varieties_batch([variety_data])
            ai_result = ai_results.get(
                variety_code,
                {"direction": "观望", "confidence": 50, "reason": "AI分析失败"},
            )

            stats = analyzer.get_stats()
            if stats["cache_hits"] > 0:
                logger.info(f"[TASK] {variety_code} 命中缓存，节省API调用")

        except Exception as e:
            logger.error(f"[TASK] AI分析失败，停止该品种: {e}")
            return {
                "success": False,
                "variety_code": variety_code,
                "error": f"AI分析失败: {str(e)}",
            }

        self.update_state(
            state="PROGRESS", meta={"current": 3, "total": 5, "step": "风险评估"}
        )

        try:
            risk_manager = FuturesRiskManager()

            entry_price = market_data.get("current_price", 0)
            if isinstance(entry_price, dict):
                entry_price = entry_price.get("price", 0)

            direction = ai_result.get("direction", "观望")
            stop_price = entry_price * 0.02
            target_price = entry_price * 0.05

            risk_assessment = risk_manager.evaluate_trade_setup(
                entry=entry_price,
                stop_loss=stop_price,
                take_profit=target_price,
                direction=direction,
            )

            self.update_state(
                state="PROGRESS", meta={"current": 4, "total": 5, "step": "保存结果"}
            )

        except Exception as e:
            logger.warning(f"[TASK] 风险评估失败: {e}")
            risk_assessment = {
                "position_size": 1,
                "stop_loss": 0,
                "take_profit": 0,
                "risk_level": "medium",
                "reason": f"风险评估异常: {str(e)}",
            }

        card_id = None
        structured = None
        try:
            from execution_layer.generate_card import generate_analysis_card
            import sys, os

            _proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if _proj_root not in sys.path:
                sys.path.insert(0, _proj_root)
            import main

            # 从 config 中查找品种的中文名（market_data 的名称可能与 config 不一致）
            config = main.load_config()
            config_variety_name = None
            for vname, vinfo in config.get("varieties", {}).items():
                if vinfo.get("code") == variety_code:
                    config_variety_name = vname
                    break
            variety_name = config_variety_name or market_data.get(
                "variety_name", variety_code
            )
            logger.info(f"[TASK] 调用 generate_analysis_card: {variety_name}")

            structured, card_or_error = generate_analysis_card(variety_name)

            if structured:
                main.save_analysis_to_db([structured])
                logger.info(
                    f"[TASK] 品种 {variety_code} ({variety_name}) 分析完成并保存到数据库"
                )
                card_id = "saved"
            else:
                logger.warning(f"[TASK] 品种 {variety_code} 分析失败: {card_or_error}")

        except Exception as e:
            logger.error(f"[TASK] 保存结果失败: {e}")
            import traceback

            traceback.print_exc()

        if card_id == "saved":
            logger.info(f"[TASK] 品种 {variety_code} 已成功保存")

        return {
            "success": True,
            "variety_code": variety_code,
            "variety_name": market_data.get("variety_name", variety_code),
            "ai_direction": ai_result.get("direction", "观望"),
            "ai_confidence": (structured or {}).get(
                "probability", ai_result.get("confidence", 50)
            ),
            "price": entry_price,
            "price_change": market_data.get("price_change", 0),
            "result_id": card_id,
        }

    except SoftTimeLimitExceeded:
        error_msg = f"品种 {variety_code} 分析超时（超过5分钟）"
        logger.error(f"[TASK] {error_msg}")
        return {
            "success": False,
            "variety_code": variety_code,
            "error": error_msg,
        }
    except Exception as exc:
        logger.exception(f"[TASK] 品种 {variety_code} 分析异常: {exc}")
        self.retry(countdown=60, exc=exc)


@celery_app.task(bind=True, max_retries=3, soft_time_limit=1800)
def batch_analyze_task(
    self, varieties: List[str], username: str = None, start_time_str: str = None
) -> Dict:
    """
    批量分析多个品种的任务
    """
    try:
        from datetime import datetime, timedelta
        import time
        import sqlite3

        logger.info(f"[BATCH] 批量分析 {len(varieties)} 个品种，用户: {username}")

        if start_time_str:
            start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
        else:
            start_time = datetime.now()

        def record_log(
            status: str,
            message: str,
            error_msg: str = None,
            success_count: int = 0,
            failed_count: int = 0,
        ):
            try:
                end_time = datetime.now()
                duration = (
                    int((end_time - start_time).total_seconds())
                    if status != "running"
                    else None
                )

                conn = sqlite3.connect("futures_analysis.db")
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO update_logs (
                        username, start_time, end_time, update_time, status, message, error_message,
                        varieties_count, success_count, failed_count, duration_seconds
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        username,
                        start_time.strftime("%Y-%m-%d %H:%M:%S"),
                        end_time.strftime("%Y-%m-%d %H:%M:%S")
                        if status != "running"
                        else None,
                        end_time.strftime("%Y-%m-%d %H:%M:%S"),
                        status,
                        message,
                        error_msg,
                        len(varieties),
                        success_count,
                        failed_count,
                        duration,
                    ),
                )
                conn.commit()
                conn.close()
                logger.info(f"[BATCH] 已记录日志: {status}, {message}")
            except Exception as e:
                logger.error(f"[BATCH] 记录日志失败: {e}")

        self.update_state(
            state="PROGRESS",
            meta={"current": 0, "total": len(varieties), "step": "初始化批量任务"},
        )

        from celery import chord
        from celery.result import AsyncResult, GroupResult

        subtasks = [analyze_variety_task.s(code, username) for code in varieties]

        callback = batch_complete_callback.s(
            username, start_time.strftime("%Y-%m-%d %H:%M:%S"), len(varieties)
        )
        result = chord(subtasks)(callback)

        logger.info(f"[BATCH] 批量任务已创建，任务组ID: {result.id}")

        return {
            "task_group_id": result.id,
            "task_type": "batch",
            "total": len(varieties),
            "status": "started",
        }

    except Exception as exc:
        logger.exception(f"[BATCH] 批量任务创建失败: {exc}")
        try:
            from datetime import datetime
            import sqlite3

            end_time = datetime.now()
            conn = sqlite3.connect("futures_analysis.db")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO update_logs (
                    username, start_time, end_time, update_time, status, message, error_message,
                    varieties_count, success_count, failed_count, duration_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    username,
                    start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    end_time.strftime("%Y-%m-%d %H:%M:%S"),
                    end_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "failed",
                    "批量任务创建失败",
                    str(exc),
                    len(varieties) if "len(varieties)" in locals() else 0,
                    0,
                    len(varieties) if "len(varieties)" in locals() else 0,
                    0,
                ),
            )
            conn.commit()
            conn.close()
        except:
            pass
        return {"status": "failed", "error": str(exc)}


@celery_app.task
def batch_complete_callback(
    results, username: str, start_time_str: str, varieties_count: int
):
    """
    批量任务完成后的回调任务
    """
    try:
        from datetime import datetime
        import sqlite3

        start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
        end_time = datetime.now()
        duration = int((end_time - start_time).total_seconds())

        success_count = sum(
            1 for r in results if isinstance(r, dict) and r.get("success")
        )
        failed_count = varieties_count - success_count

        if success_count == varieties_count:
            status = "success"
            message = f"数据分析完成（{success_count}个品种）"
            error_msg = None
        elif success_count > 0:
            status = "success"
            message = f"数据分析部分完成（{success_count}/{varieties_count}个品种）"
            error_msg = f"{failed_count}个品种分析失败"
        else:
            status = "failed"
            message = f"数据分析失败（0/{varieties_count}个品种）"
            error_msg = "所有品种分析失败"

        conn = sqlite3.connect("futures_analysis.db")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO update_logs (
                username, start_time, end_time, update_time, status, message, error_message,
                varieties_count, success_count, failed_count, duration_seconds
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                username,
                start_time.strftime("%Y-%m-%d %H:%M:%S"),
                end_time.strftime("%Y-%m-%d %H:%M:%S"),
                end_time.strftime("%Y-%m-%d %H:%M:%S"),
                status,
                message,
                error_msg,
                varieties_count,
                success_count,
                failed_count,
                duration,
            ),
        )
        log_id = cursor.lastrowid

        # 写入每个品种的明细
        for r in results:
            if not isinstance(r, dict):
                continue
            r_status = "success" if r.get("success") else "failed"
            cursor.execute(
                """
                INSERT INTO update_log_details (
                    log_id, variety_code, variety_name, status,
                    ai_direction, ai_confidence, price, price_change, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    log_id,
                    r.get("variety_code", ""),
                    r.get("variety_name", ""),
                    r_status,
                    r.get("ai_direction"),
                    r.get("ai_confidence"),
                    r.get("price"),
                    r.get("price_change"),
                    r.get("error"),
                ),
            )

        conn.commit()
        conn.close()

        # 推送最有条件的品种告警（仅当有布局信号时才推送）
        try:
            import requests
            from urllib.parse import quote

            # 查询布局信号的品种
            conn2 = sqlite3.connect("futures_analysis.db")
            conn2.row_factory = sqlite3.Row
            cursor2 = conn2.cursor()
            cursor2.execute(
                """
                SELECT variety_code, variety_name, trade_direction, 
                       entry_price, stop_loss, target_price
                FROM analysis_records
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                            ROW_NUMBER() OVER (PARTITION BY variety_code ORDER BY run_time DESC, id DESC) as rn
                        FROM analysis_records
                    ) ranked WHERE rn = 1
                )
                AND signal_tier = '布局'
                AND trade_direction IN ('做多', '做空')
                ORDER BY 
                    CASE WHEN trade_direction = '做多' THEN target_price - entry_price 
                         ELSE entry_price - target_price END DESC
                LIMIT 1
            """
            )
            best_variety = cursor2.fetchone()
            conn2.close()

            if best_variety:
                variety_name = (
                    best_variety["variety_name"] or best_variety["variety_code"]
                )
                direction = "多" if best_variety["trade_direction"] == "做多" else "空"
                entry = best_variety["entry_price"] or 0
                stop = best_variety["stop_loss"] or 0
                target = best_variety["target_price"] or 0

                # title: 品种名+方向
                title = f"{variety_name}{direction}头信号"
                if len(title) > 20:
                    title = title[:20]

                # content: 入场-止损-目标（紧凑格式）
                content = f"入{entry:.0f} 止{stop:.0f} 目标{target:.0f}"
                if len(content) > 20:
                    content = content[:20]

                # URL 编码
                push_url = f"https://push.spug.cc/xsend/e7ffaad41ca3450a988e99e0b4b41e68?title={quote(title)}&content={quote(content)}"
                resp = requests.get(push_url, timeout=5)
                logger.info(f"[PUSH] 已推送: {title} - {content} - {resp.text}")
            else:
                logger.info("[PUSH] 无布局信号，跳过推送")
        except Exception as push_err:
            logger.warning(f"[PUSH] 推送失败: {push_err}")

        logger.info(
            f"[BATCH] 回调已记录日志: {status}, 成功{success_count}/{varieties_count}"
        )
        return {
            "status": status,
            "success_count": success_count,
            "failed_count": failed_count,
        }

    except Exception as e:
        logger.error(f"[BATCH] 回调记录日志失败: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task(bind=True)
def update_all_varieties_task(self, username: str = None) -> Dict:
    """
    更新所有品种的任务
    """
    try:
        from datetime import datetime
        import yaml

        logger.info(f"[UPDATE_ALL] 用户 {username} 启动全品种更新")

        # ========== 预检查：验证市场数据可用性 ==========
        from data_layer.fetch_market import get_market_summary

        test_code = "RB"
        test_data = get_market_summary(test_code, use_cache=False)
        close_prices = test_data.get("close_prices", [])
        if not close_prices or len(close_prices) < 20:
            logger.error(
                f"[UPDATE_ALL] 行情数据不足 (测试品种 {test_code}, K线条数={len(close_prices)}), "
                "可能处于休市日, 取消本次全品种更新以保护现有数据"
            )
            return {
                "success": False,
                "error": f"行情数据不足(K线={len(close_prices)}条,需≥20条), 休市日请勿批量更新以免覆盖有效数据",
                "varieties_processed": 0,
            }
        logger.info(
            f"[UPDATE_ALL] 行情数据检查通过 (测试品种 {test_code}, K线={len(close_prices)}条)"
        )
        # ========== 预检查结束 ==========

        # 从项目根目录加载配置
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(project_root, "config.yaml")

        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            # 从配置字典中提取品种代码
            varieties_config = config.get("varieties", {})
            if varieties_config and isinstance(varieties_config, dict):
                # 从字典的值中提取 code 字段
                varieties = [
                    info.get("code")
                    for info in varieties_config.values()
                    if info.get("code")
                ]
            else:
                varieties = []

            if not varieties:
                logger.warning("[UPDATE_ALL] 配置文件中没有品种，使用默认品种")
                varieties = [
                    "RB",
                    "MA",
                    "SA",
                    "V",
                    "RM",
                ]
        else:
            varieties = [
                "RB",
                "MA",
                "SA",
                "V",
                "RM",
            ]

        start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.update_state(
            state="PROGRESS",
            meta={"current": 0, "total": len(varieties), "step": "初始化批量任务"},
        )

        job = batch_analyze_task.delay(varieties, username)

        logger.info(f"[UPDATE_ALL] 全品种更新任务已创建，任务ID: {job.id}")

        return {
            "task_id": job.id,
            "task_type": "update_all",
            "total": len(varieties),
            "status": "started",
            "start_time": start_time_str,
        }

    except Exception as exc:
        logger.exception(f"[UPDATE_ALL] 创建全品种更新任务失败: {exc}")

        try:
            import sqlite3
            from datetime import datetime

            conn = sqlite3.connect("futures_analysis.db")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO update_logs (
                    username, start_time, end_time, update_time, status, message, error_message, 
                    varieties_count, success_count, failed_count, duration_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    username,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "failed",
                    "创建更新任务失败",
                    str(exc),
                    0,
                    0,
                    0,
                    0,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[UPDATE_ALL] 记录失败日志时出错: {e}")

        return {
            "task_id": "",
            "task_type": "update_all",
            "status": "failed",
            "error": str(exc),
        }
