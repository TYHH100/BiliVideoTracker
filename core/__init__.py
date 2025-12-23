"""
核心模块初始化文件，定义统一的异常类和错误处理机制
"""

# 从logger模块导入日志功能
from .logger import (
    logger,
    clean_logs,
    daily_log_maintenance,
    debug_log,
    set_debug_mode,
    get_debug_mode,
)


class BiliVideoTrackerBaseError(Exception):
    """所有BiliVideoTracker异常的基类"""

    pass


class APIError(BiliVideoTrackerBaseError):
    """API调用相关错误"""

    def __init__(self, message, status_code=None, url=None):
        self.status_code = status_code
        self.url = url
        super().__init__(message)


class DatabaseError(BiliVideoTrackerBaseError):
    """数据库操作相关错误"""

    pass


class AuthenticationError(BiliVideoTrackerBaseError):
    """认证相关错误"""

    pass


class ConfigurationError(BiliVideoTrackerBaseError):
    """配置相关错误"""

    pass


class ValidationError(BiliVideoTrackerBaseError):
    """数据验证错误"""

    pass


# 导出常用类和函数
from .bili_api import BiliAPI
from .database import (
    init_dbs,
    verify_token,
    set_token,
    get_token_info,
    get_all_settings,
    update_setting,
    add_monitor,
    get_monitors,
    delete_monitor,
    update_monitor_status,
    add_video_update,
    get_recent_updates,
    update_monitor_active_status,
    get_active_monitors,
)
from .scheduler import start_scheduler, stop_monitor, start_monitor, run_once
from .notifier import send_notification
from . import clean_logs
