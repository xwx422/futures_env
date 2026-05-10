/**
 * AI期货分析助手 - 移动端核心JavaScript
 * 功能：PWA支持、UI交互、网络状态监控、Toast提示
 */

(function() {
    'use strict';

    // ============================================
    // 全局配置
    // ============================================
    const CONFIG = {
        toastDuration: 3000,
        refreshThreshold: 80, // 下拉刷新阈值(px)
        apiBaseUrl: '', // 相对路径
        cachePrefix: 'futures_ai_'
    };

    // ============================================
    // DOM 工具函数
    // ============================================
    const $ = (selector) => document.querySelector(selector);
    const $$ = (selector) => document.querySelectorAll(selector);

    const dom = {
        on: (element, event, handler) => {
            element.addEventListener(event, handler, { passive: true });
        },
        off: (element, event, handler) => {
            element.removeEventListener(event, handler);
        },
        ready: (callback) => {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', callback);
            } else {
                callback();
            }
        }
    };

    // ============================================
    // Toast 提示系统
    // ============================================
    const toast = {
        container: null,
        
        init() {
            this.container = $('#toast-container');
            if (!this.container) {
                this.container = document.createElement('div');
                this.container.id = 'toast-container';
                this.container.className = 'toast-container';
                document.body.appendChild(this.container);
            }
        },

        show(message, type = 'info', duration = CONFIG.toastDuration) {
            if (!this.container) this.init();

            const toastEl = document.createElement('div');
            toastEl.className = `toast ${type}`;
            toastEl.textContent = message;

            this.container.appendChild(toastEl);

            // 自动移除
            setTimeout(() => {
                toastEl.style.opacity = '0';
                toastEl.style.transform = 'translateY(-20px)';
                setTimeout(() => toastEl.remove(), 300);
            }, duration);
        },

        success(message, duration) {
            this.show(message, 'success', duration);
        },

        error(message, duration) {
            this.show(message, 'error', duration);
        },

        warning(message, duration) {
            this.show(message, 'warning', duration);
        }
    };

    // ============================================
    // 网络状态监控
    // ============================================
    const network = {
        statusEl: null,
        isOnline: navigator.onLine,

        init() {
            this.statusEl = $('#network-status');
            
            dom.on(window, 'online', () => this.handleOnline());
            dom.on(window, 'offline', () => this.handleOffline());

            // 初始化状态
            this.isOnline = navigator.onLine;
        },

        handleOnline() {
            this.isOnline = true;
            toast.success('网络已恢复');
            
            // 触发同步事件
            document.dispatchEvent(new CustomEvent('network:online'));
        },

        handleOffline() {
            this.isOnline = false;
            toast.warning('网络已断开，部分功能可能不可用');
            
            // 触发离线事件
            document.dispatchEvent(new CustomEvent('network:offline'));
        },

        check() {
            return this.isOnline;
        }
    };

    // ============================================
    // 加载状态管理
    // ============================================
    const loading = {
        el: null,

        init() {
            this.el = $('#global-loading');
        },

        show() {
            if (this.el) this.el.style.display = 'flex';
        },

        hide() {
            if (this.el) this.el.style.display = 'none';
        },

        async wrap(promise, message = '加载中...') {
            this.show();
            try {
                const result = await promise;
                return result;
            } finally {
                this.hide();
            }
        }
    };

    // ============================================
    // 下拉刷新
    // ============================================
    const pullRefresh = {
        init(selector, callback) {
            const container = $(selector);
            if (!container) return;

            let startY = 0;
            let currentY = 0;
            let isPulling = false;
            let isRefreshing = false;

            const indicator = document.createElement('div');
            indicator.className = 'pull-refresh-indicator';
            indicator.innerHTML = '<span class="loading-spinner" style="width:20px;height:20px;margin-right:8px;"></span>下拉刷新';
            container.prepend(indicator);

            const touchStart = (e) => {
                if (container.scrollTop > 0 || isRefreshing) return;
                startY = e.touches[0].clientY;
                isPulling = true;
            };

            const touchMove = (e) => {
                if (!isPulling || isRefreshing) return;
                
                currentY = e.touches[0].clientY;
                const diff = currentY - startY;
                
                if (diff > 0 && container.scrollTop === 0) {
                    e.preventDefault();
                    const pullDistance = Math.min(diff * 0.5, 100);
                    container.style.transform = `translateY(${pullDistance}px)`;
                    
                    if (pullDistance >= CONFIG.refreshThreshold) {
                        indicator.innerHTML = '<span style="margin-right:8px;">⬆</span>释放刷新';
                    }
                }
            };

            const touchEnd = () => {
                if (!isPulling || isRefreshing) return;
                
                const diff = currentY - startY;
                isPulling = false;

                if (diff >= CONFIG.refreshThreshold) {
                    // 触发刷新
                    isRefreshing = true;
                    container.style.transform = `translateY(50px)`;
                    container.style.transition = 'transform 0.2s ease';
                    indicator.innerHTML = '<span class="loading-spinner" style="width:20px;height:20px;margin-right:8px;"></span>刷新中...';
                    
                    Promise.resolve(callback()).finally(() => {
                        setTimeout(() => {
                            container.style.transform = 'translateY(0)';
                            isRefreshing = false;
                            indicator.innerHTML = '<span class="loading-spinner" style="width:20px;height:20px;margin-right:8px;"></span>下拉刷新';
                        }, 500);
                    });
                } else {
                    container.style.transform = 'translateY(0)';
                    container.style.transition = 'transform 0.2s ease';
                }

                setTimeout(() => {
                    container.style.transition = '';
                }, 200);
            };

            container.addEventListener('touchstart', touchStart, { passive: false });
            container.addEventListener('touchmove', touchMove, { passive: false });
            container.addEventListener('touchend', touchEnd, { passive: true });
        }
    };

    // ============================================
    // 本地存储工具
    // ============================================
    const storage = {
        set(key, value) {
            try {
                localStorage.setItem(CONFIG.cachePrefix + key, JSON.stringify(value));
                return true;
            } catch (e) {
                console.error('Storage set error:', e);
                return false;
            }
        },

        get(key, defaultValue = null) {
            try {
                const item = localStorage.getItem(CONFIG.cachePrefix + key);
                return item ? JSON.parse(item) : defaultValue;
            } catch (e) {
                console.error('Storage get error:', e);
                return defaultValue;
            }
        },

        remove(key) {
            localStorage.removeItem(CONFIG.cachePrefix + key);
        },

        clear() {
            Object.keys(localStorage)
                .filter(key => key.startsWith(CONFIG.cachePrefix))
                .forEach(key => localStorage.removeItem(key));
        }
    };

    // ============================================
    // API 请求封装
    // ============================================
    const api = {
        async request(url, options = {}) {
            const defaultOptions = {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json'
                }
            };

            const response = await fetch(url, { ...defaultOptions, ...options });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return response.json();
            }
            return response.text();
        },

        get(url) {
            return this.request(url);
        },

        post(url, data) {
            return this.request(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
        }
    };

    // ============================================
    // 底部导航激活状态
    // ============================================
    const bottomNav = {
        init() {
            const nav = $('#bottom-nav');
            if (!nav) return;

            const currentPage = document.body.dataset.page;
            if (!currentPage) return;

            nav.querySelectorAll('.nav-item').forEach(item => {
                if (item.dataset.page === currentPage) {
                    item.classList.add('active');
                } else {
                    item.classList.remove('active');
                }
            });
        }
    };

    // ============================================
    // 手势返回支持
    // ============================================
    const gestures = {
        init() {
            let startX = 0;
            let startTime = 0;

            dom.on(document, 'touchstart', (e) => {
                startX = e.touches[0].clientX;
                startTime = Date.now();
            });

            dom.on(document, 'touchend', (e) => {
                const endX = e.changedTouches[0].clientX;
                const endTime = Date.now();
                const diffX = endX - startX;
                const diffTime = endTime - startTime;

                // 边缘右滑返回
                if (startX < 30 && diffX > 80 && diffTime < 300) {
                    this.goBack();
                }
            });
        },

        goBack() {
            if (window.history.length > 1) {
                window.history.back();
            }
        }
    };

    // ============================================
    // 初始化
    // ============================================
    dom.ready(() => {
        // 初始化各模块
        toast.init();
        network.init();
        loading.init();
        bottomNav.init();
        gestures.init();

        // 防止 iOS 双击缩放
        let lastTouchEnd = 0;
        dom.on(document, 'touchend', (e) => {
            const now = Date.now();
            if (now - lastTouchEnd <= 300) {
                e.preventDefault();
            }
            lastTouchEnd = now;
        }, false);

        // 禁止 iOS 弹性滚动回弹时的空白
        dom.on(document, 'touchmove', (e) => {
            if (e.target.closest('.scroll-container')) return;
        }, { passive: true });

        console.log('🚀 Mobile app initialized');
    });

    // ============================================
    // 暴露全局 API
    // ============================================
    window.MobileApp = {
        toast,
        loading,
        network,
        storage,
        api,
        pullRefresh,
        utils: {
            $,
            $$,
            dom
        }
    };

})();
