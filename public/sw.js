const CACHE = 'yt-watcher-v2';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/yt-watcher/'])));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(r => {
      const c = r.clone();
      caches.open(CACHE).then(ca => ca.put(e.request, c));
      return r;
    }).catch(() => caches.match(e.request))
  );
});

self.addEventListener('push', e => {
  let data = {};
  try { data = e.data.json(); } catch {}
  const title = data.title || 'YT Watcher';
  const body  = data.body  || '';
  const url   = data.url   || '/yt-watcher/';
  e.waitUntil(Promise.all([
    self.registration.showNotification(title, {
      body,
      tag:  'yt-watcher',
      data: { url }
    }),
    self.clients.matchAll({ type: 'window' }).then(clients => {
      for (const c of clients) c.postMessage({ type: 'push', title, body, url });
    })
  ]));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = e.notification.data?.url || '/yt-watcher/';
  e.waitUntil(clients.openWindow(url));
});
