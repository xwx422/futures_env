import re
# coding: utf-8
#!/usr/bin/env python3
# AI期货分析助手 - 主应用入口（会员+管理员体系升级版）

import os
import json
import sqlite3
import logging
import hashlib
import uuid
import yaml
from datetime import datetime, timedelta
from functools import lru_cache, wraps
from typing import Dict, List, Optional, Tuple

# 加载 .env 文件中的环境变量
try:
    from dotenv import load_dotenv

    load_dotenv()
    print("[Init] .env 文件已加载")
except ImportError:
    print("[Init] python-dotenv 未安装，跳过 .env 加载")

from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    url_for,
    jsonify,
    flash,
)
from logging_config import setup_logging

# 设置日志
setup_logging()
logger = logging.getLogger(__name__)

# 导入路由蓝图
from routes.update_routes import register_update_routes
from routes.task_routes import task_bp
from routes.market_data_routes import market_data_bp
from routes.monitor_routes import monitor_bp
from routes.adaptive_params_routes import adaptive_bp
from routes.divergence_routes import divergence_bp
from routes.signal_routes import signal_bp
from routes.price_routes import register_price_routes
from config.cache_config import init_cache

# 导入Celery任务（注册任务到Celery）
import tasks.analysis_tasks

# 导入内容生成服务
from execution_layer.risk_manager import calculate_position_for_variety

# 尝试导入海龟策略模块（另一个子代理会添加）
try:
    from analysis_layer import turtle_strategy as turtle_strategy_module
except ImportError:
    turtle_strategy_module = None

# 导入设备检测工具
try:
    from utils.device_detector import (
        is_mobile_device,
        should_use_mobile_template,
        get_template_path,
        toggle_view_mode as device_toggle_view_mode,
        get_device_info,
    )
except ImportError:
    # 如果导入失败，提供默认实现
    def is_mobile_device(user_agent=None):
        return False

    def should_use_mobile_template(user_agent=None):
        return False

    def get_template_path(template_name, user_agent=None):
        return template_name

    def device_toggle_view_mode():
        return "pc"

    def get_device_info(user_agent=None):
        return {"device_type": "pc", "is_mobile": False}


# 创建Flask应用实例
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-here")


# Favicon 路由
@app.route("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.ico")


# 启动时自动确保数据库结构完整（安全添加缺失列，不影响现有数据）
try:
    from init_db import init_database

    init_database()
except Exception as _db_init_err:
    import logging as _logging

    _logging.getLogger(__name__).warning(f"数据库自动迁移跳过: {_db_init_err}")

# 初始化缓存
cache = init_cache(app)


# 全局上下文处理器 - 为所有模板提供通用变量
@app.context_processor
def inject_global_vars():
    """为所有模板注入全局变量"""
    context = {}
    return context


def get_server_time() -> str:
    """
    获取服务器本地时间，格式化为字符串
    用于替代 SQLite 的 CURRENT_TIMESTAMP（UTC时间）
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def calculate_usage_time(created_at_str: str) -> str:
    """
    计算从创建时间到当前时间的使用时长
    显示格式：X天Y小时
    """
    try:
        # 解析创建时间
        created_at = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()

        # 计算时间差
        diff = now - created_at

        # 计算天数和小时数
        days = diff.days
        hours = diff.seconds // 3600

        if days > 0:
            return f"{days}天{hours}小时"
        else:
            return f"{hours}小时"
    except Exception:
        return "未知"


def _init_free_search_table():
    """初始化免费搜索限流日志表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS free_search_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT,
                session_id TEXT,
                variety_code TEXT,
                search_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_free_search_time 
            ON free_search_logs(ip_address, session_id, search_time)
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"初始化 free_search_logs 表失败: {e}")


def _get_or_create_search_session_id() -> str:
    """获取或创建搜索会话ID（用于未登录用户限流）"""
    if "search_session_id" not in session:
        session["search_session_id"] = uuid.uuid4().hex
    return session["search_session_id"]


def _check_free_search_limit(ip_address: str, session_id: str) -> tuple:
    """
    检查未登录用户免费搜索次数

    Returns:
        (是否允许, 今日已用次数)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        today_start = datetime.now().strftime("%Y-%m-%d 00:00:00")

        cursor.execute(
            """
            SELECT COUNT(*) as count FROM free_search_logs
            WHERE search_time >= ? AND (ip_address = ? OR session_id = ?)
        """,
            (today_start, ip_address, session_id),
        )
        used = cursor.fetchone()["count"]
        conn.close()
        return used < 3, used
    except Exception as e:
        logger.error(f"检查免费搜索限流失败: {e}")
        return True, 0


def _record_free_search(ip_address: str, session_id: str, variety_code: str):
    """记录一次免费搜索"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO free_search_logs (ip_address, session_id, variety_code, search_time)
            VALUES (?, ?, ?, ?)
        """,
            (ip_address, session_id, variety_code, get_server_time()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"记录免费搜索失败: {e}")


def _resolve_search_variety(query: str) -> tuple:
    """
    解析用户搜索输入为品种代码和名称

    Returns:
        (variety_code, variety_name) 或 (None, None)
    """
    query = query.strip().upper()
    if not query:
        return None, None

    # 直接匹配代码（如 RB）
    from data_layer.fetch_market import EXCHANGE_MAP, VARIETY_NAME_MAP

    if query in EXCHANGE_MAP:
        return query, VARIETY_NAME_MAP.get(query, query)

    # 中文名匹配
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        varieties = config.get("varieties", {})
        for name, info in varieties.items():
            if name == query or name.upper() == query:
                code = info.get("code", "")
                return code, name
            if info.get("code", "") == query:
                return code, name
    except Exception:
        pass

    return None, None


# 添加全局模板函数和过滤器
app.jinja_env.globals.update(min=min, max=max, now_dt=datetime.now)
app.jinja_env.filters["usage_time"] = calculate_usage_time

# 注册蓝图
register_update_routes(app)
register_price_routes(app)
app.register_blueprint(task_bp)
app.register_blueprint(market_data_bp)
app.register_blueprint(monitor_bp)
app.register_blueprint(adaptive_bp)
app.register_blueprint(divergence_bp)
app.register_blueprint(signal_bp)


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect("futures_analysis.db")
    conn.row_factory = sqlite3.Row
    return conn


@lru_cache(maxsize=1)
def _load_sector_map() -> Dict[str, str]:
    """从 config.yaml 加载品种代码到板块映射"""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    sector_map: Dict[str, str] = {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        for info in (config.get("varieties") or {}).values():
            code = (info or {}).get("code")
            sector = (info or {}).get("sector")
            if code and sector:
                sector_map[code] = sector
    except Exception as e:
        logger.warning(f"加载板块映射失败: {e}")
    return sector_map


def _normalize_sector(variety: Dict) -> None:
    """修正板块字段，避免展示“未知”标签"""
    current_sector = (variety.get("sector") or "").strip()
    if current_sector and current_sector != "未知":
        return
    mapped_sector = _load_sector_map().get(variety.get("variety_code", ""))
    variety["sector"] = mapped_sector or "其他"


# 初始化免费搜索限流日志表（必须在 get_db_connection 定义之后）
_init_free_search_table()


def parse_json_fields(row: Dict) -> Dict:
    """解析行中的JSON字段"""
    json_fields = [
        "news_items",
        "tech_indicators",
        "timeframe_analysis",
        "volume_analysis",
        "trend_info",
        "adx_info",
        "support_resistance",
        "fund_analysis",
        "rollover_info",
        "position_analysis",
        "turtle_channel",
        "trade_plan",
    ]
    for field in json_fields:
        if row.get(field) and isinstance(row[field], str):
            try:
                row[field] = json.loads(row[field])
            except:
                row[field] = {}
    return row


# ============ 用户认证相关函数 ============


def get_user_by_username(username: str) -> Optional[Dict]:
    """根据用户名获取用户信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_client_ip() -> str:
    """
    获取客户端真实IP地址
    优先从代理头获取，支持X-Forwarded-For和X-Real-IP
    """
    # 尝试从X-Forwarded-For获取（多层代理）
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # 取第一个IP（客户端真实IP）
        ip = forwarded_for.split(",")[0].strip()
        if ip:
            return ip

    # 尝试从X-Real-IP获取（单层代理，如Nginx）
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # 尝试从X-Forwarded获取（旧版代理）
    forwarded = request.headers.get("X-Forwarded")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # 最后使用remote_addr
    return request.remote_addr or "127.0.0.1"


