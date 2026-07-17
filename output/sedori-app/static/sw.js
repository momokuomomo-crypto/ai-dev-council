/**
 * Service Worker: 登録済みデータのオフラインキャッシュ・閲覧機能を提供する。
 *
 * 方針:
 * - 静的リソース（CSS/JS/マニフェスト/アイコン）はキャッシュファースト。
 * - ページ（ホーム/一覧/設定）はネットワークファースト。
 *   オンライン時は常に最新のHTML（=最新の登録商品データ）を取得してキャッシュを更新し、
 *   オフライン時はキャッシュ済みの最後のページ（＝最後に閲覧した登録商品一覧など）を表示する。
 * - POST等の書き込みリクエスト（登録・削除・設定変更）はキャッシュ対象外。オフライン時は
 *   ネットワークエラーとなる（オフラインでの新規登録・削除は非対応。閲覧のみサポート）。
 */

var CACHE_NAME = "sedori-cache-v1";

var PRECACHE_URLS = [
  "/",
  "/products",
  "/settings",
  "/static/css/style.css",
  "/static/js/app.js",
  "/static/js/scanner.js",
  "/static/manifest.json",
  "/static/icons/icon-192.svg",
  "/static/icons/icon-512.svg",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then(function (cache) {
        return Promise.all(
          PRECACHE_URLS.map(function (url) {
            return cache.add(url).catch(function () {
              // 初回インストール時にサーバーが起動していない等でも失敗させない
            });
          })
        );
      })
      .then(function () {
        return self.skipWaiting();
      })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (keys) {
        return Promise.all(
          keys
            .filter(function (key) {
              return key !== CACHE_NAME;
            })
            .map(function (key) {
              return caches.delete(key);
            })
        );
      })
      .then(function () {
        return self.clients.claim();
      })
  );
});

function isWriteRequest(request) {
  return request.method !== "GET";
}

function networkFirst(request) {
  return fetch(request)
    .then(function (response) {
      if (response && response.ok) {
        var responseClone = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(request, responseClone);
        });
      }
      return response;
    })
    .catch(function () {
      return caches.match(request).then(function (cached) {
        if (cached) {
          return cached;
        }
        return new Response(
          "<html><body><h1>オフラインです</h1>" +
            "<p>ネットワークに接続できないため、このページはまだキャッシュされていません。</p></body></html>",
          { headers: { "Content-Type": "text/html; charset=utf-8" }, status: 200 }
        );
      });
    });
}

function cacheFirst(request) {
  return caches.match(request).then(function (cached) {
    return (
      cached ||
      fetch(request).then(function (response) {
        if (response && response.ok) {
          var responseClone = response.clone();
          caches.open(CACHE_NAME).then(function (cache) {
            cache.put(request, responseClone);
          });
        }
        return response;
      })
    );
  });
}

self.addEventListener("fetch", function (event) {
  var request = event.request;

  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) {
    // 書き込み系リクエスト・外部オリジン（ECサイトへのリンク遷移等）はそのままネットワークへ
    return;
  }

  var url = new URL(request.url);
  var isStatic = url.pathname.indexOf("/static/") === 0;

  if (isStatic) {
    event.respondWith(cacheFirst(request));
  } else {
    event.respondWith(networkFirst(request));
  }
});
