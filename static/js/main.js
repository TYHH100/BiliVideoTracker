// 全局变量
const API_BASE = '/api';
let currentToken = localStorage.getItem('bili_monitor_token');
let currentFilter = 'active';
let isPublicMode = false;

// --- 图片加载队列系统（重构版）--- 
// 更稳定的图片加载和缓存架构，支持优先级、重试机制和本地缓存
class ImageLoadQueue {
    constructor(maxConcurrent = 2) {
        this.queue = [];
        this.running = 0;
        this.maxConcurrent = maxConcurrent;
        this.cacheName = 'bili-monitor-image-cache';
        this.maxRetries = 2;
        this.retryDelay = 500;
        
        // 初始化浏览器本地存储缓存
        this.initCache();
    }
    
    // 初始化本地缓存
    async initCache() {
        try {
            if ('caches' in window) {
                await caches.open(this.cacheName);
            }
        } catch (error) {
            console.warn('无法初始化图片缓存:', error);
        }
    }
    
    // 清空队列
    clear() {
        this.queue = [];
    }
    
    // 添加图片到加载队列（支持优先级）
    addImage(imgElement, priority = 0) {
        // 检查图片元素是否有效
        if (!imgElement || !imgElement.dataset.src) {
            console.warn('无效的图片元素或data-src属性');
            return;
        }
        
        // 生成唯一标识符
        const imageId = imgElement.id || `img-${Math.random().toString(36).substr(2, 9)}`;
        imgElement.id = imgElement.id || imageId;
        
        // 检查是否已经在队列中
        const existingIndex = this.queue.findIndex(item => item.element.id === imageId);
        if (existingIndex !== -1) {
            // 如果已经在队列中，更新优先级
            this.queue[existingIndex].priority = priority;
            this.queue.sort((a, b) => b.priority - a.priority); // 按优先级排序
            return;
        }
        
        // 添加到队列
        this.queue.push({
            element: imgElement,
            priority: priority,
            retries: 0,
            timestamp: Date.now()
        });
        
        // 按优先级排序队列（优先级高的先加载）
        this.queue.sort((a, b) => b.priority - a.priority);
        
        // 开始处理队列
        this.processQueue();
    }
    
    // 处理加载队列
    processQueue() {
        // 如果队列中有图片且运行中的任务数小于最大并发数
        while (this.running < this.maxConcurrent && this.queue.length > 0) {
            const queueItem = this.queue.shift();
            this.loadImage(queueItem);
        }
    }
    
    // 加载单个图片（支持本地缓存和重试机制）
    async loadImage(queueItem) {
        const { element } = queueItem;
        const imageUrl = element.dataset.src;
        
        if (!imageUrl) {
            console.warn('图片URL无效');
            this.completeImage(element);
            return;
        }
        
        this.running++;
        
        try {
            // 1. 尝试从浏览器缓存加载
            let cachedImage = await this.getCachedImage(imageUrl);
            
            if (cachedImage) {
                // 使用缓存的图片
                element.src = cachedImage;
            } else {
                // 2. 从网络加载
                await this.loadImageFromNetwork(queueItem);
                
                // 3. 缓存图片到浏览器
                this.cacheImage(imageUrl, element.src);
            }
            
            // 图片加载成功
            element.classList.add('image-loaded');
            element.classList.remove('image-loading', 'image-error');
        } catch (error) {
            console.warn(`图片加载失败 (${queueItem.retries + 1}/${this.maxRetries}):`, imageUrl, error);
            
            // 重试机制
            if (queueItem.retries < this.maxRetries) {
                queueItem.retries++;
                // 延迟重试
                setTimeout(() => {
                    // 重新添加到队列，降低优先级
                    this.addImage(element, queueItem.priority - 1);
                }, this.retryDelay * Math.pow(2, queueItem.retries)); // 指数退避
            } else {
                // 重试次数用尽，使用默认图片
                element.src = '/static/images/viedeo_material_default.png';
                element.classList.add('image-error');
                element.classList.remove('image-loading');
            }
        } finally {
            // 完成加载，继续处理队列
            this.running--;
            this.processQueue();
        }
    }
    
    // 从网络加载图片（支持重试）
    async loadImageFromNetwork(queueItem) {
        const { element } = queueItem;
        const imageUrl = element.dataset.src;
        
        return new Promise((resolve, reject) => {
            // 设置加载状态
            element.classList.add('image-loading');
            
            // 创建新的图片对象用于加载
            const img = new Image();
            
            img.onload = () => {
                // 加载成功，设置到原始元素
                element.src = img.src;
                resolve();
            };
            
            img.onerror = (error) => {
                reject(error);
            };
            
            // 设置超时
            const timeoutId = setTimeout(() => {
                img.src = ''; // 取消加载
                reject(new Error('图片加载超时'));
            }, 10000); // 10秒超时
            
            // 开始加载
            img.src = imageUrl;
        });
    }
    
    // 从浏览器缓存获取图片
    async getCachedImage(url) {
        if (!('caches' in window)) {
            return null;
        }
        
        try {
            const cache = await caches.open(this.cacheName);
            const response = await cache.match(url);
            
            if (response) {
                const blob = await response.blob();
                return URL.createObjectURL(blob);
            }
        } catch (error) {
            console.warn('获取图片缓存失败:', error);
        }
        
        return null;
    }
    