def record_login_log(username: str, role: str, status: str, fail_reason: str = None):
    """记录登录日志"""
    conn = get_db_connection()
    cursor = conn.cursor()
    from datetime import datetime

    cursor.execute(
        """
        INSERT INTO login_logs (username, role, login_status, login_ip, fail_reason, user_agent, login_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            username,
            role,
            status,
            get_client_ip(),
            fail_reason,
            request.headers.get("User-Agent", "")[:200],
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    conn.close()


def record_variety_view_log(username: str, variety_code: str, variety_name: str):
    """记录期货查看日志"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO variety_view_logs (username, variety_code, variety_name)
        VALUES (?, ?, ?)
    """,
        (username, variety_code, variety_name),
    )
    conn.commit()
    conn.close()


# ============ 登录验证装饰器 ============


def login_required(f):
    """登录验证装饰器"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """管理员权限验证装饰器"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("无权访问该页面", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


# ============ 路由定义 ============


@app.route("/api/notice")
def get_notice():
    """获取通知公告内容"""
    try:
        notice_path = os.path.join(os.path.dirname(__file__), "doc", "notice.md")
        if os.path.exists(notice_path):
            with open(notice_path, "r", encoding="utf-8") as f:
                content = f.read()
            return jsonify({"success": True, "content": content})
        else:
            return jsonify({"success": False, "error": "通知文件不存在"})
    except Exception as e:
        logger.error(f"读取通知文件失败: {e}")
        return jsonify({"success": False, "error": "读取通知失败"})


@app.route("/")
def index():
    """官网首页"""
    return render_template("index.html")


@app.route("/product")
def product():
    """产品介绍页面"""
    return render_template("product.html")


@app.route("/changelog")
def changelog():
    """升级日志页面"""
    return render_template("changelog.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """登录页面"""

    # 如果已登录，直接跳转到首页
    if "username" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        # 查询用户信息
        user = get_user_by_username(username)

        if not user:
            record_login_log(username, "unknown", "failed", "用户不存在")
            return render_template("login.html", error="用户名或密码错误")

        # 检查账号状态
        if user["status"] == 0:
            record_login_log(username, user["role"], "failed", "账号已禁用")
            return render_template("login.html", error="账号已禁用，无法登录")

        # 验证密码
        if user["password"] != password:
            record_login_log(username, user["role"], "failed", "密码错误")
            return render_template("login.html", error="用户名或密码错误")

        # 登录成功
        session["username"] = username
        session["role"] = user["role"]
        record_login_log(username, user["role"], "success")

        # 每天登录送3次分析次数（不累计）
        today = datetime.now().strftime("%Y-%m-%d")
        if user.get("last_analysis_date") != today:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET daily_analysis_count = 3, last_analysis_date = ? WHERE username = ?",
                (today, username),
            )
            conn.commit()
            conn.close()

        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    """退出登录"""
    session.pop("username", None)
    session.pop("role", None)
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    """注册页面 - 用户自助注册"""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        phone = request.form.get("phone", "").strip()
        register_code = request.form.get("register_code", "").strip()

        # 验证注册码
        valid_codes = ["0351", "1418", "9527"]
        if not register_code or register_code not in valid_codes:
            return render_template(
                "register.html",
                error="注册码无效，请关注公众号回复【期货分析助手】获取注册码",
            )

        # 验证字段
        if not username or not password:
            return render_template("register.html", error="请填写账号和密码")

        # 验证手机号必填
        if not phone:
            return render_template("register.html", error="请填写联系电话")

        # 验证手机号格式（11位，1开头）
        import re

        if not re.match(r"^1[3-9][0-9]{9}$", phone):
            return render_template(
                "register.html", error="手机号格式不正确，请输入正确的11位手机号码"
            )

        # 验证账号长度
        if len(username) < 4 or len(username) > 20:
            return render_template("register.html", error="账号长度需为4-20位")

        # 验证账号格式：必须以字母开头，仅允许字母、数字、下划线、连字符
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]{3,19}$", username):
            return render_template(
                "register.html",
                error="账号格式不正确，请使用字母、数字、下划线或连字符，且必须以字母开头",
            )

        # 验证密码长度
        if len(password) < 6:
            return render_template("register.html", error="密码长度不能少于6位")

        # 验证密码是否一致
        if password != confirm_password:
            return render_template("register.html", error="两次输入的密码不一致")

        # 检查账号和手机号是否已存在
        conn = get_db_connection()
        cursor = conn.cursor()

        # 检查账号是否已存在
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            return render_template(
                "register.html", error="账号已被注册，请更换其他账号"
            )

        # 检查手机号是否已存在
        cursor.execute("SELECT id FROM users WHERE phone = ?", (phone,))
        if cursor.fetchone():
            conn.close()
            return render_template(
                "register.html", error="该手机号已被注册，请更换其他手机号"
            )

        # 创建新用户
        try:
            current_time = get_server_time()

            cursor.execute(
                """
                INSERT INTO users (username, password, phone, role, status, created_at, updated_at)
                VALUES (?, ?, ?, 'member', 1, ?, ?)
            """,
                (username, password, phone, current_time, current_time),
            )
            conn.commit()
            conn.close()

            # 记录注册日志
            logger.info(f"新用户注册: {username}")

            # 注册成功，跳转到登录页面
            flash("注册成功！请登录", "success")
            return redirect(url_for("login"))

        except Exception as e:
            conn.close()
            logger.error(f"注册失败: {e}")
            return render_template("register.html", error="注册失败，请稍后重试")

    return render_template("register.html")


@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    """修改密码"""
    if request.method == "POST":
        old_password = request.form.get("old_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        # 验证参数
        if not old_password or not new_password or not confirm_password:
            return render_template("change_password.html", error="请填写所有字段")

        if new_password != confirm_password:
            return render_template(
                "change_password.html", error="两次输入的新密码不一致"
            )

        if len(new_password) < 6:
            return render_template(
                "change_password.html", error="新密码长度不能少于6位"
            )

        # 验证旧密码
        user = get_user_by_username(session["username"])
        if not user or user["password"] != old_password:
            return render_template("change_password.html", error="原密码错误")

        # 更新密码
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE users SET password = ?, updated_at = ? 
            WHERE username = ?
        """,
            (new_password, get_server_time(), session["username"]),
        )
        conn.commit()
        conn.close()

        flash("密码修改成功，请重新登录", "success")
        return redirect(url_for("logout"))

    return render_template("change_password.html")


@app.route("/search", methods=["GET", "POST"])
def search_variety():
    """
    品种搜索（支持未登录用户免费体验）
    查询 analysis_records 最新数据，不重新执行 AI 分析
    """
    query = (
        request.args.get("q", "").strip()
        if request.method == "GET"
        else request.form.get("q", "").strip()
    )

    if not query:
        if "username" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("index"))

    variety_code, variety_name = _resolve_search_variety(query)

    if not variety_code:
        flash(
            f"未找到品种：{query}，请尝试输入代码（如 RB）或中文名（如 螺纹钢）",
            "error",
        )
        if "username" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("index"))

    # 已登录用户：直接跳转到详情页
    if "username" in session:
        return redirect(url_for("variety_detail", variety_code=variety_code))

    # 未登录用户：直接查询并展示简化结果（取消次数限制，作为引流手段）
    client_ip = get_client_ip()
    session_id = _get_or_create_search_session_id()

    # 查询最新分析数据
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM analysis_records
        WHERE variety_code = ?
        ORDER BY run_time DESC
        LIMIT 1
    """,
        (variety_code,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        flash(f"{variety_name} 今日暂未分析，请稍后查看", "error")
        return redirect(url_for("index"))

    # 记录搜索日志（用于数据分析）
    _record_free_search(client_ip, session_id, variety_code)

    variety = parse_json_fields(dict(row))
    variety["suitability"] = get_investor_suitability(variety)
    variety = _enrich_variety_for_display(variety)

    return render_template(
        "search_result.html",
        variety=variety,
    )


# ============ 数据展示页面（原 index 重命名） ============


@app.route("/dashboard")
@login_required
def dashboard():
    """数据展示主页面（原 index 功能）"""
    varieties, latest_time, stats = get_latest_analysis()

    # 为每个品种添加投资者适合度分析
    for v in varieties:
        v["suitability"] = get_investor_suitability(v)

    # 信号追踪统计
    tracking_stats = get_signal_tracking_stats(varieties)

    return render_template(
        "dashboard.html",
        varieties=varieties,
        latest_update_time=latest_time if latest_time else "暂无数据",
        stats=stats,
        tracking_stats=tracking_stats,
    )


@app.route("/user-profile")
@login_required
def user_profile():
    """用户个人资料页"""
    username = session.get("username")
    role = session.get("role")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取用户信息
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()

    # 获取登录日志（最近10条）
    cursor.execute(
        """
        SELECT * FROM login_logs
        WHERE username = ?
        ORDER BY login_time DESC
        LIMIT 10
    """,
        (username,),
    )
    login_logs = [dict(row) for row in cursor.fetchall()]

    # 获取查看日志（最近20条）
    cursor.execute(
        """
        SELECT * FROM variety_view_logs
        WHERE username = ?
        ORDER BY view_time DESC
        LIMIT 20
    """,
        (username,),
    )
    view_logs = [dict(row) for row in cursor.fetchall()]

    conn.close()

    if user:
        user_dict = dict(user)
    else:
        user_dict = {"username": username, "role": role}

    return render_template(
        "user_profile.html",
        user=user_dict,
        login_logs=login_logs,
        view_logs=view_logs,
    )


@app.route("/variety/<variety_code>")
@login_required
def variety_detail(variety_code):
    """品种详情页"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM analysis_records
        WHERE variety_code = ?
        ORDER BY run_time DESC
        LIMIT 1
        """,
        (variety_code,),
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        return redirect(url_for("dashboard"))

    variety = parse_json_fields(dict(row))

    # 修复数据结构
    if "fund_data" not in variety:
        variety["fund_data"] = {}

    if "price_percentile" in variety and variety["price_percentile"] is not None:
        variety["fund_data"]["price_percentile"] = variety["price_percentile"]
    elif "volume_analysis" in variety and isinstance(variety["volume_analysis"], dict):
        volume_analysis = variety["volume_analysis"]
        if "price_percentile" in volume_analysis:
            variety["fund_data"]["price_percentile"] = volume_analysis[
                "price_percentile"
            ]

    if "oi_change" not in variety or variety["oi_change"] is None:
        variety["oi_change"] = 0

    variety["suitability"] = get_investor_suitability(variety)
    vc = variety.get("variety_code", variety_code)

    # 读取基差 + 价差数据
    latest_basis = {}
    try:
        cursor.execute(
            """
            SELECT variety_code, spot_price, basis, basis_rate, basis_percentile,
                   main_price, secondary_price, spread, annualized_roll_yield
            FROM spread_data
            WHERE date = (SELECT MAX(date) FROM spread_data)
              AND variety_code = ?
            """,
            (vc,),
        )
        r = cursor.fetchone()
        if r:
            if r["spot_price"] is not None:
                latest_basis[r["variety_code"]] = {
                    "spot_price": r["spot_price"],
                    "basis": r["basis"],
                    "basis_rate": r["basis_rate"],
                    "basis_percentile": r["basis_percentile"],
                }
            if r["main_price"] is not None:
                variety["spread_data"] = {
                    "main_price": r["main_price"],
                    "secondary_price": r["secondary_price"],
                    "spread": r["spread"],
                    "annualized_roll_yield": r["annualized_roll_yield"],
                }
    except Exception:
        pass

    conn.close()

    # 统一补充所有展示层字段
    variety = _enrich_variety_for_display(
        variety,
        latest_basis=latest_basis,
    )

    # 记录查看日志
    record_variety_view_log(
        session["username"], variety_code, variety.get("variety_name", variety_code)
    )

    return render_template("variety_detail.html", variety=variety)


# ============ 管理员后台功能 ============


@app.route("/xwx422")
@admin_required
def admin_dashboard():
    """管理员后台首页"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 统计信息
    stats = {}

    # ========== 1. 时间范围计算 ==========
    now = datetime.now()

    # ========== 2. 时间范围计算 ==========
    today = now.strftime("%Y-%m-%d")
    today_start = f"{today} 00:00:00"
    today_end = f"{today} 23:59:59"

    # 本周开始（周一）和结束
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end = (now + timedelta(days=6 - now.weekday())).strftime("%Y-%m-%d")

    # 本月开始和结束
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1)
    else:
        next_month = now.replace(month=now.month + 1, day=1)
    month_end = (next_month - timedelta(days=1)).strftime("%Y-%m-%d")

    # ========== 3. 登录统计 ==========
    # 今日登录次数
    cursor.execute(
        """
        SELECT COUNT(*) as total FROM login_logs 
        WHERE login_time >= ? AND login_time <= ? AND login_status = 'success'
    """,
        (today_start, today_end),
    )
    stats["today_logins"] = cursor.fetchone()["total"]

    # 本周登录次数
    cursor.execute(
        """
        SELECT COUNT(*) as total FROM login_logs 
        WHERE date(login_time) >= ? AND date(login_time) <= ? AND login_status = 'success'
    """,
        (week_start, week_end),
    )
    stats["weekly_logins"] = cursor.fetchone()["total"]

    # 本月登录次数
    cursor.execute(
        """
        SELECT COUNT(*) as total FROM login_logs 
        WHERE date(login_time) >= ? AND date(login_time) <= ? AND login_status = 'success'
    """,
        (month_start, month_end),
    )
    stats["monthly_logins"] = cursor.fetchone()["total"]

    # ========== 4. 其他统计 ==========
    # 今日查看统计
    cursor.execute(
        """
        SELECT COUNT(*) as total FROM variety_view_logs 
        WHERE view_time LIKE ?
    """,
        (f"{today}%",),
    )
    stats["today_views"] = cursor.fetchone()["total"]

    # ========== 5. 会员统计 ==========
    # 总会员数
    cursor.execute("SELECT COUNT(*) as total FROM users")
    stats["total_members"] = cursor.fetchone()["total"]

    # 管理员数
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'admin'")
    stats["admin_count"] = cursor.fetchone()["total"]

    # 普通会员数
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role = 'member'")
    stats["member_count"] = cursor.fetchone()["total"]

    # 今日注册数
    cursor.execute(
        "SELECT COUNT(*) as total FROM users WHERE date(created_at) = ?",
        (today,),
    )
    stats["today_registrations"] = cursor.fetchone()["total"]

    # 本周注册数
    cursor.execute(
        "SELECT COUNT(*) as total FROM users WHERE date(created_at) >= ? AND date(created_at) <= ?",
        (week_start, week_end),
    )
    stats["weekly_registrations"] = cursor.fetchone()["total"]

    # 本月注册数
    cursor.execute(
        "SELECT COUNT(*) as total FROM users WHERE date(created_at) >= ? AND date(created_at) <= ?",
        (month_start, month_end),
    )
    stats["monthly_registrations"] = cursor.fetchone()["total"]

    # 今日活跃用户数（去重）
    cursor.execute(
        """
        SELECT COUNT(DISTINCT username) as total FROM login_logs 
        WHERE login_time >= ? AND login_time <= ? AND login_status = 'success'
    """,
        (today_start, today_end),
    )
    stats["today_active_users"] = cursor.fetchone()["total"]

    # 未读反馈统计
    conn.close()

    return render_template("admin/dashboard.html", stats=stats)


# 会员管理
@app.route("/xwx422/members")
@admin_required
def admin_members():
    """用户管理页面（包含管理员和普通会员）"""
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "").strip()
    member_type = request.args.get("member_type", "").strip()
    per_page = 10
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    # 构建查询条件
    where_clauses = []
    params = []

    if search:
        where_clauses.append("username LIKE ?")
        params.append(f"%{search}%")

    if member_type:
        where_clauses.append("member_type = ?")
        params.append(member_type)

    where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    # 查询总数
    cursor.execute(f"SELECT COUNT(*) as total FROM users {where_clause}", params)
    total = cursor.fetchone()["total"]

    # 查询分页数据
    query_params = params + [per_page, offset]
    cursor.execute(
        f"""
        SELECT * FROM users {where_clause} 
        ORDER BY role DESC, created_at DESC 
        LIMIT ? OFFSET ?
    """,
        query_params,
    )
    members = [dict(row) for row in cursor.fetchall()]

    conn.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        "admin/members.html",
        members=members,
        now_dt=datetime.now(),
        page=page,
        total_pages=total_pages,
        total=total,
        search=search,
        member_type=member_type,
    )


