from flask import Flask, request, jsonify, render_template, Response, send_from_directory
import os
import core.database as db
from core.bili_api import BiliAPI
import core.scheduler as sched
import core.notifier as notifier
import secrets
import requests
import sys
import uuid
import argparse
import hashlib
import mimetypes
from urllib.parse import urlparse
import time
import logging
from core import debug_log

# 配置日志
logger = logging.getLogger(__name__)

# 处理 PyInstaller 路径
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask('BiliVideoTracker', template_folder=template_folder, static_folder=static_folder)
else:
    app = Flask('BiliVideoTracker')

# 创建data目录
# 获取应用根目录，兼容PyInstaller打包环境
if getattr(sys, 'frozen', False):
    # 打包后的环境
    project_root = sys._MEIPASS
    # 数据目录放在程序所在目录，与database.py保持一致
    data_dir = os.path.join(os.path.dirname(sys.executable), 'data')
else:
    # 开发环境
    project_root = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(project_root, 'data')

if not os.path.exists(data_dir):
    os.makedirs(data_dir)

# 创建cache/uploads目录用于保存上传的图片
if getattr(sys, 'frozen', False):
    # 打包后的环境，使用程序所在目录
    uploads_dir = os.path.join(os.path.dirname(sys.executable), 'cache', 'uploads')
    # 创建cache/images目录用于保存图片缓存
    cache_dir = os.path.join(os.path.dirname(sys.executable), 'cache', 'images')
else:
    # 开发环境，将uploads目录放在cache目录下
    uploads_dir = os.path.join(project_root, 'cache', 'uploads')
    # 创建cache/images目录用于保存图片缓存
    cache_dir = os.path.join(project_root, 'cache', 'images')

# 确保cache和uploads目录存在
if not os.path.exists(os.path.dirname(uploads_dir)):
    os.makedirs(os.path.dirname(uploads_dir), exist_ok=True)
if not os.path.exists(uploads_dir):
    os.makedirs(uploads_dir, exist_ok=True)

# 创建cache/images目录
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir, exist_ok=True)

# 初始化
db.init_dbs()
sched.start_scheduler()
api_client = BiliAPI()

# --- 鉴权装饰器 ---
def auth_required(f):
    """API请求认证装饰器"""
    def wrapper(*args, **kwargs):
        # 检查Authorization头
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'code': 401, 'msg': '缺少认证令牌'}), 401
        
        # 验证令牌
        if not db.verify_token(token):
            return jsonify({'code': 401, 'msg': '无效的认证令牌'}), 401
            
        return f(*args, **kwargs)
    # 设置装饰器函数的名称，避免Flask路由冲突
    wrapper.__name__ = f.__name__
    return wrapper

# 兼容旧的check_auth函数
def check_auth():
    token = request.headers.get('Authorization')
    return db.verify_token(token)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/public/status', methods=['GET'])
