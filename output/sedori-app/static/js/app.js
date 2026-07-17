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
    initServiceWorker();
  });
})();
