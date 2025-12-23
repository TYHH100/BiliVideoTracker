import sqlite3
import os
import bcrypt
import datetime
import sys
from . import logger
from core import debug_log

# 确定数据库路径 (兼容 PyInstaller 打包后的路径)
if getattr(sys, "frozen", False):
    # 打包后的环境，使用程序所在目录
    BASE_DIR = os.path.dirname(sys.executable)
    DATA_DIR = os.path.join(BASE_DIR, "data")
else:
    # 开发环境
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, "data")

# 确保数据目录存在
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

TOKEN_DB = os.path.join(DATA_DIR, "token_store.db")
DATA_DB = os.path.join(DATA_DIR, "monitor_data.db")


class SQLiteConnectionPool:
    """SQLite连接池实现，支持多线程"""

    def __init__(self, db_path):
        self.db_path = db_path
        debug_log(f"[DB] 初始化连接池，数据库路径: {self.db_path}")

    def get_connection(self):
        """获取一个数据库连接"""
        # 为每个线程创建新连接，避免线程安全问题
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # 默认使用字典格式
        debug_log(f"[DB] 获取数据库连接: {id(conn)}, 数据库: {self.db_path}")
        return conn

    def return_connection(self, conn):
        """归还数据库连接"""
        # 直接关闭连接，因为每个线程都有自己的连接
        try:
            debug_log(f"[DB] 关闭数据库连接: {id(conn)}")
            conn.close()
        except Exception as e:
            logger.error(f"关闭数据库连接失败: {e}")
            debug_log(f"[DB] 关闭数据库连接失败: {e}")
            pass

    def close_all(self):
        """关闭所有连接"""
        # 由于每个线程都有自己的连接，这里不需要做任何操作
        debug_log(f"[DB] 关闭所有连接")
        pass


# 创建全局连接池实例
token_pool = SQLiteConnectionPool(TOKEN_DB)
data_pool = SQLiteConnectionPool(DATA_DB)


