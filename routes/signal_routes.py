# -*- coding: utf-8 -*-
"""信号跟踪相关API"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
import sqlite3
import logging

logger = logging.getLogger(__name__)

signal_bp = Blueprint("signal", __name__, url_prefix="/api/signal")


def get_db_connection():
    conn = sqlite3.connect("futures_analysis.db")
    conn.row_factory = sqlite3.Row
    return conn


@signal_bp.route("/variety/<variety_code>")
def get_variety_signals(variety_code):
    """获取品种的信号跟踪统计"""
    days = request.args.get("days", 30, type=int)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 计算时间范围
        start_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        
        # 查询该品种在指定时间范围内的信号
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN pnl = 0 OR pnl IS NULL THEN 1 ELSE 0 END) as neutral,
                AVG(pnl) as avg_pnl,
                AVG(pnl_pct) as avg_pnl_pct,
                SUM(pnl) as total_pnl
            FROM signal_tracking
            WHERE variety_code = ?
              AND signal_time >= ?
              AND status = 'closed'
        """, (variety_code.upper(), start_time))
        
        row = cursor.fetchone()
        
        if row and row["total"] > 0:
            total = row["total"]
            wins = row["wins"] or 0
            win_rate = round(wins / total * 100, 1) if total > 0 else 0
            
            stats = {
                "total": total,
                "wins": wins,
                "losses": row["losses"] or 0,
                "neutral": row["neutral"] or 0,
                "win_rate": win_rate,
                "avg_pnl": round(row["avg_pnl"] or 0, 2),
                "avg_pnl_pct": round(row["avg_pnl_pct"] or 0, 2),
                "total_pnl": round(row["total_pnl"] or 0, 2)
            }
        else:
            stats = {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "neutral": 0,
                "win_rate": 0,
                "avg_pnl": 0,
                "avg_pnl_pct": 0,
                "total_pnl": 0
            }
        
        return jsonify({"success": True, "stats": stats})
        
    except Exception as e:
        logger.error(f"获取品种信号统计失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()
