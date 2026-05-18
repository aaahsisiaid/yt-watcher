const CACHE = 'yt-watcher-v3';
const PRECACHE = ['/yt-watcher/', '/yt-watcher/index.html', '/yt-watcher/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  if (e.request.url.includes('/api/') || e.request.url.includes('workers.dev')) return;
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

// Push notification
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data.json(); } catch {}
  const title = data.title || 'YT Watcher';
  const body  = data.body  || '';
  const url   = data.url   || '/yt-watcher/';
  e.waitUntil(Promise.all([
    self.registration.showNotification(title, {
      body,
      tag:  data.type || 'yt-watcher',
      data: { url },
      actions: url ? [{ action: 'open', title: '開く' }] : []
    }),
    self.clients.matchAll({ type: 'window' }).then(clients => {
      clients.forEach(c => c.postMessage({ type: 'push', title, body, url }));
    })
  ]));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = e.notification.data?.url || '/yt-watcher/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cls => {
      for (const c of cls) {
        if (c.url.includes('/yt-watcher') && 'focus' in c) return c.focus();
      }
      return clients.openWindow(url);
    })
  );
});