def init_dbs():
    """初始化数据库表结构"""
    debug_log(f"[DB] 开始初始化数据库")
    # 1. 令牌数据库
    conn = token_pool.get_connection()
    try:
        c = conn.cursor()
        debug_log(f"[DB] 创建auth_token表")
        c.execute(
            """CREATE TABLE IF NOT EXISTS auth_token (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
        )
        conn.commit()
        debug_log(f"[DB] auth_token表创建成功")
    finally:
        token_pool.return_connection(conn)

    conn = token_pool.get_connection()
    try:
        c = conn.cursor()
        debug_log(f"[DB] 检查auth_token表是否为空")
        c.execute("SELECT COUNT(*) FROM auth_token")
        if c.fetchone()[0] == 0:
            import secrets

            initial_token = secrets.token_hex(16)
            set_token(initial_token)
            debug_log(f"[DB] 生成初始访问令牌: {initial_token}")
            print("=" * 50)
            print(f"初始访问令牌已生成: {initial_token}")
            print("请使用此令牌登录系统")
            print("=" * 50)
    finally:
        token_pool.return_connection(conn)

    # 2. 数据数据库
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        # 设置表
        debug_log(f"[DB] 创建settings表")
        c.execute(
            """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )"""
        )
        debug_log(f"[DB] settings表创建成功")
        # 监控列表
        # type: 'series' 或 'season'
        # last_check_ts: 上次检查的时间戳
        # is_active: 是否激活监控 (0=暂停, 1=激活)
        debug_log(f"[DB] 创建monitor_list表")
        c.execute(
            """CREATE TABLE IF NOT EXISTS monitor_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mid TEXT,
            remote_id TEXT,
            type TEXT,
            name TEXT,
            cover TEXT,
            total_count INTEGER DEFAULT 0,
            last_check_ts INTEGER DEFAULT 0,
            up_mid TEXT,
            desc TEXT,
            is_active INTEGER DEFAULT 1,
            archived INTEGER DEFAULT 0
        )"""
        )
        debug_log(f"[DB] monitor_list表创建成功")

        # 检查并添加缺失的字段到monitor_list表
        try:
            # 获取当前表格的字段信息
            c.execute("PRAGMA table_info(monitor_list)")
            columns = {col[1] for col in c.fetchall()}

            # 定义所有应该存在的字段
            expected_columns = {
                "id",
                "mid",
                "remote_id",
                "type",
                "name",
                "cover",
                "total_count",
                "last_check_ts",
                "up_mid",
                "desc",
                "is_active",
                "archived",
            }

            # 检查缺失的字段
            missing_columns = expected_columns - columns

            # 为缺失的字段添加ALTER TABLE语句
            # 注意：SQLite的ALTER TABLE有局限性，只能添加字段到表的末尾
            for column in missing_columns:
                # 根据字段名确定类型和默认值
                if column == "total_count":
                    c.execute(
                        "ALTER TABLE monitor_list ADD COLUMN total_count INTEGER DEFAULT 0"
                    )
                elif column == "last_check_ts":
                    c.execute(
                        "ALTER TABLE monitor_list ADD COLUMN last_check_ts INTEGER DEFAULT 0"
                    )
                elif column == "up_mid":
                    c.execute("ALTER TABLE monitor_list ADD COLUMN up_mid TEXT")
                elif column == "desc":
                    c.execute("ALTER TABLE monitor_list ADD COLUMN desc TEXT")
                elif column == "is_active":
                    c.execute(
                        "ALTER TABLE monitor_list ADD COLUMN is_active INTEGER DEFAULT 1"
                    )
                elif column == "archived":
                    c.execute(
                        "ALTER TABLE monitor_list ADD COLUMN archived INTEGER DEFAULT 0"
                    )
                else:
                    # 默认添加TEXT类型字段
                    c.execute(f"ALTER TABLE monitor_list ADD COLUMN {column} TEXT")

                logger.info(f"向monitor_list表添加了缺失的字段: {column}")
        except Exception as e:
            logger.error(f"检查monitor_list表字段时出错: {e}")
            # 忽略错误，继续执行
            pass

        # 视频更新记录表
        # 存储监控到的视频更新信息
        debug_log(f"[DB] 创建video_updates表")
        c.execute(
            """CREATE TABLE IF NOT EXISTS video_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER,
            video_id TEXT,
            video_title TEXT,
            publish_time INTEGER,
            cover TEXT,
            FOREIGN KEY (monitor_id) REFERENCES monitor_list (id)
        )"""
        )
        debug_log(f"[DB] video_updates表创建成功")

        # 检查并添加缺失的字段到video_updates表
        try:
            # 获取当前表格的字段信息
            c.execute("PRAGMA table_info(video_updates)")
            columns = {col[1] for col in c.fetchall()}

            # 定义所有应该存在的字段
            expected_columns = {
                "id",
                "monitor_id",
                "video_id",
                "video_title",
                "publish_time",
                "cover",
            }

            # 检查缺失的字段
            missing_columns = expected_columns - columns

            # 为缺失的字段添加ALTER TABLE语句
            for column in missing_columns:
                # 根据字段名确定类型和默认值
                if column == "monitor_id":
                    c.execute("ALTER TABLE video_updates ADD COLUMN monitor_id INTEGER")
                elif column == "publish_time":
                    c.execute(
                        "ALTER TABLE video_updates ADD COLUMN publish_time INTEGER DEFAULT 0"
                    )
                else:
                    # 默认添加TEXT类型字段
                    c.execute(f"ALTER TABLE video_updates ADD COLUMN {column} TEXT")

                logger.info(f"向video_updates表添加了缺失的字段: {column}")
        except Exception as e:
            logger.error(f"检查video_updates表字段时出错: {e}")
            # 忽略错误，继续执行
            pass

        # 初始化默认设置
        default_settings = {
            "smtp_enable": "0",
            "smtp_server": "smtp.163.com",
            "smtp_port": "465",
            "email_account": "",
            "email_auth_code": "",
            "sender_name": "B站合集监控",
            "receiver_emails": "",
            "use_tls": "1",
            "smtp_batch_send": "0",  # 集中发送邮件开关 (0=关闭, 1=开启)
            "monitor_active": "0",  # 全局监控开关
            "next_check_time": "未调度",
            "server_host": "127.0.0.1",  # 服务器IP地址
            "server_port": "5000",  # 服务器端口号
            "recent_updates_limit": "10",  # 前端显示的最近更新视频数量限制
            "recent_updates_save_limit": "30",  # 后端保存的最近更新视频数量限制
            "log_auto_clean": "1",  # 日志自动清理开关 (0=关闭, 1=开启)
            "log_retention_days": "7",  # 日志保留天数
            #'log_max_size_mb': '100' # 日志文件最大大小 (MB)
            "debug_mode": "0",  # Debug模式开关 (0=关闭, 1=开启)
        }

        # 获取当前数据库中的所有设置
        c.execute("SELECT key, value FROM settings")
        current_settings = {row[0]: row[1] for row in c.fetchall()}

        # 检查并添加缺失的设置项
        for k, v in default_settings.items():
            if k not in current_settings:
                c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
                logger.info(f"添加了缺失的设置项: {k} = {v}")

        conn.commit()
    finally:
        data_pool.return_connection(conn)


# --- 令牌管理 ---


def verify_token(raw_token):
    """验证前端传来的令牌"""
    if not raw_token:
        debug_log(f"[DB] 验证令牌: None")
        return False
    debug_log(f"[DB] 验证令牌: {raw_token[:8]}...")
    conn = token_pool.get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT token_hash FROM auth_token WHERE id=1")
        row = c.fetchone()
        if not row:
            debug_log(f"[DB] 未设置令牌")
            return False  # 未设置令牌
        # 对比哈希
        result = bcrypt.checkpw(raw_token.encode(), row[0].encode())
        debug_log(f"[DB] 令牌验证结果: {result}")
        return result
    except Exception as e:
        logger.error(f"令牌验证出错: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        token_pool.return_connection(conn)


def set_token(raw_token):
    """重置/设置令牌"""
    debug_log(f"[DB] 设置新令牌: {raw_token[:8]}...")
    # 生成哈希
    hashed = bcrypt.hashpw(raw_token.encode(), bcrypt.gensalt()).decode()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = token_pool.get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM auth_token")
        c.execute(
            "INSERT INTO auth_token (id, token_hash, created_at) VALUES (1, ?, ?)",
            (hashed, now),
        )
        conn.commit()
        debug_log(f"[DB] 令牌设置成功")
    finally:
        token_pool.return_connection(conn)


def get_token_info():
    """获取令牌信息（仅哈希前几位和时间）"""
    conn = token_pool.get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT token_hash, created_at FROM auth_token WHERE id=1")
        row = c.fetchone()
        if row:
            return {
                "hash_preview": row[0][:8] + "...",
                "created_at": row[1],
                "exists": True,
            }
        return {"hash_preview": "未设置", "created_at": "", "exists": False}
    finally:
        token_pool.return_connection(conn)


# --- 设置与监控数据管理 ---


def get_all_settings():
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM settings")
        return {row["key"]: row["value"] for row in c.fetchall()}
    finally:
        data_pool.return_connection(conn)


def update_setting(key, value):
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        conn.commit()
    finally:
        data_pool.return_connection(conn)


def add_monitor(data):
    """添加新的监控项"""
    debug_log(
        f"[DB] 添加监控项: remote_id={data['remote_id']}, type={data['type']}, name={data['name']}"
    )
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        # 查重
        debug_log(
            f"[DB] 检查监控项是否已存在: remote_id={data['remote_id']}, type={data['type']}"
        )
        c.execute(
            "SELECT id FROM monitor_list WHERE remote_id=? AND type=?",
            (data["remote_id"], data["type"]),
        )
        if c.fetchone():
            debug_log(
                f"[DB] 监控项已存在: remote_id={data['remote_id']}, type={data['type']}"
            )
            return False, "已存在该监控项"

        debug_log(f"[DB] 插入监控项数据")
        c.execute(
            """INSERT INTO monitor_list 
            (mid, remote_id, type, name, cover, total_count, last_check_ts, up_mid, desc, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["mid"],
                data["remote_id"],
                data["type"],
                data["name"],
                data["cover"],
                data["total"],
                int(datetime.datetime.now().timestamp()),
                data["mid"],
                data["desc"],
                1,
            ),  # 默认激活
        )
        conn.commit()
        debug_log(f"[DB] 监控项添加成功")
    finally:
        data_pool.return_connection(conn)
    return True, "添加成功"