    // 缓存图片到浏览器
    async cacheImage(url, src) {
        if (!('caches' in window)) {
            return;
        }
        
        try {
            // 如果是data URL，不缓存
            if (src.startsWith('data:')) {
                return;
            }
            
            const cache = await caches.open(this.cacheName);
            const response = await fetch(src);
            
            if (response.ok) {
                await cache.put(url, response.clone());
            }
        } catch (error) {
            console.warn('缓存图片失败:', error);
        }
    }
    
    // 完成图片加载（清理资源）
    completeImage(imgElement) {
        if (imgElement.dataset.src) {
            delete imgElement.dataset.src;
        }
        this.running--;
        this.processQueue();
    }
    
    // 获取队列状态
    getQueueStatus() {
        return {
            queued: this.queue.length,
            running: this.running,
            maxConcurrent: this.maxConcurrent
        };
    }
}

// 创建图片加载队列实例，最大并发数为2，减少Nginx连接数
const imageLoadQueue = new ImageLoadQueue(2);

// 预设背景图片URL
const presetBackgrounds = [
    'https://images.unsplash.com/photo-1478720568477-152d9b164e26?ixlib=rb-1.2.1&auto=format&fit=crop&w=1950&q=80',
    'https://images.unsplash.com/photo-1518770660439-4636190af475?ixlib=rb-1.2.1&auto=format&fit=crop&w=1950&q=80',
    'https://images.unsplash.com/photo-1506748686214-e9df14d4d9d0?ixlib=rb-1.2.1&auto=format&fit=crop&w=1950&q=80'
];

// --- 初始化与认证 ---

document.addEventListener('DOMContentLoaded', async () => {
    // 检查主题
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);

    // 初始化背景图片
    await initBackground();

    // 确保应用主界面始终可见
    document.getElementById('app-main').style.display = 'block';

    // 如果有保存的token，自动验证
    if (currentToken) {
        await verifyToken(currentToken);
    } else {
        // 公共访问模式：默认显示页面内容
        loadPublicData();
    }
});

async function verifyToken(token) {
    try {
        const res = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token })
        });
        const data = await res.json();
        
        if (res.status === 200) {
            currentToken = token;
            localStorage.setItem('bili_monitor_token', token);
            document.getElementById('auth-modal').classList.remove('active');
            
            // 切换到管理模式
            switchToAdminMode();
            loadAllData(); // 登录成功加载所有数据
        } else {
            showAuthError('令牌无效，请重试');
            // 如果验证失败但有令牌，清除它
            localStorage.removeItem('bili_monitor_token');
            currentToken = null;
            // 加载公共数据，确保用户仍能查看内容
            loadPublicData();
        }
    } catch (e) {
        showAuthError('无法连接服务器');
        // 加载公共数据，确保用户仍能查看内容
        loadPublicData();
    }
}

function handleLogin() {
    const input = document.getElementById('auth-input').value.trim();
    if (!input) return;
    verifyToken(input);
}

function showAuthError(msg) {
    document.getElementById('auth-msg').textContent = msg;
}

function logout() {
    localStorage.removeItem('bili_monitor_token');
    location.reload();
}

// --- 统一 API 请求封装 ---

async function fetchAPI(endpoint, method = 'GET', body = null) {
    const headers = {
        'Content-Type': 'application/json'
    };
    // 只有当currentToken存在时才添加Authorization头
    if (currentToken) {
        headers.Authorization = currentToken;
    }
    const config = { method, headers };
    if (body) config.body = JSON.stringify(body);

    try {
        const res = await fetch(`${API_BASE}${endpoint}`, config);
        if (res.status === 401) {
            showAuthError('会话过期，请重新登录');
            return null;
        }
        return await res.json();
    } catch (e) {
        console.error("API Error", e);
        return null;
    }
}

// --- 公共访问模式相关函数 ---

async function loadPublicData() {
    try {
        // 获取公共API的数据
        const res = await fetch(`${API_BASE}/public/status`);
        const data = await res.json();
        
        if (data.code === 0) {
            // 渲染监控列表（公共模式）
            await renderMonitors(data.monitors, true);
            // 渲染最近更新
            renderRecentUpdatesList(data.updates);
            // 加载状态信息
            loadStatus();
        } else {
            console.error('加载公共数据失败:', data.msg);
        }
    } catch (e) {
        console.error('公共API请求失败:', e);
    }
}