@app.route("/xwx422/members/add", methods=["POST"])
@admin_required
def admin_add_member():
    """添加用户（支持普通会员或管理员）"""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    phone = request.form.get("phone", "").strip()
    role = request.form.get("role", "member").strip()

    if not username or not password:
        flash("用户名和密码不能为空", "error")
        return redirect(url_for("admin_members"))

    if len(password) < 6:
        flash("密码长度不能少于6位", "error")
        return redirect(url_for("admin_members"))

    # 验证角色有效性
    if role not in ["member", "admin"]:
        role = "member"

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        current_time = get_server_time()

        if role == "admin":
            # 管理员账号
            cursor.execute(
                """
                INSERT INTO users (username, password, phone, role, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
                (username, password, phone, role, current_time, current_time),
            )
        else:
            # 会员账号
            cursor.execute(
                """
                INSERT INTO users (username, password, phone, role, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
                (
                    username,
                    password,
                    phone,
                    role,
                    current_time,
                    current_time,
                ),
            )

        conn.commit()
        role_text = "管理员" if role == "admin" else "会员"
        flash(f"{role_text} {username} 创建成功", "success")
    except sqlite3.IntegrityError:
        flash("用户名已存在", "error")
    finally:
        conn.close()

    return redirect(url_for("admin_members"))


@app.route("/xwx422/members/<username>/reset_password", methods=["POST"])
@admin_required
def admin_reset_password(username):
    """重置会员密码"""
    new_password = request.form.get("new_password", "").strip()

    if not new_password or len(new_password) < 6:
        flash("密码长度不能少于6位", "error")
        return redirect(url_for("admin_members"))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE users SET password = ?, updated_at = ?
        WHERE username = ? AND role = 'member'
    """,
        (new_password, get_server_time(), username),
    )
    conn.commit()
    conn.close()

    flash(f"会员 {username} 的密码已重置", "success")
    return redirect(url_for("admin_members"))


@app.route("/xwx422/members/<username>/toggle_status", methods=["POST"])
@admin_required
def admin_toggle_status(username):
    """切换用户启用/禁用状态"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取当前状态（排除当前登录的管理员自己）
    cursor.execute("SELECT status, username FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("用户不存在", "error")
        return redirect(url_for("admin_members"))

    # 防止管理员禁用自己
    if row["username"] == session["username"]:
        conn.close()
        flash("不能禁用当前登录的账号", "error")
        return redirect(url_for("admin_members"))

    new_status = 0 if row["status"] == 1 else 1
    status_text = "启用" if new_status == 1 else "禁用"

    cursor.execute(
        """
        UPDATE users SET status = ?, updated_at = ?
        WHERE username = ?
    """,
        (new_status, get_server_time(), username),
    )
    conn.commit()
    conn.close()

    flash(f"用户 {username} 已{status_text}", "success")
    return redirect(url_for("admin_members"))


@app.route("/xwx422/members/<username>/change_role", methods=["POST"])
@admin_required
def admin_change_role(username):
    """切换用户角色（管理员/普通会员）"""
    new_role = request.form.get("role", "").strip()

    if new_role not in ["admin", "member"]:
        flash("无效的角色", "error")
        return redirect(url_for("admin_members"))

    conn = get_db_connection()
    cursor = conn.cursor()

    # 检查用户是否存在
    cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("用户不存在", "error")
        return redirect(url_for("admin_members"))

    # 防止管理员取消自己的管理员权限
    if row["username"] == session["username"] and new_role == "member":
        conn.close()
        flash("不能将自己的管理员权限取消", "error")
        return redirect(url_for("admin_members"))

    role_text = "管理员" if new_role == "admin" else "普通会员"

    cursor.execute(
        """
        UPDATE users SET role = ?, updated_at = ?
        WHERE username = ?
    """,
        (new_role, get_server_time(), username),
    )
    conn.commit()
    conn.close()

    flash(f"用户 {username} 已修改为{role_text}", "success")
    return redirect(url_for("admin_members"))


@app.route("/xwx422/members/batch", methods=["POST"])
@admin_required
def admin_batch_operation():
    """批量操作用户"""
    usernames = request.form.get("usernames", "").strip()
    action = request.form.get("action", "").strip()

    if not usernames:
        flash("未选择任何用户", "error")
        return redirect(url_for("admin_members"))

    username_list = [u.strip() for u in usernames.split(",") if u.strip()]
    if not username_list:
        flash("未选择任何用户", "error")
        return redirect(url_for("admin_members"))

    conn = get_db_connection()
    cursor = conn.cursor()
    current_time = get_server_time()

    success_count = 0
    failed_users = []

    for username in username_list:
        # 不能操作自己
        if username == session.get("username"):
            failed_users.append(f"{username}(不能操作自己)")
            continue

        try:
            if action == "disable":
                # 禁用用户
                cursor.execute(
                    "UPDATE users SET status = 0, updated_at = ? WHERE username = ?",
                    (current_time, username),
                )
                if cursor.rowcount > 0:
                    success_count += 1

            elif action == "enable":
                # 启用用户
                cursor.execute(
                    "UPDATE users SET status = 1, updated_at = ? WHERE username = ?",
                    (current_time, username),
                )
                if cursor.rowcount > 0:
                    success_count += 1

            elif action.startswith("reset_password:"):
                # 重置密码
                new_password = action.split(":", 1)[1]
                cursor.execute(
                    "UPDATE users SET password = ?, updated_at = ? WHERE username = ?",
                    (new_password, current_time, username),
                )
                if cursor.rowcount > 0:
                    success_count += 1

            elif action == "delete":
                # 删除用户（不能删除管理员）
                cursor.execute(
                    "DELETE FROM users WHERE username = ? AND role != 'admin'",
                    (username,),
                )
                if cursor.rowcount > 0:
                    success_count += 1
                else:
                    failed_users.append(f"{username}(管理员无法删除)")

        except Exception as e:
            failed_users.append(f"{username}({str(e)})")

    conn.commit()
    conn.close()

    # 构建提示消息
    messages = []
    if success_count > 0:
        action_names = {
            "disable": "禁用",
            "enable": "启用",
        }
        action_name = action_names.get(action.split(":")[0], "操作")
        messages.append(f"成功{action_name} {success_count} 个用户")

    if failed_users:
        messages.append(f"失败: {', '.join(failed_users)}")

    flash("; ".join(messages), "success" if success_count > 0 else "error")
    return redirect(url_for("admin_members"))


# 日志查看
@app.route("/xwx422/logs/login")
@admin_required
def admin_login_logs():
    """登录日志查看"""
    page = request.args.get("page", 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page

    username = request.args.get("username", "").strip()
    status = request.args.get("status", "").strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    # 构建查询条件
    where_clause = "WHERE 1=1"
    params = []
    if username:
        where_clause += " AND username LIKE ?"
        params.append(f"%{username}%")
    if status:
        where_clause += " AND login_status = ?"
        params.append(status)

    # 查询总数
    cursor.execute(f"SELECT COUNT(*) as total FROM login_logs {where_clause}", params)
    total = cursor.fetchone()["total"]

    # 查询数据
    cursor.execute(
        f"""
        SELECT * FROM login_logs {where_clause}
        ORDER BY login_time DESC LIMIT ? OFFSET ?
    """,
        params + [per_page, offset],
    )
    logs = [dict(row) for row in cursor.fetchall()]

    conn.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        "admin/login_logs.html",
        logs=logs,
        page=page,
        total_pages=total_pages,
        total=total,
        username=username,
        status=status,
    )


@app.route("/xwx422/logs/variety_views")
@admin_required
def admin_view_logs():
    """期货查看日志"""
    page = request.args.get("page", 1, type=int)
    per_page = 10
    offset = (page - 1) * per_page

    username = request.args.get("username", "").strip()
    variety_code = request.args.get("variety_code", "").strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    # 构建查询条件
    where_clause = "WHERE 1=1"
    params = []
    if username:
        where_clause += " AND username LIKE ?"
        params.append(f"%{username}%")
    if variety_code:
        where_clause += " AND variety_code LIKE ?"
        params.append(f"%{variety_code}%")

    # 查询总数
    cursor.execute(
        f"SELECT COUNT(*) as total FROM variety_view_logs {where_clause}", params
    )
    total = cursor.fetchone()["total"]

    # 查询数据
    cursor.execute(
        f"""
        SELECT * FROM variety_view_logs {where_clause}
        ORDER BY view_time DESC LIMIT ? OFFSET ?
    """,
        params + [per_page, offset],
    )
    logs = [dict(row) for row in cursor.fetchall()]

    # 获取品种列表用于筛选
    cursor.execute(
        "SELECT DISTINCT variety_code, variety_name FROM variety_view_logs ORDER BY variety_code"
    )
    varieties = [dict(row) for row in cursor.fetchall()]

    conn.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        "admin/view_logs.html",
        logs=logs,
        page=page,
        total_pages=total_pages,
        total=total,
        varieties=varieties,
        username=username,
        variety_code=variety_code,
    )


# 数据统计分析
@app.route("/xwx422/analysis")
@admin_required
def admin_analysis():
    """数据统计分析"""
    conn = get_db_connection()
    cursor = conn.cursor()

    analysis = {}
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # 1. 品种更新趋势 - 只显示最近7天的数据，超出的归为"更早"
    cursor.execute(
        """
        SELECT 
            DATE(run_time) as date,
            COUNT(DISTINCT variety_code) as variety_count
        FROM analysis_records
        WHERE run_time >= ?
        GROUP BY DATE(run_time)
        ORDER BY date DESC
        LIMIT 7
    """,
        (seven_days_ago,),
    )
    update_trend_recent = [dict(row) for row in cursor.fetchall()]

    # 计算更早时间段的汇总数据
    cursor.execute(
        """
        SELECT 
            COUNT(DISTINCT DATE(run_time)) as days,
            COUNT(DISTINCT variety_code) as total_varieties
        FROM analysis_records
        WHERE run_time >= ? AND run_time < ?
    """,
        (thirty_days_ago, seven_days_ago),
    )
    earlier_data = cursor.fetchone()

    analysis["update_trend"] = {
        "recent": update_trend_recent,
        "earlier_days": earlier_data["days"] if earlier_data else 0,
        "earlier_varieties": earlier_data["total_varieties"] if earlier_data else 0,
    }

    # 2. 品种查看热度排行（最近30天）
    cursor.execute(
        """
        SELECT 
            variety_code,
            variety_name,
            COUNT(*) as view_count
        FROM variety_view_logs
        WHERE view_time >= ?
        GROUP BY variety_code, variety_name
        ORDER BY view_count DESC
        LIMIT 10
    """,
        (thirty_days_ago,),
    )
    analysis["hot_varieties"] = [dict(row) for row in cursor.fetchall()]

    # 3. 活跃用户排行（最近30天）
    cursor.execute(
        """
        SELECT 
            username,
            COUNT(*) as view_count
        FROM variety_view_logs
        WHERE view_time >= ?
        GROUP BY username
        ORDER BY view_count DESC
        LIMIT 10
    """,
        (thirty_days_ago,),
    )
    analysis["active_users"] = [dict(row) for row in cursor.fetchall()]

    # 4. 登录统计 - 简化为汇总数据
    cursor.execute(
        """
        SELECT 
            SUM(CASE WHEN login_status = 'success' THEN 1 ELSE 0 END) as total_success,
            SUM(CASE WHEN login_status = 'failed' THEN 1 ELSE 0 END) as total_failed,
            COUNT(*) as total_count
        FROM login_logs
        WHERE login_time >= ?
    """,
        (thirty_days_ago,),
    )
    login_summary = cursor.fetchone()

    # 获取最近7天的详细数据用于趋势展示
    cursor.execute(
        """
        SELECT 
            DATE(login_time) as date,
            SUM(CASE WHEN login_status = 'success' THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN login_status = 'failed' THEN 1 ELSE 0 END) as failed_count,
            COUNT(*) as total_count
        FROM login_logs
        WHERE login_time >= ?
        GROUP BY DATE(login_time)
        ORDER BY date DESC
        LIMIT 7
    """,
        (seven_days_ago,),
    )
    login_trend = [dict(row) for row in cursor.fetchall()]

    analysis["login_stats"] = {
        "summary": {
            "total": login_summary["total_count"] if login_summary else 0,
            "success": login_summary["total_success"] if login_summary else 0,
            "failed": login_summary["total_failed"] if login_summary else 0,
        },
        "trend": login_trend,
    }

    # 5. 胜率分布统计
    cursor.execute("""
        SELECT 
            CASE 
                WHEN fund_probability >= 70 THEN '高胜率(≥70%)'
                WHEN fund_probability >= 40 THEN '中等胜率(40-70%)'
                ELSE '低胜率(<40%)'
            END as probability_level,
            COUNT(*) as count
        FROM analysis_records
        WHERE run_time = (SELECT MAX(run_time) FROM analysis_records)
        GROUP BY probability_level
        ORDER BY MIN(fund_probability) DESC
    """)
    analysis["probability_distribution"] = [dict(row) for row in cursor.fetchall()]

    # 6. 板块统计
    cursor.execute("""
        SELECT 
            sector,
            COUNT(*) as count,
            AVG(fund_probability) as avg_probability
        FROM analysis_records
        WHERE run_time = (SELECT MAX(run_time) FROM analysis_records)
        GROUP BY sector
        ORDER BY count DESC
    """)
    analysis["sector_stats"] = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template("admin/analysis.html", analysis=analysis)


# 数据查看页面
@app.route("/xwx422/data_view")
@admin_required
def admin_data_view():
    """数据查看页面 - 查看数据库中所有期货数据，支持分页和分组"""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    group_by = request.args.get(
        "group_by", "all"
    )  # all: 全部, latest: 最新记录, variety: 按品种
    variety_code = request.args.get("variety_code", "").strip()
    trade_direction = request.args.get("direction", "").strip()

    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    # 构建查询条件
    where_clause = "WHERE 1=1"
    params = []

    if variety_code:
        where_clause += " AND variety_code LIKE ?"
        params.append(f"%{variety_code}%")

    if trade_direction:
        where_clause += " AND trade_direction = ?"
        params.append(trade_direction)

    # 获取所有品种列表（用于筛选）
    cursor.execute("""
        SELECT DISTINCT variety_code, variety_name 
        FROM analysis_records 
        ORDER BY variety_code
    """)
    varieties = [dict(row) for row in cursor.fetchall()]

    # 获取总数
    if group_by == "latest":
        # 只显示每个品种的最新记录
        cursor.execute("""
            SELECT COUNT(*) as total FROM analysis_records a1
            WHERE run_time = (
                SELECT MAX(run_time) FROM analysis_records a2 
                WHERE a2.variety_code = a1.variety_code
            )
        """)
    else:
        cursor.execute(
            f"SELECT COUNT(*) as total FROM analysis_records {where_clause}", params
        )

    total = cursor.fetchone()["total"]

    # 查询数据
    if group_by == "latest":
        # 只显示每个品种的最新记录
        cursor.execute(
            """
            SELECT a1.* FROM analysis_records a1
            WHERE run_time = (
                SELECT MAX(run_time) FROM analysis_records a2 
                WHERE a2.variety_code = a1.variety_code
            )
            ORDER BY a1.variety_code ASC
            LIMIT ? OFFSET ?
        """,
            (per_page, offset),
        )
    else:
        cursor.execute(
            f"""
            SELECT * FROM analysis_records 
            {where_clause}
            ORDER BY run_time DESC, variety_code ASC
            LIMIT ? OFFSET ?
        """,
            params + [per_page, offset],
        )

    records = [dict(row) for row in cursor.fetchall()]

    conn.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        "admin/data_view.html",
        records=records,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total=total,
        varieties=varieties,
        variety_code=variety_code,
        trade_direction=trade_direction,
        group_by=group_by,
    )