def update_monitor_active_status(monitor_id, is_active):
    """更新监控项的激活状态"""
    debug_log(
        f"[DB] 更新监控项激活状态: monitor_id={monitor_id}, is_active={is_active}"
    )
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE monitor_list SET is_active=? WHERE id=?", (is_active, monitor_id)
        )
        conn.commit()
        debug_log(f"[DB] 监控项激活状态更新成功")
        return True, "状态更新成功"
    except Exception as e:
        logger.error(
            f"更新监控项状态失败: {e}, monitor_id={monitor_id}, is_active={is_active}"
        )
        return False, f"更新失败: {str(e)}"
    finally:
        data_pool.return_connection(conn)


def get_active_monitors():
    """获取所有激活的监控项"""
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM monitor_list WHERE is_active=1 ORDER BY id DESC")
        return [dict(row) for row in c.fetchall()]
    finally:
        data_pool.return_connection(conn)


def get_monitors():
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        debug_log(f"[DB] 获取所有监控项列表")
        c.execute("SELECT * FROM monitor_list ORDER BY id DESC")
        monitors = [dict(row) for row in c.fetchall()]
        debug_log(f"[DB] 获取到{len(monitors)}个监控项")
        return monitors
    finally:
        data_pool.return_connection(conn)


def delete_monitor(monitor_id):
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        debug_log(f"[DB] 删除监控项: monitor_id={monitor_id}")
        c.execute("DELETE FROM monitor_list WHERE id=?", (monitor_id,))
        conn.commit()
        debug_log(f"[DB] 监控项删除成功")
    finally:
        data_pool.return_connection(conn)