// 切换到管理模式
function switchToAdminMode() {
    // 更新页面标题
    const brand = document.querySelector('.navbar .brand');
    if (brand) {
        brand.innerHTML = '📺 BiliVideoTracker - <span style="color: var(--accent);">管理模式</span>';
    }
    
    // 显示设置选项卡
    const navLinks = document.querySelector('.navbar .nav-links');
    if (navLinks && !navLinks.querySelector('a[onclick="switchTab(\'settings\')"]')) {
        navLinks.innerHTML += '<a href="#" onclick="switchTab(\'settings\')">系统设置</a>';
    }
    
    // 更新控制按钮
    const controls = document.querySelector('.navbar .controls');
    if (controls) {
        // 移除登录按钮
        const loginBtn = controls.querySelector('button[onclick="showAuthModal()"]');
        if (loginBtn) loginBtn.remove();
        
        // 添加管理模式的按钮
        if (!controls.querySelector('button[onclick="showBackgroundModal()"]')) {
            controls.innerHTML += '<button class="icon-btn" onclick="showBackgroundModal()" title="自定义背景">🖼️</button>';
        }
        if (!controls.querySelector('button[onclick="logout()"]')) {
            controls.innerHTML += '<button class="icon-btn logout-btn" onclick="logout()" title="退出登录">⛔</button>';
        }
    }
    
    // 显示操作按钮
    const statusActions = document.querySelector('.status-card .status-actions');
    if (statusActions) {
        statusActions.innerHTML = `
            <button id="btn-start" class="btn-primary" onclick="controlMonitor('start')">▶ 启用监控</button>
            <button id="btn-stop" class="btn-danger" onclick="controlMonitor('stop')">⏹ 停止监控</button>
            <button id="btn-check" class="btn-secondary" onclick="controlMonitor('check_now')">🔄 立即检查</button>
        `;
    }
    
    // 显示筛选选项卡和添加监控按钮
    const monitorHeader = document.querySelector('#monitor-grid').parentElement.querySelector('.status-header');
    if (monitorHeader && !monitorHeader.querySelector('.filter-tabs')) {
        monitorHeader.innerHTML = `
            <h3>监控列表</h3>
            <div class="filter-tabs">
                <button class="filter-btn" onclick="filterMonitors('all')">全部</button>
                <button class="filter-btn active" onclick="filterMonitors('active')">活跃</button>
                <button class="filter-btn" onclick="filterMonitors('archived')">已归档</button>
            </div>
            <button class="btn-primary" onclick="showAddModal()">+ 添加新监控</button>
        `;
    }
}

// 显示认证模态框
function showAuthModal() {
    document.getElementById('auth-modal').classList.add('active');
}

// 关闭模态框
function closeModal(id) {
    document.getElementById(id).classList.remove('active');
    // 如果是关闭认证模态框，确保应用主界面可见并加载数据
    if (id === 'auth-modal') {
        document.getElementById('app-main').style.display = 'block';
        // 如果没有令牌，确保加载公共数据
        if (!currentToken) {
            loadPublicData();
        } else {
            loadAllData();
        }
    }
}

// --- 页面逻辑：加载数据 ---

async function loadAllData() {
    loadStatus();
    loadMonitors();
    loadSettings();
    refreshRecentUpdates();
}

// 1. 状态与概览
async function loadStatus() {
    let data;
    
    // 根据是否有令牌选择不同的API端点
    if (currentToken) {
        data = await fetchAPI('/status');
    } else {
        // 公共模式下使用公共API
        const res = await fetch(`${API_BASE}/public/status`);
        data = await res.json();
    }
    
    if (!data || data.code !== 0) return;
    
    const active = data.status.active;
    const statusText = document.getElementById('monitor-status-text');
    statusText.textContent = active ? "运行中 🟢" : "已停止 🔴";
    document.getElementById('next-check-time').textContent = data.status.next_check;

    // 仅在有令牌时显示按钮状态
    if (currentToken) {
        const btnStart = document.getElementById('btn-start');
        const btnStop = document.getElementById('btn-stop');
        if (btnStart && btnStop) {
            btnStart.style.display = active ? 'none' : 'inline-block';
            btnStop.style.display = active ? 'inline-block' : 'none';
        }
    }
}

// 筛选监控项
function filterMonitors(filterType) {
    currentFilter = filterType;
    
    // 更新筛选按钮状态
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');
    
    // 重新加载监控列表
    loadMonitors();
}

