/**
 * ホーム画面（商品登録・利益計算・スキャン）の画面制御ロジック。
 * - 初回免責事項モーダルの表示制御
 * - 入力値からの即時利益計算（サーバーの /api/calculate を呼び出す）
 * - JANコード入力に応じたECサイト検索リンクの更新
 * - バーコードスキャンUIの開始/停止
 * - Service Workerの登録
 */
(function () {
  "use strict";

  var DISCLAIMER_KEY = "sedori_disclaimer_ack_v1";

  function initDisclaimerModal() {
    var modal = document.getElementById("disclaimer-modal");
    var agreeBtn = document.getElementById("disclaimer-agree-btn");
    if (!modal || !agreeBtn) {
      return;
    }
    var acknowledged = false;
    try {
      acknowledged = window.localStorage.getItem(DISCLAIMER_KEY) === "1";
    } catch (e) {
      acknowledged = false;
    }
    if (!acknowledged) {
      modal.hidden = false;
    }
    agreeBtn.addEventListener("click", function () {
      modal.hidden = true;
      try {
        window.localStorage.setItem(DISCLAIMER_KEY, "1");
      } catch (e) {
        /* localStorageが使えない環境でも閉じられるようにする */
      }
    });
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      var ctx = this;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(ctx, args);
      }, wait);
    };
  }

  function initCalculator() {
    var form = document.getElementById("product-form");
    if (!form) {
      return;
    }
    var purchaseEl = document.getElementById("purchase_price");
    var sellingEl = document.getElementById("selling_price");
    var feeEl = document.getElementById("fee_rate");
    var shippingEl = document.getElementById("shipping_cost");
    var profitEl = document.getElementById("calc-profit");
    var marginEl = document.getElementById("calc-profit-margin");

    function runCalculation() {
      var payload = {
        purchase_price: purchaseEl.value,
        selling_price: sellingEl.value,
        fee_rate: feeEl.value,
        shipping_cost: shippingEl.value,
      };
      fetch("/api/calculate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          if (data.ok) {
            profitEl.textContent = data.profit;
            marginEl.textContent = data.profit_margin;
          } else {
            profitEl.textContent = "-";
            marginEl.textContent = "-";
          }
        })
        .catch(function () {
          profitEl.textContent = "-";
          marginEl.textContent = "-";
        });
    }

    var debounced = debounce(runCalculation, 250);
    [purchaseEl, sellingEl, feeEl, shippingEl].forEach(function (el) {
      if (el) {
        el.addEventListener("input", debounced);
      }
    });
  }

  function initEcLinks() {
    var janInput = document.getElementById("jan_code");
    var linkList = document.getElementById("ec-link-list");
    if (!janInput || !linkList || !window.EC_SITE_TEMPLATES) {
      return;
    }
    var templates = {};
    window.EC_SITE_TEMPLATES.forEach(function (site) {
      templates[site.key] = site.url_template;
    });

    function updateLinks() {
      var jan = encodeURIComponent(janInput.value.trim());
      var links = linkList.querySelectorAll(".ec-link");
      links.forEach(function (link) {
        var key = link.getAttribute("data-site-key");
        var template = templates[key];
        if (template) {
          link.setAttribute("href", template.replace("{jan}", jan));
        }
      });
    }

    janInput.addEventListener("input", updateLinks);
    updateLinks();
  }

  function initScanner() {
    var startBtn = document.getElementById("scan-start-btn");
    var stopBtn = document.getElementById("scan-stop-btn");
    var videoWrap = document.getElementById("scan-video-wrap");
    var video = document.getElementById("scan-video");
    var status = document.getElementById("scan-status");
    var janInput = document.getElementById("jan_code");

    if (!startBtn || !window.SedoriScanner) {
      return;
    }

    startBtn.addEventListener("click", function () {
      videoWrap.hidden = false;
      startBtn.hidden = true;
      stopBtn.hidden = false;
      status.textContent = "カメラを起動しています...";

      window.SedoriScanner.start(
        video,
        function onDetected(code) {
          janInput.value = code;
          janInput.dispatchEvent(new Event("input"));
          status.textContent = "バーコードを読み取りました: " + code;
          videoWrap.hidden = true;
          startBtn.hidden = false;
          stopBtn.hidden = true;
        },
        function onError(message) {
          status.textContent = message;
          videoWrap.hidden = true;
          startBtn.hidden = false;
          stopBtn.hidden = true;
        }
      );
    });

    stopBtn.addEventListener("click", function () {
      window.SedoriScanner.stop();
      videoWrap.hidden = true;
      startBtn.hidden = false;
      stopBtn.hidden = true;
      status.textContent = "スキャンを停止しました。";
    });
  }

  function initPhotoIdentify() {
    var btn = document.getElementById("photo-identify-btn");
    var input = document.getElementById("photo-input");
    var status = document.getElementById("identify-status");
    var list = document.getElementById("identify-candidates");
    var nameInput = document.getElementById("name");
    if (!btn || !input || !status || !list || !nameInput) {
      return;
    }

    btn.addEventListener("click", function () {
      input.click();
    });

    input.addEventListener("change", function () {
      if (!input.files || input.files.length === 0) {
        return;
      }
      var file = input.files[0];
      var formData = new FormData();
      formData.append("photo", file);

      status.textContent = "AIが商品を判別しています...";
      list.innerHTML = "";
      btn.disabled = true;

      fetch("/api/identify", { method: "POST", body: formData })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          btn.disabled = false;
          input.value = "";
          if (!data.ok) {
            status.textContent = data.error || "判別に失敗しました。";
            return;
          }
          if (!data.candidates || data.candidates.length === 0) {
            status.textContent =
              "商品を特定できませんでした。別の角度から撮影するか、商品名を直接入力してください。";
            return;
          }
          status.textContent = "候補をタップすると商品名欄に入力されます。";
          data.candidates.forEach(function (candidate) {
            var li = document.createElement("li");
            var a = document.createElement("a");
            a.href = "#";
            a.className = "ec-link";
            a.textContent =
              candidate.name + (candidate.note ? "（" + candidate.note + "）" : "");
            a.addEventListener("click", function (e) {
              e.preventDefault();
              nameInput.value = candidate.name;
              nameInput.dispatchEvent(new Event("input"));
              status.textContent = "商品名欄に入力しました: " + candidate.name;
            });
            li.appendChild(a);
            list.appendChild(li);
          });
        })
        .catch(function () {
          btn.disabled = false;
          input.value = "";
          status.textContent = "通信エラーが発生しました。";
        });
    });
  }

  /**
   * 横断価格比較機能（楽天市場API・Yahoo!ショッピングAPI）。
   * - 楽天市場: サーバー側の /api/prices を呼び出す（サーバーが有効/無効を判定済み）。
   * - Yahoo!ショッピング: ブラウザから直接APIを呼び出す。CORS等で失敗した場合は
   *   検索リンク提示のみへ自動フォールバックする。
   * 取得した最安値・中央値はワンタップで想定売価欄に設定できる（自動確定はしない）。
   */
  function initPriceComparison() {
    var btn = document.getElementById("price-fetch-btn");
    var janInput = document.getElementById("jan_code");
    var sellingEl = document.getElementById("selling_price");
    var status = document.getElementById("price-status");
    var summaryBox = document.getElementById("price-summary");
    var lowestEl = document.getElementById("price-lowest");
    var medianEl = document.getElementById("price-median");
    var rakutenStatus = document.getElementById("price-rakuten-status");
    var rakutenList = document.getElementById("price-rakuten-list");
    var yahooStatus = document.getElementById("price-yahoo-status");
    var yahooList = document.getElementById("price-yahoo-list");

    if (!btn || !janInput || !sellingEl) {
      return;
    }

    var lastPrices = { lowest: null, median: null };

    function median(sortedNums) {
      var n = sortedNums.length;
      if (n === 0) {
        return null;
      }
      var mid = Math.floor(n / 2);
      if (n % 2 === 0) {
        return (sortedNums[mid - 1] + sortedNums[mid]) / 2;
      }
      return sortedNums[mid];
    }

    function renderItems(listEl, items) {
      listEl.innerHTML = "";
      items.forEach(function (item) {
        var li = document.createElement("li");
        var label = (item.item_name || "商品") + " - " + item.price + "円";
        if (item.url) {
          var a = document.createElement("a");
          a.href = item.url;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.className = "ec-link";
          a.textContent = label;
          li.appendChild(a);
        } else {
          li.textContent = label;
        }
        listEl.appendChild(li);
      });
    }

    function updateSummary(allPrices) {
      if (!allPrices || allPrices.length === 0) {
        summaryBox.hidden = true;
        lastPrices = { lowest: null, median: null };
        return;
      }
      var sorted = allPrices.slice().sort(function (a, b) {
        return a - b;
      });
      lastPrices = { lowest: sorted[0], median: median(sorted) };
      lowestEl.textContent = lastPrices.lowest;
      medianEl.textContent = lastPrices.median;
      summaryBox.hidden = false;
    }

    function fetchRakuten(jan) {
      if (!window.RAKUTEN_ENABLED) {
        rakutenStatus.textContent = "楽天市場API未設定のため利用できません。";
        rakutenList.innerHTML = "";
        return Promise.resolve([]);
      }
      rakutenStatus.textContent = "取得中...";
      return fetch("/api/prices?jan=" + encodeURIComponent(jan))
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.data.ok) {
            rakutenStatus.textContent =
              (result.data.error || "楽天市場の価格取得に失敗しました。") + " 再取得できます。";
            rakutenList.innerHTML = "";
            return [];
          }
          var items = result.data.rakuten.prices || [];
          rakutenStatus.textContent = items.length
            ? "取得件数: " + items.length + "件（" + result.data.fetched_at + " 時点）"
            : "該当する商品が見つかりませんでした。";
          renderItems(rakutenList, items);
          return items.map(function (p) {
            return p.price;
          });
        })
        .catch(function () {
          rakutenStatus.textContent =
            "楽天市場の価格取得に失敗しました。通信状況を確認し、再取得してください。";
          rakutenList.innerHTML = "";
          return [];
        });
    }

    function fetchYahoo(jan) {
      if (!window.YAHOO_CLIENT_ID) {
        yahooStatus.textContent =
          "Yahoo!ショッピングAPI未設定のため利用できません（下部の検索リンクをご利用ください）。";
        yahooList.innerHTML = "";
        return Promise.resolve([]);
      }
      yahooStatus.textContent = "取得中...";
      var url =
        window.YAHOO_API_URL +
        "?appid=" +
        encodeURIComponent(window.YAHOO_CLIENT_ID) +
        "&jan_code=" +
        encodeURIComponent(jan) +
        "&results=" +
        (window.YAHOO_SEARCH_RESULTS || 20) +
        "&sort=+price";

      return fetch(url)
        .then(function (res) {
          if (!res.ok) {
            throw new Error("yahoo shopping api error: " + res.status);
          }
          return res.json();
        })
        .then(function (data) {
          var hits = (data && data.hits) || [];
          var items = hits.map(function (hit) {
            return {
              price: hit.price,
              item_name: hit.name,
              url: hit.url,
            };
          });
          yahooStatus.textContent = items.length
            ? "取得件数: " + items.length + "件"
            : "該当する商品が見つかりませんでした。";
          renderItems(yahooList, items);
          return items.map(function (i) {
            return i.price;
          });
        })
        .catch(function () {
          // CORS等で取得できない場合は検索リンク提示のみへ自動フォールバックする。
          yahooStatus.textContent =
            "Yahoo!ショッピングの価格取得に失敗しました。下部の検索リンクをご利用ください。";
          yahooList.innerHTML = "";
          return [];
        });
    }

    btn.addEventListener("click", function () {
      var jan = janInput.value.trim();
      if (!jan) {
        status.textContent = "JANコードを入力してから取得してください。";
        return;
      }
      btn.disabled = true;
      summaryBox.hidden = true;
      status.textContent = "価格を取得しています...";

      Promise.all([fetchRakuten(jan), fetchYahoo(jan)]).then(function (results) {
        updateSummary(results[0].concat(results[1]));
        var fetchedAt = new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
        status.textContent = "取得が完了しました（" + fetchedAt + "時点の価格。実売相場・在庫を保証するものではありません）。";
        btn.disabled = false;
      });
    });

    var setButtons = summaryBox
      ? summaryBox.querySelectorAll(".btn-set-price")
      : [];
    setButtons.forEach(function (setBtn) {
      setBtn.addEventListener("click", function () {
        var target = setBtn.getAttribute("data-target");
        var value = lastPrices[target];
        if (value === null || value === undefined) {
          return;
        }
        // ワンタップで想定売価欄へ設定するが、自動確定はしない
        // （ユーザーが値を確認・編集できる）。
        sellingEl.value = Math.round(value);
        sellingEl.dispatchEvent(new Event("input"));
        status.textContent =
          "想定売価欄に" + (target === "lowest" ? "最安値" : "中央値") +
          "（" + Math.round(value) + "円）を設定しました。内容をご確認ください。";
      });
    });
  }

  function initServiceWorker() {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/static/sw.js").catch(function () {
        /* SW登録失敗時も画面利用は継続可能なため握りつぶす */
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initDisclaimerModal();
    initCalculator();
    initEcLinks();
    initScanner();
    initPhotoIdentify();
    initPriceComparison();
    initServiceWorker();
  });
})();