def update_monitor_status(monitor_id, new_total, timestamp):
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        debug_log(
            f"[DB] 更新监控项状态: monitor_id={monitor_id}, new_total={new_total}, timestamp={timestamp}"
        )
        c.execute(
            "UPDATE monitor_list SET total_count=?, last_check_ts=? WHERE id=?",
            (new_total, timestamp, monitor_id),
        )
        conn.commit()
        debug_log(f"[DB] 更新监控项状态成功")
    finally:
        data_pool.return_connection(conn)


def update_monitor_archived_status(monitor_id, archived):
    """更新监控项的归档状态"""
    debug_log(f"[DB] 更新监控项归档状态: monitor_id={monitor_id}, archived={archived}")
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        # 归档时同时暂停监控
        if archived:
            c.execute(
                "UPDATE monitor_list SET archived=?, is_active=0 WHERE id=?",
                (archived, monitor_id),
            )
        else:
            c.execute(
                "UPDATE monitor_list SET archived=? WHERE id=?", (archived, monitor_id)
            )
        conn.commit()
        debug_log(f"[DB] 监控项归档状态更新成功")
        return True, "状态更新成功"
    except Exception as e:
        logger.error(
            f"更新监控项归档状态失败: {e}, monitor_id={monitor_id}, archived={archived}"
        )
        return False, f"更新失败: {str(e)}"
    finally:
        data_pool.return_connection(conn)