# 管理后台品种详情页
@app.route("/xwx422/variety/<variety_code>")
@admin_required
def admin_variety_detail(variety_code):
    """管理后台品种详情页"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM analysis_records
        WHERE variety_code = ?
        ORDER BY run_time DESC
        LIMIT 1
    """,
        (variety_code,),
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        return redirect(url_for("admin_dashboard"))

    variety = parse_json_fields(dict(row))

    # 修复数据结构
    if "fund_data" not in variety:
        variety["fund_data"] = {}

    if "price_percentile" in variety and variety["price_percentile"] is not None:
        variety["fund_data"]["price_percentile"] = variety["price_percentile"]
    elif "volume_analysis" in variety and isinstance(variety["volume_analysis"], dict):
        volume_analysis = variety["volume_analysis"]
        if "price_percentile" in volume_analysis:
            variety["fund_data"]["price_percentile"] = volume_analysis[
                "price_percentile"
            ]

    if "oi_change" not in variety or variety["oi_change"] is None:
        variety["oi_change"] = 0

    variety["suitability"] = get_investor_suitability(variety)

    # 统一补充所有展示层字段
    variety = _enrich_variety_for_display(variety)

    conn.close()

    return render_template("admin/variety_detail.html", variety=variety)


# 数据更新页面
@app.route("/xwx422/update")
@admin_required
def admin_update_data():
    """数据更新管理页面"""
    # 获取最新的更新记录
    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取最近5条更新日志
    cursor.execute("""
        SELECT * FROM update_logs
        ORDER BY update_time DESC
        LIMIT 5
    """)
    recent_logs = [dict(row) for row in cursor.fetchall()]

    # 获取统计数据
    cursor.execute("SELECT COUNT(*) FROM analysis_records")
    total_records = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT variety_code) FROM analysis_records")
    total_varieties = cursor.fetchone()[0]

    cursor.execute("""
        SELECT run_time FROM analysis_records
        ORDER BY run_time DESC LIMIT 1
    """)
    latest = cursor.fetchone()
    latest_time = latest[0] if latest else "暂无数据"

    cursor.execute("""
        SELECT MIN(run_time), MAX(run_time) FROM analysis_records
    """)
    date_range_row = cursor.fetchone()
    date_range = f"{date_range_row[0] or '-'} ~ {date_range_row[1] or '-'}"

    conn.close()

    stats = {
        "total_records": total_records,
        "total_varieties": total_varieties,
        "latest_update": latest_time,
        "date_range": date_range,
    }

    return render_template(
        "admin/update_data.html", recent_logs=recent_logs, stats=stats
    )


# 数据提取页面
# 行情简报页面
# 意见反馈管理
def generate_variety_text_report(variety: Dict) -> str:
    """
    生成品种的文本分析报告，用于文案编写
    """
    lines = []

    # 基本信息
    lines.append(
        f"【{variety.get('variety_name', '未知品种')} ({variety.get('variety_code', '')})】"
    )
    lines.append(f"主力合约：{variety.get('main_contract_clean', 'N/A')}")
    lines.append(f"更新时间：{variety.get('run_time', 'N/A')}")
    lines.append("")

    # 核心交易建议
    lines.append("=" * 40)
    lines.append("【核心交易建议】")
    lines.append(f"交易方向：{variety.get('trade_direction', '观望')}")
    lines.append(f"交易周期：{variety.get('trade_cycle', '中线')}")
    lines.append(f"综合胜率：{variety.get('fund_probability', 0)}%")
    lines.append(f"多周期共振：{variety.get('timeframe_confluence', 'N/A')}")
    lines.append("")

    # 交易计划
    lines.append("=" * 40)
    lines.append("【交易计划】")
    entry_price = variety.get("entry_price")
    stop_loss = variety.get("stop_loss")
    target_price = variety.get("target_price")

    if entry_price:
        lines.append(f"建议入场：{entry_price:.0f}")
    if stop_loss:
        lines.append(f"止损位：{stop_loss:.0f}")
    if target_price:
        lines.append(f"目标位：{target_price:.0f}")
    if variety.get("stop_type"):
        lines.append(f"止损类型：{variety['stop_type']}")
    if variety.get("risk_reward_ratio"):
        lines.append(f"风险回报比：{variety['risk_reward_ratio']:.1f}:1")
    if variety.get("composite_score"):
        lines.append(f"综合评分：{variety['composite_score']}")
    lines.append("")

    # 趋势分析
    lines.append("=" * 40)
    lines.append("【趋势分析】")
    if variety.get("trend_info"):
        trend = variety["trend_info"]
        lines.append(f"趋势方向：{trend.get('direction', 'N/A')}")
        lines.append(f"趋势评分：{trend.get('trend_score', 'N/A')}/100")
        if trend.get("ma_short") and trend.get("ma_long"):
            lines.append(
                f"均线排列：MA10 {trend['ma_short']:.0f} / MA30 {trend['ma_long']:.0f}"
            )
        if trend.get("is_golden_cross"):
            lines.append("⚠️ 刚刚形成金叉信号")
        elif trend.get("is_dead_cross"):
            lines.append("⚠️ 刚刚形成死叉信号")

    if variety.get("adx_info"):
        adx = variety["adx_info"]
        lines.append(
            f"趋势强度(ADX)：{adx.get('trend_strength', 'N/A')} ({adx.get('adx', 0):.1f})"
        )
    lines.append("")

    # 多周期分析
    lines.append("=" * 40)
    lines.append("【多时间周期分析】")
    if variety.get("timeframe_analysis"):
        for tf_name, tf_data in variety["timeframe_analysis"].items():
            direction = tf_data.get("direction", "N/A")
            trend = tf_data.get("trend", "N/A")
            rsi = tf_data.get("rsi")
            rsi_signal = tf_data.get("rsi_signal", "")
            volatility = tf_data.get("volatility")

            line = f"{tf_name.upper()}：{direction} | {trend}"
            if rsi is not None:
                line += f" | RSI {rsi:.0f}({rsi_signal})"
            if volatility is not None:
                line += f" | 波动{volatility * 100:.2f}%"
            lines.append(line)
    lines.append("")

    # 压力支撑
    lines.append("=" * 40)
    lines.append("【压力支撑分析】")
    if variety.get("support_resistance"):
        sr = variety["support_resistance"]
        current_price = sr.get("current_price")
        if current_price:
            lines.append(f"当前价格：{current_price:.0f}")

        if sr.get("resistances"):
            lines.append("🔴 阻力位：")
            for r in sr["resistances"]:
                if current_price:
                    pct = (r - current_price) / current_price * 100
                    lines.append(f"   {r:.0f} (+{pct:.1f}%)")
                else:
                    lines.append(f"   {r:.0f}")

        if sr.get("supports"):
            lines.append("🟢 支撑位：")
            for s in sr["supports"]:
                if current_price:
                    pct = (current_price - s) / current_price * 100
                    lines.append(f"   {s:.0f} (-{pct:.1f}%)")
                else:
                    lines.append(f"   {s:.0f}")

        if sr.get("pivot_points"):
            pivot = sr["pivot_points"]
            lines.append(f"枢轴点：{pivot.get('pivot', 0):.0f}")
    lines.append("")

    # 资金分析
    lines.append("=" * 40)
    lines.append("【主力资金分析】")
    if variety.get("fund_analysis") and variety["fund_analysis"].get("oi_analysis"):
        oi = variety["fund_analysis"]["oi_analysis"]
        lines.append(f"持仓信号：{oi.get('signal', 'N/A')}")
        lines.append(f"持仓变化：{oi.get('oi_change_pct', 0):.1f}%")
        lines.append(f"价格变化(5日)：{oi.get('price_change_pct', 0):.1f}%")
        lines.append(f"持仓强度：{oi.get('strength', 0):.0f}")
        if oi.get("interpretation"):
            lines.append(f"解读：{oi['interpretation']}")
        if oi.get("is_strong_signal"):
            signal = "强烈看多" if oi.get("strength", 0) > 60 else "强烈看空"
            lines.append(f"⚠️ {signal}")
    lines.append("")

    # 价格与波动
    lines.append("=" * 40)
    lines.append("【价格与波动】")
    if variety.get("price"):
        lines.append(f"当前价格：{variety['price']:.0f}")
    if variety.get("fund_data") and variety["fund_data"].get("price_percentile"):
        lines.append(f"价格分位：{variety['fund_data']['price_percentile']:.0f}%")
    if variety.get("atr_value"):
        lines.append(f"ATR波动率：{variety['atr_value']:.2f}")
    if variety.get("atr_ratio"):
        lines.append(f"波动率比例：{variety['atr_ratio'] * 100:.2f}%")

    # 风险评估
    lines.append("")
    lines.append("=" * 40)
    lines.append("【风险评估】")
    if variety.get("position_analysis"):
        pa = variety["position_analysis"]
        if pa.get("suggested_lots"):
            lines.append(f"建议手数：{pa['suggested_lots']}手")
        if pa.get("risk_amount") is not None:
            lines.append(
                f"风险金额：¥{pa['risk_amount']:.0f} ({pa.get('actual_risk_pct', 0):.2f}%)"
            )
        if pa.get("margin_required") is not None:
            lines.append(
                f"保证金占用：¥{pa['margin_required']:.0f} ({pa.get('position_pct', 0):.1f}%)"
            )
    else:
        if variety.get("risk_max_position_pct"):
            lines.append(f"最大仓位：{variety['risk_max_position_pct'] * 100:.0f}%")
        if variety.get("risk_max_daily_loss_pct"):
            lines.append(
                f"单日最大亏损：{variety['risk_max_daily_loss_pct'] * 100:.0f}%"
            )
        if variety.get("risk_suggested_position"):
            lines.append(f"建议手数(50万)：{variety['risk_suggested_position']}手")
    lines.append("")

    # 技术分析
    lines.append("=" * 40)
    lines.append("【技术分析】")
    if variety.get("tech_trend"):
        lines.append(f"技术趋势：{variety['tech_trend']}")
    if variety.get("tech_indicators"):
        ti = variety["tech_indicators"]
        if ti.get("macd"):
            lines.append(f"MACD：{ti['macd'].get('macd_signal', 'N/A')}")
        if ti.get("rsi"):
            rsi = ti["rsi"]
            lines.append(
                f"RSI：{rsi.get('rsi_value', 0):.0f} ({rsi.get('rsi_signal', 'N/A')})"
            )
        if ti.get("bollinger"):
            bb = ti["bollinger"]
            lines.append(
                f"布林带：{bb.get('bb_signal', 'N/A')} ({bb.get('bb_position', 0) * 100:.0f}%)"
            )
        if ti.get("kdj"):
            kdj = ti["kdj"]
            lines.append(
                f"KDJ：K{kdj.get('k_value', 0):.0f}/D{kdj.get('d_value', 0):.0f} ({kdj.get('kdj_signal', 'N/A')})"
            )
    lines.append("")

    # 量价分析
    lines.append("=" * 40)
    lines.append("【量价分析】")
    if variety.get("volume_analysis"):
        va = variety["volume_analysis"]
        lines.append(f"资金流向：{va.get('signal', 'N/A')}")
        lines.append(f"成交量趋势：{va.get('volume_trend', 'N/A')}")
        if va.get("volume_ratio"):
            lines.append(f"量比：{va['volume_ratio']:.2f}")
        if va.get("price_change_5d") is not None:
            lines.append(f"5日价格变化：{va['price_change_5d'] * 100:.2f}%")
    lines.append("")

    # 换月风险提示
    if variety.get("rollover_info") and variety["rollover_info"].get(
        "is_rollover_period"
    ):
        lines.append("=" * 40)
        lines.append("【⚠️ 换月风险提示】")
        rollover = variety["rollover_info"]
        lines.append(f"{rollover.get('message', '')}")
        lines.append(
            f"合约月份：{rollover.get('contract_month', 'N/A')} | 距离交割：{rollover.get('days_to_delivery', 0)}天"
        )
        lines.append("")

    # 分析理由
    lines.append("=" * 40)
    lines.append("【分析理由】")
    lines.append(variety.get("reason_full", "暂无详细分析理由"))
    lines.append("")

    return "\n".join(lines)