def get_public_status():
    """公共API：获取监控列表和最近更新"""
    try:
        # 获取监控列表
        monitors = db.get_monitors()
        # 获取最近更新
        updates = db.get_recent_updates(limit=10)
        # 获取运行状态和下次检查时间
        settings = db.get_all_settings()
        
        return jsonify({
            'code': 0,
            'monitors': monitors,
            'updates': updates,
            'status': {
                'active': settings.get('monitor_active') == '1',
                'next_check': settings.get('next_check_time', '--')
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500

# --- API 接口 ---

@app.route('/api/login', methods=['POST'])
def login():
    try:
        # 验证请求格式
        if not request.is_json:
            return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
        
        data = request.json
        token = data.get('token')
        
        if not token:
            return jsonify({'code': 400, 'msg': '缺少令牌参数'}), 400
        
        if db.verify_token(token):
            return jsonify({'code': 0, 'msg': '认证成功'})
        return jsonify({'code': 401, 'msg': '令牌错误'}), 401
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500

@app.route('/api/status', methods=['GET'])
@auth_required
def get_status():
    """获取主页状态信息"""
    settings = db.get_all_settings()
    monitors = db.get_monitors()
    
    return jsonify({
        'code': 0,
        'status': {
            'active': settings.get('monitor_active') == '1',
            'next_check': settings.get('next_check_time', '--')
        },
        'monitors': monitors
    })

@app.route('/api/control', methods=['POST'])
@auth_required
def control_monitor():
    """启用/停止/立即检查"""
    # 验证请求格式
    if not request.is_json:
        return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
    
    action = request.json.get('action')
    if not action:
        return jsonify({'code': 400, 'msg': '缺少操作参数'}), 400
    
    # 验证操作类型
    if action not in ['start', 'stop', 'check_now']:
        return jsonify({'code': 400, 'msg': '无效的操作类型'}), 400
    if action == 'start':
        sched.start_monitor()
    elif action == 'stop':
        sched.stop_monitor()
    elif action == 'check_now':
        sched.run_once()
        
    return jsonify({'code': 0, 'msg': '操作成功'})

#@app.route('/api/test/run_once', methods=['GET'])
#def test_run_once():
#    """测试用：立即检查更新，无需身份验证"""
#    try:
#        sched.run_once()
#        return jsonify({'code': 0, 'msg': '手动检查更新已触发'})
#    except Exception as e:
#        import traceback
#        traceback.print_exc()
#        return jsonify({'code': 1, 'msg': f'检查更新失败: {str(e)}'})

@app.route('/api/monitor/add', methods=['POST'])
@auth_required
def add_monitor_item():
    """添加监控"""
    # 验证请求格式
    if not request.is_json:
        return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
    
    url = request.json.get('url')
    if not url:
        return jsonify({'code': 400, 'msg': '缺少监控URL参数'}), 400
    
    # 验证URL格式
    if not url.startswith(('http://', 'https://')):
        return jsonify({'code': 400, 'msg': '无效的URL格式'}), 400
    
    # 解析URL
    mid, remote_id, m_type = api_client.parse_url(url)
    if not mid or not remote_id:
        return jsonify({'code': 400, 'msg': '无法解析该链接，请确保是系列或合集链接'}), 400
    
    # 获取详细信息
    info = api_client.get_info(m_type, remote_id, mid)
    if not info:
        return jsonify({'code': 1, 'msg': '无法从B站获取信息，请检查ID或网络'})
    
    # 存入数据库
    data = {
        'mid': mid,
        'remote_id': remote_id,
        'type': m_type,
        'name': info['name'],
        'cover': info['cover'],
        'total': info['total'],
        'desc': info['desc']
    }
    
    success, msg = db.add_monitor(data)
    if success:
        # 获取新添加监控项的ID
        # 查询刚刚添加的监控项（根据remote_id和type）
        monitors = db.get_monitors()
        new_monitor_id = None
        for monitor in monitors:
            if monitor['remote_id'] == remote_id and monitor['type'] == m_type:
                new_monitor_id = monitor['id']
                break
        
        # 添加成功后立即检查该合集的更新
        from core.scheduler import check_single_monitor
        import threading
        # 在后台线程中执行检查，避免阻塞响应
        if new_monitor_id:
            threading.Thread(target=check_single_monitor, args=(new_monitor_id,), daemon=True).start()
        
        return jsonify({'code': 0, 'msg': '添加成功'})
    else:
        return jsonify({'code': 1, 'msg': msg})

@app.route('/api/monitor/import_old', methods=['POST'])
@auth_required
def import_old_monitor_data():
    """导入旧版监控数据"""
    if not check_auth(): return jsonify({'code': 401}), 401
    
    data = request.json.get('data')
    if not data or not data.get('seasons'):
        return jsonify({'code': 1, 'msg': '无效的数据格式'})
    
    imported_count = 0
    
    for item in data['seasons']:
        # 转换旧版格式到新版数据库格式
        monitor_data = {
            'mid': item.get('mid', ''),
            'remote_id': item.get('series_id', item.get('season_id', '')),
            'type': item.get('type', 'series'),
            'name': item.get('name', ''),
            'cover': item.get('cover', ''),
            'total': item.get('total', item.get('last_episode_count', 0)),
            'desc': ''  # 旧版没有desc字段
        }
        
        if not monitor_data['mid'] or not monitor_data['remote_id']:
            continue
        
        # 添加到数据库
        success, msg = db.add_monitor(monitor_data)
        if success:
            imported_count += 1
    
    return jsonify({'code': 0, 'msg': '导入完成', 'imported': imported_count})

@app.route('/api/monitor/delete', methods=['POST'])
@auth_required
def delete_monitor_item():
    # 验证请求格式
    if not request.is_json:
        return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
    
    monitor_id = request.json.get('id')
    if monitor_id is None:
        return jsonify({'code': 400, 'msg': '缺少监控ID参数'}), 400
    
    # 验证ID格式
    try:
        monitor_id = int(monitor_id)
    except (TypeError, ValueError):
        return jsonify({'code': 400, 'msg': '无效的监控ID格式'}), 400
    
    db.delete_monitor(monitor_id)
    return jsonify({'code': 0, 'msg': '删除成功'})

@app.route('/api/monitor/toggle_active', methods=['POST'])
@auth_required
def toggle_monitor_active():
    if not check_auth(): return jsonify({'code': 401}), 401
    monitor_id = request.json.get('id')
    is_active = request.json.get('is_active')
    success, msg = db.update_monitor_active_status(monitor_id, is_active)
    if success:
        return jsonify({'code': 0, 'msg': msg})
    else:
        return jsonify({'code': 1, 'msg': msg})

@app.route('/api/monitor/recent_updates', methods=['GET'])
@auth_required
def get_recent_updates():
    """获取最近更新的视频列表"""
    # 获取前端显示最近更新视频数量限制
    settings = db.get_all_settings()
    limit = int(settings.get('recent_updates_limit', 10))
    
    # 使用前端显示数量获取更新记录
    updates = db.get_recent_updates(limit=limit)
    return jsonify({'code': 0, 'data': updates})

@app.route('/api/monitor/<int:monitor_id>/update_stats', methods=['GET'])
def get_monitor_update_stats(monitor_id):
    """获取单个监控项的视频更新统计信息"""
    try:
        stats = db.get_monitor_update_stats(monitor_id)
        return jsonify({'code': 0, 'data': stats})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500

@app.route('/api/monitor/batch_update_stats', methods=['POST'])
def batch_get_monitor_update_stats():
    """批量获取多个监控项的视频更新统计信息"""
    try:
        # 验证请求格式
        if not request.is_json:
            return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
        
        data = request.json
        monitor_ids = data.get('monitor_ids', [])
        
        if not isinstance(monitor_ids, list) or len(monitor_ids) == 0:
            return jsonify({'code': 400, 'msg': '无效的监控项ID列表'}), 400
        
        # 限制批量请求数量，避免过度消耗资源
        if len(monitor_ids) > 50:
            return jsonify({'code': 400, 'msg': '批量请求数量不能超过50个'}), 400
        
        # 批量获取统计信息
        stats = db.get_batch_monitor_update_stats(monitor_ids)
        return jsonify({'code': 0, 'data': stats})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500

@app.route('/api/settings/get', methods=['GET'])
@auth_required
def get_settings():
    
    settings = db.get_all_settings()
    token_info = db.get_token_info()
    
    # 脱敏处理
    return jsonify({
        'code': 0,
        'config': settings,
        'token': token_info
    })

@app.route('/api/settings/save', methods=['POST'])
@auth_required
def save_settings():
    # 验证请求格式
    if not request.is_json:
        return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
    
    data = request.json
    # 遍历保存
    allow_keys = ['smtp_enable', 'smtp_server', 'smtp_port', 'email_account', 
                  'email_auth_code', 'sender_name', 'receiver_emails', 'use_tls', 
                  'smtp_batch_send', 'global_cooldown', 'item_cooldown', 'background_image',
                  'server_host', 'server_port', 'recent_updates_limit', 'recent_updates_save_limit',
                  'log_auto_clean', 'log_retention_days', 'debug_mode']
    
    for k in allow_keys:
        if k in data:
            db.update_setting(k, data[k])
            
    return jsonify({'code': 0, 'msg': '保存成功'})

@app.route('/api/debug/set', methods=['POST'])
@auth_required
def set_debug_mode_api():
    """设置Debug模式"""
    # 验证请求格式
    if not request.is_json:
        return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
    
    data = request.json
    enable = data.get('enable', False)
    
    # 更新数据库设置
    db.update_setting('debug_mode', '1' if enable else '0')
    
    # 立即应用debug模式
    from core import set_debug_mode
    set_debug_mode(enable)
    
    return jsonify({'code': 0, 'msg': 'Debug模式已更新'})

@app.route('/api/settings/email_test', methods=['POST'])
@auth_required
def email_test():
    """测试邮件配置"""
    # 验证请求格式
    if not request.is_json:
        return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
    
    # 使用前端传来的临时配置进行测试，而不是数据库里的
    temp_settings = request.json
    if not temp_settings:
        return jsonify({'code': 400, 'msg': '缺少邮件配置参数'}), 400
    subject = "B站视频追踪 - 测试邮件"
    content = "<h1>配置成功</h1><p>如果您收到这封邮件，说明您的SMTP配置正确。</p>"
    
    if notifier.send_notification(temp_settings, subject, content):
        return jsonify({'code': 0, 'msg': '发送成功，请查收'})
    else:
        return jsonify({'code': 1, 'msg': '发送失败，请检查控制台日志或配置'})

@app.route('/api/token/reset', methods=['POST'])
def reset_token():
    # 验证请求格式
    if not request.is_json:
        return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
    
    # 特殊逻辑：如果已存在token，需要先校验旧token
    # 但如果是第一次设置（或物理访问点击重置），这里为了简化，假设只要能访问到这个接口（如果加了auth则需要auth）
    # 实际部署建议：未登录状态下不允许重置，除非手动删库。这里假设必须登录后重置，或者初始状态。
    
    # 简单起见：如果数据库里没token，允许设置。如果有，必须鉴权。
    token_info = db.get_token_info()
    if token_info['exists']:
        if not check_auth(): return jsonify({'code': 401, 'msg': '需要先登录才能重置'}), 401

    new_token = secrets.token_hex(16)
    db.set_token(new_token)
    return jsonify({'code': 0, 'token': new_token})

# 导入所需的库（将导入移到函数外部）
import hashlib
import mimetypes
import time
from urllib.parse import urlparse
from core import logger
from PIL import Image
import io

# --- 图片反代 (绕过B站防盗链) ---
@app.route('/proxy/image')
def proxy_image():
    """图片代理，解决跨域问题并实现服务器端与客户端双重缓存
    
    优先使用服务器本地缓存，如果缓存存在则直接返回，否则从原始URL获取并缓存
    """
    try:
        image_url = request.args.get('url')
        if not image_url:
            return jsonify({"error": "缺少图片URL参数"}), 400
        
        # 验证URL格式
        if not image_url.startswith(('http://', 'https://')):
            return jsonify({"error": "无效的URL格式"}), 400
        
        # 生成基于图片URL的唯一缓存文件名
        url_hash = hashlib.md5(image_url.encode('utf-8')).hexdigest()
        
        # 获取文件扩展名
        parsed_url = urlparse(image_url)
        ext = parsed_url.path.split('.')[-1] if '.' in parsed_url.path else 'jpg'
        
        # 确保扩展名长度合理
        if len(ext) > 10:
            ext = 'jpg'
        
        # 主流浏览器都支持webp格式，直接转换并返回webp格式
        
        # 使用绝对路径确保缓存文件正确保存
        cache_filename = os.path.join(cache_dir, f"{url_hash}.{ext}")
        webp_cache_filename = os.path.join(cache_dir, f"{url_hash}.webp")
        
        # 检查服务器缓存是否存在（优先使用webp格式）
        if os.path.exists(webp_cache_filename):
            logger.debug(f"使用webp缓存图片: {webp_cache_filename}")
            
            # 读取webp缓存文件
            with open(webp_cache_filename, 'rb') as f:
                image_data = f.read()
            
            # 生成ETag
            etag = hashlib.md5(image_data).hexdigest()
            
            # 检查条件请求头
            if request.headers.get('If-None-Match') == etag:
                return '', 304, {
                    'Cache-Control': 'public, max-age=86400',  # 缓存1天
                    'Access-Control-Allow-Origin': '*'
                }
            
            # 返回webp图片
            return Response(
                image_data,
                content_type='image/webp',
                headers={
                    'Cache-Control': 'public, max-age=86400',  # 缓存1天
                    'Access-Control-Allow-Origin': '*',  # 允许跨域访问
                    'ETag': etag,  # 图片内容的唯一标识
                    'Last-Modified': os.path.getmtime(webp_cache_filename)  # 使用缓存文件的修改时间
                }
            )
        elif os.path.exists(cache_filename):
            logger.debug(f"使用服务器缓存图片: {cache_filename}")
            
            # 读取原始缓存文件
            with open(cache_filename, 'rb') as f:
                image_data = f.read()
            
            # 生成ETag
            etag = hashlib.md5(image_data).hexdigest()
            
            # 检查条件请求头
            if request.headers.get('If-None-Match') == etag:
                return '', 304, {
                    'Cache-Control': 'public, max-age=86400',  # 缓存1天
                    'Access-Control-Allow-Origin': '*'
                }
            
            # 返回缓存的图片
            # 检测文件的MIME类型
            content_type, _ = mimetypes.guess_type(cache_filename)
            if not content_type:
                content_type = f'image/{ext}'
                # 如果扩展名也无法确定，使用默认的jpeg类型
                if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg']:
                    content_type = 'image/jpeg'
            
            return Response(
                image_data,
                content_type=content_type,
                headers={
                    'Cache-Control': 'public, max-age=86400',  # 缓存1天，避免长时间缓存过期图片
                    'Access-Control-Allow-Origin': '*',  # 允许跨域访问
                    'ETag': etag,  # 图片内容的唯一标识
                    'Last-Modified': os.path.getmtime(cache_filename)  # 使用缓存文件的修改时间
                }
            )
        
        debug_log(f"缓存图片不存在，从原始URL获取: {image_url}")
        
        # 设置请求头，模拟浏览器请求
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.bilibili.com/',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
        }
        
        # 添加限速延迟，避免请求过快导致Nginx连接限制
        time.sleep(0.5)  # 延迟0.5秒，平衡请求速度和连接限制
        
        # 发送请求获取图片，添加超时和重试机制
        try:
            response = requests.get(image_url, headers=headers, timeout=15, stream=True)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            logger.error(f"图片请求超时: {image_url}")
            return jsonify({"error": "图片请求超时"}), 504
        except requests.exceptions.RequestException as e:
            logger.error(f"获取图片失败: {image_url}, 错误: {str(e)}")
            return jsonify({"error": "获取图片失败"}), 500
        
        # 确保响应是图片
        content_type = response.headers.get('content-type')
        if not content_type or not content_type.startswith('image/'):
            logger.error(f"获取的内容不是图片: {image_url}, Content-Type: {content_type}")
            return jsonify({"error": "获取的内容不是图片"}), 400
        
        # 保存图片到缓存目录并同时保存到变量中
        image_data = b''
        try:
            with open(cache_filename, 'wb') as f:
                # 分块写入，处理大图片
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        image_data += chunk
            
            debug_log(f"图片已缓存到: {cache_filename}")
            
            # 转换并缓存webp格式（排除GIF和SVG）
            debug_log(f"准备转换图片为webp格式，原始Content-Type: {content_type}, webp缓存文件: {webp_cache_filename}")
            if content_type not in ['image/gif', 'image/svg+xml']:
                try:
                    # 打开原始图片并转换为webp
                    img = Image.open(io.BytesIO(image_data))
                    
                    # 保存为webp格式
                    with open(webp_cache_filename, 'wb') as f:
                        img.save(f, 'webp', quality=85)
                    
                    debug_log(f"图片已转换为webp并缓存到: {webp_cache_filename}")
                    
                    # 转换成功后删除原始缓存文件以节省存储空间
                    if os.path.exists(cache_filename):
                        os.remove(cache_filename)
                        debug_log(f"已删除原始缓存文件: {cache_filename}")
                    
                except Exception as e:
                    logger.error(f"转换图片为webp格式失败: {str(e)}")
                    import traceback
                    logger.error(f"转换错误详细信息: {traceback.format_exc()}")
                    # 转换失败不影响原始图片的使用
            else:
                debug_log(f"跳过转换为webp格式，图片类型为: {content_type}")
        except IOError as e:
            logger.error(f"保存图片缓存失败: {cache_filename}, 错误: {str(e)}")
            # 如果保存失败，尝试直接从响应中读取
            image_data = response.content
        
        # 生成ETag
        etag = hashlib.md5(image_data).hexdigest()
        
        # 如果webp缓存已创建，返回webp格式
        if os.path.exists(webp_cache_filename):
            with open(webp_cache_filename, 'rb') as f:
                webp_data = f.read()
            
            webp_etag = hashlib.md5(webp_data).hexdigest()
            
            return Response(
                webp_data,
                content_type='image/webp',
                headers={
                    'Cache-Control': 'public, max-age=86400',  # 缓存1天
                    'Access-Control-Allow-Origin': '*',  # 允许跨域访问
                    'ETag': webp_etag,  # 图片内容的唯一标识
                    'Last-Modified': time.time()  # 使用当前时间
                }
            )
        
        # 返回原始图片数据
        return Response(
            image_data,
            content_type=content_type,
            headers={
                'Cache-Control': 'public, max-age=86400',  # 缓存1天
                'Access-Control-Allow-Origin': '*',  # 允许跨域访问
                'ETag': etag,  # 图片内容的唯一标识
                'Last-Modified': time.time()  # 使用当前时间
            }
        )
        
    except requests.RequestException as e:
        logger.error(f"图片获取失败: {str(e)}, URL: {image_url}")
        return jsonify({"error": f"图片获取失败: {str(e)}"}), 502
    except Exception as e:
        logger.error(f"服务器错误: {str(e)}, URL: {image_url}")
        return jsonify({"error": f"服务器错误: {str(e)}"}), 500

@app.route('/api/upload/background', methods=['POST'])
@auth_required
def upload_background():
    """上传背景图片"""
    
    try:
        # 检查是否有文件上传
        if 'file' not in request.files:
            return jsonify({'code': 1, 'msg': '没有选择文件'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'code': 1, 'msg': '没有选择文件'}), 400
        
        # 检查文件类型
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
            return jsonify({'code': 1, 'msg': '不支持的文件类型，仅支持PNG、JPG、JPEG、GIF、WEBP格式'}), 400
        
        # 检查文件大小（限制在10MB以内）
        max_size = 10 * 1024 * 1024  # 10MB
        if file.content_length > max_size:
            return jsonify({'code': 1, 'msg': '文件过大，最大支持10MB'}), 400
        
        # 删除旧的背景图片
        for old_file in os.listdir(uploads_dir):
            if old_file.startswith('background_'):
                os.remove(os.path.join(uploads_dir, old_file))
        
        # 生成唯一文件名
        filename = f'background_{uuid.uuid4().hex}.{file.filename.rsplit(".", 1)[1].lower()}'
        file_path = os.path.join(uploads_dir, filename)
        
        # 保存文件
        file.save(file_path)
        
        # 返回图片URL
        image_url = f'/uploads/{filename}'
        return jsonify({'code': 0, 'msg': '上传成功', 'url': image_url})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'code': 500, 'msg': '服务器内部错误'}), 500