def get_archived_monitors():
    """获取所有已归档的监控项"""
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        debug_log(f"[DB] 获取已归档监控项列表")
        c.execute("SELECT * FROM monitor_list WHERE archived=1 ORDER BY id DESC")
        monitors = [dict(row) for row in c.fetchall()]
        debug_log(f"[DB] 获取到{len(monitors)}个已归档监控项")
        return monitors
    finally:
        data_pool.return_connection(conn)


def add_video_update(monitor_id, video_id, video_title, publish_time, cover):
    """添加视频更新记录"""
    debug_log(
        f"[DB] 添加视频更新记录: monitor_id={monitor_id}, video_id={video_id}, title={video_title}"
    )
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        # 先检查是否已存在相同的视频记录
        debug_log(f"[DB] 检查视频是否已存在: video_id={video_id}")
        c.execute("SELECT id FROM video_updates WHERE video_id=?", (video_id,))
        if c.fetchone():
            debug_log(f"[DB] 视频记录已存在: video_id={video_id}")
            return False, "该视频已存在记录"

        debug_log(f"[DB] 插入视频更新记录")
        c.execute(
            """INSERT INTO video_updates 
            (monitor_id, video_id, video_title, publish_time, cover)
            VALUES (?, ?, ?, ?, ?)""",
            (monitor_id, video_id, video_title, publish_time, cover),
        )

        # 获取后端保存最近更新视频数量限制
        c.execute("SELECT value FROM settings WHERE key='recent_updates_save_limit'")
        limit_row = c.fetchone()
        limit = int(limit_row[0]) if limit_row else 5

        # 清理旧记录，只保留最新的limit条记录
        debug_log(f"[DB] 准备清理旧视频记录，保留最新{limit}条")
        c.execute(
            """SELECT id, cover FROM video_updates 
                     ORDER BY publish_time DESC LIMIT -1 OFFSET ?""",
            (limit,),
        )
        old_records = [row for row in c.fetchall()]

        if old_records:
            # 提取旧记录的ID和封面URL
            old_ids = [row[0] for row in old_records]
            old_covers = [row[1] for row in old_records if row[1]]

            # 删除旧记录
            c.execute(
                f"DELETE FROM video_updates WHERE id IN ({','.join(['?']*len(old_ids))})",
                old_ids,
            )
            logger.info(f"清理了{len(old_ids)}条旧视频更新记录")
            debug_log(f"[DB] 清理了{len(old_ids)}条旧视频更新记录")

            # 清理对应的图片缓存
            import hashlib
            import os

            cache_dir = os.path.join(BASE_DIR, "cache", "images")

            for cover_url in old_covers:
                try:
                    # 生成缓存文件名
                    url_hash = hashlib.md5(cover_url.encode("utf-8")).hexdigest()
                    # 获取文件扩展名
                    from urllib.parse import urlparse

                    parsed_url = urlparse(cover_url)
                    ext = (
                        parsed_url.path.split(".")[-1]
                        if "." in parsed_url.path
                        else "jpg"
                    )
                    if len(ext) > 10:
                        ext = "jpg"

                    # 构建完整缓存路径
                    cache_path = os.path.join(cache_dir, f"{url_hash}.{ext}")

                    # 删除缓存文件
                    if os.path.exists(cache_path):
                        os.remove(cache_path)
                        logger.info(f"清理了图片缓存: {cache_path}")
                except Exception as e:
                    logger.error(f"清理图片缓存时出错: {e}")

        conn.commit()
    finally:
        data_pool.return_connection(conn)
    return True, "添加成功"