# ==================== 内容生成 API ====================


# 更新日志查看
@app.route("/xwx422/logs/update", endpoint="admin_update_logs")
@admin_required
def admin_update_logs():
    """数据更新日志查看"""
    page = request.args.get("page", 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    # 查询总数
    cursor.execute("SELECT COUNT(*) as total FROM update_logs")
    total = cursor.fetchone()["total"]

    # 查询日志数据
    cursor.execute(
        """
        SELECT * FROM update_logs
        ORDER BY update_time DESC
        LIMIT ? OFFSET ?
    """,
        (per_page, offset),
    )

    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        "admin/update_logs.html",
        logs=logs,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@app.route("/xwx422/logs/update/<int:log_id>", endpoint="admin_update_log_detail")
@admin_required
def admin_update_log_detail(log_id: int):
    """数据更新日志详情"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM update_logs WHERE id = ?", (log_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("日志记录不存在", "error")
        return redirect(url_for("admin_update_logs"))

    log = dict(row)

    # 查询品种级明细
    cursor.execute(
        "SELECT * FROM update_log_details WHERE log_id = ? ORDER BY status, variety_code",
        (log_id,),
    )
    details = [dict(d) for d in cursor.fetchall()]
    conn.close()

    return render_template("admin/update_log_detail.html", log=log, details=details)


@app.route("/xwx422/logs/update/clear", methods=["POST"])
@admin_required
def admin_clear_update_logs():
    """清空数据更新日志"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 清空所有日志
        cursor.execute("DELETE FROM update_logs")

        conn.commit()
        conn.close()

        logger.info(f"[ADMIN] 用户 {session.get('username')} 清空了更新日志")

        return jsonify({"success": True, "message": "日志已清空"})

    except Exception as e:
        logger.error(f"[ADMIN] 清空日志失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============ API 接口 ============


@app.route("/api/reanalyze/<variety_code>")
def api_reanalyze(variety_code: str):
    """单品种实时重新分析（同步直连执行）"""
    try:
        username = session.get("username")
        role = session.get("role")

        # 检查分析次数（管理员不受限制）
        if role != "admin":
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT daily_analysis_count, last_analysis_date FROM users WHERE username = ?",
                (username,),
            )
            user = cursor.fetchone()

            if not user:
                conn.close()
                return jsonify({"success": False, "error": "用户不存在"}), 404

            today = datetime.now().strftime("%Y-%m-%d")
            count = (
                user["daily_analysis_count"]
                if user["last_analysis_date"] == today
                else 3
            )

            if count <= 0:
                conn.close()
                return jsonify(
                    {
                        "success": False,
                        "error": "no_count",
                        "message": "今日分析次数已用完，如需更多分析请联系客服",
                    }
                ), 403

            # 扣减次数
            cursor.execute(
                "UPDATE users SET daily_analysis_count = daily_analysis_count - 1, last_analysis_date = ? WHERE username = ?",
                (today, username),
            )
            conn.commit()
            conn.close()

        from tasks.analysis_tasks import analyze_variety_task

        result = analyze_variety_task.apply(
            args=[variety_code],
            kwargs={"username": username},
            throw=True,
        )
        return jsonify(
            {
                "success": result.get("success", False),
                "done": True,
                "variety_code": variety_code,
            }
        )
    except Exception as e:
        logger.error(f"重新分析 {variety_code} 失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/varieties")
@login_required
def api_varieties():
    """API: 获取所有品种列表"""
    varieties, _, _ = get_latest_analysis()
    return jsonify({"success": True, "data": varieties})


@app.route("/api/stats")
@login_required
def api_stats():
    """API: 获取统计数据"""
    _, _, stats = get_latest_analysis()
    return jsonify({"success": True, "data": stats})


@app.route("/api/analysis_count")
@login_required
def api_analysis_count():
    """API: 获取用户今日剩余分析次数"""
    username = session.get("username")
    role = session.get("role")

    # 管理员不受限制
    if role == "admin":
        return jsonify({"success": True, "count": -1, "is_admin": True})

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT daily_analysis_count, last_analysis_date FROM users WHERE username = ?",
        (username,),
    )
    user = cursor.fetchone()
    conn.close()

    if not user:
        return jsonify({"success": False, "error": "用户不存在"}), 404

    today = datetime.now().strftime("%Y-%m-%d")
    count = user["daily_analysis_count"] if user["last_analysis_date"] == today else 3

    return jsonify({"success": True, "count": count, "is_admin": False})


# ============ 错误处理 ============


@app.errorhandler(404)
def not_found(error):
    """404错误处理 - 返回详细错误信息便于调试"""
    if request.path.startswith("/api/"):
        return jsonify(
            {
                "success": False,
                "error": "Not Found",
                "path": request.path,
                "method": request.method,
                "available_blueprints": [bp.name for bp in app.blueprints.values()],
                "message": "API endpoint not found",
            }
        ), 404
    return redirect(url_for("index"))


@app.errorhandler(500)
def internal_error(error):
    """500错误处理 - 返回详细错误信息便于调试"""
    import traceback

    logger.exception("服务器内部错误")
    if request.path.startswith("/api/"):
        return jsonify(
            {
                "success": False,
                "error": "Internal Server Error",
                "path": request.path,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
        ), 500
    # 非API请求：显示错误页面而非静默重定向，便于排查问题
    return render_template_string(
        """
        <!DOCTYPE html>
        <html><head><meta charset="utf-8"><title>500 - 服务器内部错误</title>
        <style>body{font-family:sans-serif;padding:2rem;background:#0a0e1a;color:#e6edf3}
        h1{color:#f85149}pre{background:#161b22;padding:1rem;border-radius:8px;overflow:auto;
        border:1px solid #30363d;font-size:0.85rem;}</style></head>
        <body><h1>500 - 服务器内部错误</h1>
        <p>请求路径: <code>{{ path }}</code></p>
        <p>错误信息: <strong>{{ error_msg }}</strong></p>
        <pre>{{ tb }}</pre>
        <p><a href="javascript:history.back()" style="color:#58a6ff">返回上一页</a>
        | <a href="/" style="color:#58a6ff">回到首页</a></p>
        </body></html>
    """,
        path=request.path,
        error_msg=str(error),
        tb=traceback.format_exc(),
    ), 500


# ============ 辅助函数 ============


def _get_latest_basis_for_variety(variety_code: str) -> Optional[Dict]:
    """读取品种最新基差数据"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT spot_price, basis, basis_rate, basis_percentile
            FROM spread_data
            WHERE variety_code = ?
              AND spot_price IS NOT NULL
            ORDER BY date DESC, id DESC
            LIMIT 1
            """,
            (variety_code,),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "spot_price": row["spot_price"],
                "basis": row["basis"],
                "basis_rate": row["basis_rate"],
                "basis_percentile": row["basis_percentile"],
            }
    except Exception as e:
        logger.warning(f"读取基差数据失败 {variety_code}: {e}")
    return None


def _apply_entry_timing(
    result: Dict,
    entry_timing_grade: str,
    entry_timing_label: str,
    trend_phase: str,
) -> Dict:
    """
    将入场时机评级应用到信号评级结果上

    规则：
    - 入场时机D级 → 无论趋势方向如何，最终评级最多C级（不建议入场）
    - 入场时机C级 → 最终评级降一级（高位追涨风险大）
    - 入场时机A级 → 不升级（趋势方向仍是核心约束）
    - 入场时机B级或无数据 → 不调整
    """
    if not entry_timing_grade:
        result["entry_timing_grade"] = "无"
        result["trend_phase"] = trend_phase
        return result

    result["entry_timing_grade"] = entry_timing_grade
    result["trend_phase"] = trend_phase
    result["entry_timing_label"] = entry_timing_label

    rating = result.get("rating", "C")
    rating_order = {"A": 4, "B": 3, "C": 2, "D": 1}
    current_level = rating_order.get(rating, 2)
    timing_level = rating_order.get(entry_timing_grade, 3)

    # 入场时机D级：不建议入场，最多给C级
    if entry_timing_grade == "D":
        if current_level > 2:  # A or B
            result["rating"] = "C"
            result["label"] = result.get("label", "") + "(等待回调)"
            result["est_win_rate"] = max(20, result.get("est_win_rate", 30) - 15)
            result["color"] = "yellow"
        elif current_level == 2:  # already C
            result["rating"] = "D"
            result["label"] = result.get("label", "") + "(不建议入场)"
            result["est_win_rate"] = max(15, result.get("est_win_rate", 25) - 10)
            result["color"] = "gray"

    # 入场时机C级：降一级
    elif entry_timing_grade == "C":
        if current_level >= 3:  # A or B → down one level
            new_rating = "B" if rating == "A" else "C"
            result["rating"] = new_rating
            result["label"] = result.get("label", "") + "(追涨风险)"
            result["est_win_rate"] = max(20, result.get("est_win_rate", 30) - 8)
            result["color"] = {"A": "green", "B": "blue", "C": "yellow"}.get(
                new_rating, "yellow"
            )

    # 入场时机A级：提升一级（方向评级C→B，B→A），但D级（观望）不提升
    elif entry_timing_grade == "A":
        if current_level == 2:  # C级 → B级
            result["rating"] = "B"
            result["label"] = result.get("label", "") + "(回调入场)"
            result["est_win_rate"] = max(35, result.get("est_win_rate", 28) + 8)
            result["color"] = "blue"
        elif current_level == 3:  # B级 → A级
            result["rating"] = "A"
            result["label"] = result.get("label", "") + "(回调入场)"
            result["est_win_rate"] = max(45, result.get("est_win_rate", 38) + 8)
            result["color"] = "green"

    result.setdefault("basis", "")
    return result


