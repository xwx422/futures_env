#!/usr/bin/env python3
"""
AI 期货分析平台 - 主程序（优化版）
功能：
1. 批量分析所有配置的期货品种
2. 整合技术面、资金面、政策面数据
3. 调用 AI 生成交易建议
4. 保存结果到 SQLite 数据库
5. 记录更新日志到 update_logs 表
"""

import os
import sys
import yaml
import sqlite3
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
import numpy as np

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 导入业务模块
from execution_layer.generate_card import generate_analysis_card
from data_layer.fetch_market import cleanup_tq_api
from analysis_layer.deepseek_agent import call_deepseek


def load_config() -> Dict:
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"加载配置文件失败：{e}")
        sys.exit(1)


def clean_contract(contract: str) -> str:
    """清理合约名称，去掉交易所前缀"""
    for prefix in ["CZCE.", "SHFE.", "DCE.", "INE.", "CFFEX.", "GFEX."]:
        if contract.startswith(prefix):
            return contract[len(prefix) :]
    return contract


def convert_to_json_serializable(obj, path="root"):
    """
    将对象转换为 JSON 可序列化的格式
    处理 numpy 类型、布尔值等
    """
    try:
        if isinstance(obj, dict):
            return {
                k: convert_to_json_serializable(v, f"{path}.{k}")
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [
                convert_to_json_serializable(item, f"{path}[{i}]")
                for i, item in enumerate(obj)
            ]
        elif isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, bool):
            return obj
        elif isinstance(obj, (int, np.integer)):
            return int(obj)
        elif isinstance(obj, (float, np.floating)):
            return float(obj)
        elif isinstance(obj, str):
            return obj
        elif obj is None:
            return None
        elif hasattr(obj, "item"):  # numpy scalar types
            return obj.item()
        else:
            # 未知类型，尝试转换为字符串
            logging.warning(f"未知类型 {type(obj)} 在路径 {path}, 值：{obj}")
            return str(obj)
    except Exception as e:
        logging.error(f"转换失败在路径 {path}: {e}, 类型：{type(obj)}, 值：{obj}")
        return str(obj)


