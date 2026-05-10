/**
 * 实时价格刷新模块
 * 
 * 功能:
 * 1. 每 3 秒自动刷新价格
 * 2. 价格异动提醒（涨跌幅>1%）
 * 3. 涨跌排行榜
 * 4. 手动刷新按钮
 * 
 * 使用方式:
 * <script src="{{ url_for('static', filename='js/price_realtime.js') }}"></script>
 */

(function() {
    'use strict';
    
    // 配置
    const CONFIG = {
        refreshInterval: 5000,      // 自动刷新间隔（毫秒）- 改为 5 秒，减少请求频率
        alertInterval: 30000,       // 价格异动检查间隔（毫秒）
        alertThreshold: 1.0,        // 价格异动阈值（%）
        flashDuration: 500,         // 价格闪烁持续时间（毫秒）
        apiBase: '/api/price'
    };
    
    // 状态
    let lastPrices = {};
    let lastUpdateTime = null;  // 最后更新时间
    let marketStatus = null;  // 市场状态
    let isRunning = false;
    let refreshTimer = null;
    let alertTimer = null;
    let alertedPrices = {};  // 记录已提示的品种和涨跌幅，避免重复弹窗
    
    /**
     * 初始化实时价格
     */
    function initPriceRealtime() {
        console.log('[PriceRealtime] 初始化实时价格模块');

        // 立即获取一次价格（强制刷新）
        console.log('[PriceRealtime] 立即获取实时价格...');
        
        fetch(`${CONFIG.apiBase}/current`)
            .then(response => response.json())
            .then(data => {
                // 休市期间，API 返回空数据和休市消息
                if (data.message && (!data.data || Object.keys(data.data).length === 0)) {
                    console.log(`[PriceRealtime] ${data.message}`);
                    const status = data.market_status || {
                        is_trading: false,
                        session: '休市',
                        reason: data.message,
                        next_session: '下午交易'
                    };
                    updateMarketStatusDisplay(status);
                    
                    // 同步市场状态到全局（供 dashboard.html 使用）
                    window.marketStatus = status;
                    
                    // 休市时不启动价格刷新，但保留警报检查（降低频率）
                    console.log('[PriceRealtime] 休市期间，暂停价格刷新，保留警报检查');
                    console.log('[PriceRealtime] 首次价格获取完成（休市状态）');

                    // 休市时启动低频警报检查（10 分钟一次），并立即执行一次
                    startAlertCheck(600000);  // 10 分钟检查一次警报
                    checkPriceAlerts();  // 立即执行一次检查，显示当前所有超过阈值的警报

                    // 5 分钟后重新检查市场状态
                    setTimeout(() => {
                        console.log('[PriceRealtime] 休市期间重新检查市场状态...');
                        fetchPrices();
                        startAutoRefresh();
                        startAlertCheck();  // 恢复正常频率
                    }, 300000);  // 5 分钟后

                    return;
                }
                
                // 交易时段，有价格数据
                if (data.success && data.data && Object.keys(data.data).length > 0) {
                    updatePriceDisplay(data.data);
                    lastPrices = data.data;
                    updateLastUpdateTime(data.update_time);

                    // 更新市场状态
                    if (data.market_status) {
                        marketStatus = data.market_status;
                        updateMarketStatusDisplay(marketStatus);
                    }

                    console.log('[PriceRealtime] 价格已更新:', Object.keys(data.data).length, '个品种');
                    
                    // 交易时段，启动警报检查和自动刷新
                    startAlertCheck();
                    startAutoRefresh();
                    
                    console.log('[PriceRealtime] 首次价格获取完成（交易时段）');
                }
            })
            .catch(err => {
                console.error('[PriceRealtime] 首次价格获取失败:', err);
                // 失败时也启动刷新，下次再试
                startAutoRefresh();
            });

        // 绑定手动刷新按钮
        bindRefreshButton();

        isRunning = true;
    }
    
    /**
     * 启动自动刷新
     */
    function startAutoRefresh() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
        }
        refreshTimer = setInterval(fetchPrices, CONFIG.refreshInterval);
        console.log(`[PriceRealtime] 自动刷新已启动，间隔${CONFIG.refreshInterval}ms`);
    }
    
    /**
     * 停止自动刷新
     */
    function stopAutoRefresh() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
            console.log('[PriceRealtime] 自动刷新已停止');
        }
    }
    
    /**
     * 启动价格异动检查
     */
    function startAlertCheck(interval = CONFIG.alertInterval) {
        if (alertTimer) {
            clearInterval(alertTimer);
        }
        alertTimer = setInterval(checkPriceAlerts, interval);
        console.log(`[PriceRealtime] 价格异动检查已启动，间隔${interval/1000}秒`);
    }

    /**
     * 停止价格异动检查
     */
    function stopAlertCheck() {
        if (alertTimer) {
            clearInterval(alertTimer);
            alertTimer = null;
            console.log('[PriceRealtime] 价格异动检查已停止');
        }
    }

    /**
     * 获取价格数据
     */
    function fetchPrices() {
        return fetch(`${CONFIG.apiBase}/current`)
            .then(response => response.json())
            .then(data => {
                // 休市期间，API 返回空数据和休市消息
                if (data.message && (!data.data || Object.keys(data.data).length === 0)) {
                    // 休市状态
                    console.log(`[PriceRealtime] ${data.message}`);
                    const status = data.market_status || {
                        is_trading: false,
                        session: '休市',
                        reason: data.message,
                        next_session: '下午交易'
                    };
                    updateMarketStatusDisplay(status);
                    
                    // 休市时停止刷新
                    if (isRunning) {
                        stopAutoRefresh();
                        stopAlertCheck();  // 休市时也停止价格异动检查
                        
                        // 5 分钟后重新检查
                        setTimeout(() => {
                            console.log('[PriceRealtime] 休市期间重新检查市场状态...');
                            fetchPrices();
                            startAutoRefresh();
                            startAlertCheck();
                        }, 300000);  // 5 分钟后
                    }
                    return data;
                }
                
                // 交易时段，有价格数据
                if (data.success && data.data && Object.keys(data.data).length > 0) {
                    updatePriceDisplay(data.data);
                    lastPrices = data.data;
                    updateLastUpdateTime(data.update_time);

                    // 更新市场状态
                    if (data.market_status) {
                        marketStatus = data.market_status;
                        updateMarketStatusDisplay(marketStatus);
                    }

                    console.log('[PriceRealtime] 价格已更新:', Object.keys(data.data).length, '个品种');
                } else if (data.error) {
                    console.warn('[PriceRealtime] 获取价格失败:', data.error);
                }
                return data;
            })
            .catch(error => {
                console.error('[PriceRealtime] 请求错误:', error);
                throw error;
            });
    }
    
    /**
     * 更新价格显示
     */
    function updatePriceDisplay(prices) {
        for (const [code, pdata] of Object.entries(prices)) {
            updateSinglePrice(code, pdata);
        }
        
        // 更新涨跌排行榜（如果存在）
        updatePriceStats(prices);
    }
    
    /**
     * 更新单个品种价格
     */
    function updateSinglePrice(code, pdata) {
        // 查找页面上对应的品种行
        const row = document.querySelector(`[data-variety="${code}"]`);
        if (!row) {
            // 尝试在 dashboard 页面查找（通过 onclick 属性匹配品种代码）
            updateDashboardPrice(code, pdata);
            return;
        }

        const priceEl = row.querySelector('.price');
        const changeEl = row.querySelector('.change-percent');
        const changeValueEl = row.querySelector('.change-value');

        if (priceEl && pdata.price > 0) {
            const oldPrice = parseFloat(priceEl.textContent.replace(/,/g, '')) || 0;
            const newPrice = pdata.price.toFixed(2);

            // 更新价格
            priceEl.textContent = newPrice;

            // 红涨绿跌 - 根据涨跌幅设置颜色
            if (pdata.change_percent > 0) {
                // 上涨 - 红色
                priceEl.style.color = 'var(--neon-red)';
                priceEl.classList.add('up');
                priceEl.classList.remove('down');
            } else if (pdata.change_percent < 0) {
                // 下跌 - 绿色
                priceEl.style.color = 'var(--neon-green)';
                priceEl.classList.add('down');
                priceEl.classList.remove('up');
            } else {
                // 平盘 - 灰色
                priceEl.style.color = 'var(--text-secondary)';
                priceEl.classList.remove('up', 'down');
            }

            // 价格变化方向指示
            if (pdata.price > oldPrice) {
                priceEl.classList.add('price-up-flash');
            } else if (pdata.price < oldPrice) {
                priceEl.classList.add('price-down-flash');
            }

            // 移除闪烁类
            setTimeout(() => {
                priceEl.classList.remove('price-up-flash', 'price-down-flash');
            }, CONFIG.flashDuration);
        }

        // 更新涨跌幅
        if (changeEl && pdata.change_percent !== undefined) {
            const changeText = `${pdata.change_percent > 0 ? '+' : ''}${pdata.change_percent.toFixed(2)}%`;
            changeEl.textContent = changeText;
            
            // 红涨绿跌
            if (pdata.change_percent > 0) {
                changeEl.style.color = 'var(--neon-red)';
                changeEl.className = 'change-percent up';
            } else if (pdata.change_percent < 0) {
                changeEl.style.color = 'var(--neon-green)';
                changeEl.className = 'change-percent down';
            } else {
                changeEl.style.color = 'var(--text-secondary)';
                changeEl.className = 'change-percent';
            }
        }

        // 更新涨跌额
        if (changeValueEl && pdata.change !== undefined) {
            const changeValueText = `${pdata.change > 0 ? '+' : ''}${pdata.change.toFixed(2)}`;
            changeValueEl.textContent = changeValueText;
            
            // 红涨绿跌
            if (pdata.change > 0) {
                changeValueEl.style.color = 'var(--neon-red)';
                changeValueEl.className = 'change-value up';
            } else if (pdata.change < 0) {
                changeValueEl.style.color = 'var(--neon-green)';
                changeValueEl.className = 'change-value down';
            } else {
                changeValueEl.style.color = 'var(--text-secondary)';
                changeValueEl.className = 'change-value';
            }
        }
    }

    /**
     * 更新 Dashboard 页面的价格显示（适配新版表格布局）
     * 通过 onclick 属性匹配品种代码
     */
    function updateDashboardPrice(code, pdata) {
        // 新版 dashboard 使用表格布局，行通过 onclick="openDetailModal('CODE')" 标识
        const rows = document.querySelectorAll(`tr[onclick*="openDetailModal('${code}')"]`);
        
        for (const row of rows) {
            const tds = row.querySelectorAll('td');
            if (tds.length < 3) continue;
            
            // 表格列结构：排名(0) | 品种(1) | 方向(2) | 胜率(3) | 趋势(4) | 多周期(5) | 最新价(6) | 涨跌幅(7) | 仓位(8) | 波动(9) | 信号来源(10)
            const priceTd = tds[6];
            const changeTd = tds[7];
            
            if (priceTd && pdata.price > 0) {
                const oldPrice = parseFloat(priceTd.textContent.replace(/,/g, '')) || 0;
                const newPrice = pdata.price.toFixed(0);  // Dashboard 显示整数价格
                
                // 更新价格
                priceTd.textContent = newPrice;
                
                // 红涨绿跌 - 根据涨跌幅设置颜色
                if (pdata.change_percent > 0) {
                    priceTd.style.color = 'var(--neon-red)';
                } else if (pdata.change_percent < 0) {
                    priceTd.style.color = 'var(--neon-green)';
                } else {
                    priceTd.style.color = 'var(--text-secondary)';
                }
                
                // 价格变化闪烁效果
                if (pdata.price > oldPrice) {
                    priceTd.classList.add('price-up-flash');
                    setTimeout(() => priceTd.classList.remove('price-up-flash'), CONFIG.flashDuration);
                } else if (pdata.price < oldPrice) {
                    priceTd.classList.add('price-down-flash');
                    setTimeout(() => priceTd.classList.remove('price-down-flash'), CONFIG.flashDuration);
                }
            }
            
            // 更新涨跌幅
            if (changeTd && pdata.change_percent !== undefined) {
                const changeText = `${pdata.change_percent > 0 ? '+' : ''}${pdata.change_percent.toFixed(2)}%`;
                changeTd.textContent = changeText;
                
                // 红涨绿跌
                if (pdata.change_percent > 0) {
                    changeTd.style.color = 'var(--neon-red)';
                } else if (pdata.change_percent < 0) {
                    changeTd.style.color = 'var(--neon-green)';
                } else {
                    changeTd.style.color = 'var(--text-secondary)';
                }
            }
        }
    }
    
    /**
     * 更新涨跌排行榜（紧凑行内式）
     */
    function updatePriceStats(prices) {
        // 排序
        const gainers = Object.values(prices)
            .filter(p => p.change_percent > 0.3)
            .sort((a, b) => b.change_percent - a.change_percent)
            .slice(0, 3);
        
        const losers = Object.values(prices)
            .filter(p => p.change_percent < -0.3)
            .sort((a, b) => a.change_percent - b.change_percent)
            .slice(0, 3);
        
        const active = Object.values(prices)
            .filter(p => p.volume > 0)
            .sort((a, b) => b.volume - a.volume)
            .slice(0, 3);
        
        // 更新领涨榜
        const gainersEl = document.getElementById('gainers-list');
        if (gainersEl && gainers.length > 0) {
            gainersEl.innerHTML = gainers.map(p => 
                `<span title="涨幅：${p.change_percent.toFixed(2)}%">${p.variety_name}<b class="stats-change up">+${p.change_percent.toFixed(2)}%</b></span>`
            ).join('');
        } else if (gainersEl) {
            gainersEl.innerHTML = '<span>-</span>';
        }
        
        // 更新领跌榜
        const losersEl = document.getElementById('losers-list');
        if (losersEl && losers.length > 0) {
            losersEl.innerHTML = losers.map(p => 
                `<span title="跌幅：${Math.abs(p.change_percent).toFixed(2)}%">${p.variety_name}<b class="stats-change down">${p.change_percent.toFixed(2)}%</b></span>`
            ).join('');
        } else if (losersEl) {
            losersEl.innerHTML = '<span>-</span>';
        }
        
        // 更新活跃榜（成交量）
        const activeEl = document.getElementById('active-list');
        if (activeEl && active.length > 0) {
            activeEl.innerHTML = active.map(p => {
                const volumeText = formatVolumeChinese(p.volume);
                const volumeNum = formatVolumeNumber(p.volume);
                return `<span title="成交量：${volumeNum}手\n${volumeText}反映市场关注度，成交量越大表示资金关注度越高，流动性越好">
                    ${p.variety_name}<small class="stats-volume">${volumeText}</small>
                </span>`;
            }).join('');
        } else if (activeEl) {
            activeEl.innerHTML = '<span>-</span>';
        }
    }
    
    /**
     * 格式化成交量为中文单位（万手/亿手）
     * 例如：852000 → 85.2 万手
     */
    function formatVolumeChinese(volume) {
        if (volume >= 100000000) {
            return (volume / 100000000).toFixed(2) + '亿手';
        } else if (volume >= 10000) {
            return (volume / 10000).toFixed(1) + '万手';
        } else {
            return volume + '手';
        }
    }
    
    /**
     * 格式化成交量为数字（带千分位）
     */
    function formatVolumeNumber(volume) {
        return volume.toLocaleString('zh-CN');
    }
    
    /**
     * 检查价格异动
     */
    function checkPriceAlerts() {
        fetch(`${CONFIG.apiBase}/alert?threshold=${CONFIG.alertThreshold}`)
            .then(response => response.json())
            .then(data => {
                if (data.success && data.alerts && data.alerts.length > 0) {
                    // 过滤已提示过的警报（相同品种且涨跌幅变化<0.5%）
                    const newAlerts = data.alerts.filter(alert => {
                        const key = alert.variety_code;
                        const lastAlertPercent = alertedPrices[key];

                        // 如果是新警报或涨跌幅变化超过 0.5%，则显示
                        // 休市期间或首次检查时，显示所有超过阈值的警报
                        if (lastAlertPercent === undefined) {
                            // 首次检查，显示所有警报
                            alertedPrices[key] = alert.change_percent;
                            return true;
                        }
                        
                        if (Math.abs(alert.change_percent - lastAlertPercent) >= 0.5) {
                            // 涨跌幅变化超过 0.5%，再次提示
                            alertedPrices[key] = alert.change_percent;
                            return true;
                        }
                        
                        return false;
                    });

                    if (newAlerts.length > 0) {
                        showAlerts(newAlerts);
                    }
                } else {
                    // 没有警报时，清除已提示记录（允许下次再提示）
                    alertedPrices = {};
                }
            })
            .catch(error => {
                console.error('[PriceRealtime] 检查异动失败:', error);
            });
    }

    /**
     * 更新市场状态显示
     */
    function updateMarketStatusDisplay(status) {
        // 只设置全局变量，由 dashboard.html 的 updateTimer 统一更新显示
        window.marketStatus = status;
        
        console.log(`[PriceRealtime] 市场状态更新：${status.is_trading ? '交易' : '休市'} - ${status.session}`);
    }

    /**
     * 显示价格异动提醒（已禁用弹窗，仅记录日志）
     */
    function showAlerts(alerts) {
        // 弹窗功能已禁用，仅在控制台记录
        alerts.forEach(alert => {
            console.log(`[PriceRealtime] 价格异动: ${alert.variety_name} ${alert.alert_type} ${alert.change_percent.toFixed(2)}%`);
        });
    }
    
    /**
     * 创建 Toast 通知（已禁用）
     */
    function createToast(alert) {
        // Toast 弹窗功能已禁用
        return null;
    }
    
    /**
     * 更新最后更新时间
     */
    function updateLastUpdateTime(updateTime) {
        lastUpdateTime = updateTime;  // 保存到全局变量
        
        // 格式化时间，只显示时分秒
        let timeStr = updateTime;
        if (updateTime && updateTime.includes(' ')) {
            // 如果有日期时间，只取时间部分
            const parts = updateTime.split(' ');
            timeStr = parts[1] || parts[0];
        } else if (updateTime && updateTime.length > 8) {
            // 如果是完整时间字符串，截取时分秒
            timeStr = updateTime.substring(0, 8);
        }
        
        const timeEl = document.getElementById('price-update-time');
        if (timeEl) {
            timeEl.textContent = `更新于 ${timeStr}`;
        }
        
        // 触发状态更新事件（通知 dashboard 更新状态显示）
        if (window.updatePriceRefreshTime) {
            window.updatePriceRefreshTime(timeStr);
        }
    }
    
    /**
     * 绑定手动刷新按钮
     */
    function bindRefreshButton() {
        const btn = document.getElementById('refresh-prices-btn');
        if (!btn) {
            return;
        }
        
        btn.addEventListener('click', function() {
            manualRefresh();
        });
    }
    
    /**
     * 手动刷新价格
     */
    function manualRefresh() {
        const btn = document.getElementById('refresh-prices-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="loading"></span> 刷新中...';
        }
        
        fetch(`${CONFIG.apiBase}/refresh`, { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // 立即获取新价格
                    setTimeout(fetchPrices, 1000);
                    showToast('价格已刷新', 'success');
                } else {
                    showToast('刷新失败：' + data.error, 'error');
                }
            })
            .catch(error => {
                showToast('刷新失败：' + error, 'error');
            })
            .finally(() => {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '🔄 刷新价格';
                }
            });
    }
    
    /**
     * 显示提示消息
     */
    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `simple-toast ${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.classList.add('toast-hide');
            setTimeout(() => toast.remove(), 300);
        }, 2000);
    }
    
    /**
     * 停止模块
     */
    function stop() {
        isRunning = false;
        stopAutoRefresh();
        stopAlertCheck();
        console.log('[PriceRealtime] 模块已停止');
    }
    
    /**
     * 重新启动模块
     */
    function restart() {
        stop();
        initPriceRealtime();
    }
    
    // 页面加载完成后自动初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPriceRealtime);
    } else {
        initPriceRealtime();
    }
    
    // 暴露全局 API
    window.PriceRealtime = {
        init: initPriceRealtime,
        stop: stop,
        restart: restart,
        refresh: manualRefresh,
        isRunning: () => isRunning
    };
    
})();