// 渲染监控列表
async function renderMonitors(monitors, isPublicMode = false) {
    const grid = document.getElementById('monitor-grid');
    grid.innerHTML = '';
    // 清空图片加载队列，避免旧请求影响新渲染
    imageLoadQueue.clear();

    // 如果没有监控项，显示提示
    if (!monitors || monitors.length === 0) {
        const noData = document.createElement('p');
        noData.className = 'no-data';
        noData.textContent = currentFilter === 'archived' ? '暂无已归档的监控项' : '暂无监控项';
        grid.appendChild(noData);
        return;
    }

    // 为每个监控项获取并显示更新统计信息
    monitors.forEach((item) => {
        const div = document.createElement('div');
        div.className = 'monitor-item';
        
        // 添加归档样式类
        if (item.archived) {
            div.classList.add('archived-item');
        }
        
        // 使用反代图片，如果封面为空则使用默认图片
        const defaultCover = '/static/images/viedeo_material_default.png';
        const coverUrl = item.cover ? `/proxy/image?url=${encodeURIComponent(item.cover)}` : defaultCover;
        const linkUrl = `https://space.bilibili.com/${item.mid}/lists/${item.remote_id}?type=${item.type}`;
        
        // 构建初始监控项HTML（不包含统计信息）
        // 使用data-src属性存储真实图片URL，由图片加载队列控制加载，避免Nginx连接限制
        const imgId = `cover-img-${item.id}`;
        let html = `
            <div class="item-status-badge">
                ${item.archived ? '📁 已归档' : (item.is_active ? '▶ 监控中' : '⏸ 已暂停')}
            </div>
            <img id="${imgId}" data-src="${coverUrl}" class="cover-img" loading="lazy" alt="封面">
            <div class="item-info">
                <a href="${linkUrl}" target="_blank" style="text-decoration:none; color:inherit;">
                    <h4 title="${item.name}">${item.name}</h4>
                </a>
                <div class="item-stats">
                    <span>视频数: ${item.total_count}</span>
                    <span>${item.type === 'series' ? '系列' : '合集'}</span>
                </div>
                <div class="update-stats" id="update-stats-${item.id}" style="margin-top: 8px; font-size: 0.85em; color: var(--text-secondary);">
                    <div class="stats-loading">加载更新统计中...</div>
                </div>
            </div>
        `;
        
        // 如果不是公共模式，添加操作按钮
        if (!isPublicMode && currentToken) {
            let archiveBtn = '';
            if (item.archived) {
                archiveBtn = `<button class="btn-secondary" style="font-size:0.8em; padding:4px 8px; margin-right:4px;" onclick="toggleArchive(${item.id}, 0)">取消归档</button>`;
            } else {
                archiveBtn = `<button class="btn-warning" style="font-size:0.8em; padding:4px 8px; margin-right:4px;" onclick="toggleArchive(${item.id}, 1)">归档</button>`;
            }
            
            html += `
                <div class="item-actions">
                    ${archiveBtn}
                    <button class="btn-warning" style="font-size:0.8em; padding:4px 8px; margin-right:4px;" onclick="toggleMonitorActive(${item.id}, ${item.is_active})">${item.is_active ? '暂停' : '恢复'}</button>
                    <button class="btn-danger" style="font-size:0.8em; padding:4px 8px;" onclick="deleteMonitor(${item.id}, '${item.name}')">删除</button>
                </div>
            `;
        }
        
        div.innerHTML = html;
        grid.appendChild(div);
        
        // 将图片添加到加载队列，控制并发请求数量
        const imgElement = document.getElementById(imgId);
        if (imgElement) {
            imageLoadQueue.addImage(imgElement);
        }
    });
    
    // 批量加载所有监控项的更新统计信息
    if (monitors.length > 0) {
        await loadBatchUpdateStats(monitors);
    }
}

// 批量加载监控项的更新统计信息
async function loadBatchUpdateStats(monitors) {
    
    try {
        // 收集所有监控项ID
        const monitorIds = monitors.map(item => item.id);
        
        // 批量请求统计信息
        const response = await fetchAPI(`/monitor/batch_update_stats`, 'POST', { monitor_ids: monitorIds });
        
        if (response && response.code === 0) {
            const allStats = response.data;
            
            // 为每个监控项渲染统计信息
            monitors.forEach(item => {
                renderUpdateStats(item.id, allStats[item.id]);
            });
        }
    } catch (err) {
        console.error('批量加载更新统计失败:', err);
        
        // 批量请求失败时，尝试逐个加载（降级处理）
        for (const item of monitors) {
            await loadSingleUpdateStats(item.id);
        }
    }
}

// 单个加载监控项的更新统计信息（降级用）
async function loadSingleUpdateStats(monitorId) {
    
    try {
        const statsElement = document.getElementById(`update-stats-${monitorId}`);
        if (!statsElement) return;
        
        const response = await fetchAPI(`/monitor/${monitorId}/update_stats`);
        if (response && response.code === 0) {
            renderUpdateStats(monitorId, response.data);
        }
    } catch (err) {
        console.error(`加载监控项 ${monitorId} 的更新统计失败:`, err);
        const statsElement = document.getElementById(`update-stats-${monitorId}`);
        if (statsElement) {
            statsElement.innerHTML = '<div class="stats-item"><span class="stats-label">统计信息加载失败</span></div>';
        }
    }
}

