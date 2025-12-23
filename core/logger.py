"""
日志管理模块，负责日志配置、日志切割和日志清理功能
"""

import logging
import os
import datetime

# 创建log目录
def create_log_dir():
    """创建log目录"""
    log_dir = 'log'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    return log_dir

# 获取log目录
log_dir = create_log_dir()

# 全局debug开关配置
global_debug_enabled = False

# 日志配置
def init_logger():
    """初始化日志系统"""
    # 设置当前日志文件名
    current_log_file = os.path.join(log_dir, 'bili_video_tracker.log')
    
    # 创建主日志记录器
    logger = logging.getLogger('BiliVideoTracker')
    logger.setLevel(logging.INFO)
    
    # 移除所有现有的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 主日志文件处理器
    file_handler = logging.FileHandler(current_log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('[%(asctime)s][%(name)s][%(levelname)s] - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('[%(asctime)s][%(levelname)s] - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # 创建debug日志记录器
    debug_logger = logging.getLogger('BiliVideoTrackerDebug')
    debug_logger.setLevel(logging.DEBUG)
    
    # 移除debug日志的所有现有处理器
    for handler in debug_logger.handlers[:]:
        debug_logger.removeHandler(handler)
    
    # debug日志文件处理器
    debug_file = os.path.join(log_dir, 'bili_video_tracker_debug.log')
    debug_handler = logging.FileHandler(debug_file, encoding='utf-8')
    debug_handler.setLevel(logging.DEBUG)
    debug_formatter = logging.Formatter('[%(asctime)s][%(name)s][%(module)s][%(funcName)s][%(levelname)s] - %(message)s')
    debug_handler.setFormatter(debug_formatter)
    debug_logger.addHandler(debug_handler)
    
    # 确保debug日志记录器不会传播日志到父记录器
    debug_logger.propagate = False
    
    return logger

# 初始化日志记录器
logger = init_logger()
# 获取debug日志记录器
debug_logger = logging.getLogger('BiliVideoTrackerDebug')


def set_debug_mode(enabled):
    """
    设置debug模式开关
    enabled: bool, True启用debug模式，False禁用debug模式
    """
    global global_debug_enabled
    global_debug_enabled = enabled
    if enabled:
        logger.info("Debug模式已启用")
        debug_logger.info("Debug日志系统已初始化")
    else:
        logger.info("Debug模式已禁用")


def debug_log(*args):
    """
    记录debug日志
    支持两种调用方式:
    1. debug_log("[MODULE] 消息内容") - 兼容旧格式
    2. debug_log(module, action, message) - 新格式
    """
    if global_debug_enabled:
        if len(args) == 1:
            # 旧格式：debug_log("[MODULE] 消息内容")
            debug_logger.debug(args[0])
        elif len(args) >= 3:
            # 新格式：debug_log(module, action, message)
            module, action, message = args[:3]
            debug_logger.debug(f"[模块: {module}][操作: {action}] {message}")
        else:
            # 参数不匹配，按旧格式处理
            debug_logger.debug(' '.join(map(str, args)))


def get_debug_mode():
    """
    获取当前debug模式状态
    return: bool, 当前debug模式状态
    """
    return global_debug_enabled


def rotate_logs():
    """
    日志切割功能
    每天零点执行，将当前日志文件重命名为带日期的备份文件
    """
    global logger  # 声明logger为全局变量
    
    current_log_file = os.path.join(log_dir, 'bili_video_tracker.log')
    
    if not os.path.exists(current_log_file):
        logger.info("当前日志文件不存在，无需切割")
        return
    
    try:
        # 获取当前日志文件的修改时间
        file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(current_log_file))
        
        # 创建带日期的备份文件名
        backup_file = os.path.join(log_dir, f"bili_video_tracker_{file_mtime.strftime('%Y%m%d_%H%M%S')}.log")
        
        # 关闭当前日志系统
        logging.shutdown()
        
        # 重命名当前日志文件为备份文件
        os.rename(current_log_file, backup_file)
        
        # 重新初始化日志系统，创建新的日志文件
        logger = init_logger()
        logger.info(f"日志文件已切割为: {backup_file}")
        logger.info("新的日志文件已创建")
        
        return True
    except Exception as e:
        # 重新初始化日志系统
        logger = init_logger()
        logger.error(f"日志切割失败: {e}")
        return False


def clean_logs(retention_days=7):
    """
    清理过期的日志备份文件
    retention_days: 保留日志备份文件的天数
    """
    try:
        # 获取当前时间
        now = datetime.datetime.now()
        
        # 计算过期时间
        expire_time = now - datetime.timedelta(days=retention_days)
        
        # 遍历log目录下的所有日志文件
        for filename in os.listdir(log_dir):
            if filename.endswith('.log') and filename != 'bili_video_tracker.log':
                file_path = os.path.join(log_dir, filename)
                
                # 获取文件修改时间
                file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
                
                # 如果文件过期，则删除
                if file_mtime < expire_time:
                    os.remove(file_path)
                    logger.info(f"已清理过期日志文件: {filename}")
        
        logger.info("日志清理完成")
        return True
    except Exception as e:
        logger.error(f"日志清理失败: {e}")
        return False


def daily_log_maintenance(retention_days=7):
    """
    每日日志维护任务
    1. 切割当前日志文件
    2. 清理过期的日志备份文件
    """
    logger.info("开始执行每日日志维护任务")
    
    # 先切割日志
    rotate_logs()
    
    # 再清理过期日志
    clean_logs(retention_days)
    
    logger.info("每日日志维护任务执行完成")