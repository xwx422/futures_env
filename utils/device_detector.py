# coding: utf-8
"""
设备检测工具模块
用于检测用户访问设备类型，实现PC端与移动端自动适配
"""

import re
from typing import Optional
from flask import request, session


class DeviceType:
    """设备类型常量"""
    PC = "pc"
    MOBILE = "mobile"
    TABLET = "tablet"


# 移动设备User-Agent匹配模式
MOBILE_PATTERNS = [
    # iOS设备
    'iPhone', 'iPod',
    # Android设备
    'Android.*Mobile', 'Android.*Phone',
    # Windows Phone
    'Windows Phone', 'IEMobile', 'WPDesktop',
    # BlackBerry
    'BlackBerry', 'BB10', 'RIM',
    # 其他移动设备
    'Opera Mini', 'Opera Mobi',
    'Mobile Safari', 'Mobile/', 'webOS',
    'Symbian', 'SymbianOS', 'Series60',
    'J2ME', 'MIDP', 'CLDC',
    'MeeGo', 'Maemo',
    'PlayStation Portable', 'PlayStation Vita',
    'Nintendo', 'Nokia',
]

# 平板设备User-Agent匹配模式
TABLET_PATTERNS = [
    'iPad',
    'Android(?!.*Mobile)',  # Android但不包含Mobile
    'Tablet',
    'Kindle', 'Silk',
    'PlayBook',
    'SM-T', 'GT-P', 'GT-N',  # Samsung平板
    ' Nexus 7', ' Nexus 9', ' Nexus 10',
]

# PC设备User-Agent匹配模式（用于排除）
PC_PATTERNS = [
    'Windows NT', 'Win32', 'Win64',
    'Macintosh', 'Mac OS X', 'MacIntel',
    'Linux x86_64', 'X11',
]


def get_user_agent() -> str:
    """获取User-Agent字符串"""
    return request.headers.get('User-Agent', '')


def is_mobile_device(user_agent: Optional[str] = None) -> bool:
    """
    检测是否为移动设备（手机）
    
    Args:
        user_agent: User-Agent字符串，如果不提供则从当前请求获取
        
    Returns:
        bool: 是否为移动设备
    """
    if user_agent is None:
        user_agent = get_user_agent()
    
    if not user_agent:
        return False
    
    # 首先检查是否为平板（平板不算作移动设备）
    if is_tablet_device(user_agent):
        return False
    
    # 检查移动设备模式
    for pattern in MOBILE_PATTERNS:
        if re.search(pattern, user_agent, re.IGNORECASE):
            return True
    
    return False


def is_tablet_device(user_agent: Optional[str] = None) -> bool:
    """
    检测是否为平板设备
    
    Args:
        user_agent: User-Agent字符串，如果不提供则从当前请求获取
        
    Returns:
        bool: 是否为平板设备
    """
    if user_agent is None:
        user_agent = get_user_agent()
    
    if not user_agent:
        return False
    
    for pattern in TABLET_PATTERNS:
        if re.search(pattern, user_agent, re.IGNORECASE):
            return True
    
    return False


def is_pc_device(user_agent: Optional[str] = None) -> bool:
    """
    检测是否为PC设备
    
    Args:
        user_agent: User-Agent字符串，如果不提供则从当前请求获取
        
    Returns:
        bool: 是否为PC设备
    """
    if user_agent is None:
        user_agent = get_user_agent()
    
    if not user_agent:
        return True  # 默认按PC处理
    
    # 如果不是移动设备也不是平板，则认为是PC
    return not is_mobile_device(user_agent) and not is_tablet_device(user_agent)


def get_device_type(user_agent: Optional[str] = None) -> str:
    """
    获取设备类型
    
    Args:
        user_agent: User-Agent字符串，如果不提供则从当前请求获取
        
    Returns:
        str: 设备类型 (pc/mobile/tablet)
    """
    if user_agent is None:
        user_agent = get_user_agent()
    
    if is_tablet_device(user_agent):
        return DeviceType.TABLET
    elif is_mobile_device(user_agent):
        return DeviceType.MOBILE
    else:
        return DeviceType.PC


