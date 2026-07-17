/**
 * バーコード（JAN/EAN）読み取り処理。
 *
 * 1. BarcodeDetector API が使えるブラウザではそれを利用する。
 * 2. 使えないブラウザ（主にiOS Safariの一部バージョン等）では
 *    ZXing.js（CDN経由で動的読み込み）にフォールバックする。
 *
 * 外部APIへの画像送信や一般物体認識は行わず、あくまで端末内でのバーコード
 * デコード処理のみを行う。
 */
(function (global) {
  "use strict";

  var ZXING_CDN_URL = "https://unpkg.com/@zxing/library@0.20.0/umd/index.min.js";
  var BARCODE_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];

  var state = {
    stream: null,
    videoEl: null,
    rafId: null,
    zxingReader: null,
    detector: null,
    running: false,
  };

  function supportsBarcodeDetector() {
    return "BarcodeDetector" in global;
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var existing = document.querySelector('script[data-sedori-src="' + src + '"]');
      if (existing) {
        resolve();
        return;
      }
      var script = document.createElement("script");
      script.src = src;
      script.dataset.sedoriSrc = src;
      script.onload = function () {
        resolve();
      };
      script.onerror = function () {
        reject(new Error("スキャナーライブラリの読み込みに失敗しました。"));
      };
      document.head.appendChild(script);
    });
  }

  function normalizeCode(rawValue) {
    return (rawValue || "").replace(/\D/g, "");
  }

  /**
   * バーコードスキャンを開始する。
   * @param {HTMLVideoElement} videoEl - プレビュー表示用のvideo要素
   * @param {Function} onDetected - 検出時のコールバック(code: string)
   * @param {Function} onError - エラー時のコールバック(message: string)
   */
  function start(videoEl, onDetected, onError) {
    if (state.running) {
      return;
    }
    state.videoEl = videoEl;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      onError("このブラウザはカメラ利用に対応していません。JANコードを直接入力してください。");
      return;
    }

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then(function (stream) {
        state.stream = stream;
        videoEl.srcObject = stream;
        state.running = true;
        return videoEl.play();
      })
      .then(function () {
        if (supportsBarcodeDetector()) {
          startWithBarcodeDetector(onDetected, onError);
        } else {
          startWithZXingFallback(onDetected, onError);
        }
      })
      .catch(function (err) {
        onError("カメラの起動に失敗しました: " + err.message);
      });
  }

  function startWithBarcodeDetector(onDetected, onError) {
    try {
      state.detector = new global.BarcodeDetector({ formats: BARCODE_FORMATS });
    } catch (err) {
      // フォーマット指定が非対応の場合はデフォルト設定で作成を試みる
      state.detector = new global.BarcodeDetector();
    }

    function tick() {
      if (!state.running) {
        return;
      }
      state.detector
        .detect(state.videoEl)
        .then(function (codes) {
          if (codes && codes.length > 0) {
            var code = normalizeCode(codes[0].rawValue);
            if (code) {
              onDetected(code);
              stop();
              return;
            }
          }
          state.rafId = global.requestAnimationFrame(tick);
        })
        .catch(function () {
          state.rafId = global.requestAnimationFrame(tick);
        });
    }
    tick();
  }

  function startWithZXingFallback(onDetected, onError) {
    loadScript(ZXING_CDN_URL)
      .then(function () {
        if (!global.ZXing) {
          onError("バーコード読み取りライブラリを利用できません。JANコードを直接入力してください。");
          return;
        }
        state.zxingReader = new global.ZXing.BrowserMultiFormatReader();
        state.zxingReader.decodeFromVideoElement(state.videoEl, function (result, err) {
          if (result) {
            var code = normalizeCode(result.getText());
            if (code) {
              onDetected(code);
              stop();
            }
          }
          // 検出できないフレームでは err (NotFoundException) が渡されるが無視して継続する
        });
      })
      .catch(function (err) {
        onError(err.message || "バーコード読み取りライブラリの読み込みに失敗しました。");
      });
  }

  function stop() {
    state.running = false;
    if (state.rafId) {
      global.cancelAnimationFrame(state.rafId);
      state.rafId = null;
    }
    if (state.zxingReader) {
      try {
        state.zxingReader.reset();
      } catch (e) {
        /* noop */
      }
      state.zxingReader = null;
    }
    if (state.stream) {
      state.stream.getTracks().forEach(function (track) {
        track.stop();
      });
      state.stream = null;
    }
    if (state.videoEl) {
      state.videoEl.srcObject = null;
    }
  }

  global.SedoriScanner = {
    start: start,
    stop: stop,
    isRunning: function () {
      return state.running;
    },
  };
})(window);
