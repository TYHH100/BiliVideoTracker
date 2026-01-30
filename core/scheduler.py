import datetime
import json
import os
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler

import core.database as db
from core import daily_log_maintenance, debug_log, logger
from core.bili_api import BiliAPI
from core.notifier import send_notification

# 确定数据目录路径 (兼容 PyInstaller 打包后的路径)
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

# 检查缓存文件路径
CHECKED_CACHE_FILE = os.path.join(DATA_DIR, 'checked_monitors.json')

# 缓存过期时间（秒）
CACHE_EXPIRY = 2700  # 45分钟



# 加载已检查的监控项缓存
def load_checked_cache():
    """加载已检查的监控项缓存"""
    try:
        if os.path.exists(CHECKED_CACHE_FILE):
            with open(CHECKED_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"加载检查缓存失败: {e}")
    return {}

# 保存已检查的监控项缓存
def save_checked_cache(cache):
    """保存已检查的监控项缓存"""
    try:
        with open(CHECKED_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存检查缓存失败: {e}")

# 检查监控项是否已检查过
def is_monitor_checked(monitor):
    """检查监控项是否已检查过"""
    cache = load_checked_cache()
    monitor_key = f"{monitor['type']}:{monitor['remote_id']}:{monitor['mid']}"
    
    if monitor_key in cache:
        check_info = cache[monitor_key]
        checked_time = check_info.get('checked_at', 0)
        # 检查缓存是否过期
        if time.time() - checked_time < CACHE_EXPIRY:
            debug_log(f"[SCHEDULER] 监控项 {monitor['name']} 最近5分钟内已检查过，跳过")
            return True
    return False

# 标记监控项为已检查
def mark_monitor_checked(monitor, info):
    """标记监控项为已检查"""
    cache = load_checked_cache()
    monitor_key = f"{monitor['type']}:{monitor['remote_id']}:{monitor['mid']}"
    
    cache[monitor_key] = {
        'checked_at': time.time(),
        'total': info.get('total', 0),
        'name': monitor['name']
    }
    
    save_checked_cache(cache)
    debug_log(f"[SCHEDULER] 标记监控项 {monitor['name']} 为已检查")

# 清空检查缓存
def clear_checked_cache():
    """清空检查缓存"""
    try:
        if os.path.exists(CHECKED_CACHE_FILE):
            os.remove(CHECKED_CACHE_FILE)
        debug_log(f"[SCHEDULER] 清空检查缓存")
    except Exception as e:
        logger.error(f"清空检查缓存失败: {e}")

scheduler = BackgroundScheduler()
bili_api = BiliAPI()


def check_updates_job():
    """定时检查任务逻辑"""
    current_time = datetime.datetime.now()
    logger.info(f"[{current_time}] 开始检查更新...")
    print(f"[{current_time}] 开始检查更新...")
    debug_log(f"[SCHEDULER] 开始检查更新任务")

    settings = db.get_all_settings()
    monitors = db.get_active_monitors()
    debug_log(f"[SCHEDULER] 获取到 {len(monitors)} 个合集监控项")

    logger.info(f"共检查 {len(monitors)} 个合集监控项")

    # 获取冷却时间配置，提供默认值
    item_cooldown = int(
        settings.get("item_cooldown", 30)
    )  # 单个监控项检查间隔，默认为30秒
    debug_log(f"[SCHEDULER] 单个监控项检查间隔: {item_cooldown}秒")

    # 更新下次检查时间到数据库（用于前端显示）
    # 简单处理：这里显示的是"正在检查"，下次时间可以在任务结束后计算
    db.update_setting("next_check_time", "正在运行...")
    debug_log(f"[SCHEDULER] 更新下次检查时间为'正在运行...'")

    has_update = False
    # 收集更新信息，用于集中发送邮件
    batch_updates = []
    # 收集失败的监控项，用于后续重新检查
    failed_monitors = []
    # 反爬检测标志
    anti_crawl_detected = False
    debug_log(f"[SCHEDULER] 初始化批量更新列表和失败监控项列表")

    for item in monitors:
        # 检查是否最近5分钟内已检查过
        if is_monitor_checked(item):
            continue
            
        debug_log(
            f"[SCHEDULER] 检查监控项: {item['name']} (类型: {item['type']}, ID: {item['remote_id']})"
        )
        # 获取最新信息
        info = bili_api.get_info(item["type"], item["remote_id"], item["mid"])
        if not info:
            debug_log(f"[SCHEDULER] 获取{item['name']}信息失败，可能触发了反爬机制")
            # 检测到反爬，中止后续操作
            anti_crawl_detected = True
            break
        
        # 标记为已检查
        mark_monitor_checked(item, info)

        current_total = item["total_count"]
        remote_total = info["total"]
        debug_log(
            f"[SCHEDULER] {item['name']} - 当前记录总数: {current_total}, B站实际总数: {remote_total}"
        )

        # 记录检查合集的信息
        logger.info(
            f"检查合集: {item['name']} (类型: {item['type']}, ID: {item['remote_id']})"
        )
        logger.info(f"  - 当前数据库记录总数: {current_total}")
        logger.info(f"  - B站实际总数: {remote_total}")

        # 发现更新
        if remote_total > current_total:
            diff = remote_total - current_total
            logger.info(f"  - 检测到更新: {diff} 个新视频")
            print(f"检测到 {item['name']} 更新了 {diff} 个视频")
            debug_log(f"[SCHEDULER] {item['name']} - 检测到更新: {diff} 个新视频")

            # 获取最新视频列表并添加到更新记录
            latest_videos = bili_api.get_latest_videos(
                item["type"], item["remote_id"], item["mid"], item.get("up_mid", item["mid"]), diff
            )
            debug_log(
                f"[SCHEDULER] {item['name']} - 获取到 {len(latest_videos)} 个最新视频"
            )

            # 获取最新视频的发布时间
            update_time = datetime.datetime.now()
            if latest_videos:
                # 最新视频在列表的第一个位置（因为sort_reverse=true）
                update_time = datetime.datetime.fromtimestamp(
                    latest_videos[0]["publish_time"]
                )
            debug_log(f"[SCHEDULER] {item['name']} - 更新时间: {update_time}")

            # 构建最新视频列表的HTML内容
            videos_html = ""
            for video in latest_videos:
                video_time = datetime.datetime.fromtimestamp(
                    video["publish_time"]
                ).strftime("%Y-%m-%d %H:%M")
                # 检查视频ID格式，如果是纯数字（AV号）则添加av前缀，否则直接使用（BV号）
                if video["video_id"].isdigit():
                    video_url = f"https://www.bilibili.com/video/av{video['video_id']}"
                else:
                    video_url = f"https://www.bilibili.com/video/{video['video_id']}"
                videos_html += f"<p>• <a href='{video_url}'>{video['title']}</a> ({video_time})</p>"

            # 构建更新信息
            update_info = {
                "name": item["name"],
                "diff": diff,
                "remote_total": remote_total,
                "update_time": update_time,
                "videos_html": videos_html,
                "mid": item["mid"],
                "remote_id": item["remote_id"],
                "type": item["type"],
            }

            # 检查是否启用集中发送
            if settings.get("smtp_batch_send") == "1":
                # 启用集中发送，收集更新信息
                batch_updates.append(update_info)
                debug_log(f"[SCHEDULER] {item['name']} - 添加到批量更新列表")
            else:
                # 不启用集中发送，立即发送邮件
                subject = f"【更新】{item['name']} 更新了 {diff} 个视频"
                content = f"""
                <h3>{item['name']}</h3>
                <p><b>更新数量:</b> {diff}</p>
                <p><b>当前总数:</b> {remote_total}</p>
                <p><b>更新时间:</b> {update_time.strftime('%Y-%m-%d %H:%M')}</p>
                <h4>最新视频：</h4>
                {videos_html}
                <h4>合集链接：</h4>
                <p><a href="https://space.bilibili.com/{item['mid']}/lists/{item['remote_id']}?type={item['type']}">点击查看合集/系列</a></p>
                """

                # 发送通知
                if settings.get("smtp_enable") == "1":
                    debug_log(f"[SCHEDULER] {item['name']} - 发送更新通知")
                    debug_log(f"[SCHEDULER] 邮件主题: {subject}")
                    debug_log(f"[SCHEDULER] 邮件内容预览: {content[:200]}...")
                    send_notification(settings, subject, content)

            # 2. 添加视频更新记录到数据库
            for video in latest_videos:
                debug_log(
                    f"[SCHEDULER] {item['name']} - 添加视频更新记录: {video['title']}"
                )
                success, msg = db.add_video_update(
                    item["id"],
                    video["video_id"],
                    video["title"],
                    video["publish_time"],
                    video["cover"],
                )
                debug_log(f"[SCHEDULER] 添加视频记录结果: 成功={success}, 消息={msg}")

            # 3. 更新数据库
            debug_log(
                f"[SCHEDULER] {item['name']} - 更新监控项状态，新总数: {remote_total}"
            )
            db.update_monitor_status(
                item["id"], remote_total, int(datetime.datetime.now().timestamp())
            )
            has_update = True

        # 在每次检查之间增加冷却时间，避免风控
        time.sleep(item_cooldown)
        debug_log(f"[SCHEDULER] 检查间隔冷却: {item_cooldown}秒")

    # 检查是否有集中发送的更新信息
    if batch_updates and settings.get("smtp_enable") == "1":
        # 如果只有1个更新，采用常规发送方式
        if len(batch_updates) == 1:
            update = batch_updates[0]
            subject = f"【更新】{update['name']} 更新了 {update['diff']} 个视频"
            content = f"""
            <h3>{update['name']}</h3>
            <p><b>更新数量:</b> {update['diff']}</p>
            <p><b>当前总数:</b> {update['remote_total']}</p>
            <p><b>更新时间:</b> {update['update_time'].strftime('%Y-%m-%d %H:%M')}</p>
            <h4>最新视频：</h4>
            {update['videos_html']}
            <h4>合集链接：</h4>
            <p><a href="https://space.bilibili.com/{update['mid']}/lists/{update['remote_id']}?type={update['type']}">点击查看合集/系列</a></p>
            """
            
            debug_log(f"[SCHEDULER] 只有1个更新，采用常规发送方式")
            debug_log(f"[SCHEDULER] 邮件主题: {subject}")
            debug_log(f"[SCHEDULER] 邮件内容预览: {content[:200]}...")
            send_notification(settings, subject, content)
        else:
            # 有2个或更多更新，采用统一发送方式
            # 构建集中发送的邮件内容
            total_updates = sum(update["diff"] for update in batch_updates)
            subject = f"[统一推送] 共检测到 {len(batch_updates)} 个合集更新，新增 {total_updates} 个视频"
            debug_log(
                f"[SCHEDULER] 统一推送更新通知 - 合集数: {len(batch_updates)}, 总视频数: {total_updates}"
            )

            # 构建批量邮件的HTML内容
            batch_content = f"""
            <h2>B站合集监控统一推送通知</h2>
            <p><b>总更新合集数:</b> {len(batch_updates)}</p>
            <p><b>总更新视频数:</b> {total_updates}</p>
            <p><b>检查时间:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <hr>
            """

            # 添加每个更新的详细信息
            for update in batch_updates:
                batch_content += f"""
                <h3>{update['name']}</h3>
                <p><b>更新数量:</b> {update['diff']}</p>
                <p><b>当前总数:</b> {update['remote_total']}</p>
                <p><b>更新时间:</b> {update['update_time'].strftime('%Y-%m-%d %H:%M')}</p>
                <h4>最新视频：</h4>
                {update['videos_html']}
                <h4>合集链接：</h4>
                <p><a href="https://space.bilibili.com/{update['mid']}/lists/{update['remote_id']}?type={update['type']}">点击查看合集/系列</a></p>
                <hr>
                """

            # 发送批量更新邮件
            debug_log(f"[SCHEDULER] 发送批量更新邮件")
            debug_log(f"[SCHEDULER] 批量邮件主题: {subject}")
            debug_log(f"[SCHEDULER] 批量邮件内容长度: {len(batch_content)} 字符")
            debug_log(f"[SCHEDULER] 批量邮件内容预览: {batch_content[:300]}...")
            send_notification(settings, subject, batch_content)

    # 重新检查失败的监控项（仅在未检测到反爬时执行）
    if failed_monitors and not anti_crawl_detected:
        logger.info(f"[{datetime.datetime.now()}] 开始重新检查 {len(failed_monitors)} 个失败的监控项")
        print(f"开始重新检查 {len(failed_monitors)} 个失败的监控项...")
        debug_log(f"[SCHEDULER] 开始重新检查 {len(failed_monitors)} 个失败的监控项")
        
        # 添加额外的延迟，避免触发反爬机制
        time.sleep(5)  # 等待5秒
        
        for item in failed_monitors:
            logger.info(f"重新检查失败监控项: {item['name']}")
            debug_log(f"[SCHEDULER] 重新检查失败监控项: {item['name']} (类型: {item['type']}, ID: {item['remote_id']})")
            
            # 添加额外的延迟
            time.sleep(2)  # 每个失败项之间等待2秒
            
            # 获取最新信息
            info = bili_api.get_info(item["type"], item["remote_id"], item["mid"])
            if not info:
                debug_log(f"[SCHEDULER] 重新检查{item['name']}仍然失败，跳过")
                continue
            
            current_total = item["total_count"]
            remote_total = info["total"]
            debug_log(
                f"[SCHEDULER] {item['name']} - 当前记录总数: {current_total}, B站实际总数: {remote_total}"
            )
            
            # 发现更新
            if remote_total > current_total:
                diff = remote_total - current_total
                logger.info(f"  - 检测到更新: {diff} 个新视频")
                print(f"检测到 {item['name']} 更新了 {diff} 个视频")
                debug_log(f"[SCHEDULER] {item['name']} - 检测到更新: {diff} 个新视频")
                
                # 获取最新视频列表并添加到更新记录
                latest_videos = bili_api.get_latest_videos(
                    item["type"], item["remote_id"], item["mid"], item.get("up_mid", item["mid"]), diff
                )
                debug_log(
                    f"[SCHEDULER] {item['name']} - 获取到 {len(latest_videos)} 个最新视频"
                )
                
                # 获取最新视频的发布时间
                update_time = datetime.datetime.now()
                if latest_videos:
                    # 最新视频在列表的第一个位置
                    update_time = datetime.datetime.fromtimestamp(
                        latest_videos[0]["publish_time"]
                    )
                debug_log(f"[SCHEDULER] {item['name']} - 更新时间: {update_time}")
                
                # 添加视频更新记录到数据库
                for video in latest_videos:
                    debug_log(
                        f"[SCHEDULER] {item['name']} - 添加视频更新记录: {video['title']}"
                    )
                    success, msg = db.add_video_update(
                        item["id"],
                        video["video_id"],
                        video["title"],
                        video["publish_time"],
                        video["cover"],
                    )
                
                # 更新数据库中的总数
                db.update_monitor_count(item["id"], remote_total)
                debug_log(f"[SCHEDULER] {item['name']} - 更新总数为: {remote_total}")
                
                has_update = True
                
                # 构建更新信息
                videos_html = ""
                for video in latest_videos:
                    video_time = datetime.datetime.fromtimestamp(
                        video["publish_time"]
                    ).strftime("%Y-%m-%d %H:%M")
                    if video["video_id"].isdigit():
                        video_url = f"https://www.bilibili.com/video/av{video['video_id']}"
                    else:
                        video_url = f"https://www.bilibili.com/video/{video['video_id']}"
                    videos_html += f"<p><a href='{video_url}' target='_blank'>{video['title']}</a> ({video_time})</p>"
                
                # 添加到批量更新列表
                batch_updates.append({
                    "id": item["id"],
                    "name": item["name"],
                    "type": item["type"],
                    "remote_id": item["remote_id"],
                    "mid": item["mid"],
                    "diff": diff,
                    "remote_total": remote_total,
                    "update_time": update_time,
                    "videos_html": videos_html
                })
    
    # 计算下一次检查时间
    if anti_crawl_detected:
        # 检测到反爬，强制延迟35分钟
        logger.warning(f"[{datetime.datetime.now()}] 检测到反爬机制，强制延迟35分钟后再检查")
        print("检测到反爬机制，强制延迟35分钟后再检查...")
        debug_log(f"[SCHEDULER] 检测到反爬机制，强制延迟35分钟后再检查")
        
        # 强制延迟35分钟
        cooldown_seconds = 35 * 60  # 35分钟
        next_time = datetime.datetime.now() + datetime.timedelta(seconds=cooldown_seconds)
        db.update_setting("next_check_time", next_time.strftime("%Y-%m-%d %H:%M:%S"))
        debug_log(
            f"[SCHEDULER] 由于反爬，更新下次检查时间为: {next_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        # 更新全局冷却时间配置，确保下次检查也使用35分钟
        db.update_setting("global_cooldown", str(cooldown_seconds))
        debug_log(f"[SCHEDULER] 更新全局冷却时间为: {cooldown_seconds}秒")
    else:
        # 正常情况，使用配置的冷却时间
        global_cooldown = int(
            settings.get("global_cooldown", 1200)
        )  # 使用与实际调度相同的默认值1200秒
        next_time = datetime.datetime.now() + datetime.timedelta(seconds=global_cooldown)
        db.update_setting("next_check_time", next_time.strftime("%Y-%m-%d %H:%M:%S"))
        debug_log(
            f"[SCHEDULER] 更新下次检查时间为: {next_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    logger.info(f"[{datetime.datetime.now()}] 检查完成")
    print("检查完成")
    debug_log(f"[SCHEDULER] 更新检查任务完成")


def daily_log_maintenance_job():
    """每日日志维护定时任务（切割和清理）"""
    # logger.info("开始执行每日日志维护任务...")

    # 获取日志清理相关设置
    settings = db.get_all_settings()
    log_auto_clean = settings.get("log_auto_clean", "1")

    if log_auto_clean == "1":
        # 获取保留天数
        retention_days = int(settings.get("log_retention_days", "7"))

        # 执行每日日志维护（切割和清理）
        daily_log_maintenance(retention_days=retention_days)
    else:
        logger.info("日志自动清理功能已关闭")


def start_scheduler():
    debug_log(f"[SCHEDULER] 准备启动调度器")
    if not scheduler.running:
        debug_log(f"[SCHEDULER] 启动调度器实例")
        scheduler.start()

    # 清除旧任务
    debug_log(f"[SCHEDULER] 清除所有旧任务")
    scheduler.remove_all_jobs()

    # 添加每日日志维护任务（每天零点执行）
    debug_log(f"[SCHEDULER] 添加每日日志维护任务（每天零点执行）")
    scheduler.add_job(
        daily_log_maintenance_job,
        "cron",
        hour=0,
        minute=0,
        id="daily_log_maintenance_job",
    )
    logger.info("已添加每日日志维护定时任务（每天零点执行）")

    # 检查监控开关
    settings = db.get_all_settings()
    debug_log(f"[SCHEDULER] 获取监控开关设置")
    if settings.get("monitor_active") == "1":
        # 获取全局冷却时间，提供默认值 (10分钟)
        global_cooldown = int(settings.get("global_cooldown", 600))
        debug_log(f"[SCHEDULER] 监控开启，全局冷却时间: {global_cooldown}秒")
        # 添加监控任务，间隔 global_cooldown 秒
        scheduler.add_job(
            check_updates_job, "interval", seconds=global_cooldown, id="monitor_job"
        )
        # 立即运行一次
        # scheduler.add_job(check_updates_job, 'date', run_date=datetime.datetime.now() + datetime.timedelta(seconds=5))
        print("调度器已启动: 监控开启")
        debug_log(f"[SCHEDULER] 调度器已启动: 监控开启")
    else:
        db.update_setting("next_check_time", "监控已停止")
        print("调度器已启动: 监控关闭")
        debug_log(f"[SCHEDULER] 调度器已启动: 监控关闭")


def stop_monitor():
    db.update_setting("monitor_active", "0")
    start_scheduler()  # 重新加载配置（移除任务）


def start_monitor():
    db.update_setting("monitor_active", "1")
    start_scheduler()  # 重新加载配置（添加任务）


def check_single_monitor(monitor_id):
    """检查单个监控项的更新"""
    current_time = datetime.datetime.now()
    debug_log(f"[SCHEDULER] 开始检查单个监控项: {monitor_id}")

    # 获取监控项信息
    monitor = None
    monitors = db.get_monitors()
    for item in monitors:
        if item["id"] == monitor_id:
            monitor = item
            break

    if not monitor:
        debug_log(f"[SCHEDULER] 未找到监控项: {monitor_id}")
        return

    settings = db.get_all_settings()

    debug_log(
        f"[SCHEDULER] 检查监控项: {monitor['name']} (类型: {monitor['type']}, ID: {monitor['remote_id']})"
    )

    # 获取最新信息
    info = bili_api.get_info(monitor["type"], monitor["remote_id"], monitor["mid"])
    if not info:
        debug_log(f"[SCHEDULER] 获取{monitor['name']}信息失败，跳过")
        return

    current_total = monitor["total_count"]
    remote_total = info["total"]
    debug_log(
        f"[SCHEDULER] {monitor['name']} - 当前记录总数: {current_total}, B站实际总数: {remote_total}"
    )

    # 更新数据库中的总数
    db.update_monitor_status(
        monitor["id"], remote_total, int(datetime.datetime.now().timestamp())
    )

    # 如果有新视频，添加到更新记录
    if remote_total > current_total:
        diff = remote_total - current_total
        debug_log(f"[SCHEDULER] {monitor['name']} - 检测到更新: {diff} 个新视频")

        # 获取最新视频列表并添加到更新记录
        latest_videos = bili_api.get_latest_videos(
            monitor["type"], monitor["remote_id"], monitor["mid"], monitor.get("up_mid", monitor["mid"]), diff
        )
        debug_log(
            f"[SCHEDULER] {monitor['name']} - 获取到 {len(latest_videos)} 个最新视频"
        )

        # 添加视频更新记录到数据库
        for video in latest_videos:
            debug_log(
                f"[SCHEDULER] {monitor['name']} - 添加视频更新记录: {video['title']}"
            )
            success, msg = db.add_video_update(
                monitor["id"],
                video["video_id"],
                video["title"],
                video["publish_time"],
                video["cover"],
            )


def run_once():
    """手动立即检查"""
    debug_log(f"[SCHEDULER] 手动触发立即检查任务")
    scheduler.add_job(check_updates_job, "date", run_date=datetime.datetime.now())