def _compute_signal_rating(variety: Dict) -> Dict:
    """
    信号评级 - 含趋势方向评级 + 入场时机评级双维度

    趋势方向评级（原逻辑）：
    A级：海龟突破+AI确认+ADX≥30+量价配合+多周期共振+基差方向一致
    B级：海龟突破+AI确认+ADX≥25 / 多周期共振+ADX≥30 / 海龟确认+ADX≥30
    C级：AI独立判断
    D级：ADX<20 / 观望 / 基差极端矛盾

    入场时机评级（新增）：
    A级：回调入场（RSI中性+布林中轨附近，趋势方向确认）
    B级：趋势跟随（RSI正常，趋势初期/成长期）
    C级：高位追涨/低位杀跌（RSI偏高/偏低，风险增大）
    D级：不建议入场（RSI极端+BB极端，等待回调）

    最终评级 = min(趋势方向评级, 入场时机评级)
    """
    direction = variety.get("trade_direction", "观望")
    adx_info = variety.get("adx_info", {})
    adx_value = adx_info.get("adx", 0) if isinstance(adx_info, dict) else 0
    signal_source = variety.get("signal_source", "AI")
    fund_prob = variety.get("fund_probability", 50)

    timeframe_confluence = variety.get("timeframe_confluence", "")
    has_resonance = "共振" in (timeframe_confluence or "")

    # === 基差/现货验证 ===
    basis_data = variety.get("basis_data") or {}
    basis_pct = basis_data.get("basis_percentile") if basis_data else None
    basis_supports = False  # 基差方向支持当前交易方向
    basis_contradicts = False  # 基差方向与当前交易方向矛盾
    basis_extreme = False  # 基差极端矛盾（强制D级）
    basis_label = ""

    if basis_pct is not None and direction in ("做多", "做空"):
        if direction == "做多":
            basis_supports = basis_pct > 60  # 升水偏强，支持做多
            basis_contradicts = basis_pct < 30  # 贴水偏弱，不利于做多
            basis_extreme = basis_pct < 15  # 极端贴水，强烈矛盾
        else:  # 做空
            basis_supports = basis_pct < 40  # 贴水偏弱，支持做空
            basis_contradicts = basis_pct > 70  # 升水偏强，不利于做空
            basis_extreme = basis_pct > 85  # 极端升水，强烈矛盾

        if basis_extreme:
            basis_label = f"基差极端矛盾({basis_pct:.0f}%)"
        elif basis_contradicts:
            basis_label = f"基差矛盾({basis_pct:.0f}%)"
        elif basis_supports:
            basis_label = f"基差支撑({basis_pct:.0f}%)"
        else:
            basis_label = f"基差中性({basis_pct:.0f}%)"
    elif direction in ("做多", "做空"):
        basis_label = "无基差数据"

    # === 入场时机评级（新增维度） ===
    # 从 variety 数据中获取入场时机评级
    entry_timing_grade = variety.get("entry_timing_grade", "")
    entry_timing_label = variety.get("entry_timing_label", "")
    trend_phase = variety.get("trend_phase", "")

    # 入场时机等级映射
    timing_grade_map = {"A": 4, "B": 3, "C": 2, "D": 1, "": 3}  # 默认B
    direction_grade_map = {"A": 4, "B": 3, "C": 2, "D": 1}

    # === D级 ===
    if direction == "观望" or adx_value < 20:
        return {
            "rating": "D",
            "label": "不建议",
            "est_win_rate": 20,
            "color": "gray",
            "direction_rating": "D",
            "entry_timing_grade": entry_timing_grade or "D",
            "trend_phase": trend_phase,
        }

    if basis_extreme:
        return {
            "rating": "D",
            "label": "基差极端矛盾",
            "est_win_rate": 15,
            "color": "gray",
            "basis": basis_label,
            "direction_rating": "D",
            "entry_timing_grade": entry_timing_grade or "D",
            "trend_phase": trend_phase,
        }

    # === 多周期矛盾检查：做多时看空≥3个周期 → 降级 ===
    tf_confluence = variety.get("timeframe_confluence", "")
    if direction == "做多" and tf_confluence:
        m = re.search(r"(\d+)/\d+.*看空", tf_confluence)
        bearish_count = int(m.group(1)) if m else 0
        if bearish_count >= 3:
            return {
                "rating": "C",
                "label": "多周期看空矛盾",
                "est_win_rate": 20,
                "color": "yellow",
                "basis": basis_label,
                "direction_rating": "C",
                "entry_timing_grade": entry_timing_grade or "C",
                "trend_phase": trend_phase,
            }
    if direction == "做空" and tf_confluence:
        m = re.search(r"(\d+)/\d+.*看多", tf_confluence)
        bullish_count = int(m.group(1)) if m else 0
        if bullish_count >= 3:
            return {
                "rating": "C",
                "label": "多周期看多矛盾",
                "est_win_rate": 20,
                "color": "yellow",
                "basis": basis_label,
                "direction_rating": "C",
                "entry_timing_grade": entry_timing_grade or "C",
                "trend_phase": trend_phase,
            }

    # === A级（回调入场策略：ADX趋势强 + 资金配合 + 多周期共振） ===
    a_core = adx_value >= 30 and fund_prob >= 60 and has_resonance
    if a_core:
        if basis_supports:
            result = {
                "rating": "A",
                "label": "强信号",
                "est_win_rate": 58,
                "color": "green",
                "basis": basis_label,
            }
        elif basis_contradicts:
            result = {
                "rating": "B",
                "label": "强信号(基差矛盾)",
                "est_win_rate": 45,
                "color": "blue",
                "basis": basis_label,
            }
        else:
            result = {
                "rating": "A",
                "label": "强信号(缺基差验证)",
                "est_win_rate": 50,
                "color": "green",
                "basis": basis_label,
            }
        result["direction_rating"] = result["rating"]
        return _apply_entry_timing(
            result, entry_timing_grade, entry_timing_label, trend_phase
        )

    # === B级（趋势确认：ADX≥25 + 资金概率≥50） ===
    if adx_value >= 25 and fund_prob >= 50:
        label = "可交易" + ("+基差支撑" if basis_supports else "")
        result = {
            "rating": "B",
            "label": label,
            "est_win_rate": 42,
            "color": "blue",
            "basis": basis_label,
        }
        result["direction_rating"] = "B"
        return _apply_entry_timing(
            result, entry_timing_grade, entry_timing_label, trend_phase
        )

    if has_resonance and adx_value >= 25:
        label = "可交易" + ("+基差支撑" if basis_supports else "")
        result = {
            "rating": "B",
            "label": label,
            "est_win_rate": 38,
            "color": "blue",
            "basis": basis_label,
        }
        result["direction_rating"] = "B"
        return _apply_entry_timing(
            result, entry_timing_grade, entry_timing_label, trend_phase
        )

    if adx_value >= 25:
        label = "可交易" + ("+基差支撑" if basis_supports else "")
        result = {
            "rating": "B",
            "label": label,
            "est_win_rate": 38,
            "color": "blue",
            "basis": basis_label,
        }
        result["direction_rating"] = "B"
        return _apply_entry_timing(
            result, entry_timing_grade, entry_timing_label, trend_phase
        )

    # === C级 ===
    result = {
        "rating": "C",
        "label": "弱信号",
        "est_win_rate": 28,
        "color": "yellow",
        "basis": basis_label,
    }
    result["direction_rating"] = "C"
    return _apply_entry_timing(
        result, entry_timing_grade, entry_timing_label, trend_phase
    )


def _compute_signal_tier(variety: Dict) -> str:
    """
    三档实战信号（替代ABCD展示）：
    🔥 布局 = 多维度对齐，可立即入场
    👀 关注 = 趋势确认但部分条件缺失，等待时机
    ⏸ 等待 = 无信号或矛盾
    """
    direction = variety.get("trade_direction", "观望")
    if direction == "观望":
        return "等待"

    adx_info = variety.get("adx_info", {})
    adx = adx_info.get("adx", 0) if isinstance(adx_info, dict) else 0
    sr = variety.get("signal_rating", {})
    rating = sr.get("rating", "D") if isinstance(sr, dict) else "D"
    direction_rating = sr.get("direction_rating", "D") if isinstance(sr, dict) else "D"
    fund_prob = variety.get("fund_probability", 0)
    confluence = variety.get("timeframe_confluence", "")
    has_resonance = "共振" in (confluence or "")
    trend_phase = variety.get("trend_phase", "")
    cont_prob = variety.get("continuation_prob", 0)

    # 多周期严重矛盾检查
    tf_serious_conflict = False
    if direction == "做多":
        import re

        m = re.search(r"(\d+)/\d+.*看空", confluence)
        tf_serious_conflict = (int(m.group(1)) if m else 0) >= 3
    elif direction == "做空":
        import re

        m = re.search(r"(\d+)/\d+.*看多", confluence)
        tf_serious_conflict = (int(m.group(1)) if m else 0) >= 3

    # 🔥 布局：方向评级A/B + ADX≥25 + 资金≥50 + 无严重矛盾
    if (
        direction_rating in ("A", "B")
        and adx >= 25
        and fund_prob >= 50
        and not tf_serious_conflict
    ):
        return "布局"

    # 👀 关注：有方向 + ADX≥20 + 无严重矛盾 + (趋势初期或持续概率≥35)
    if adx >= 20 and not tf_serious_conflict:
        if trend_phase in ("趋势初期", "趋势成长") or cont_prob >= 35:
            return "关注"

    # ⏸ 等待
    return "等待"


def _compute_pre_trend(variety: Dict, variety_code: str) -> Dict:
    """
    从现有数据库字段计算趋势预判评分
    不依赖数据库新字段，仅使用已有JSON数据
    """
    try:
        from analysis_layer.pre_trend_engine import PreTrendEngine
        import yaml as _yaml

        _config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        with open(_config_path, "r", encoding="utf-8") as _f:
            _config = _yaml.safe_load(_f) or {}
        engine = PreTrendEngine(_config)

        ti = variety.get("trend_info") or {}
        ai = variety.get("adx_info") or {}
        if not isinstance(ti, dict):
            ti = {}
        if not isinstance(ai, dict):
            ai = {}
        tech = variety.get("tech_indicators") or {}
        if not isinstance(tech, dict):
            tech = {}
        fa = variety.get("fund_analysis") or {}
        if not isinstance(fa, dict):
            fa = {}
        bd = variety.get("basis_data") or {}
        if not isinstance(bd, dict):
            bd = {}

        rsi_info_for_engine = {
            "rsi_value": ti.get(
                "rsi",
                tech.get("rsi", {}).get("rsi_value", 50)
                if isinstance(tech.get("rsi"), dict)
                else 50,
            ),
        }
        vol_info = {
            "atr_ratio": variety.get("atr_ratio", 0),
        }

        # 从 support_resistance 中获取近期极值，用于趋势空间计算
        _sr = variety.get("support_resistance") or {}
        if not isinstance(_sr, dict):
            _sr = {}
        # 也尝试从 adx_info 获取 rsi
        if (
            isinstance(ai, dict)
            and ai.get("rsi")
            and rsi_info_for_engine["rsi_value"] == 50
        ):
            rsi_info_for_engine["rsi_value"] = ai.get("rsi", 50)

        market_data = {
            "price": variety.get("price", 0),
            "atr_value": variety.get("atr_value", 0),
            "close_prices": [],
            "sr_levels": {
                "recent_extremes": _sr.get("recent_extremes", {}),
            },
        }

        return engine.evaluate(
            variety_code=variety_code,
            market=market_data,
            tech_indicators=tech,
            trend_info=ti,
            adx_info=ai,
            rsi_info=rsi_info_for_engine,
            volatility_info=vol_info,
            fund_analysis=fa,
            basis_data=bd,
            trade_direction=variety.get("trade_direction"),
        )
    except Exception as e:
        return {
            "pre_trend_score": 0,
            "pre_trend_label": "计算失败",
            "pre_trend_color": "gray",
            "veto": False,
            "veto_reasons": [],
            "early_bird_factor": 0.5,
            "capital_confirm": 0.5,
            "position_safety": 0.5,
            "risk_reward_coef": 1.0,
            "suggested_entry_low": 0,
            "suggested_entry_high": 0,
            "suggested_stop": 0,
            "suggested_target": 0,
            "trend_room": 0.5,
            "trend_room_score": 50,
            "trend_room_desc": "",
            "trend_move_atr": 0,
            "trend_remaining_atr": 0,
        }