def should_use_mobile_template(user_agent: Optional[str] = None) -> bool:
    """
    判断是否应该使用移动端模板
    手机使用移动端模板，平板和PC使用PC端模板
    
    Args:
        user_agent: User-Agent字符串，如果不提供则从当前请求获取
        
    Returns:
        bool: 是否使用移动端模板
    """
    if user_agent is None:
        user_agent = get_user_agent()
    
    # 检查session中是否有强制切换标记（仅在请求上下文中）
    try:
        if 'force_view_mode' in session:
            return session['force_view_mode'] == 'mobile'
    except RuntimeError:
        # 不在请求上下文中，忽略session检查
        pass
    
    # 只给真正的手机使用移动端模板
    # 平板使用PC端模板以获得更好的体验
    return is_mobile_device(user_agent)


def get_template_path(template_name: str, user_agent: Optional[str] = None) -> str:
    """
    根据设备类型获取模板路径
    
    Args:
        template_name: 模板名称（如 'dashboard.html'）
        user_agent: User-Agent字符串，如果不提供则从当前请求获取
        
    Returns:
        str: 完整的模板路径
    """
    if should_use_mobile_template(user_agent):
        return f'mobile/{template_name}'
    return template_name


def toggle_view_mode() -> str:
    """
    切换视图模式（PC/移动端手动切换）
    
    Returns:
        str: 切换后的模式
    """
    current_mode = session.get('force_view_mode')
    
    if current_mode == 'mobile':
        session['force_view_mode'] = 'pc'
        return 'pc'
    else:
        session['force_view_mode'] = 'mobile'
        return 'mobile'


def get_device_info(user_agent: Optional[str] = None) -> dict:
    """
    获取详细的设备信息
    
    Args:
        user_agent: User-Agent字符串，如果不提供则从当前请求获取
        
    Returns:
        dict: 设备信息字典
    """
    if user_agent is None:
        user_agent = get_user_agent()
    
    device_type = get_device_type(user_agent)
    
    # 尝试解析设备名称
    device_name = "Unknown"
    if 'iPhone' in user_agent:
        device_name = "iPhone"
    elif 'iPad' in user_agent:
        device_name = "iPad"
    elif 'Android' in user_agent:
        # 尝试获取Android设备名称
        match = re.search(r'Android [\d.]+; ([^;]+)', user_agent)
        if match:
            device_name = match.group(1).strip()
        else:
            device_name = "Android Device"
    elif 'Windows Phone' in user_agent:
        device_name = "Windows Phone"
    elif 'Windows NT' in user_agent:
        device_name = "Windows PC"
    elif 'Macintosh' in user_agent or 'Mac OS X' in user_agent:
        device_name = "Mac"
    elif 'Linux' in user_agent:
        device_name = "Linux"
    
    # 尝试解析浏览器信息
    browser = "Unknown"
    if 'Chrome' in user_agent and 'Edg' not in user_agent:
        browser = "Chrome"
    elif 'Safari' in user_agent and 'Chrome' not in user_agent:
        browser = "Safari"
    elif 'Firefox' in user_agent:
        browser = "Firefox"
    elif 'Edg' in user_agent:
        browser = "Edge"
    elif 'Opera' in user_agent or 'OPR' in user_agent:
        browser = "Opera"
    elif 'WeChat' in user_agent or 'MicroMessenger' in user_agent:
        browser = "WeChat"
    elif 'QQ' in user_agent:
        browser = "QQ Browser"
    
    return {
        'user_agent': user_agent,
        'device_type': device_type,
        'device_name': device_name,
        'browser': browser,
        'is_mobile': device_type == DeviceType.MOBILE,
        'is_tablet': device_type == DeviceType.TABLET,
        'is_pc': device_type == DeviceType.PC,
        'use_mobile_template': should_use_mobile_template(user_agent),
    }