def save_analysis_to_db(all_results: List[Dict]) -> bool:
    """
    保存分析结果到数据库

    Args:
        all_results: 分析结果列表

    Returns:
        是否成功保存
    """
    try:
        if not all_results:
            logger.warning("没有数据需要保存")
            return False

        # 转换所有结果为 JSON 可序列化格式
        all_results = convert_to_json_serializable(all_results)

        # 过滤掉 None 值
        all_results = [r for r in all_results if r is not None]

        conn = sqlite3.connect("futures_analysis.db")
        cursor = conn.cursor()

        # 获取当前时间
        run_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 判断时段
        hour = datetime.now().hour
        if 5 <= hour < 11:
            session = "morning"
        elif 11 <= hour < 15:
            session = "afternoon"
        elif 17 <= hour < 23:
            session = "night"
        else:
            session = "night"

        saved_count = 0
        for res in all_results:
            try:
                # 提取数据
                variety = res.get("variety", "")
                variety_name = res.get("variety_name", variety)
                variety_code = res.get("variety_code", variety)  # 使用英文代码
                sector = res.get("sector", "其他")
                price = res.get("price", 0)
                main_contract_clean = clean_contract(res.get("main_contract", ""))
                policy_sentiment = json.dumps(
                    res.get("policy_sentiment", {}), ensure_ascii=False
                )
                fund_probability = res.get("probability", 50)
                tech_trend = res.get("tech_trend", "中性")
                tech_indicators_summary = res.get("tech_indicators_summary", "")
                tech_indicators = json.dumps(
                    res.get("tech_indicators", {}), ensure_ascii=False
                )
                timeframe_analysis = json.dumps(
                    res.get("timeframe_analysis", {}), ensure_ascii=False
                )
                timeframe_confluence = res.get("timeframe_confluence", "未知")
                trade_direction = res.get("trade_plan", {}).get("direction", "观望")
                trade_cycle = res.get("trade_plan", {}).get("cycle", "短线")
                entry_price = res.get("trade_plan", {}).get("entry_price", 0)
                stop_loss = res.get("trade_plan", {}).get("stop_loss", 0)
                target_price = res.get("trade_plan", {}).get("take_profit", 0)
                composite_score = res.get("trade_plan", {}).get("confidence", "中")
                reason_full = res.get("reason", "")
                atr_value = res.get("atr_value", 0)
                atr_ratio = res.get("atr_ratio", 0)
                volume_analysis = json.dumps(
                    res.get("volume_analysis", {}), ensure_ascii=False
                )
                price_change = res.get("change_percent", res.get("price_change", 0))
                volume_trend = res.get("volume_trend", "平稳")
                oi_change = res.get("oi_change", 0)
                price_percentile = res.get("price_percentile", 50)
                risk_max_position_pct = res.get("position_analysis", {}).get(
                    "position_pct", 10
                )
                risk_max_daily_loss_pct = res.get("position_analysis", {}).get(
                    "actual_risk_pct", 2
                )
                risk_suggested_position = res.get("risk_suggested_position", 1)
                risk_margin_per_contract = res.get("risk_margin_per_contract", 0)
                summary_text = res.get("summary", "")
                trend_info = json.dumps(res.get("trend_info", {}), ensure_ascii=False)
                adx_info_dict = res.get("adx_info", {})
                if isinstance(adx_info_dict, dict):
                    adx_info_dict["trend_phase"] = res.get("trend_phase", "")
                    adx_info_dict["trend_phase_score"] = res.get("trend_phase_score", 0)
                    adx_info_dict["entry_timing_grade"] = res.get(
                        "entry_timing_grade", ""
                    )
                    adx_info_dict["entry_timing_label"] = res.get(
                        "entry_timing_label", ""
                    )
                    entry_timing_raw = res.get("entry_timing", {})
                    if isinstance(entry_timing_raw, dict):
                        adx_info_dict["entry_timing"] = entry_timing_raw
                adx_info = json.dumps(adx_info_dict, ensure_ascii=False)
                support_resistance = json.dumps(
                    res.get("support_resistance", {}), ensure_ascii=False
                )
                fund_analysis = json.dumps(
                    res.get("fund_analysis", {}), ensure_ascii=False
                )
                rollover_info = json.dumps(
                    res.get("rollover_info", {}), ensure_ascii=False
                )
                position_analysis = json.dumps(
                    res.get("position_analysis", {}), ensure_ascii=False
                )
                risk_reward_ratio = res.get("risk_reward_ratio", 1.5)
                stop_type = res.get("stop_type", "ATR")
                turtle_channel = json.dumps(
                    res.get("turtle_channel", {}), ensure_ascii=False
                )
                basis_data = json.dumps(res.get("basis_data", {}), ensure_ascii=False)
                trade_plan = json.dumps(res.get("trade_plan", {}), ensure_ascii=False)

                # 先尝试更新该品种的最新记录（不区分 session），不存在则插入
                data_params = (
                    run_time,
                    session,
                    variety_name,
                    sector,
                    price,
                    main_contract_clean,
                    policy_sentiment,
                    fund_probability,
                    tech_trend,
                    tech_indicators_summary,
                    tech_indicators,
                    timeframe_analysis,
                    timeframe_confluence,
                    trade_direction,
                    trade_cycle,
                    entry_price,
                    stop_loss,
                    target_price,
                    composite_score,
                    reason_full,
                    atr_value,
                    atr_ratio,
                    volume_analysis,
                    price_change,
                    volume_trend,
                    oi_change,
                    price_percentile,
                    risk_max_position_pct,
                    risk_max_daily_loss_pct,
                    risk_suggested_position,
                    risk_margin_per_contract,
                    summary_text,
                    trend_info,
                    adx_info,
                    support_resistance,
                    fund_analysis,
                    rollover_info,
                    position_analysis,
                    risk_reward_ratio,
                    stop_type,
                    turtle_channel,
                    basis_data,
                    trade_plan,
                )
                cursor.execute(
                    """UPDATE analysis_records SET
                        run_time=?, session=?, variety_name=?, sector=?,
                        price=?, main_contract_clean=?, policy_sentiment=?,
                        fund_probability=?, tech_trend=?, tech_indicators_summary=?,
                        tech_indicators=?, timeframe_analysis=?, timeframe_confluence=?,
                        trade_direction=?, trade_cycle=?, entry_price=?, stop_loss=?,
                        target_price=?, composite_score=?, reason_full=?, atr_value=?,
                        atr_ratio=?, volume_analysis=?, price_change=?, volume_trend=?,
                        oi_change=?, price_percentile=?, risk_max_position_pct=?,
                        risk_max_daily_loss_pct=?, risk_suggested_position=?,
                        risk_margin_per_contract=?, summary_text=?, trend_info=?,
                        adx_info=?, support_resistance=?, fund_analysis=?,
                        rollover_info=?, position_analysis=?, risk_reward_ratio=?,
                        stop_type=?, turtle_channel=?, basis_data=?, trade_plan=?
                    WHERE id = (SELECT id FROM analysis_records WHERE variety_code=? ORDER BY id DESC LIMIT 1)""",
                    data_params + (variety_code,),
                )

                if cursor.rowcount == 0:
                    cursor.execute(
                        """INSERT INTO analysis_records (
                            run_time, session, variety_code, variety_name, sector,
                            price, main_contract_clean, policy_sentiment,
                            fund_probability, tech_trend, tech_indicators_summary,
                            tech_indicators, timeframe_analysis, timeframe_confluence,
                            trade_direction, trade_cycle, entry_price, stop_loss,
                            target_price, composite_score, reason_full, atr_value,
                            atr_ratio, volume_analysis, price_change, volume_trend,
                            oi_change, price_percentile, risk_max_position_pct,
                            risk_max_daily_loss_pct, risk_suggested_position,
                            risk_margin_per_contract, summary_text, trend_info,
                            adx_info, support_resistance, fund_analysis,
                            rollover_info, position_analysis, risk_reward_ratio,
                            stop_type, turtle_channel, basis_data, trade_plan
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        data_params[:2] + (variety_code,) + data_params[2:],
                    )
                saved_count += 1

            except Exception as e:
                logger.error(f"保存 {res.get('variety', '未知')} 失败：{e}")
                continue

        conn.commit()
        conn.close()
        logger.info(f"成功保存 {saved_count}/{len(all_results)} 条分析结果到数据库")
        return saved_count > 0

    except Exception as e:
        logger.error(f"保存分析结果到数据库失败：{e}")
        return False


def generate_summary(all_results: List[Dict]):
    """生成分析摘要"""
    high_prob_list = []

    for res in all_results:
        name = res.get("variety_name", res.get("variety", "未知"))
        prob = res.get("probability", 0)

        # 高概率品种
        if prob > 80:
            high_prob_list.append(f"{name}（{prob}%）")

    # 输出摘要
    print("\n" + "=" * 80)
    print("🔥 今日重点关注摘要")
    print("-" * 80)

    print(
        f"✅ 高胜率机会（资金概率 > 80%）：{'、'.join(high_prob_list) if high_prob_list else '无'}"
    )

    print("=" * 80)
    print("💡 建议：优先关注资金胜率较高的品种，结合技术面和基本面综合判断。")


def analyze_variety(variety: str) -> tuple:
    """
    分析单个品种

    Returns:
        (结构化数据，是否成功)
    """
    try:
        structured, card_or_error = generate_analysis_card(variety)

        if structured:
            return structured, True
        else:
            logger.warning(f"{variety}: {card_or_error}")
            return None, False

    except Exception as e:
        logger.error(f"{variety} 分析异常：{e}")
        return None, False


def record_update_log(
    success_count: int,
    total_count: int,
    is_success: bool,
    error_msg: str = None,
    variety_results: List[Dict] = None,
):
    """
    记录更新日志到 update_logs 表

    Args:
        success_count: 成功数量
        total_count: 总数量
        is_success: 是否成功
        error_msg: 错误信息（可选）
        variety_results: 品种级结果列表
    """
    try:
        conn = sqlite3.connect("futures_analysis.db")
        cursor = conn.cursor()

        end_time = datetime.now()
        start_time = end_time.replace(second=max(0, end_time.second - 30))
        start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
        duration = 30

        if is_success:
            cursor.execute(
                """
                INSERT INTO update_logs (
                    username, start_time, end_time, update_time, status, message, error_message,
                    varieties_count, success_count, failed_count, duration_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "schedule_runner",
                    start_time_str,
                    end_time_str,
                    end_time_str,
                    "success",
                    f"数据分析完成（{success_count}个品种）",
                    None,
                    total_count,
                    success_count,
                    total_count - success_count,
                    duration,
                ),
            )
            logger.info(
                f"[MAIN] 已记录更新日志：成功{success_count}/{total_count}个品种"
            )
        else:
            cursor.execute(
                """
                INSERT INTO update_logs (
                    username, start_time, end_time, update_time, status, message, error_message,
                    varieties_count, success_count, failed_count, duration_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "schedule_runner",
                    start_time_str,
                    end_time_str,
                    end_time_str,
                    "failed",
                    "数据分析失败",
                    error_msg or "所有品种分析失败",
                    total_count,
                    0,
                    total_count,
                    duration,
                ),
            )
            logger.info(f"[MAIN] 已记录失败日志：{error_msg}")

        # 写入品种级明细
        if variety_results:
            log_id = cursor.lastrowid
            for vr in variety_results:
                cursor.execute(
                    """
                    INSERT INTO update_log_details (
                        log_id, variety_code, variety_name, status,
                        ai_direction, ai_confidence, price, price_change, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        log_id,
                        vr.get("variety_code", ""),
                        vr.get("variety_name", ""),
                        "success" if vr.get("success") else "failed",
                        vr.get("ai_direction"),
                        vr.get("ai_confidence"),
                        vr.get("price"),
                        vr.get("price_change"),
                        vr.get("error"),
                    ),
                )

        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[MAIN] 记录更新日志失败：{e}")


