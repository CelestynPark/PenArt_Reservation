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

    
})