def get_recent_updates(limit=None):
    """获取最近更新的视频，按发布时间倒序排列"""
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        debug_log(
            f"[DB] 获取最近更新视频记录，限制{limit if limit is not None else '默认'}"
        )

        # 如果没有指定limit参数，则从设置中获取
        if limit is None:
            c.execute("SELECT value FROM settings WHERE key='recent_updates_limit'")
            limit_row = c.fetchone()
            limit = int(limit_row[0]) if limit_row else 5
            debug_log(f"[DB] 从设置获取到最近更新限制: {limit}")

        c.execute(
            """SELECT vu.*, ml.name as monitor_name FROM video_updates vu 
                     JOIN monitor_list ml ON vu.monitor_id = ml.id 
                     ORDER BY vu.publish_time DESC LIMIT ?""",
            (limit,),
        )
        updates = [dict(row) for row in c.fetchall()]
        debug_log(f"[DB] 获取到{len(updates)}条最近更新视频记录")
        return updates
    finally:
        data_pool.return_connection(conn)


def get_monitor_update_stats(monitor_id):
    """获取单个监控项的视频更新统计信息，包括平均更新间隔和推测下一次更新时间"""
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        debug_log(f"[DB] 获取监控项更新统计: monitor_id={monitor_id}")

        # 获取该监控项的所有视频发布时间，按时间倒序排列
        c.execute(
            """SELECT publish_time FROM video_updates 
                     WHERE monitor_id = ? 
                     ORDER BY publish_time DESC""",
            (monitor_id,),
        )
        publish_times = [row[0] for row in c.fetchall()]

        return _calculate_update_stats(monitor_id, publish_times)
    finally:
        data_pool.return_connection(conn)


def get_batch_monitor_update_stats(monitor_ids):
    """批量获取多个监控项的视频更新统计信息"""
    conn = data_pool.get_connection()
    try:
        c = conn.cursor()
        debug_log(f"[DB] 批量获取监控项更新统计: monitor_ids={monitor_ids}")

        # 使用IN语句批量获取所有监控项的发布时间
        placeholders = ",".join(["?"] * len(monitor_ids))
        c.execute(
            f"""SELECT monitor_id, publish_time FROM video_updates 
                     WHERE monitor_id IN ({placeholders}) 
                     ORDER BY monitor_id, publish_time DESC""",
            tuple(monitor_ids),
        )

        # 按monitor_id分组
        monitor_times = {}
        for row in c.fetchall():
            monitor_id, publish_time = row
            if monitor_id not in monitor_times:
                monitor_times[monitor_id] = []
            monitor_times[monitor_id].append(publish_time)

        # 为每个监控项计算统计信息
        results = {}
        for monitor_id in monitor_ids:
            publish_times = monitor_times.get(monitor_id, [])
            results[monitor_id] = _calculate_update_stats(monitor_id, publish_times)

        debug_log(f"[DB] 批量统计完成，共处理{len(results)}个监控项")
        return results
    finally:
        data_pool.return_connection(conn)


def _calculate_update_stats(monitor_id, publish_times):
    """计算单个监控项的更新统计信息"""
    if len(publish_times) < 2:
        # 如果视频数量不足2个，无法计算间隔
        debug_log(
            f"[DB] 视频数量不足，无法计算更新间隔: monitor_id={monitor_id}, {len(publish_times)}个视频"
        )
        return {
            "average_interval_days": None,
            "next_update_prediction": None,
            "total_videos": len(publish_times),
            "last_update_time": publish_times[0] if publish_times else None,
        }

    # 计算相邻视频发布的时间间隔（单位：天）
    intervals = []
    for i in range(len(publish_times) - 1):
        interval_days = (publish_times[i] - publish_times[i + 1]) / (
            24 * 3600
        )  # 转换为天
        intervals.append(interval_days)

    # 计算平均间隔
    average_interval = sum(intervals) / len(intervals)

    # 推测下一次更新时间（基于最近一次发布时间 + 平均间隔）
    last_update_time = publish_times[0]
    next_update_prediction = last_update_time + (average_interval * 24 * 3600)

    return {
        "average_interval_days": round(average_interval, 2),
        "next_update_prediction": int(next_update_prediction),
        "total_videos": len(publish_times),
        "last_update_time": last_update_time,
        "intervals_count": len(intervals),
    }