// 渲染单个监控项的更新统计信息
function renderUpdateStats(monitorId, stats) {
    try {
        const statsElement = document.getElementById(`update-stats-${monitorId}`);
        if (!statsElement || !stats) return;
        
        let statsHtml = '';
        
        // 添加距离上次更新时间的显示
        let timeSinceUpdateText = '';
        if (stats.last_update_time) {
            if (stats.days_since_last_update !== null) {
                if (stats.days_since_last_update > 0) {
                    timeSinceUpdateText = `${stats.days_since_last_update}天${stats.hours_since_last_update}小时`;
                } else if (stats.hours_since_last_update > 0) {
                    timeSinceUpdateText = `${stats.hours_since_last_update}小时${stats.minutes_since_last_update}分钟`;
                } else {
                    timeSinceUpdateText = `${stats.minutes_since_last_update}分钟`;
                }
            } else {
                timeSinceUpdateText = new Date(stats.last_update_time * 1000).toLocaleString();
            }
        }
        
        if (stats.average_interval_days !== null && stats.next_update_prediction !== null) {
            const nextUpdateTime = new Date(stats.next_update_prediction * 1000).toLocaleDateString();
            statsHtml = `
                <div class="stats-item">
                    <span class="stats-label">距离上次更新过去了:</span>
                    <span class="stats-value">${timeSinceUpdateText}</span>
                </div>
                <div class="stats-item">
                    <span class="stats-label">平均更新间隔[仅供参考]:</span>
                    <span class="stats-value">${stats.average_interval_days}天</span>
                </div>
                <div class="stats-item">
                    <span class="stats-label">推测下次更新[图一乐就行]:</span>
                    <span class="stats-value">${nextUpdateTime}</span>
                </div>
                <div class="stats-item">
                    <span class="stats-label">数据库已记录更新视频:</span>
                    <span class="stats-value">${stats.total_videos}个</span>
                </div>
            `;
        } else if (stats.last_update_time) {
            // 只有上次更新时间，没有足够数据预测下次更新
            statsHtml = `
                <div class="stats-item">
                    <span class="stats-label">距离上次更新过去了:</span>
                    <span class="stats-value">${timeSinceUpdateText}</span>
                </div>
                <div class="stats-item">
                    <span class="stats-label">数据库已记录更新视频:</span>
                    <span class="stats-value">${stats.total_videos}个</span>
                </div>
                <div class="stats-item">
                    <span class="stats-label">更新数据不足，无法预测下次更新时间</span>
                </div>
            `;
        } else {
            statsHtml = `
                <div class="stats-item">
                    <span class="stats-label">数据库最近更新视频数量不足，无法计算统计</span>
                </div>
            `;
        }
        
        statsElement.innerHTML = statsHtml;
    } catch (err) {
        console.error(`渲染监控项 ${monitorId} 的更新统计失败:`, err);
        const statsElement = document.getElementById(`update-stats-${monitorId}`);
        if (statsElement) {
            statsElement.innerHTML = '<div class="stats-item"><span class="stats-label">统计信息加载失败</span></div>';
        }
    }
}

// 2. 监控列表加载
async function loadMonitors() {
    let data;
    if (currentToken) {
        data = await fetchAPI('/status');
    } else {
        // 公共模式下使用公共API
        const res = await fetch(`${API_BASE}/public/status`);
        data = await res.json();
    }
    
    if (!data) return;
    
    // 根据筛选条件过滤监控项
    let monitors = data.monitors || [];
    if (currentFilter === 'active') {
        monitors = monitors.filter(item => !item.archived);
    } else if (currentFilter === 'archived') {
        monitors = monitors.filter(item => item.archived);
    }
    
    await renderMonitors(monitors);
}

// 获取并渲染最近更新视频列表
async function refreshRecentUpdates() {
    try {
        let response;
        
        // 根据是否有令牌选择不同的API端点
        if (currentToken) {
            response = await fetchAPI('/monitor/recent_updates');
            if (response && response.code === 0) {
                renderRecentUpdatesList(response.data);
            }
        } else {
            // 公共模式下使用公共API
            const res = await fetch(`${API_BASE}/public/status`);
            const data = await res.json();
            if (data && data.code === 0) {
                renderRecentUpdatesList(data.updates);
            }
        }
    } catch (err) {
        console.error('获取最近更新失败:', err);
    }
}

// 渲染最近更新视频列表
function renderRecentUpdatesList(updates) {
    const container = document.getElementById('recent-updates');
    
    if (!updates || updates.length === 0) {
        container.innerHTML = '<p class="no-data">暂无更新记录</p>';
        return;
    }
    
    let html = '';
    for (const update of updates) {
        const updateTime = new Date(update.publish_time * 1000).toLocaleString();
        // 如果封面为空则使用默认图片，否则使用代理服务
        const defaultCover = '/static/images/viedeo_material_default.png';
        const coverUrl = update.cover ? `/proxy/image?url=${encodeURIComponent(update.cover)}` : defaultCover;
        html += `
            <div class="update-item" onclick="openVideo('${update.video_id}')">
                <img class="update-cover" src="${coverUrl}" alt="${update.video_title}">
                <div class="update-info">
                    <div class="update-title">${update.video_title}</div>
                    <div class="update-details">
                        <span class="monitor-name">${update.monitor_name}</span>
                        <span class="update-time">${updateTime}</span>
                    </div>
                </div>
            </div>
        `;
    }
    
    container.innerHTML = html;
}

// 打开视频
function openVideo(videoId) {
    window.open(`https://www.bilibili.com/video/av${videoId}`, '_blank');
}

// --- 交互操作 ---

async function controlMonitor(action) {
    const res = await fetchAPI('/control', 'POST', { action });
    if (res && res.code === 0) {
        if(action === 'check_now') showNotification('操作成功', '已触发立即检查', 'success');
        loadStatus(); // 刷新状态
        refreshRecentUpdates(); // 刷新最近更新
    }
}

function showAddModal() {
    document.getElementById('add-modal').classList.add('active');
    document.getElementById('add-msg').textContent = '';
}

async function submitAddMonitor() {
    const url = document.getElementById('add-url-input').value.trim();
    if (!url) return;

    const btn = document.querySelector('#add-modal .btn-primary');
    const originalText = btn.textContent;
    btn.textContent = '获取中...';
    btn.disabled = true;

    const res = await fetchAPI('/monitor/add', 'POST', { url });
    btn.textContent = originalText;
    btn.disabled = false;

    if (res && res.code === 0) {
        closeModal('add-modal');
        document.getElementById('add-url-input').value = '';
        
        // 添加一个短暂的延迟，确保后台线程有足够的时间来完成监控项的添加和数据的获取
        showNotification('添加成功', '正在获取最新信息，请稍候...', 'success');
        setTimeout(() => {
            loadMonitors();
        }, 1000);
    } else {
        document.getElementById('add-msg').textContent = res ? res.msg : '请求失败';
    }
}

