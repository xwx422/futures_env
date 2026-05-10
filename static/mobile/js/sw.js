/**
 * AI期货分析助手 - Service Worker
 * 功能：离线缓存、后台同步、推送通知支持
 */

const CACHE_NAME = 'futures-ai-v1';
const STATIC_CACHE = 'futures-ai-static-v1';
const DYNAMIC_CACHE = 'futures-ai-dynamic-v1';

// 核心静态资源 - 安装时缓存
const CORE_ASSETS = [
    '/static/mobile/css/mobile.css',
    '/static/mobile/js/mobile.js',
    '/static/fonts/inter.css',
    '/static/logo.svg'
];

// 核心页面 - 用于离线访问
const CORE_PAGES = [
    '/mobile/dashboard',
    '/mobile/signals',
    '/mobile/profile',
    '/mobile/login'
];

// 安装事件 - 预缓存核心资源
self.addEventListener('install', (event) => {
    console.log('[SW] Installing Service Worker...');
    
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[SW] Caching core static assets');
                return cache.addAll(CORE_ASSETS);
            })
            .then(() => {
                // 缓存核心页面
                return caches.open(DYNAMIC_CACHE);
            })
            .then((cache) => {
                // 使用addAll会失败如果任何请求失败，所以使用单独缓存
                const pagePromises = CORE_PAGES.map(url => 
                    fetch(url)
                        .then(response => {
                            if (response.ok) {
                                return cache.put(url, response);
                            }
                        })
                        .catch(err => console.log('[SW] Failed to cache page:', url, err))
                );
                return Promise.all(pagePromises);
            })
            .then(() => {
                console.log('[SW] Installation complete');
                return self.skipWaiting();
            })
            .catch((error) => {
                console.error('[SW] Installation failed:', error);
            })
    );
});

// 激活事件 - 清理旧缓存
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating Service Worker...');
    
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((name) => {
                            // 删除旧的缓存版本
                            return name !== STATIC_CACHE && 
                                   name !== DYNAMIC_CACHE &&
                                   !name.startsWith('futures-ai-');
                        })
                        .map((name) => {
                            console.log('[SW] Deleting old cache:', name);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => {
                console.log('[SW] Activation complete');
                return self.clients.claim();
            })
    );
});

// 获取请求的处理策略
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);
    
    // 跳过非GET请求
    if (request.method !== 'GET') {
        return;
    }
    
    // 跳过Chrome扩展请求
    if (url.protocol === 'chrome-extension:') {
        return;
    }
    
    // 跳过API请求（不缓存）
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    // 策略1: 静态资源 - Cache First
    if (isStaticAsset(url.pathname)) {
        event.respondWith(cacheFirst(request));
        return;
    }
    
    // 策略2: 页面请求 - Network First with Cache Fallback
    if (isPageRequest(request)) {
        event.respondWith(networkFirstWithCache(request));
        return;
    }
    
    // 策略3: 其他请求 - Stale While Revalidate
    event.respondWith(staleWhileRevalidate(request));
});

// 判断是否为静态资源
function isStaticAsset(pathname) {
    const staticExtensions = [
        '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
        '.woff', '.woff2', '.ttf', '.eot', '.otf'
    ];
    return staticExtensions.some(ext => pathname.endsWith(ext));
}

// 判断是否为页面请求
function isPageRequest(request) {
    const acceptHeader = request.headers.get('accept') || '';
    return acceptHeader.includes('text/html');
}

// Cache First 策略
async function cacheFirst(request) {
    const cache = await caches.open(STATIC_CACHE);
    const cached = await cache.match(request);
    
    if (cached) {
        // 后台更新缓存
        fetch(request).then(response => {
            if (response.ok) {
                cache.put(request, response.clone());
            }
        }).catch(() => {});
        return cached;
    }
    
    try {
        const response = await fetch(request);
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        console.error('[SW] Cache first failed:', error);
        throw error;
    }
}

// Network First with Cache Fallback 策略
async function networkFirstWithCache(request) {
    try {
        const networkResponse = await fetch(request);
        
        if (networkResponse.ok) {
            // 更新缓存
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, networkResponse.clone());
            return networkResponse;
        }
        
        throw new Error('Network response not ok');
    } catch (error) {
        console.log('[SW] Network failed, trying cache:', request.url);
        
        const cache = await caches.open(DYNAMIC_CACHE);
        const cached = await cache.match(request);
        
        if (cached) {
            return cached;
        }
        
        // 如果页面缓存也没有，返回离线页面
        if (request.mode === 'navigate') {
            const offlinePage = await cache.match('/mobile/offline');
            if (offlinePage) {
                return offlinePage;
            }
        }
        
        throw error;
    }
}

// Stale While Revalidate 策略
async function staleWhileRevalidate(request) {
    const cache = await caches.open(DYNAMIC_CACHE);
    const cached = await cache.match(request);
    
    const networkFetch = fetch(request).then(response => {
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    }).catch(() => cached);
    
    return cached || networkFetch;
}

// 后台同步事件
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-analysis-data') {
        event.waitUntil(syncAnalysisData());
    }
});

// 模拟同步分析数据
async function syncAnalysisData() {
    console.log('[SW] Syncing analysis data...');
    // 这里可以实现后台数据同步逻辑
}

// 推送通知事件
self.addEventListener('push', (event) => {
    if (!event.data) return;
    
    const data = event.data.json();
    const options = {
        body: data.body || '您有新的期货分析信号',
        icon: '/static/images/icon-192x192.png',
        badge: '/static/images/icon-72x72.png',
        tag: data.tag || 'futures-signal',
        requireInteraction: true,
        data: data.data || {},
        actions: [
            {
                action: 'view',
                title: '查看详情'
            },
            {
                action: 'close',
                title: '关闭'
            }
        ]
    };
    
    event.waitUntil(
        self.registration.showNotification(
            data.title || 'AI期货分析助手',
            options
        )
    );
});

// 通知点击事件
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    
    const { action, data } = event.notification;
    
    if (action === 'close') {
        return;
    }
    
    // 默认打开应用
    event.waitUntil(
        clients.matchAll({ type: 'window' })
            .then((clientList) => {
                const urlToOpen = data.url || '/mobile/dashboard';
                
                // 检查是否有已打开的窗口
                for (const client of clientList) {
                    if (client.url.includes(urlToOpen) && 'focus' in client) {
                        return client.focus();
                    }
                }
                
                // 没有则打开新窗口
                if (clients.openWindow) {
                    return clients.openWindow(urlToOpen);
                }
            })
    );
});

// 消息事件（来自主线程）
self.addEventListener('message', (event) => {
    if (event.data === 'skipWaiting') {
        self.skipWaiting();
    }
    
    if (event.data.type === 'CACHE_URLS') {
        event.waitUntil(
            caches.open(DYNAMIC_CACHE)
                .then(cache => cache.addAll(event.data.urls))
        );
    }
});

// 周期性后台同步（如果支持）
if ('periodicSync' in self.registration) {
    self.addEventListener('periodicsync', (event) => {
        if (event.tag === 'update-analysis') {
            event.waitUntil(updateAnalysisData());
        }
    });
}

async function updateAnalysisData() {
    console.log('[SW] Periodic sync: updating analysis data');
    // 实现定期更新逻辑
}

console.log('[SW] Service Worker loaded');
