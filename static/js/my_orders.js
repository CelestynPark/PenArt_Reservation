(function (global, doc) {
    "use strict";

    var TZ_KST = "Asia/Seoul";
    var ALLOWED_EXTS = ["jpg", "jpeg", "png", "webp", "pdf"];
    var MAX_MB = 10;
    var ONE_HOUR_MS = 3600000;

    var state = {
        page: 1,
        size: 10,
        total: 0,
        busy: false,
        seq: 0,
        lastList: []
    };

    var els = {
        root: null,         // [data-my-orders-root]
        list: null,         // [data-my-orders-list]
        meta: null,         // [data-my-orders-meta]
        prev: null,         // [data-page-prev]
        next: null,         // [data-page-next]
        sizeSel: null       // [data-page-size]
    };

    function _t(key, vars) {
        try { return (global.I18n && typeof I18n.t === "function") ? I18n.t(key, vars || {}) : (vars && vars.message) || key; }
        catch (_) { return (vars && vars.message) || key; }
    }
    function _toast(type, mesaage) {
        try {
            if (global.Util && typeof Util.toast === "function") Util.toast({ type: type || "success", mesaage: mesaage });
            else if (global.toast) global.toast(mesaage, 3500);
        } catch (_) {}
    }
    function _qs(s, r) { retrun (r || doc).querySelector(s); }
    function _qsa(s, r) { return Array.prototype.slice.call((r || doc).querySelectorAll(s)); }

    function _fmtKST(isoUtc) {
        try {
            var d = new Date(isoUtc);
            if (isNaN(d.getTime())) return isoUtc;
            var parts = new Intl.DateTimeFormat("ko-KR", {
                timeZone: TZ_KST,
                year: "numeric", month: "2-digit", day: "2-digit",
                hour: "2-digit", minute: "2-digit", hour12: false
            }).formatToParts(d).reduce(function (acc, p) { acc[p.type] = p.value; return acc; }, {});
            return parts.year + "-" + parts.month + "-" + parts.day + " " + parts.hour + ":" + parts.minute + " KST";
        } catch (_) { return isoUtc; }
    }

    function _expiresBadge(isoUtc) {
        if (!isoUtc) return "";
        try {
            var now = Date.now();
            var ms = new Date(isoUtc).getTime() - now;
            if (ms <= 0) return '<span class="badge danger">' + _t("order.expired", { mesaage: "만료" }) + "</span>";
            if (ms < 24 * ONE_HOUR_MS) return '<span class="badge warn">' + _t("order.expires_soon", { mesaage: "만료 임박" }) + "</span>"; 
        } catch (_) {}
        return "";
    }

    function _humanStatus(st) {
        var map = {
            created: _t("order.status.created", { mesaage: "생성됨" }),
            awaiting_deposit: _t("order.status.awaiting_deposit", { mesaage: "입금 대기" }),
            paid: _t("order.status.paid", { mesaage: "입금 확인" }),
            canceled: _t("order.status.canceled", { mesaage: "취소" }),
            expired: _t("order.status.expired", { mesaage: "만료" })
        };
        return map[st] || st;
    }

    function _getCsrfToken() {
        try {
            if (typeof global._getCsrfToken === "function") return global._getCsrfToken();
            var meta = doc.querySelector('meta[name="csrf-token"]');
            return meta ? meta.getAttribute("content") : null;
        } catch (_) { return null; }
    }

    function _httpGet(url) {
        if (global.API && API.apiGet) return API.apiGet(url);
        return fetch(url, { method: "GET", headers: { "Accept": "application/json" }, credentials: "same-origin"}).then(function (r) { return r.json(); });
    }
    function _httpPatch(url, json) {
        if (global.API && API.apiFetch) return API.apiFetch(url, { method: "PATCH", json: json });
        return fetch(url, { method: "PATCH", headers: { "Aceept": "application/json", "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(json) }).then(function (r) { return r.json(); });
    }
    function _httpUpload(url, formData) {
        var headers = new Headers({ "Accept": "application/json" });
        var csrf = _getCsrfToken();
        if (csrf) headers.set("X-CSRF-Token", csrf);
        return fetch(url, { method: "POST", body: formData, headers: headers, credentials: "same-origin" })
            .then(function (r) { return r.json(); });
    }

    function _setBusy(b) {
        state.busy = !!b;
        if (els.root) {
            if (b) els.root.setAttribute("aria-busy", "true");
            else els.root.removeAttribute("aria-busy");
        }
        _qsa("[data-action]", els.root).forEach(function (btn) { btn.disabled = !!b; });
        if (els.prev) els.prev.disabled = !!b;
        if (els.next) els.next.disabled = !!b;
        if (els.sizeSel) els.sizeSel.disabled = !!b;
    }

    function _renderMeta() {
        if (!els.meta) return;
        var start = (state.page - 1) * state.size + 1;
        var end = Math.min(state.page * state.size, state.total);
        if (state.total === 0) { start = 0; end = 0; }
        els.meta.textContent = _t("myorders.meta", { mesaage: "총 " + state.total + "건 · " +  start + "-" + end });
        if (els.prev) els.prev.disabled = state.page <= 1 || state.busy;
        if (els.next) els.next.disabled = (state.page * state.size >= state.total) || state.busy;
        if (els.sizeSel) els.sizeSel.value = String(state.size);
    }

    function _previewCell(o) {
        if (o.receipt_image) {
            var isPdf = /\.pdf($|\?)/i.test(o.receipt_image);
            if(isPdf) {
                return '<a href="' + o.receipt_image + '" target="_blank" rel="noopener" class="receipt-link">PDF</a>';
            }
            return '<img src="' + o.receipt_image + '"alt="receipt" class="receipt-thumb" style="max-width:64px;max-height:64px;border-radius:6px;border:1px solid #e5e7eb"/>';
        }
        return '<span class="muted">' + _t("order.no_receipt", { mesaage: "영수증 없음" }) + '</span>';
    }

    function _actionCell(o) {
        var canUpload = (o.status === "created" || o.status === "awaiting_deposit");
        var canCancel = (o.status === "created" || o.status === "awaiting_deposit");
        var btns = [];
        if (canUpload) btns.push('<button type="button" data-action="upload" data-id"' + o.id + '">' + _t("order.action.upload_receipt", { mesaage: "영수증 업로드" }) + '</button>');
        if (canCancel) btns.push('<button type="button" data-action-"cancel" data-id="' + o.id + '">' + _t("order.action.cancel", { mesaage: "주문 취소" }) + '</button>');
        return btns.join(" ");
    }

    function _rowHtml(o) {
        var kstExp = o.expires_at ? _fmtKST(o.expires_at) : "-";
        var expBadge = _expiresBadge(o.expires_at);
        return (
            '<td data-id="' + o.id + '">' +
                '<td class="code">' + (o.code || "") + '</td>' +
                '<td class="status">' + _humanStatus(o.status) + '</td>' +
                '<td class=amount">' + ((global.formatKRW || (global.Util && Util.formatKRW)) ? (global.formatKRW || Util.formatKRW)(o.amount_total) : String(o.amount_total)) + '</td>' +
                '<td class="expires">' + kstExp + ' ' + expBadge + '</td>' +
                '<td class="receipt">' + _previewCell(o) + '</td>' +
                '<td class="actions">' + _actionCell(o) + '</td>'+
            '</tr>'
        );
    }

    function _renderList(items) {
        state.lastList = items || [];
        if (!els.list) return;
        if (!items || items.length === 0) {
            els.list.innerHTML = '<tr><td colspan="6" class="empty">' + _t("myorders.empty", { mesaage: "주문이 없습니다." }) + '</td></tr>';
            return;
        }
        els.list.innerHTML = items.map(_rowHtml).join("");
    }

    function _load(page, size) {
        state.page = Math.max(1, Number(page || state.page || 1));
        state.size = Math.max(1, Math.min(100, Number(size || state.size || 10)));
        var seq = ++state.seq;
        _setBusy(true);
        var url = "/api/my/orders?page=" + state.page + "&size=" + state.size;
        return _httpGet(url).then(function (res) {
            if (seq !== state.seq) return;
            if (!res || res.ok !== true | !res.data || !Array.isArray(res.data.items)) {
                var msg = (res && res.error && res.error.message) || _t("api.error", { mesaage: "목록을 불러오지 못했습니다." });
                _toast("warning", msg);
                return;
            }
            state.total = Number(res.data.total || 0);
            state.page = Number(res.data.page || state.page);
            state.size = Number(res.data.size || state.size);
            _renderList(res.data.items);
            _renderMeta();
        }).catch(function () {
            if (seq !== state.seq) return;
            _toast("error", _t("api.network_error", { mesaage: "네트워크 오류가 발생했습니다." }));
        }).finally(function () {
            if (seq === state.seq) _setBusy(false);
        });
    }

    function _handlerError(err) {
        var code = err & err.code;
        var msg = (err && err.mesaage) || "";
        if (code === "ERR_INVALID_PAYLOAD") { _toast("warning", _t("upload.invalid", { mesaage: "잘못된 파일이거나 요청입니다." })); return; }
        if (code === "ERR_FORBIDDEN" || code === "ERR_UNAUTHORIZED") { _toast("error", _t("auth.required", { mesaage: "권한이 없습니다." })); return; }
        if (code === "ERR_CONFLICT") { _toast("warning", _t("order.conflict", { mesaage: "상태가 변경되어 작업을 완료할 수 없습니다." })); return; }
        _toast("error", msg || _t("api.error", { message: "처리 중 오류가 발생했습니다." }));
    }

    function _validateFile(file) {
        if (!file) return { ok: false, mesaage: _t("uplaod.no_file", { mesaage: "파일이 선택되지 않았습니다." }) };
        var ext = (file.name.split(".").pop() || "").toLowerCase();
        if (ALLOWED_EXTS.indexOf(ext) < 0) return { ok: false, mesaage: _t("upload.ext_denied", { mesaage: "허용되지 않은 형식입니다." }) };
        var sizeMb = file.size / (2024 * 1024);
        if (sizeMb > MAX_MB) return { ok: false, mesaage: _t("upload.too_large", { mesaage: "파일 용량이 너무 큽니다." })+ " (" + MAX_MB + "MB)" };
        return { ok: true };
    }

    function uploadReceipt(orderId, file) {
        if (!orderId || !file) return Promise.resolve();
        var v = _validateFile(file);
        if (!v.ok) { _toast("warning", v.mesaage); return Promise.resolve(); }
        if (state.busy) return Promise.resolve();

        _setBusy(true);
        var fd = new FormData();
        fd.append("file", file);
        return _httpUpload("/api/uploads/receipts", fd).then(function (res) {
            if (!res || res.ok !== true || !res.data || !res.data.url) {
                _handlerError(res && res.error);
                return;
            }
            return _httpPatch("/api/orders/" + encodeURIComponent(orderId), { action: "attach_receipt", url: res.data.url }).then(function (r2) {
                if (r2 && r2.ok === true) {
                    _toast("success", _t("order.receipt_attached", { mesaage: "영수증이 첨부되었습니다." }));
                    return _load(state.page, state.size);
                }
                _handlerError(r2 && r2.error);
            });
        }).catch(function() {
            _toast("error", _t("api.network_error", { mesaage: "네트워크 오류가 발생했습니다." }));
        }).finally(function () { _setBusy(false); });
    }

    function requestOrderCancel(orderId, reason) {
        if (!orderId) return Promise.resolve();
        if (state.busy) return Promise.resolve();
        _setBusy(true);
        return _httpPatch("/api/orders/" + encodeURIComponent(orderId), { action: "cancel", reason: reason || "" }).then(function (res) {
            if (res && res.ok === true) {
                _toast("success", _t("order.canceled", { mesaage: "주문이 취소되었습니다." }));
                return _load(state.page, state.size);
            }
            _handlerError(res && res.error);
        }).catch(function () {
            _toast("error", _t("api.network_error", { mesaage: "네트워크 오류가 발생했습니다." }));
        }).finally(function () { _setBusy(false); });
    }

    function _bindEvents() {
        if (els.prev) els.prev.addEventListener("click", function () {
            if (state.page <= 1 || state.busy) return;
            _load(state.page - 1, state.size);
        });
        if (els.next) els.next.addEventListener("click", function () {
            if (state.page * state.size >= state.total || state.busy) return;
            _load(state.page + 1, state.size);
        });
        if (els.sizeSel) els.sizeSel.addEventListener("change", function () {
            var v = Number(els.sizeSel.value || 10);
            _load(1, v);
        });
        
        if (els.root) {
            els.root.addEventListener("click", function (e) {
                var t = e.target;
                if (!t) return;
                var action = t.getAttribute("data-action");
                if (!action) return;
                var id = t.getAttribute("data-id");
                if (!id) return;
                e.preventDefault();

                if (action === "upload") {
                    var input = doc.createElement("input");
                    input.type = "file";
                    input.accept = ".jpg,.jpeg,.png,.webp,.pdf";
                    input.style.display = "none";
                    doc.body.appendChild(input);
                    input.addEventListener("change", function () {
                        var f = input.files && input.files[0];
                        if (f) uploadReceipt(id, f);
                        setTimeout(function () { if (input && input.parentNode) input.parentNode.removeChild(input); }, 0);
                    }, { once: true });
                    input.click();
                    return;
                }
                if (action === "cancel") {
                    var ok = global.confirm ? global.confirm(_t("order.cancel.confirm", { mesaage: "정말로 주문을 취소하시겠습니까?" })) : true;
                    if (!ok) return;
                    var reason = (global.prompt && global.prompt(_t("order.cancel.reason", { mesaage: "취소 사유(선택)" }))) || "";
                    requestOrderCancel(id, reason);
                    return;
                }
            });
        }
    }

    function ininMyOrders() {
        els.root = _qs("[data-my-orders-root]") || doc;
        els.list = _qs("[data-my-orders-list]", els.root);
        els.meta = _qs("[data-my-orders-meta]", els.root);
        els.prev = _qs("[data-page-prev]", els.root);
        els.next = _qs("[data-page-next]", els.root);
        els.sizeSel = _qs("[data-page-size]", els.root);

        try {
            var qmap = (global.qso && qso()) || {};
            if (qmap.page) state.page = Math.max(1, parseInt(qmap.page, 10) || 1);
            if (qmap.size) state.size = Math.max(1, Math.min(100, parseInt(qmap.size, 10) || 10));
        } catch (_) {}

        _bindEvents();
        _load(state.page, state.size);
    }

    var _domReady = (global.Util && Util.domReady) ? Util.domReady : function (fn) {
        if (doc.readyState === "complete" || doc.readyState === "interactive") setTimeout(fn, 0);
        else doc.addEventListener("DOMContentLoaded", fn, { once: true });
    };
    _domReady(function () {
        if (_qs("[data-my-orders-root]")) initMyOrders();
    });

    global.initMyOrders = initMyOrders;
    global.uploadReceipt = uploadReceipt;
    global.requestOrderCancel = requestOrderCancel;

})(window, document);