def _enrich_variety_for_display(
    variety: Dict,
    latest_basis: Dict = None,
) -> Dict:
    """
    统一为品种数据补充所有展示层所需字段（Dashboard 卡片与详情页共用）
    精简版：只保留核心分析展示，移除信号追踪/回测/ML/价差/持仓排名
    """
    vc = variety.get("variety_code", "")
    price = variety.get("price", 0)
    atr = variety.get("atr_value", 0)

    # === 1. 海龟信号已移除（突破策略与回调入场逻辑冲突） ===
    variety["turtle_signal"] = "观望"
    variety["turtle_distance"] = None

    # === 2. 仓位计算（新手验证系统：固定1手） ===
    import yaml as _yaml, os as _os

    _multiplier, _margin_rate = 10.0, 0.10
    try:
        _config_path = _os.path.join(_os.path.dirname(__file__), "config.yaml")
        with open(_config_path, "r", encoding="utf-8") as _f:
            _config = _yaml.safe_load(_f) or {}
        _rules = _config.get("commodity_rules", {}).get(vc, {})
        _multiplier = float(_rules.get("position_multiplier", 10))
        _margin_rate = float(_rules.get("margin_rate", 0.10))
    except Exception:
        pass

    variety["position_size"] = 1  # 固定1手

    # === 2.5 每手盈亏计算（保证金按当前价，止损止盈从交易计划读取） ===
    if atr and price:
        _dir = variety.get("trade_direction", "观望")
        _db_entry = variety.get("entry_price") or 0
        _db_sl = variety.get("stop_loss") or 0
        _db_tp = variety.get("target_price") or 0

        # 止损止盈：优先使用数据库存储的交易计划值
        if _dir == "做空":
            _sl = _db_sl if _db_sl else (price + atr * 1.5)
            _tp = _db_tp if _db_tp else (price - atr * 2.0)
        else:
            _sl = _db_sl if _db_sl else (price - atr * 1.5)
            _tp = _db_tp if _db_tp else (price + atr * 2.0)

        # 保证金按当前价计算
        _margin_per_lot = price * _multiplier * _margin_rate

        _stop_dist = abs(price - _sl)
        _tp_dist = abs(_tp - price)
        _sl_rmb = _stop_dist * _multiplier
        _tp_rmb = _tp_dist * _multiplier

        if _sl_rmb > 100:
            _stop_dist = 100.0 / _multiplier
            _sl_rmb = 100.0
            _sl = price + _stop_dist if _dir == "做空" else price - _stop_dist
        _tp_rmb = min(_tp_rmb, _sl_rmb * 2)

        _rr = round(_tp_rmb / _sl_rmb, 2) if _sl_rmb > 0 else 0

        variety["position_info"] = {
            "lots": 1,
            "margin_per_lot": round(_margin_per_lot, 0),
            "entry_price": round(price, 1),
            "stop_loss": round(_sl, 1),
            "target_price": round(_tp, 1),
            "stop_loss_rmb": round(_sl_rmb, 0),
            "take_profit_rmb": round(_tp_rmb, 0),
            "risk_reward_ratio": _rr,
        }
        # 建议入场价：仅当AI建议回调入场且价差在0.3%~2%之间（超过2%为过期建议）
        if (
            _db_entry
            and 0.003 < abs(_db_entry - price) / price < 0.02
            and _db_entry != price
        ):
            variety["position_info"]["suggested_entry"] = round(_db_entry, 1)
    else:
        variety["position_info"] = None

    # === 2.6 趋势持续概率预测（前向预测） ===
    _adx_val = (
        (variety.get("adx_info") or {}).get("adx", 0)
        if isinstance(variety.get("adx_info"), dict)
        else 0
    )
    _dir = variety.get("trade_direction", "观望")
    _tp = variety.get("trend_phase", "")
    _tf_confluence = variety.get("timeframe_confluence", "")
    _ti = variety.get("trend_info") or {}
    _rsi = 50
    if isinstance(_ti, dict):
        _rsi = _ti.get("rsi", 50)

    if _dir == "观望":
        variety["continuation_prob"] = 0
    else:
        _prob = 50
        if _adx_val > 40:
            _prob += 20
        elif _adx_val > 30:
            _prob += 12
        elif _adx_val > 25:
            _prob += 6
        elif _adx_val > 20:
            _prob += 2
        elif _adx_val >= 15:
            _prob -= 10
        else:
            _prob -= 25
        if _tp == "趋势初期":
            _prob += 12
        elif _tp == "趋势成长":
            _prob += 8
        elif _tp == "趋势成熟":
            _prob += 0
        elif _tp == "趋势衰竭":
            _prob -= 18
        if "共振" in (_tf_confluence or ""):
            _prob += 12
        elif _tf_confluence and "多数" in _tf_confluence:
            _prob += 5
        elif _tf_confluence and "分歧" in _tf_confluence:
            _prob -= 8
        if _dir == "做多":
            if _rsi < 30:
                _prob += 5
            elif _rsi > 75:
                _prob -= 12
            elif _rsi > 65:
                _prob -= 5
        else:
            if _rsi > 70:
                _prob += 5
            elif _rsi < 25:
                _prob -= 12
            elif _rsi < 35:
                _prob -= 5
        variety["continuation_prob"] = max(15, min(85, _prob))

    # === 2.7 结构目标位 + 反转条件（基于支撑阻力，含最小距离过滤） ===
    _sr = variety.get("support_resistance") or {}
    _resistances = _sr.get("resistances", []) if isinstance(_sr, dict) else []
    _supports = _sr.get("supports", []) if isinstance(_sr, dict) else []
    _ns = _sr.get("nearest_support") if isinstance(_sr, dict) else None
    _nr = _sr.get("nearest_resistance") if isinstance(_sr, dict) else None
    _pi = variety.get("position_info") or {}

    # 最小目标距离：max(1 ATR, 0.5% 价格)
    _min_target_dist = max(atr * 1.0, price * 0.005) if atr and price else price * 0.01

    if _dir == "做多":
        # 找到第一个足够远的阻力位
        _target = None
        for _r in _resistances or []:
            if _r > price + _min_target_dist:
                _target = _r
                break
        if _target:
            _pi["structure_target"] = round(_target, 1)
        else:
            _pi["structure_target"] = (
                round(price + atr * 2, 1) if atr else round(price * 1.02, 1)
            )
        _pi["reversal_condition"] = (
            f"跌破{_ns:.0f}支撑转空" if _ns else f"跌破{round(price * 0.98, 0):.0f}转空"
        )

    elif _dir == "做空":
        _target = None
        for _s in _supports or []:
            if _s < price - _min_target_dist:
                _target = _s
                break
        if _target:
            _pi["structure_target"] = round(_target, 1)
        else:
            _pi["structure_target"] = (
                round(price - atr * 2, 1) if atr else round(price * 0.98, 1)
            )
        _pi["reversal_condition"] = (
            f"突破{_nr:.0f}阻力转多" if _nr else f"突破{round(price * 1.02, 0):.0f}转多"
        )

    else:
        _pi["structure_target"] = 0
        _pi["reversal_condition"] = ""

    variety["position_info"] = _pi

    # === 3. 从分析记录的 tech_indicators 中提取唐奇安通道（备用） ===
    if not variety.get("turtle_channel") and variety.get("tech_indicators"):
        tech = variety["tech_indicators"]
        if isinstance(tech, dict) and "d20_high" in tech:
            variety["turtle_channel"] = {
                "d20_high": tech["d20_high"],
                "d20_low": tech["d20_low"],
                "d55_high": tech.get("d55_high"),
                "d55_low": tech.get("d55_low"),
            }

    # === 4. 附加基差数据 ===
    if latest_basis is not None:
        basis_data = latest_basis.get(vc)
        variety["basis_data"] = basis_data if basis_data else None
    else:
        variety["basis_data"] = _get_latest_basis_for_variety(vc)

    # === 5. 信号源默认值 ===
    if not variety.get("signal_source"):
        variety["signal_source"] = "AI"

    # === 6. 胜率等级 ===
    prob = variety.get("fund_probability", 50)
    if prob >= 70:
        variety["win_rate_level"] = "high"
    elif prob >= 40:
        variety["win_rate_level"] = "medium"
    else:
        variety["win_rate_level"] = "low"

    # === 7. 统一补充海龟实时数据兜底 ===
    _position_info = variety.get("position_info")
    _position_size = variety.get("position_size")
    variety = _enrich_variety_with_turtle_data(variety)
    if _position_info is not None:
        variety["position_info"] = _position_info
    if _position_size is not None:
        variety["position_size"] = _position_size

    # === 7.5 从 adx_info 中提取入场时机数据 ===
    adx_info_raw = variety.get("adx_info", {})
    if isinstance(adx_info_raw, dict):
        variety["trend_phase"] = adx_info_raw.get("trend_phase", "")
        variety["trend_phase_score"] = adx_info_raw.get("trend_phase_score", 0)
        variety["entry_timing_grade"] = adx_info_raw.get("entry_timing_grade", "")
        variety["entry_timing_label"] = adx_info_raw.get("entry_timing_label", "")
        variety["entry_timing"] = adx_info_raw.get("entry_timing", {})
    # trade_plan 中也可能有（来自实时分析）
    trade_plan = variety.get("trade_plan", {})
    if isinstance(trade_plan, dict):
        if not variety.get("entry_timing_grade"):
            variety["entry_timing_grade"] = trade_plan.get("entry_timing_grade", "")
        if not variety.get("entry_timing_label"):
            variety["entry_timing_label"] = trade_plan.get("entry_timing_label", "")
        if not variety.get("trend_phase"):
            variety["trend_phase"] = trade_plan.get("trend_phase", "")

    # 安全转换：确保传到前端的字段一定是字符串
    for _k in ("trend_phase", "entry_timing_grade", "entry_timing_label"):
        _v = variety.get(_k, "")
        if not isinstance(_v, str):
            variety[_k] = str(_v) if _v else ""
    # entry_timing 可能是 dict，不直接传前端（已在 label/grade 中体现）
    variety.pop("entry_timing", None)

    # === 8. 信号评级 ===
    signal_rating = _compute_signal_rating(variety)
    variety["signal_rating"] = signal_rating
    variety["signal_tier"] = _compute_signal_tier(variety)

    # === 9.5 AI趋势判断（仅走AI结果，不兜底） ===
    _trade_plan = variety.get("trade_plan") or {}
    _ai_outlook = (
        _trade_plan.get("trend_outlook", "") if isinstance(_trade_plan, dict) else ""
    )
    variety["trend_outlook"] = _ai_outlook if _ai_outlook else ""
    if not variety.get("trade_plan"):
        variety["trade_plan"] = {}
    if isinstance(variety.get("trade_plan"), dict):
        variety["trade_plan"]["trend_outlook"] = variety["trend_outlook"]

    # === 10. 趋势预判评分（必须在排序之前计算，联动信号和排序） ===
    _pre_trend = _compute_pre_trend(variety, vc)
    variety["pre_trend_score"] = _pre_trend.get("pre_trend_score", 0)
    variety["pre_trend_label"] = _pre_trend.get("pre_trend_label", "观望")
    variety["pre_trend_color"] = _pre_trend.get("pre_trend_color", "gray")
    variety["pre_trend_veto"] = _pre_trend.get("veto", False)
    variety["pre_trend_veto_reasons"] = _pre_trend.get("veto_reasons", [])
    variety["pre_trend_early_bird"] = _pre_trend.get("early_bird_factor", 0.5)
    variety["pre_trend_capital"] = _pre_trend.get("capital_confirm", 0.5)
    variety["pre_trend_safety"] = _pre_trend.get("position_safety", 0.5)
    variety["pre_trend_rr_coef"] = _pre_trend.get("risk_reward_coef", 1.0)
    variety["pre_trend_entry_low"] = _pre_trend.get("suggested_entry_low", 0)
    variety["pre_trend_entry_high"] = _pre_trend.get("suggested_entry_high", 0)
    variety["pre_trend_stop"] = _pre_trend.get("suggested_stop", 0)
    variety["pre_trend_room_score"] = _pre_trend.get("trend_room_score", 50)
    variety["pre_trend_room_desc"] = _pre_trend.get("trend_room_desc", "")
    variety["pre_trend_move_atr"] = _pre_trend.get("trend_move_atr", 0)
    variety["pre_trend_remaining_atr"] = _pre_trend.get("trend_remaining_atr", 0)

    # === 10.5 预判结果联动修正（消除信号矛盾） ===
    _sr = variety.get("signal_rating") or {}
    if variety["pre_trend_veto"]:
        variety["signal_tier"] = "等待"
        if isinstance(_sr, dict):
            _sr["rating"] = "D"
            _sr["label"] = _sr.get("label", "") + "(预判否决)"
            _sr["est_win_rate"] = max(10, _sr.get("est_win_rate", 20) - 20)
            _sr["color"] = "gray"
        variety["signal_rating"] = _sr
        variety["focus_priority"] = -9999
    elif variety["pre_trend_score"] < 30:
        _old_tier = variety.get("signal_tier", "等待")
        if _old_tier in ("布局", "关注"):
            variety["signal_tier"] = "等待"
        if isinstance(_sr, dict):
            _sr["label"] = _sr.get("label", "") + "(预判低分)"
            _sr["est_win_rate"] = max(15, _sr.get("est_win_rate", 25) - 10)
        variety["signal_rating"] = _sr
        tier_priority = {"布局": 2000, "关注": 1000, "等待": 0}
        focus_priority = prob + tier_priority.get(variety.get("signal_tier", "等待"), 0)
        if "共振" in (variety.get("timeframe_confluence") or ""):
            focus_priority += 100
        focus_priority -= 3000
        variety["focus_priority"] = focus_priority
    else:
        _old_tier = variety.get("signal_tier", "等待")
        if variety["pre_trend_score"] >= 70:
            if _old_tier == "等待":
                variety["signal_tier"] = "关注"
        elif variety["pre_trend_score"] < 50:
            # 预判分中等偏低 → "布局"降为"关注"
            if _old_tier == "布局":
                variety["signal_tier"] = "关注"
        tier_priority = {"布局": 2000, "关注": 1000, "等待": 0}
        focus_priority = prob + tier_priority.get(variety.get("signal_tier", "等待"), 0)
        if "共振" in (variety.get("timeframe_confluence") or ""):
            focus_priority += 100
        if variety["pre_trend_score"] >= 70:
            focus_priority += 500
        elif variety["pre_trend_score"] >= 50:
            focus_priority += 200
        elif variety["pre_trend_score"] >= 40:
            focus_priority += 0
        else:
            focus_priority -= 500  # 预判30-40分 → 小惩罚
        variety["focus_priority"] = focus_priority

    return variety