def main():
    """主函数"""
    config = load_config()
    varieties = list(config.get("varieties", {}).keys())

    if not varieties:
        logger.error("config.yaml 中未定义任何品种")
        record_update_log(0, 0, False, "config.yaml 中未定义任何品种")
        return

    logger.info(f"🚀 开始分析 {len(varieties)} 个期货品种")
    print("=" * 80)

    all_results = []
    variety_results = []

    # 逐个品种分析
    for i, variety in enumerate(varieties, 1):
        logger.info(f"[{i}/{len(varieties)}] 分析 {variety}...")

        structured, success = analyze_variety(variety)

        if success and structured:
            all_results.append(structured)
            price = structured.get("price", 0)
            prob = structured.get("probability", 0)
            direction = structured.get("trade_plan", {}).get("direction", "未知")
            print(f"  ✅ 价格：{price:.2f}, 概率：{prob}%, 方向：{direction}")
            variety_results.append(
                {
                    "variety_code": structured.get("variety_code", variety),
                    "variety_name": structured.get("variety_name", variety),
                    "success": True,
                    "price": price,
                    "price_change": structured.get(
                        "change_percent", structured.get("price_change")
                    ),
                    "ai_direction": direction,
                    "ai_confidence": prob,
                }
            )
        else:
            print(f"  ⚠️ 分析失败")
            variety_results.append(
                {
                    "variety_code": variety,
                    "variety_name": variety,
                    "success": False,
                    "error": "分析失败",
                }
            )

    # 保存结果到数据库并记录更新日志
    if all_results:
        save_analysis_to_db(all_results)
        success_count = len(all_results)
        failed_count = len(varieties) - success_count
        print(f"\n📊 分析完成：成功 {success_count}/{len(varieties)} 个品种")

        # 记录更新日志（含品种明细）
        record_update_log(
            success_count, len(varieties), True, variety_results=variety_results
        )

        generate_summary(all_results)
    else:
        print("\n❌ 所有品种分析都失败了！请检查网络连接和 API 配置。")

        # 记录失败日志
        record_update_log(
            0,
            len(varieties),
            False,
            "所有品种分析失败",
            variety_results=variety_results,
        )

    # 更新跨期价差数据（spread_data）
    try:
        from data_layer.spread_analyzer import update_spread_for_variety

        logger.info("📐 开始更新跨期价差数据...")
        spread_updated = 0
        spread_failed = 0
        for variety in varieties:
            try:
                result = update_spread_for_variety(variety)
                if result:
                    spread_updated += 1
            except Exception as e:
                spread_failed += 1
                logger.warning(f"  价差更新失败 {variety}: {e}")
        logger.info(
            f"📐 价差更新完成：成功 {spread_updated}/{len(varieties)}，失败 {spread_failed}"
        )
    except Exception as e:
        logger.warning(f"价差分析模块加载失败：{e}")

    # 清理资源
    try:
        cleanup_tq_api()
    except:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断执行")
        try:
            cleanup_tq_api()
        except:
            pass
        sys.exit(0)
    except Exception as e:
        logger.exception(f"程序运行出错：{e}")
        try:
            # 记录异常日志
            config = load_config()
            varieties = list(config.get("varieties", {}).keys()) if config else []
            record_update_log(0, len(varieties), False, str(e))

            cleanup_tq_api()
        except:
            pass
        sys.exit(1)
