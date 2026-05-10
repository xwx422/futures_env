/**
 * 移动端实时价格刷新模块
 * 
 * 功能:
 * 1. 每 5 秒自动刷新价格
 * 2. 价格变化时高亮提示
 * 3. 支持列表页和详情页
 */

(function() {
    'use strict';
    
    // 配置
    const CONFIG = {
        refreshInterval: 5000,      // 自动刷新间隔（毫秒）
        flashDuration: 800,         // 价格闪烁持续时间（毫秒）
        apiBase: '/api/price'
    };
    
    // 状态
    let lastPrices = {};
    let isRunning = false;
    let refreshTimer = null;
    
    /**
     * 初始化实时价格
     */
    function initMobilePriceRealtime() {
        console.log('[MobilePrice] 初始化实时价格模块 v1.0');
        console.log('[MobilePrice] 当前页面:', window.location.pathname);
        
        // 立即获取一次价格
        fetchPrices();
        
        // 启动自动刷新
        startAutoRefresh();
        
        // 页面可见性变化时处理
        document.addEventListener('visibilitychange', handleVisibilityChange);
        
        // 显示调试信息
        const priceSections = document.querySelectorAll('.price-section');
        console.log('[MobilePrice] 找到价格元素数量:', priceSections.length);
    }
    
    /**
     * 获取实时价格
     */
    function fetchPrices() {
        console.log('[MobilePrice] 正在获取价格...');
        fetch(`${CONFIG.apiBase}/current`)
            .then(response => {
                console.log('[MobilePrice] API响应状态:', response.status);
                return response.json();
            })
            .then(data => {
                console.log('[MobilePrice] API返回数据:', data.success, '品种数:', Object.keys(data.data || {}).length);
                if (data.success && data.data) {
                    updatePriceDisplay(data.data);
                    lastPrices = data.data;
                } else {
                    console.log('[MobilePrice] API返回异常:', data);
                }
            })
            .catch(err => {
                console.error('[MobilePrice] 获取价格失败:', err);
            });
    }
    
    /**
     * 更新价格显示
     */
    function updatePriceDisplay(prices) {
        // 更新列表页价格
        updateListPrices(prices);
        
        // 更新详情页价格（如果在详情页）
        updateDetailPrice(prices);
    }
    
    /**
     * 更新列表页价格
     */
    function updateListPrices(prices) {
        // 查找所有价格元素
        const priceElements = document.querySelectorAll('.price-section');
        console.log('[MobilePrice] 找到价格元素:', priceElements.length, '个');
        
        let updatedCount = 0;
        
        priceElements.forEach(el => {
            // 获取品种代码 - 从父元素的链接 href 中提取
            const card = el.closest('.variety-card');
            if (!card) return;
            
            const href = card.getAttribute('href');
            if (!href) return;
            
            // 提取品种代码 /mobile/variety/XXXX
            const match = href.match(/\/variety\/(\w+)/);
            if (!match) return;
            
            const code = match[1];
            const data = prices[code];
            if (!data) return;
            
            // 更新价格
            const priceEl = el.querySelector('.current-price');
            const changeEl = el.querySelector('.price-change');
            
            if (priceEl && data.price) {
                const oldPrice = parseFloat(priceEl.textContent) || 0;
                const newPrice = data.price;
                
                // 格式化价格
                priceEl.textContent = Math.round(newPrice).toString();
                
                // 设置颜色
                const color = getPriceColor(data.change_percent);
                priceEl.style.color = color;
                
                // 价格变化时闪烁
                if (oldPrice !== 0 && Math.abs(newPrice - oldPrice) > 0.01) {
                    flashElement(priceEl, newPrice > oldPrice ? 'up' : 'down');
                }
            }
            
            if (changeEl && data.change_percent !== undefined) {
                const changePercent = data.change_percent;
                const sign = changePercent > 0 ? '+' : '';
                changeEl.textContent = `${sign}${changePercent.toFixed(2)}%`;
                
                // 设置涨跌样式
                changeEl.className = 'price-change';
                if (changePercent > 0) {
                    changeEl.classList.add('up');
                } else if (changePercent < 0) {
                    changeEl.classList.add('down');
                }
            }
            
            updatedCount++;
        });
        
        console.log('[MobilePrice] 已更新', updatedCount, '个品种价格');
    }
    
    /**
     * 更新详情页价格
     */
    function updateDetailPrice(prices) {
        // 检查是否在详情页
        const priceCard = document.querySelector('.price-card .current-price');
        if (!priceCard) return;
        
        // 从URL获取品种代码
        const match = window.location.pathname.match(/\/variety\/(\w+)/);
        if (!match) return;
        
        const code = match[1];
        const data = prices[code];
        if (!data) return;
        
        // 更新价格
        if (data.price) {
            const oldPrice = parseFloat(priceCard.textContent) || 0;
            priceCard.textContent = Math.round(data.price).toString();
            
            // 设置颜色
            const color = getPriceColor(data.change_percent);
            priceCard.style.color = color;
            
            // 价格变化时闪烁
            if (oldPrice !== 0 && Math.abs(data.price - oldPrice) > 0.01) {
                flashElement(priceCard, data.price > oldPrice ? 'up' : 'down');
            }
        }
        
        // 更新涨跌幅
        const changeEl = document.querySelector('.price-card .change-value');
        if (changeEl && data.change_percent !== undefined) {
            const changePercent = data.change_percent;
            const sign = changePercent > 0 ? '+' : '';
            changeEl.textContent = `${sign}${changePercent.toFixed(2)}%`;
            
            // 设置颜色
            changeEl.style.color = getPriceColor(changePercent);
        }
    }
    
    /**
     * 获取价格颜色
     */
    function getPriceColor(changePercent) {
        if (changePercent > 0) return 'var(--neon-red)';
        if (changePercent < 0) return 'var(--neon-green)';
        return 'var(--text-primary)';
    }
    
    /**
     * 元素闪烁效果
     */
    function flashElement(el, direction) {
        const flashClass = direction === 'up' ? 'flash-up' : 'flash-down';
        el.classList.add(flashClass);
        
        setTimeout(() => {
            el.classList.remove(flashClass);
        }, CONFIG.flashDuration);
    }
    
    /**
     * 启动自动刷新
     */
    function startAutoRefresh() {
        if (isRunning) return;
        
        isRunning = true;
        refreshTimer = setInterval(fetchPrices, CONFIG.refreshInterval);
        console.log('[MobilePrice] 自动刷新已启动');
    }
    
    /**
     * 停止自动刷新
     */
    function stopAutoRefresh() {
        if (!isRunning) return;
        
        isRunning = false;
        if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
        }
        console.log('[MobilePrice] 自动刷新已停止');
    }
    
    /**
     * 处理页面可见性变化
     */
    function handleVisibilityChange() {
        if (document.hidden) {
            // 页面隐藏时停止刷新（节省资源）
            stopAutoRefresh();
        } else {
            // 页面显示时恢复刷新
            fetchPrices(); // 立即刷新一次
            startAutoRefresh();
        }
    }
    
    // 暴露全局接口
    window.MobilePriceRealtime = {
        init: initMobilePriceRealtime,
        refresh: fetchPrices,
        start: startAutoRefresh,
        stop: stopAutoRefresh
    };
    
    // 自动初始化（如果页面已加载完成）
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        initMobilePriceRealtime();
    } else {
        document.addEventListener('DOMContentLoaded', initMobilePriceRealtime);
    }
})();
