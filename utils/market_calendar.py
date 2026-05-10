# utils/market_calendar.py
"""
期货交易日历工具
提供交易日判断、下次更新时间计算等功能
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# 配置文件路径
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "holidays_2026.json"
)


class MarketCalendar:
    """期货交易日历"""

    def __init__(self, year: int = 2026):
        self.year = year
        self.holidays: Dict[str, str] = {}
        self.night_session_closed: Dict[str, str] = {}
        self.update_schedule: List[Dict] = []
        self._load_config()

    def _load_config(self):
        """加载节假日配置"""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
                self.holidays = config.get("holidays", {})
                self.night_session_closed = config.get("night_session_closed", {})
                self.update_schedule = config.get(
                    "update_schedule",
                    [
                        {"hour": 8, "minute": 30, "label": "上午8:30"},
                        {"hour": 10, "minute": 20, "label": "上午10:20"},
                        {"hour": 13, "minute": 0, "label": "下午1:00"},
                        {"hour": 14, "minute": 0, "label": "下午2:00"},
                        {"hour": 20, "minute": 30, "label": "晚上8:30"},
                        {"hour": 22, "minute": 0, "label": "晚上10:00"},
                    ],
                )
        except FileNotFoundError:
            print(f"警告: 未找到配置文件 {CONFIG_PATH}，使用默认配置")
            self.update_schedule = [
                {"hour": 8, "minute": 30, "label": "上午8:30"},
                {"hour": 10, "minute": 20, "label": "上午10:20"},
                {"hour": 13, "minute": 0, "label": "下午1:00"},
                {"hour": 14, "minute": 0, "label": "下午2:00"},
                {"hour": 20, "minute": 30, "label": "晚上8:30"},
                {"hour": 22, "minute": 0, "label": "晚上10:00"},
            ]

    def is_trading_day(self, date: datetime) -> bool:
        """
        判断指定日期是否是交易日

        Args:
            date: 日期

        Returns:
            True表示是交易日，False表示不是
        """
        date_str = date.strftime("%Y-%m-%d")

        # 检查是否是节假日
        if date_str in self.holidays:
            return False

        # 检查是否是周末（周六=5，周日=6）
        if date.weekday() >= 5:
            return False

        return True

    def is_night_session_open(self, date: datetime) -> bool:
        """
        判断指定日期的夜盘是否开盘

        Args:
            date: 日期

        Returns:
            True表示夜盘开盘，False表示不开
        """
        date_str = date.strftime("%Y-%m-%d")

        # 检查节假日前夜
        if date_str in self.night_session_closed:
            return False

        # 检查是否是交易日
        if not self.is_trading_day(date):
            return False

        return True

    def is_trading_time(self, check_time: datetime = None) -> Dict:
        """
        判断指定时间是否在交易时段内

        期货交易时段：
        - 早盘：09:00-10:15, 10:30-11:30
        - 下午：13:30-15:00
        - 夜盘：21:00-23:00（部分品种）

        Args:
            check_time: 要检查的时间，默认为现在

        Returns:
            {
                'is_trading': bool,
                'session': str,
                'reason': str,
                'next_session': str
            }
        """
        if check_time is None:
            check_time = datetime.now()

        # 检查是否是交易日
        if not self.is_trading_day(check_time):
            return {
                'is_trading': False,
                'session': '休市',
                'reason': '非交易日',
                'next_session': '下一个交易日开盘'
            }

        hour = check_time.hour
        minute = check_time.minute
        time_value = hour * 100 + minute

        # 早盘时段
        if 900 <= time_value < 1015:
            return {
                'is_trading': True,
                'session': '早盘',
                'reason': '早盘交易时段',
                'next_session': '10:30 继续交易'
            }
        
        # 早盘休息（10:15-10:30）
        if 1015 <= time_value < 1030:
            return {
                'is_trading': False,
                'session': '休息',
                'reason': '早盘盘中休息',
                'next_session': '10:30 继续交易'
            }
        
        # 早盘后半段
        if 1030 <= time_value < 1130:
            return {
                'is_trading': True,
                'session': '早盘',
                'reason': '早盘交易时段',
                'next_session': '13:30 下午交易'
            }
        
        # 午休（11:30-13:30）
        if 1130 <= time_value < 1330:
            return {
                'is_trading': False,
                'session': '午休',
                'reason': '中午休市',
                'next_session': '13:30 下午交易'
            }
        
        # 下午时段
        if 1330 <= time_value < 1500:
            return {
                'is_trading': True,
                'session': '下午',
                'reason': '下午交易时段',
                'next_session': '夜盘 21:00 开始' if self.is_night_session_open(check_time) else '明日 09:00 开盘'
            }
        
        # 日盘结束到夜盘（15:00-21:00）
        if 1500 <= time_value < 2100:
            if self.is_night_session_open(check_time):
                return {
                    'is_trading': False,
                    'session': '盘间',
                    'reason': '日盘结束，等待夜盘',
                    'next_session': '21:00 夜盘交易'
                }
            else:
                return {
                    'is_trading': False,
                    'session': '休市',
                    'reason': '日盘已结束',
                    'next_session': '明日 09:00 开盘'
                }
        
        # 夜盘时段（21:00-23:00）
        if 2100 <= time_value < 2300:
            if self.is_night_session_open(check_time):
                return {
                    'is_trading': True,
                    'session': '夜盘',
                    'reason': '夜盘交易时段',
                    'next_session': '明日 09:00 开盘'
                }
            else:
                return {
                    'is_trading': False,
                    'session': '休市',
                    'reason': '节假日无夜盘',
                    'next_session': '明日 09:00 开盘'
                }
        
        # 深夜（23:00-次日 09:00）
        return {
            'is_trading': False,
            'session': '休市',
            'reason': '夜盘已结束',
            'next_session': '明日 09:00 开盘'
        }

    def get_next_trading_day(self, date: datetime) -> datetime:
        """
        获取下一个交易日

        Args:
            date: 起始日期

        Returns:
            下一个交易日的日期
        """
        next_day = date + timedelta(days=1)
        while not self.is_trading_day(next_day):
            next_day += timedelta(days=1)
        return next_day

    def get_next_update_time(
        self, current_time: Optional[datetime] = None
    ) -> Tuple[datetime, str]:
        """
        获取下次更新时间

        Args:
            current_time: 当前时间，默认为现在

        Returns:
            (下次更新时间, 描述文字)
        """
        if current_time is None:
            current_time = datetime.now()

        # 检查今天是否是交易日
        if not self.is_trading_day(current_time):
            # 如果不是交易日，找到下一个交易日，使用第一个时间点
            next_trading_day = self.get_next_trading_day(current_time)
            first_schedule = self.update_schedule[0]
            next_update = next_trading_day.replace(
                hour=first_schedule["hour"],
                minute=first_schedule["minute"],
                second=0,
                microsecond=0,
            )
            days_diff = (next_trading_day.date() - current_time.date()).days
            if days_diff == 1:
                desc = f"明天 {first_schedule['label']}"
            else:
                desc = (
                    f"{next_trading_day.strftime('%m月%d日')} {first_schedule['label']}"
                )
            return next_update, desc

        # 是交易日，检查今天的剩余时间点
        current_hour = current_time.hour
        current_minute = current_time.minute
        current_total_minutes = current_hour * 60 + current_minute

        # 检查是否有夜盘（节假日前夜无夜盘）
        has_night_session = self.is_night_session_open(current_time)

        for schedule in self.update_schedule:
            schedule_total_minutes = schedule["hour"] * 60 + schedule["minute"]

            # 如果是夜盘时间（20:30之后），检查是否有夜盘
            if schedule["hour"] >= 20 and not has_night_session:
                continue

            if schedule_total_minutes > current_total_minutes:
                # 找到下一个时间点
                next_update = current_time.replace(
                    hour=schedule["hour"],
                    minute=schedule["minute"],
                    second=0,
                    microsecond=0,
                )
                return next_update, f"今天 {schedule['label']}"

        # 今天的所有时间点都过了，找下一个交易日的第一个时间点
        next_trading_day = self.get_next_trading_day(current_time)
        first_schedule = self.update_schedule[0]
        next_update = next_trading_day.replace(
            hour=first_schedule["hour"],
            minute=first_schedule["minute"],
            second=0,
            microsecond=0,
        )
        days_diff = (next_trading_day.date() - current_time.date()).days
        if days_diff == 1:
            desc = f"明天 {first_schedule['label']}"
        else:
            desc = f"{next_trading_day.strftime('%m月%d日')} {first_schedule['label']}"
        return next_update, desc

    def format_countdown(
        self, target_time: datetime, current_time: Optional[datetime] = None
    ) -> str:
        """
        格式化倒计时

        Args:
            target_time: 目标时间
            current_time: 当前时间，默认为现在

        Returns:
            倒计时文字，如"5小时30分钟"
        """
        if current_time is None:
            current_time = datetime.now()

        diff = target_time - current_time
        total_seconds = diff.total_seconds()

        if total_seconds <= 0:
            return "即将更新"

        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)

        if hours > 0:
            return f"{hours}小时{minutes}分钟"
        elif minutes > 0:
            return f"{minutes}分钟{seconds}秒"
        else:
            return f"{seconds}秒"


# 全局实例
calendar = MarketCalendar(2026)


def get_next_update_info() -> Dict:
    """
    获取下次更新信息（供API调用）

    Returns:
        {
            'next_update_time': '2026-02-10 08:30:00',
            'next_update_desc': '明天 上午8:30',
            'countdown': '5小时30分钟',
            'is_trading_day': True,
            'is_updating': False
        }
    """
    now = datetime.now()
    next_time, desc = calendar.get_next_update_time(now)
    countdown = calendar.format_countdown(next_time, now)

    # 检查是否正在更新中（只在更新时间点前后1分钟内）
    diff = (next_time - now).total_seconds()
    # 当倒计时接近0（60秒内）或刚刚过去（30秒内）时显示"即将更新/正在更新"
    is_updating = -30 <= diff <= 60  # 前1分钟到后30秒

    return {
        "next_update_time": next_time.strftime("%Y-%m-%d %H:%M:%S"),
        "next_update_desc": desc,
        "countdown": countdown,
        "is_trading_day": calendar.is_trading_day(now),
        "is_updating": is_updating,
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    # 测试
    cal = MarketCalendar(2026)

    # 测试几个日期
    test_dates = [
        datetime(2026, 2, 9, 10, 0),  # 正常交易日
        datetime(2026, 2, 13, 21, 0),  # 春节前夜（无夜盘）
        datetime(2026, 2, 15, 9, 0),  # 春节（非交易日）
        datetime(2026, 2, 10, 23, 0),  # 正常交易日晚上
    ]

    for test_date in test_dates:
        is_trading = cal.is_trading_day(test_date)
        has_night = cal.is_night_session_open(test_date)
        next_time, desc = cal.get_next_update_time(test_date)
        countdown = cal.format_countdown(next_time, test_date)

        print(f"\n测试时间: {test_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"  是否交易日: {is_trading}")
        print(f"  是否有夜盘: {has_night}")
        print(f"  下次更新: {desc}")
        print(f"  倒计时: {countdown}")