async function deleteMonitor(id, name) {
    if (!confirm(`确定要删除监控 "${name}" 吗？\n此操作不可撤销！`)) return;
    const res = await fetchAPI('/monitor/delete', 'POST', { id });
    if (res && res.code === 0) loadMonitors();
}

async function toggleMonitorActive(id, isActive) {
    const action = isActive ? '暂停' : '恢复';
    if (!confirm(`确定要${action}监控项吗？`)) return;
    const res = await fetchAPI('/monitor/toggle_active', 'POST', { id, is_active: isActive ? 0 : 1 });
    if (res && res.code === 0) {
        showNotification('操作成功', res.msg, 'success');
        loadMonitors();
    } else {
        showNotification('操作失败', res.msg || '操作失败', 'error');
    }
}

// 归档/取消归档函数
async function toggleArchive(id, archived) {
    const action = archived ? '归档' : '取消归档';
    if (!confirm(`确定要${action}此监控项吗？${archived ? '归档后将自动停止监控。' : ''}`)) return;
    
    const res = await fetchAPI('/monitor/archive', 'POST', { id, archived });
    if (res && res.code === 0) {
        showNotification('操作成功', res.msg, 'success');
        loadMonitors();
    } else {
        showNotification('操作失败', res.msg || '操作失败', 'error');
    }
}

// --- 设置逻辑 ---

async function loadSettings() {
    const res = await fetchAPI('/settings/get');
    if (!res) return;
    
    const cfg = res.config;
    // 填充表单
    document.getElementById('set-smtp-enable').checked = cfg.smtp_enable === '1';
    document.getElementById('set-smtp-server').value = cfg.smtp_server;
    document.getElementById('set-smtp-port').value = cfg.smtp_port;
    document.getElementById('set-email-account').value = cfg.email_account;
    document.getElementById('set-email-auth').value = cfg.email_auth_code;
    document.getElementById('set-sender-name').value = cfg.sender_name;
    document.getElementById('set-receivers').value = cfg.receiver_emails;
    document.getElementById('set-use-tls').checked = cfg.use_tls === '1';
    document.getElementById('set-smtp-batch-send').checked = cfg.smtp_batch_send === '1';
    
    // 服务器配置
    document.getElementById('set-server-host').value = cfg.server_host || '127.0.0.1';
    document.getElementById('set-server-port').value = cfg.server_port || '5000';
    
    // 填充冷却时间配置
    document.getElementById('set-global-cooldown').value = cfg.global_cooldown || '600';
    document.getElementById('set-item-cooldown').value = cfg.item_cooldown || '30';
    
    // 填充最近更新视频数量配置
    document.getElementById('set-recent-updates-limit').value = cfg.recent_updates_limit || '5';
    document.getElementById('set-recent-updates-save-limit').value = cfg.recent_updates_save_limit || '5';
    
    // 填充调试设置
    document.getElementById('set-debug-mode').checked = cfg.debug_mode === '1';
    
    // 填充Token信息
    document.getElementById('token-hash-view').textContent = res.token.hash_preview;
    document.getElementById('token-date-view').textContent = res.token.created_at;
    
    // 填充日志清理配置
    document.getElementById('set-log-auto-clean').checked = cfg.log_auto_clean === '1';
    document.getElementById('set-log-retention-days').value = cfg.log_retention_days || '7';
}

async function saveSettings() {
    const data = {
        smtp_enable: document.getElementById('set-smtp-enable').checked ? '1' : '0',
        smtp_server: document.getElementById('set-smtp-server').value,
        smtp_port: document.getElementById('set-smtp-port').value,
        email_account: document.getElementById('set-email-account').value,
        email_auth_code: document.getElementById('set-email-auth').value,
        sender_name: document.getElementById('set-sender-name').value,
        receiver_emails: document.getElementById('set-receivers').value,
        use_tls: document.getElementById('set-use-tls').checked ? '1' : '0',
        smtp_batch_send: document.getElementById('set-smtp-batch-send').checked ? '1' : '0',
        global_cooldown: document.getElementById('set-global-cooldown').value,
        item_cooldown: document.getElementById('set-item-cooldown').value,
        server_host: document.getElementById('set-server-host').value,
        server_port: document.getElementById('set-server-port').value,
        recent_updates_limit: document.getElementById('set-recent-updates-limit').value,
        recent_updates_save_limit: document.getElementById('set-recent-updates-save-limit').value,
        log_auto_clean: document.getElementById('set-log-auto-clean').checked ? '1' : '0',
        log_retention_days: document.getElementById('set-log-retention-days').value,
        debug_mode: document.getElementById('set-debug-mode').checked ? '1' : '0'
    };
    
    const res = await fetchAPI('/settings/save', 'POST', data);
    if (res && res.code === 0) {
        // 无论debug模式是启用还是禁用，都立即应用
        await fetchAPI('/debug/set', 'POST', { enable: data.debug_mode === '1' });
        showNotification('操作成功', '设置已保存', 'success');
    }
}

