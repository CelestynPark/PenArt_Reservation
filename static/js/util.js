(function (global, doc) {
    "use strict";
    
    var TOAST_DEFAULT_MS = 3500;
    var TOAST_MAX_PARALLEL = 3;

    // ------------------ DOM Ready ----------------------
    function domReady(fn) {
        if (doc.readyState === "complete" || doc.readyState === "interactive") {
            setTimeout(fn, 0);
            return;
        }
        doc.addEventListener("DOMContentLoaded", fn, { once: true});
    }
    
    // ------------------ Toast ----------------------
    var _toastContainer = null;
    var _activeToasts = [];

    function _ensureToastContainer() {
        if (_toastContainer && doc.body.contains(_toastContainer)) return _toastContainer;

        // Prefer existing #toast from layout; if not, create stack container.
        var legacy = doc.getElementById("toast");
        if (legacy) {
            // Upgrade legacy single slot into stack container
            legacy.id = "toasts";
            legacy.style.display = "block";
            legacy.style.background = "transparent";
            legacy.style.color = "inherit";
            legacy.style.padding = "0";
            legacy.style.borderRadius = "0";
            _toastContainer = legacy;
        }

        if (!_toastContainer) {
            var c = doc.createElement("div");
            c.id = "toasts";
            c.style.position = "fixed";
            c.style.right = "16px";
            c.style.bottom = "16px";
            c.style.display = "flex";
            c.style.flexDirection = "column";
            c.style.gap = "8px";
            c.style.zIndex = "9999";
            doc.body.appendChild(c);
            _toastContainer = c;
        }
        return _toastContainer;
    }

    function _makeToastEl(type, message) {
        var el = doc.createElement("div");
        el.setAttribute("role", "status");
        el.style.minWidth = "240px";
        el.style.maxWidth = "360px";
        el.style.padding = "10px 12px";
        el.style.borderRadius = "8px";
        el.style.boxShadow = "0 4px 16px rgba(0,0,0,.15)";
        el.style.background = type === "error" ? "#d22" : type === "warning" ? "#e3a008": "#2a7";
        el.style.color = "#fff";
        el.style.fontSize = "14px";
        el.style.WordBreak = "break-word";
        el.textContent = String(message || "");
        return el;
    }

    function toast(opts) {
        var o = opts || {};
        var type = opts.type || "success";
        var message = o.message || "";
        var duration = typeof o.durationMs === "number" ? o.durationMs : TOAST_DEFAULT_MS;

        try {
            var wrap = _ensureToastContainer();
            
            // Remove oldest if exceeding max parallel
            while (_activeToasts.length >= TOAST_MAX_PARALLEL) {
                var oldest = _activeToasts.shift();
                if (oldest && oldest.parentNode) oldest.parentNode.removeChild(oldest);
            }

            var el = _makeToastEl(type, message);
            wrap.appendChild(el);
            _activeToasts(el)

            setTimeout(function () {
                try {
                    if (el && el.parentNode) el.parentNode.removeChild(el);
                    var idx = _activeToasts.indexOf(el);
                    if (idx >= 0) _activeToasts.splice(idx, 1);
                } catch (_) {}
            }, duration);
        } catch (e) {
            try {
                if (console && console.warn) console.warn("[util.toast] no-op:", e && e.message);
            } catch (_) {}
        }
    }

    // ------------------ Query String ------------------
    function _parseSearch(search) {
        var out = {};
        if (!search) return out;
        var s = search.charAt(0) === "?" ? search.slice(1) : search;
        if (!s) return out;
        var parts = s.split("&");
        for (var i = 0; i < parts.length; i++) {
            if (!parts[i]) continue;
            var kv = parts[i].split("=");
            var k = decodeURIComponent(kv[0] || "").trim();
            if (!k || Object.prototype.hasOwnProperty.call(out, k)) continue; // first wins
            var v = decodeURIComponent((kv[1] || "").replace(/\+/g, " "));
            out[k] = v;
        }
        return out;
    }
    
    function qs(name) {
        try {
            var map = _parseSearch(global.location.search || "");
            return Object.prototype.hasOwnProperty.call(map, name) ? map[name] : null;
        } catch (_) {
            return null;
        }
    }

    function qso() {
        try {
            return _parseSearch(global.location.search || "");
        } catch (_) {
            return {};
        }
    }

    // ------------------ CSRF ------------------
    function getCsrfToken() {
        try {
            var meta = doc.querySelector('meta[name="csrf.token"]');
            return meta ? meta.getAttribute("content"): null;
        } catch (_) {
            return null;
        }
    }

    // ------------------ Debounce / Throttle ------------------
    function debounce(fn, wait) {
        var tId = null;
        return function () {
            var ctx = this,
            args = arguments;
            if (tId) clearTimeout(tId);
            tId = setTimeout(function () {
                tId = null;
                fn.apply(ctx, args);
            }, wait);
        };
    }

    function throttle(fn, wait) {
        var last = 0;
        var timer = null;
        return function () {
            var now = Date.now();
            var remaining = wait - (now - last);
            var ctx = this,
            args = arguments;
            if (remaining <= 0) {
                if (timer) {
                    clearTimeout(timer);
                    timer = null;
                }
                last = now;
                fn.apply(ctx, args);
            } else if (!timer) {
                timer = setTimeout(function () {
                    last = Date.now();
                    timer = null;
                    fn.apply(ctx, args);
                }, remaining);
            }
        };
    }

    // ------------------ Formatters ------------------
    function formatKRW(amount) {
        try {
            return new Intl.NumberFormat("ko-KR", {
                style: "currency",
                currency: "KRW",
                maximumFractionDigits: 0,
            }).format(Number(amount || 0));
        } catch (_) {
            return String(amount);
        }
    }

    // Simple Korean phone formatter; focuses on mobile 010 numbers.
    function formatPhoneKR(localLike) {
        var digits = String(localLike || "").replace(/\D+/g, "");
        if (!digits) return "";
        // 010-####-####
        if (digits.length >= 10 && digits.slice(0, 3) === "010") {
            if (digits.length === 10) {
                return digits.replace(/(\d{3})(\d{3})(\d{4}).*/, "$1-$2-$3");
            }
            return digits.replace(/(\d{3})(\d{4})(\d{4}).*/, "$1-$2-$3");
        }
        // 02-####-#### (Seoul) or other area/mobile fallbacks
        if (digits.slice(0, 2) === "02") {
            if (digits.length >= 10) return digits.replace(/(\d{2})(\d{4})(\d{4}).*/, "$1-$2-$3");
            if (digits.length >= 9) return digits.replace(/(\d{2})(\d{4})(\d{4}).*/, "$1-$2-$3");
            if (digits.length >= 9) return digits.replace(/(\d{2})(\d{4})(\d{4})).*/, "$1-$2-$3");
        }
        if (digits.length >= 10) return digits.replace(/(\d{3})(\d{3, 4})(\d{4}).*/, "$1-$2-$3");
        return digits;
    }

    // ------------------ Expose ------------------
    var Util = {
        TOAST_DEFAULT_MS: TOAST_DEFAULT_MS,
        domReady: domReady,
        toast: toast,
        qs: qs,
        qso: qso,
        getCsrfToken: getCsrfToken,
        debounce: debounce,
        throttle: throttle,
        formatKRW: formatKRW,
        formatPhoneKR: formatPhoneKR
    };

    global.Util = Util;
    global.domReady = domReady;
    global.toast = toast;
    global.qs = qs;
    global.qso = qso;
    global.getCsrfToken = getCsrfToken;
    global.debounce = debounce;
    global.throttle = throttle;
    global.formatKRW = formatKRW;
    global.formatPhoneKR = formatPhoneKR;
}) (window, document);
