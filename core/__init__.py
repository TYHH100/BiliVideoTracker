"""
核心模块初始化文件，定义统一的异常类和错误处理机制
"""

# 从logger模块导入日志功能
from .logger import (
    clean_logs,
    daily_log_maintenance,
    debug_log,
    get_debug_mode,
    logger,
    set_debug_mode,
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


from . import clean_logs

# 导出常用类和函数
from .bili_api import BiliAPI
from .database import (
    add_monitor,
    add_video_update,
    delete_monitor,
    get_active_monitors,
    get_all_settings,
    get_monitors,
    get_recent_updates,
    get_token_info,
    init_dbs,
    set_token,
    update_monitor_active_status,
    update_monitor_status,
    update_setting,
    verify_token,
)
from .notifier import send_notification
from .scheduler import run_once, start_monitor, start_scheduler, stop_monitor