async function testEmail() {
    // 临时获取表单数据进行测试
    const data = {
        smtp_enable: '1',
        smtp_server: document.getElementById('set-smtp-server').value,
        smtp_port: document.getElementById('set-smtp-port').value,
        email_account: document.getElementById('set-email-account').value,
        email_auth_code: document.getElementById('set-email-auth').value,
        sender_name: document.getElementById('set-sender-name').value,
        receiver_emails: document.getElementById('set-receivers').value,
        use_tls: document.getElementById('set-use-tls').checked ? '1' : '0'
    };
    if(!data.email_account || !data.email_auth_code) {
        showNotification('输入错误', '请先填写邮箱账号和授权码', 'error');
        return;
    }
    showNotification('提示', '正在发送测试邮件，请稍候...', 'info');
    const res = await fetchAPI('/settings/email_test', 'POST', data);
    if(res) showNotification('邮件测试结果', res.msg, res.code === 0 ? 'success' : 'error');
}

async function resetToken() {
    if (!confirm('危险操作：重置后你需要使用新生成的令牌重新登录。确定继续吗？')) return;
    
    const res = await fetchAPI('/token/reset', 'POST', {});
    if (res && res.code === 0) {
        alert(`重置成功！\n请务必复制保存新的令牌：\n\n${res.token}\n\n点击确定后将跳转至登录页。`);
        logout();
    }
}

async function importOldMonitors() {
    const fileInput = document.getElementById('import-json-file');
    const file = fileInput.files[0];
    
    if (!file) {
        showNotification('导入错误', '请先选择要导入的JSON文件', 'error');
        return;
    }
    
    if (!file.name.endsWith('.json')) {
        showNotification('导入错误', '请选择有效的JSON文件', 'error');
        return;
    }
    
    try {
        const reader = new FileReader();
        reader.onload = async (e) => {
            try {
                const jsonData = JSON.parse(e.target.result);
                
                // 验证JSON结构
                if (!jsonData.seasons || !Array.isArray(jsonData.seasons)) {
                    showNotification('导入错误', 'JSON文件结构不正确，缺少seasons数组', 'error');
                    return;
                }
                
                // 显示导入确认
                if (!confirm(`确认要导入 ${jsonData.seasons.length} 个监控项吗？\n导入后将添加到现有监控列表中`)) {
                    return;
                }
                
                // 调用API导入数据
                const res = await fetchAPI('/monitor/import_old', 'POST', { data: jsonData });
                
                if (res && res.code === 0) {
                    showNotification('导入成功', `成功导入 ${res.imported} 个监控项！`, 'success');
                    loadMonitors(); // 刷新监控列表
                    // 清空文件选择
                    fileInput.value = '';
                } else {
                    showNotification('导入失败', '导入失败：' + (res?.msg || '未知错误'), 'error');
                }
            } catch (parseError) {
                showNotification('JSON解析失败', 'JSON解析失败：' + parseError.message, 'error');
            }
        };
        
        reader.readAsText(file);
    } catch (error) {
        showNotification('文件读取失败', '文件读取失败：' + error.message, 'error');
    }
}

