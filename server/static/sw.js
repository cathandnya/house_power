// Service Worker for PWA
const CACHE_NAME = 'power-monitor-v1';
const ASSETS = [
  '/',
  '/static/manifest.json',
  'https://cdn.jsdelivr.net/npm/chart.js'
];

// インストール時にキャッシュ
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS);
    })
  );
  self.skipWaiting();
});

// アクティベート時に古いキャッシュを削除
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// プッシュ通知受信
self.addEventListener('push', event => {
  if (!event.data) {
    return;
  }

  try {
    const data = event.data.json();
    const options = {
      body: data.body || '',
      icon: data.icon || '/static/icons/icon-192.png',
      badge: data.badge || '/static/icons/icon-72.png',
      tag: data.tag || 'power-monitor',
      requireInteraction: data.requireInteraction || false,
      data: {
        url: data.url || '/'
      }
    };

    event.waitUntil(
      self.registration.showNotification(data.title || '電力モニター', options)
    );
  } catch (e) {
    console.error('Push notification error:', e);
  }
});

// 通知クリック時
self.addEventListener('notificationclick', event => {
  event.notification.close();

  const url = event.notification.data?.url || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      // 既存のウィンドウがあればフォーカス
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          return client.focus();
        }
      }
      // なければ新規ウィンドウを開く
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});

// ネットワーク優先、失敗時にキャッシュ
self.addEventListener('fetch', event => {
  // API/WebSocketはキャッシュしない
  if (event.request.url.includes('/api/') || event.request.url.includes('/ws/')) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // 成功したらキャッシュを更新
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          cache.put(event.request, responseClone);
        });
        return response;
      })
      .catch(() => {
        // オフライン時はキャッシュから
        return caches.match(event.request);
      })
  );
});