def get_latest_analysis() -> tuple:
    """
    获取最新分析结果（每个品种的最新记录）
    按准确度与可靠性排序：胜率 > 多周期一致性 > 趋势强度 > 时间

    Returns:
        (品种列表, 最新更新时间, 统计信息)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 使用窗口函数获取每个品种的最新记录（不在SQL中排序，改为Python层排序）
    cursor.execute(
        """
        SELECT 
            ar.*
        FROM analysis_records ar
        WHERE ar.id IN (
            SELECT id FROM (
                SELECT 
                    id,
                    ROW_NUMBER() OVER (PARTITION BY variety_code ORDER BY run_time DESC, id DESC) as rn
                FROM analysis_records
            ) ranked
            WHERE rn = 1
        )
    """
    )

    rows = cursor.fetchall()

    # 过滤：只保留 config.yaml 中启用的品种
    try:
        _cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        with open(_cfg_path, "r", encoding="utf-8") as _cf:
            _cfg = yaml.safe_load(_cf) or {}
        _active_codes = {
            (v or {}).get("code", "").upper()
            for v in (_cfg.get("varieties") or {}).values()
            if v
        }
        if _active_codes:
            rows = [r for r in rows if r["variety_code"].upper() in _active_codes]
    except Exception as e:
        logger.warning(f"过滤品种列表失败: {e}")

    # 获取最新的更新时间
    latest_analysis_time = None
    if rows:
        try:
            cursor.execute("SELECT MAX(run_time) FROM analysis_records")
            latest_analysis_time = cursor.fetchone()[0]
            if not latest_analysis_time:
                latest_analysis_time = None
        except Exception as e:
            logger.warning(f"获取最新更新时间失败: {e}")
            latest_analysis_time = None
    else:
        latest_analysis_time = None

    # 获取上次完整分析时间（从 update_logs 表）
    try:
        cursor.execute(
            "SELECT update_time FROM update_logs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
        )
        latest_full_update = cursor.fetchone()
        latest_full_update_time = latest_full_update[0] if latest_full_update else None
    except Exception as e:
        logger.warning(f"获取上次完整分析时间失败: {e}")
        latest_full_update_time = None

    # 优先使用完整分析时间，如果没有则使用最新分析时间
    latest_time = latest_full_update_time or latest_analysis_time

    # 批量读取最新基差数据
    latest_basis = {}
    try:
        cursor.execute(
            """
            SELECT variety_code, spot_price, basis, basis_rate, basis_percentile
            FROM spread_data
            WHERE date = (SELECT MAX(date) FROM spread_data)
              AND spot_price IS NOT NULL
            """
        )
        for row in cursor.fetchall():
            latest_basis[row["variety_code"]] = {
                "spot_price": row["spot_price"],
                "basis": row["basis"],
                "basis_rate": row["basis_rate"],
                "basis_percentile": row["basis_percentile"],
            }
    except Exception as e:
        logger.warning(f"读取基差数据失败: {e}")

    conn.close()

    # 解析数据
    varieties = []
    for row in rows:
        row_dict = dict(row)
        variety = parse_json_fields(row_dict)
        _normalize_sector(variety)
        vc = variety.get("variety_code", "")

        variety = _enrich_variety_for_display(
            variety,
            latest_basis=latest_basis,
        )

        varieties.append(variety)

    # 统一按 focus_priority 排序（与前端 dashboard 保持一致）
    # focus_priority 已综合了 calibrated_prob、信号评级、多周期共振等因素
    varieties.sort(key=lambda v: v.get("focus_priority", 0), reverse=True)

    # 计算统计数据
    stats = calculate_stats(varieties)

    return varieties, latest_time, stats


def get_signal_tracking_stats(varieties: list) -> Dict:
    """
    轻量信号追踪：检查上一次分析记录的入场/目标/止损是否被当前价格触发
    返回：布局信号胜率、关注信号胜率
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 获取每个品种的倒数第二条记录（上上次分析）
    cursor.execute(
        """
        SELECT ar.* FROM analysis_records ar
        WHERE ar.id IN (
            SELECT id FROM (
                SELECT id,
                    ROW_NUMBER() OVER (PARTITION BY variety_code ORDER BY run_time DESC, id DESC) as rn
                FROM analysis_records
            ) ranked WHERE rn = 2
        )
    """
    )
    prev_rows = {r["variety_code"]: dict(r) for r in cursor.fetchall()}
    conn.close()

    # 构建当前价格映射
    current_prices = {}
    for v in varieties:
        code = v.get("variety_code", "")
        price = v.get("price", 0)
        if code and price:
            current_prices[code] = price

    deploy_hit, deploy_total = 0, 0
    watch_hit, watch_total = 0, 0

    for v in varieties:
        code = v.get("variety_code", "")
        tier = v.get("signal_tier", "等待")
        if tier == "等待":
            continue
        prev = prev_rows.get(code)
        if not prev:
            continue

        entry = prev.get("entry_price")
        stop = prev.get("stop_loss")
        target = prev.get("target_price")
        direction = prev.get("trade_direction", "")
        cur_price = current_prices.get(code, 0)

        if not (
            entry and stop and target and cur_price and direction in ("做多", "做空")
        ):
            continue

        if direction == "做多":
            # 做多：止损在下方，目标在上方
            # 如果当前价格低于止损位，说明已经触发止损，不算达标
            if cur_price <= stop:
                hit = False  # 已触发止损
            else:
                hit = cur_price >= target
        else:
            # 做空：止损在上方，目标在下方
            # 如果当前价格高于止损位，说明已经触发止损，不算达标
            if cur_price >= stop:
                hit = False  # 已触发止损
            else:
                hit = cur_price <= target

        if tier == "布局":
            deploy_total += 1
            if hit:
                deploy_hit += 1
        elif tier == "关注":
            watch_total += 1
            if hit:
                watch_hit += 1

    return {
        "deploy_win_rate": round(deploy_hit / deploy_total * 100)
        if deploy_total
        else 0,
        "deploy_total": deploy_total,
        "deploy_hit": deploy_hit,
        "watch_win_rate": round(watch_hit / watch_total * 100) if watch_total else 0,
        "watch_total": watch_total,
        "watch_hit": watch_hit,
        "total_tracked": deploy_total + watch_total,
    }


def _enrich_variety_with_turtle_data(variety: Dict, variety_code: str = None) -> Dict:
    """为品种数据补充海龟交易相关字段"""
    if not variety:
        return variety

    # 固定1手（新手验证系统）
    variety["position_size"] = 1

    # 补充唐奇安通道数据
    if not variety.get("turtle_channel") and variety.get("tech_indicators"):
        tech = variety["tech_indicators"]
        if isinstance(tech, dict) and "d20_high" in tech:
            variety["turtle_channel"] = {
                "d20_high": tech["d20_high"],
                "d20_low": tech["d20_low"],
                "d55_high": tech.get("d55_high"),
                "d55_low": tech.get("d55_low"),
            }

    # 若仍无通道数据，尝试从实时行情计算
    vc = variety_code or variety.get("variety_code", "")
    price = variety.get("price", 0)
    if not variety.get("turtle_channel") and vc and turtle_strategy_module:
        try:
            from data_layer.fetch_market import get_market_summary
            import pandas as pd

            mkt = get_market_summary(vc, use_cache=True)
            close_prices = mkt.get("close_prices", [])
            high_prices = mkt.get("high_prices", [])
            low_prices = mkt.get("low_prices", [])
            if len(close_prices) >= 20:
                df = pd.DataFrame(
                    {
                        "high": high_prices,
                        "low": low_prices,
                        "close": close_prices,
                    }
                )
                ch = turtle_strategy_module.calculate_donchian_channels(df)
                if ch:
                    variety["turtle_channel"] = ch
        except Exception:
            pass

    # 海龟信号已移除（突破策略与回调入场逻辑冲突）
    variety["turtle_signal"] = "观望"
    variety["turtle_distance"] = None

    # === 信号评级 ===
    variety["signal_rating"] = _compute_signal_rating(variety)

    return variety


def calculate_stats(varieties: List[Dict]) -> Dict:
    """计算统计数据"""
    if not varieties:
        return {}

    total = len(varieties)
    high_prob = sum(1 for v in varieties if v.get("fund_probability", 0) >= 70)
    medium_prob = sum(1 for v in varieties if 40 <= v.get("fund_probability", 0) < 70)
    low_prob = sum(1 for v in varieties if v.get("fund_probability", 0) < 40)

    bullish = sum(1 for v in varieties if v.get("trade_direction") == "做多")
    bearish = sum(1 for v in varieties if v.get("trade_direction") == "做空")
    neutral = sum(1 for v in varieties if v.get("trade_direction") == "观望")

    # 计算平均波动率
    avg_atr = sum(v.get("atr_ratio", 0) for v in varieties) / total if total > 0 else 0

    # 统计多周期一致性
    confluence_stats = {}
    for v in varieties:
        conf = v.get("timeframe_confluence", "未知")
        confluence_stats[conf] = confluence_stats.get(conf, 0) + 1

    return {
        "total": total,
        "high_probability": high_prob,
        "medium_probability": medium_prob,
        "low_probability": low_prob,
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "avg_atr_ratio": avg_atr,
        "confluence_stats": confluence_stats,
    }


def get_investor_suitability(variety: Dict) -> Dict:
    """
    判断品种适合的投资者类型

    Returns:
        {
            'beginner': bool,      # 适合新手
            'intermediate': bool,  # 适合中级
            'professional': bool,  # 适合专业
            'reason': str          # 原因说明
        }
    """
    prob = variety.get("fund_probability", 50)
    atr_ratio = variety.get("atr_ratio", 0.02)
    direction = variety.get("trade_direction", "观望")
    confluence = variety.get("timeframe_confluence", "")

    # 多周期一致性判断
    is_confluence = "共振" in confluence
    is_divergence = "分歧" in confluence

    suitability = {
        "beginner": False,
        "intermediate": False,
        "professional": False,
        "reason": "",
    }

    # 适合新手的条件：高胜率 + 低波动 + 多周期一致 + 明确方向
    if prob >= 70 and atr_ratio < 0.02 and is_confluence and direction != "观望":
        suitability["beginner"] = True
        suitability["reason"] = "高胜率+低波动+趋势明确"

    # 适合中级的条件：中等胜率 + 有方向
    elif prob >= 50 and direction != "观望":
        suitability["intermediate"] = True
        suitability["reason"] = "中等胜率，趋势可把握"

    # 适合专业的条件：低胜率或高波动或多周期分歧
    else:
        suitability["professional"] = True
        reasons = []
        if prob < 50:
            reasons.append("低胜率")
        if atr_ratio >= 0.025:
            reasons.append("高波动")
        if is_divergence:
            reasons.append("多周期分歧")
        if direction == "观望":
            reasons.append("方向不明")
        suitability["reason"] = "+".join(reasons) if reasons else "需要专业判断"

    return suitability


@app.route("/xwx422/task-health")
@admin_required
def admin_task_health():
    """任务健康监控页面 - P0-P3 数据流监控"""
    conn = get_db_connection()
    cursor = conn.cursor()

    health = {}

    # 0. Celery 服务状态检测
    import subprocess

    def _check_svc(name):
        try:
            r = subprocess.run(
                ["systemctl", "is-active", name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return r.stdout.strip() == "active"
        except Exception:
            return False

    def _check_process(keyword):
        try:
            r = subprocess.run(
                ["pgrep", "-f", keyword],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return bool(r.stdout.strip())
        except Exception:
            return False

    celery_beat_ok = _check_svc("futures-ai-beat.service") or _check_process(
        "celery.*beat"
    )
    celery_worker_ok = _check_svc("futures-ai-celery.service") or _check_process(
        "celery.*worker"
    )
    redis_ok = False
    try:
        import redis as _redis

        _redis_pw = os.getenv("REDIS_PASSWORD", "") or None
        _r = _redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=1,
            password=_redis_pw,
            socket_timeout=2,
        )
        redis_ok = _r.ping()
    except ImportError:
        # redis 包未安装，降级为 redis-cli
        try:
            _rr = subprocess.run(
                ["redis-cli", "ping"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            redis_ok = "PONG" in _rr.stdout
        except Exception:
            pass
    except Exception:
        # Python redis 连接失败，降级为 redis-cli（带密码）
        try:
            _cli_args = ["redis-cli"]
            _redis_pw = os.getenv("REDIS_PASSWORD", "")
            if _redis_pw:
                _cli_args += ["-a", _redis_pw]
            _cli_args += ["ping"]
            _rr = subprocess.run(
                _cli_args,
                capture_output=True,
                text=True,
                timeout=3,
            )
            redis_ok = "PONG" in _rr.stdout
        except Exception:
            pass

    health["celery"] = {
        "beat_running": celery_beat_ok,
        "worker_running": celery_worker_ok,
        "redis_ok": redis_ok,
    }

    # 1. 全量分析任务（update_logs）
    cursor.execute(
        "SELECT status, update_time, success_count, failed_count FROM update_logs ORDER BY update_time DESC LIMIT 1"
    )
    row = cursor.fetchone()
    health["last_analysis"] = dict(row) if row else None

    # 2. 基差数据
    cursor.execute(
        "SELECT MAX(date) as latest, COUNT(*) as count FROM spread_data WHERE spot_price IS NOT NULL"
    )
    basis_row = cursor.fetchone()
    health["basis_data"] = {
        "latest": basis_row["latest"],
        "varieties": basis_row["count"] or 0,
    }

    conn.close()
    return render_template("admin/task_health.html", health=health)


# ============ 主程序入口 ============

if __name__ == "__main__":
    if not os.path.exists("futures_analysis.db"):
        logger.error("数据库不存在，请先运行 init_db.py")
        exit(1)

    app.run(host="0.0.0.0", port=5000, debug=True)
