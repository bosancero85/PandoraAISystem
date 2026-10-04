'use strict';
// Service Worker: hält die App-Hülle offline bereit.
// Netzwerk zuerst (Updates kommen sofort an), Cache nur als Rückfall.
// Anfragen an Ollama (andere Herkunft oder /api/) und alles außer GET bleiben unberührt.
const CACHE = 'pandora-code-v3';
const SHELL = ['ollama.html', 'style.css', 'script.js', 'manifest.json', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-maskable-512.png', 'icons/apple-touch-icon.png'];

self.addEventListener('install', function(e){
  e.waitUntil(caches.open(CACHE).then(function(c){ return c.addAll(SHELL); }).then(function(){ return self.skipWaiting(); }));
});

self.addEventListener('activate', function(e){
  e.waitUntil(
    caches.keys()
      .then(function(keys){ return Promise.all(keys.filter(function(k){ return k !== CACHE; }).map(function(k){ return caches.delete(k); })); })
      .then(function(){ return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function(e){
  const req = e.request;
  if(req.method !== 'GET') return;
  const url = new URL(req.url);
  if(url.origin !== self.location.origin || url.pathname.indexOf('/api/') >= 0) return;
  e.respondWith(
    fetch(req).then(function(res){
      if(res && res.ok && res.type === 'basic'){
        const copy = res.clone();
        caches.open(CACHE).then(function(c){ return c.put(req, copy); });
      }
      return res;
    }).catch(function(){
      return caches.match(req, { ignoreSearch: true }).then(function(hit){
        return hit || (req.mode === 'navigate' ? caches.match('ollama.html') : Response.error());
      });
    })
  );
});