function showNotification(title, message, type = 'info', duration = 5000) {
    // 检查并创建通知容器
    let container = document.querySelector('.notification-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'notification-container';
        document.body.appendChild(container);
    }
    
    // 创建通知元素
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    
    // 构建通知内容
    notification.innerHTML = `
        <div class="notification-icon">
            ${type === 'success' ? '✓' : type === 'error' ? '✗' : type === 'warning' ? '⚠' : 'ℹ'}
        </div>
        <div class="notification-content">
            <div class="notification-title">${title}</div>
            <div class="notification-message">${message}</div>
        </div>
        <button class="notification-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    
    // 添加到容器（新通知显示在最上方）
    container.prepend(notification);
    
    // 激活通知
    setTimeout(() => {
        notification.classList.add('active');
    }, 10);
    
    // 自动关闭
    setTimeout(() => {
        notification.classList.remove('active');
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
                
                // 如果容器为空，移除容器
                if (container.children.length === 0) {
                    container.remove();
                }
            }
        }, 400);
    }, duration);
}

// --- 工具函数 ---

function switchTab(tabName) {
    // 移除所有导航链接的active类
    const navLinks = document.querySelectorAll('.nav-links a');
    navLinks.forEach(link => link.classList.remove('active'));
    
    // 移除所有标签内容的active类
    const tabContents = document.querySelectorAll('.tab-content');
    tabContents.forEach(content => content.classList.remove('active'));
    
    // 添加当前导航链接的active类
    const currentNavLink = document.querySelector(`.nav-links a[onclick="switchTab('${tabName}')"]`);
    if (currentNavLink) {
        currentNavLink.classList.add('active');
    }
    
    // 添加当前标签内容的active类
    const currentTabContent = document.getElementById(`tab-${tabName}`);
    if (currentTabContent) {
        currentTabContent.classList.add('active');
    }
    
    // 检查是否需要显示/隐藏设置相关的功能
    if (tabName === 'settings') {
        // 当切换到设置页面时，加载设置
        loadSettings();
    } else if (tabName === 'home') {
        // 当切换回主页时，重新加载数据
        loadAllData();
    }
}

function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
}

// --- 背景图片功能 --- 

// 初始化背景图片
async function initBackground() {
    const bgImage = document.getElementById('background-image');
    
    try {
        // 优先从服务器获取背景图片设置
        const res = await fetchAPI('/settings/get');
        if (res && res.config && res.config.background_image) {
            bgImage.src = res.config.background_image;
            localStorage.setItem('background_image', res.config.background_image);
        } else {
            // 如果服务器没有设置，则使用localStorage或默认背景
            const savedBg = localStorage.getItem('background_image');
            if (savedBg) {
                bgImage.src = savedBg;
                // 将localStorage中的设置同步到服务器
                await setBackground(savedBg);
            } else {
                // 使用默认背景
                bgImage.src = presetBackgrounds[0];
                localStorage.setItem('background_image', presetBackgrounds[0]);
                // 将默认设置同步到服务器
                await setBackground(presetBackgrounds[0]);
            }
        }
    } catch (e) {
        console.error('获取背景图片设置失败:', e);
        // 出错时使用localStorage或默认背景
        const savedBg = localStorage.getItem('background_image');
        if (savedBg) {
            bgImage.src = savedBg;
        } else {
            bgImage.src = presetBackgrounds[0];
            localStorage.setItem('background_image', presetBackgrounds[0]);
        }
    }
    
    // 显示背景容器
    document.getElementById('background-container').style.display = 'block';
}

// 显示背景设置模态框
function showBackgroundModal() {
    document.getElementById('background-modal').classList.add('active');
}

// 设置预设背景
async function setPresetBackground(index) {
    if (index >= 1 && index <= presetBackgrounds.length) {
        const bgUrl = presetBackgrounds[index - 1];
        await setBackground(bgUrl);
        closeModal('background-modal');
    }
}

// 设置自定义背景
async function setCustomBackground() {
    const urlInput = document.getElementById('custom-bg-url');
    const customUrl = urlInput.value.trim();
    
    if (customUrl) {
        // 简单验证URL格式
        if (customUrl.match(/^https?:\/\//)) {
            await setBackground(customUrl);
            closeModal('background-modal');
            urlInput.value = '';
        } else {
            showNotification('输入错误', '请输入有效的图片URL（必须以http://或https://开头）', 'error');
        }
    }
}

// 上传本地背景图片
async function uploadLocalBackground() {
    const fileInput = document.getElementById('local-bg-file');
    const file = fileInput.files[0];
    
    if (!file) {
        showNotification('上传错误', '请先选择一个本地图片文件', 'error');
        return;
    }
    
    // 检查文件类型
    if (!file.type.match('image.*')) {
        showNotification('上传错误', '请选择一个有效的图片文件', 'error');
        return;
    }
    
    // 检查文件大小（限制在10MB以内）
    const maxSize = 10 * 1024 * 1024; // 10MB
    if (file.size > maxSize) {
        showNotification('上传错误', '图片文件过大, 请选择小于10MB的图片', 'error');
        return;
    }
    
    // 创建FormData对象
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        // 发送请求到后端API
        const res = await fetch(`${API_BASE}/upload/background`, {
            method: 'POST',
            headers: {
                'Authorization': currentToken
            },
            body: formData
        });
        
        const data = await res.json();
        
        if (res.status === 200 && data.code === 0) {
            // 上传成功，设置新背景
            setBackground(data.url);
            closeModal('background-modal');
            showNotification('上传成功', '背景图片上传成功！', 'success');
        } else {
            showNotification('上传失败', '上传失败：' + (data.msg || '未知错误'), 'error');
        }
    } catch (e) {
        console.error('上传错误:', e);
        showNotification('上传失败', '上传失败：网络错误', 'error');
    } finally {
        // 清空文件输入
        fileInput.value = '';
    }
}

// 重置背景
async function resetBackground() {
    await setBackground(presetBackgrounds[0]);
    closeModal('background-modal');
}

// 设置背景图片
async function setBackground(url) {
    const bgImage = document.getElementById('background-image');
    bgImage.src = url;
    localStorage.setItem('background_image', url);
    
    // 将背景图片URL保存到服务器数据库
    try {
        await fetchAPI('/settings/save', 'POST', {
            background_image: url
        });
    } catch (e) {
        console.error('保存背景图片设置失败:', e);
    }
    
    // 添加过渡效果
    bgImage.style.transform = 'scale(1.05)';
    setTimeout(() => {
        bgImage.style.transform = 'scale(1)';
    }, 500);
}

// 切换设置页面的TAB
function switchSettingsTab(tabName) {
    // 获取所有TAB按钮和内容
    const tabBtns = document.querySelectorAll('.settings-tabs .tab-btn');
    const tabContents = document.querySelectorAll('.settings-tab-content');
    
    // 移除所有按钮的active类
    tabBtns.forEach(btn => btn.classList.remove('active'));
    // 隐藏所有内容
    tabContents.forEach(content => content.classList.remove('active'));
    
    // 添加当前按钮的active类
    event.target.classList.add('active');
    // 显示当前内容
    document.getElementById(`settings-tab-${tabName}`).classList.add('active');
}