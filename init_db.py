# init_db.py
"""
数据库初始化脚本 - 精简版
只保留核心表：分析记录、用户体系、更新日志、基差数据
"""

import sqlite3
import json
import os
import yaml


def init_database():
    """
    初始化期货分析数据库表结构（精简版）
    """
    conn = sqlite3.connect("futures_analysis.db")
    cursor = conn.cursor()

    def _add_column_if_missing(cursor, table, column, definition):
        cursor.execute(f"PRAGMA table_info({table})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # ============ analysis_records 表 ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_time TEXT NOT NULL,
            session TEXT NOT NULL,
            variety_code TEXT NOT NULL,
            variety_name TEXT NOT NULL,
            sector TEXT NOT NULL,
            price REAL,
            main_contract_clean TEXT,
            policy_sentiment TEXT,
            fund_probability INTEGER,
            tech_trend TEXT,
            tech_indicators_summary TEXT,
            tech_indicators TEXT,
            timeframe_analysis TEXT,
            timeframe_confluence TEXT,
            trade_direction TEXT,
            trade_cycle TEXT,
            entry_price REAL,
            stop_loss REAL,
            target_price REAL,
            composite_score TEXT,
            reason_full TEXT,
            atr_value REAL,
            atr_ratio REAL,
            volume_analysis TEXT,
            price_change REAL,
            volume_trend TEXT,
            oi_change REAL,
            price_percentile REAL,
            risk_max_position_pct REAL,
            risk_max_daily_loss_pct REAL,
            risk_suggested_position INTEGER,
            risk_margin_per_contract REAL,
            summary_text TEXT,
            trend_info TEXT,
            adx_info TEXT,
            support_resistance TEXT,
            fund_analysis TEXT,
            rollover_info TEXT,
            position_analysis TEXT,
            risk_reward_ratio REAL,
            stop_type TEXT,
            turtle_channel TEXT,
            basis_data TEXT,
            trade_plan TEXT,
            signal_source TEXT DEFAULT 'AI',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建索引
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_run_time ON analysis_records(run_time)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_variety ON analysis_records(variety_code)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sector ON analysis_records(sector)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_probability ON analysis_records(fund_probability)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_timeframe_confluence ON analysis_records(timeframe_confluence)"
    )

    # 迁移：为已有数据库添加 trade_plan 列
    try:
        cursor.execute("ALTER TABLE analysis_records ADD COLUMN trade_plan TEXT")
        logger.info("已添加 trade_plan 列")
    except sqlite3.OperationalError:
        pass

    # ============ 用户表 ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT,
            role TEXT NOT NULL DEFAULT 'member',
            member_type TEXT DEFAULT 'trial',
            expire_at TEXT,
            formal_start_at TEXT,
            status INTEGER DEFAULT 1,
            daily_analysis_count INTEGER DEFAULT 3,
            last_analysis_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")

    # 迁移：为已有数据库添加 daily_analysis_count 和 last_analysis_date 列
    _add_column_if_missing(cursor, "users", "daily_analysis_count", "INTEGER DEFAULT 3")
    _add_column_if_missing(cursor, "users", "last_analysis_date", "TEXT")

    # ============ 登录日志表 ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            login_time TEXT DEFAULT CURRENT_TIMESTAMP,
            login_status TEXT NOT NULL,
            login_ip TEXT,
            fail_reason TEXT,
            user_agent TEXT
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_logs_username ON login_logs(username)"
    )

    # ============ 品种查看日志表 ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS variety_view_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            view_time TEXT DEFAULT CURRENT_TIMESTAMP,
            variety_code TEXT NOT NULL,
            variety_name TEXT NOT NULL
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_view_logs_username ON variety_view_logs(username)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_view_logs_variety ON variety_view_logs(variety_code)"
    )

    # ============ 数据更新日志表 ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS update_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            update_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            message TEXT,
            error_message TEXT,
            varieties_count INTEGER,
            success_count INTEGER,
            failed_count INTEGER,
            duration_seconds INTEGER
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_update_logs_time ON update_logs(update_time)"
    )

    # ============ 数据更新日志明细表（每个品种的结果） ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS update_log_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id INTEGER NOT NULL,
            variety_code TEXT NOT NULL,
            variety_name TEXT,
            status TEXT NOT NULL,
            ai_direction TEXT,
            ai_confidence INTEGER,
            price REAL,
            price_change REAL,
            error_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (log_id) REFERENCES update_logs(id)
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_update_log_details_log_id ON update_log_details(log_id)"
    )

    # ============ 基差数据表（保留用于基差分析） ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spread_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variety_code TEXT NOT NULL,
            date TEXT NOT NULL,
            main_price REAL,
            secondary_price REAL,
            spread REAL,
            annualized_roll_yield REAL,
            spot_price REAL,
            basis REAL,
            basis_rate REAL,
            basis_percentile REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_spread_variety_date ON spread_data(variety_code, date)"
    )

    # ============ 免费搜索限流表 ============
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS free_search_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            search_time TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_free_search_ip ON free_search_log(ip_address)"
    )

    # 插入默认管理员账号
    cursor.execute("""
        INSERT OR IGNORE INTO users (username, password, phone, role, member_type, status, created_at, updated_at)
        VALUES ('admin', 'admin123', NULL, 'admin', 'admin', 1, datetime('now'), datetime('now'))
    """)

    conn.commit()
    conn.close()
    print("✅ 数据库已初始化（精简版）")


def init_news_module_files():
    """初始化新闻模块所需的文件"""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        return False

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    data_layer_dir = os.path.join(os.path.dirname(__file__), "data_layer")
    os.makedirs(data_layer_dir, exist_ok=True)

    for filename, default in [
        (
            "policy_cache.yaml",
            {name: "中性" for name in config.get("varieties", {}).keys()},
        ),
        ("news_cache.json", {}),
        ("sentiment_cache.json", {}),
    ]:
        filepath = os.path.join(data_layer_dir, filename)
        if not os.path.exists(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                if filename.endswith(".yaml"):
                    yaml.dump(default, f, allow_unicode=True, default_flow_style=False)
                else:
                    json.dump(default, f, ensure_ascii=False, indent=2)
            print(f"✅ 创建: {filepath}")
        else:
            print(f"✅ 已存在: {filepath}")

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("期货分析系统初始化（精简版）")
    print("=" * 60)

    print("\n📁 初始化新闻模块文件...")
    init_news_module_files()

    print("\n🗄️ 初始化数据库...")
    init_database()

    print("\n" + "=" * 60)
    print("✅ 初始化完成！")
    print("=" * 60)