@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    """提供上传文件的静态访问"""
    return send_from_directory(uploads_dir, filename)
    
@app.route('/api/monitor/archive', methods=['POST'])
@auth_required
def archive_monitor():
    """归档/取消归档监控项"""
    # 验证请求格式
    if not request.is_json:
        return jsonify({'code': 400, 'msg': '无效的请求格式'}), 400
    
    monitor_id = request.json.get('id')
    archived = request.json.get('archived', 1)  # 默认为归档
    
    if monitor_id is None:
        return jsonify({'code': 400, 'msg': '缺少监控ID参数'}), 400
    
    # 验证ID格式
    try:
        monitor_id = int(monitor_id)
    except (TypeError, ValueError):
        return jsonify({'code': 400, 'msg': '无效的监控ID格式'}), 400
    
    success, msg = db.update_monitor_archived_status(monitor_id, archived)
    if success:
        return jsonify({'code': 0, 'msg': msg})
    else:
        return jsonify({'code': 1, 'msg': msg})

@app.route('/api/monitor/archived', methods=['GET'])
def get_archived_monitors():
    """获取已归档的监控项"""
    monitors = db.get_archived_monitors()
    return jsonify({'code': 0, 'data': monitors})
        
if __name__ == '__main__':
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='B站合集监控助手')
    parser.add_argument('--debug', action='store_true', help='启用Debug模式')
    args = parser.parse_args()
    
    # 生产环境部署
    # 配置Flask日志，隐藏请求日志
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.logger.setLevel(logging.ERROR)
    
    # 获取服务器配置
    settings = db.get_all_settings()
    host = settings.get('server_host', '127.0.0.1')
    port = int(settings.get('server_port', '5000'))
    
    # 初始化debug模式
    from core import set_debug_mode, get_debug_mode
    
    # 优先使用命令行参数
    debug_enabled = args.debug
    
    # 如果命令行没有指定，使用数据库设置
    if not debug_enabled:
        debug_enabled = settings.get('debug_mode', '0') == '1'
    
    set_debug_mode(debug_enabled)
    
    # 在控制台输出服务器信息
    print(f"服务器已启动: http://{host}:{port}")
    print(f"Debug模式: {'已启用' if debug_enabled else '已关闭'}")
    print("=" * 50)
    
    app.run(host=host, port=port, debug=False, use_reloader=False)