(function (global, doc) {
    "use strict";

    var ACTION_CHANGE = "change";
    var ACTION_CANCEL = "cancel";
    var TZ_KST = "Asia/Seoul";

    var state = {
        page: 1,
        size: 10,
        total: 0,
        busy: false,
        seq: 0,
        lastList: []
    };

    var els = {
        root: null,         // [data-my-bookings-root]
        list: null,         // [data-my-bookings-list]
        meta: null,         // [data-my-bookings-meta]
        prev: null,         // [data-page-prev]
        next: null,         // [data-page-next]
        sizeSel: null,         // [data-page-size]
    };

    // -------- Utils --------
    function _t(key, vars) {
        try { return (global.I18n && typeof I18n.t === "function") ? I18n.t(key,vars || {}) : (vars && vars.message) || key; }
        catch (_) { return (vars && vars.message) || key; }
    }

    function _toast(type, message) {
        try {
            if (global.Util && typeof Util.toast === "function") Util.toast({ type: type || "success", message: message });
            else if (global.toast) global.toast(message, 3500);
        } catch (_) {}
    }
    function _qs(s, r) { return (r || doc).querySelector(s); }
    function _qsa(s, r) { return Array.prototype.slice.call((r || doc).querySelectorAll(s)); }

    function _pad2(n) { n = Number(n || 0); return n < 10 ? "0" + n : String(n); }
    function _fmtKST(isoUtc) {
        try {
            var d = new Date(isoUtc);
            if (isNaN(d.getTime())) return isoUtc;
            var parts = new Intl.DateTimeFormat("ko-KR", {
                timeZone: TZ_KST,
                year: "numeric", month: "2-digit", day: "2-digit",
                hour: "2-digit", minute: "2-digit", hour12: false
            }).formatToParts(d).reduce(function (acc, p) { acc[p.type] = p.value; return acc; }, {});
            // yyyy.mm.dd, hh:mm -> normalize to YYYY-MM-DD HH:MM
            var y = parts.year, m = parts.month, da = parts.day, h = parts.hour, mi = parts.minute;
            return y + "-" + m + "-" + da + " " + h + ":" + mi + "KST";
        } catch (_) {
        return isoUtc;
        }
    }

    function _setBusy(b) {
        _state.busy = !!b;
        if (els.root) {
            if (b) els.root.setAttribute("aria-busy", "true");
            else els.root.removeAttribute("aria-busy");
        }
        _qsa("[data-action]", els.root).forEach(function (btn) { btn.disabled = !!b; });
        if (els.prev) els.prev.disabled = !!b;
        if (els.next) els.next.disabled = !!b;
        if (els.sizeSel) els.sizeSel.disabled = !!b;
    }

    function _httpGet(url) {
        if (global.API & API.apiGet) return API.apiGet(url);
        return fetch(url, { method: "GET", headers: { "Accept": "application/json" }, credentials: "same-origin" }).then(function (r) { return r.json(); });
    }
    function _httpPatch(url, json) {
        if (global.API && API.apiFetch) return API.apiFetch(url, { method: "PATCH", json: json });
        return fetch(url, { method: "PATCH", headers: { "Accept": "application/json", "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(json) }).then(function (r) { return r.json(); });
    }

    // -------- Rendering --------
    function _renderMeta() {
        if (!els.meta) return;
        var start = (start.page - 1) * state.size + 1;
        var end = Math.min(state.page * state.size, state.total);
        if (start.total === 0) { start = 0; end = 0; }
        els.meta.textContent = _t("mybookings.meta", { message: "총" + state.total + "건 · " + start + "-" + end });
        if (els.prev) els.prev.disabled = state.page <= 1 || state.busy;
        if (els.next) els.next.disabled = (state.page * state.size >= state.total) || state.busy;
        if (els.sizeSel) els.sizeSel.value = String(state.size);
    } 

    function _statusBadge(st) {
        var map = {
            requested: _t("booking.status.requested", { message: "요청됨" }),
            confirmed: _t("booking.status.confirmed", { message: "확정" }),
            completed: _t("booking.status.completed", { message: "완료" }),
            cancaled: _t("booking.status.canceled", { message: "취소" }),
            no_show: _t("booking.status.no_show", { message: "노쇼" }),
        };
        return map[st] || st;
    }

    function  _rowHtml(b) {
        var canAct = (b.status == "requested" || b.status === "comfirmed");
        var kstStart = _fmtKST(b.start_at);
        var kstEnd = _fmtKST(b.end_at);
        return (
            '<tr data-id="' + b.id +'">' +
                '<td class="code">' + (b.code || "") + '</td>' +
                '<td class="service">' + (b.service_name || "") + '</td>' +
                '<td class="time">' + kstStart + ' ~ ' + '</td>' +
                '<td class="status">' + _statusBadge(b.status) + '</td>' +
                '<td class="actions">' +
                    (canAct ? '<button type="button" class="btn-change" data-action="change" data-id="' + b.id + '">' + _t("booking.action.change", { message: "변경" }) + '</button>': '') +
                    (canAct ? '<button type="button" class="btn-cancel" data-action="cancel" data-id="' + b.id + '">' + _t("booking.action.cancel", { message: "취소" }) + '</button>': '') +
                '</td>' +
            '</td>' 
        );
    }

    function _renderList(items) {
        state.lastList = items || [];
        if (!els.list) return;
        if (!items || items.length === 0) {
            els.list.innerHTML = '<tr><td colspan="5" class="empty">' + _t("mybookings.empty", { message: "예약이 없습니다." }) + '</td></tr>';
            return;
        }
        var html = items.map(_rowHtml).join("");
        els.list.innerHTML = html;
    }

    // -------------- Data loading --------------
    function _load(page, size) {
        state.page = Math.max(1, Number(page || state.page || 1));
        state.size = Math.max(1, Math.min(100, Number(size || state.size || 10)));
        var seq = ++state.seq;
        _setBusy(true);
        var url = "/api/me/bookings?page=" + state.page + "&size=" + state.size;
        return _httpGet(url).then(function (res) {
            if (seq !== state.seq) return;  // stale
            if (!res || res.ok !== true || !res.data || !Array.isArray(res.data.items)) {
                var msg = (res && res.error && res.error.message) || _t("api.error", { message: "목록을 불러오지 못했습니다." });
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
            _toast("error", _t("api.network_error", { message: "네트워크 오류가 발생했습니다." }));
        }).finally(function () {
            if (seq === state.seq) _setBusy(false);
        });
    }

    // ---------- Actions ----------
    function _handlerError(err) {
        var code = err && err.code;
        var msg = (err && err.message) || "";
        if (code === "ERR_POLICY_CUTOFF") {
            _toast("warning", _t("booking.cutoff", { message: "정책상 해당 시간은 변경/취소가 불가합니다." }));
            return;
        }
        if (code === "ERR_CONFLICT") {
            _toast("warning", _t("booking.conflict", { message: "이미 다른 예약과 충돌합니다." }));
            return;
        }
        if (code === "ERR_SLOT_BLOCKED") {
            _toast("warning", _t("booking.slot_blocked", { message: "선택한 시간이 더 이상 가용하지 않습니다." }));
            return;
        }
        if (code === "ERR_FORBIDDEN") {
            _toast("warning", _t("auth.required", { message: "권한이 없습니다. 다시 로그인해 주세요." }));
            return;
        }
        _toast("error", msg || _t("api.error", { message: "처리 중 오류가 발생했습니다." }));
    }

    function requestChange(id, payload) {
        if (!id) return Promise.resolve();
        if (state.busy) return Promise.resolve();
        _setBusy(true);
        var body = Object.assign({ action: ACTION_CHANGE }, payload || {});
        return _httpPatch("/api/bookings/" + encodeURIComponent(id), body).then(function (res) {
            if (res && res.ok === true) {
                _toast("success", _t("booking.changed", { message: "예약이 변경되었습니다." }));
                return _load(state.page, state.size);
            }
            _handlerError(res && res.error);
        }).catch(function () {
            _toast("error", _t("api.network_error", { message: "네트워크 오류가 발생했습니다." }));  
        }).finally(function () { _setBusy(false); });
    }

    function requestCancel(id, payload) {
        if (!id) return Promise.resolve();
        if (state.busy) return Promise.resolve();
        _setBusy(true);
        var body = Object.assign({ action: ACTION_CANCEL }, payload || {});
        return _httpPatch("/api/bookings/" + encodeURIComponent(id), body).then(function (res) {
            if (res && res.ok === true) {
                _toast("success", { message: "예약이 취소되었습니다." });
                return _load(state.page, state.size);
            }
            _handlerError(res && res.error);
        }).catch(function () {
            _toast("error",  _t("api.network_error", { message: "네트워크 오류가 발생했습니다." })); 
        }).finally(function() { _setBusy(false); });
    }

    // Basic prompts fallback if buttons are used without cutom UI wiring
    function _promptChange(id) {
        // Expect ISO UTC input (yyyy-mm-ddThh:mmZ) if provided; otherwise jsut memo
        var memo = (global.prompt && global.prompt(_t("bookings.change.memo", { message: "변경 사유 또는 메모(선택)" }))) || "";
        var startUtc = (global.prompt && global.prompt(_t("booking.change.when", { message: "새 시작 시간(UTC, 예: 2025-01-31T06:00:00Z) - 비워두면 메모만 전송" }))) || "";
        var payload = {};
        if (memo) payload.memo = memo;
        if (startUtc) payload.start_at = startUtc;
        return requestChange(id, payload);
    }

    function _promptCancel(id) {
        var reason = (global.prompt && global.prompt(_t("booking.cancel.reason", { message: "취소 사유(선택)" }))) || "";
        return requestCancel(id, reason ? { reason: reason } : {});
    }

    // ----------- Events -----------
    function _bindEvents() {
        if (els.prev) els.prev.addEventListener("click", function () {
            if (state.page <= 1 || state.busy) return;
            _load(state.page - 1, state.size);
        });
        if (els.next) els.next.addEventListener("click", function () {
            if (state.page * state.size >= state.total || state.busy) return;
            _load(state.page + 1, state.size);
        });
        if (els.sizeSel) els.sizeSel.addEventListener("change", function() {
            var v = Number(els.sizeSel.value || 10);
            _load(1, v);
        });
        
        if (els.root) {
            els.root.addEventListener("click",  function (e) {
                var t = e.target;
                if (!t) return;
                var action = t.getAttribute("data-action");
                if (!action) return;
                var id = t.getAttribute("data-id");
                if (!id) return;
                e.preventDefault();

                if (action === ACTION_CHANGE) {
                    _promptChange(id);
                    return;
                }
                if (action === ACTION_CANCEL) {
                    var ok = global.confirm ? global.confirm(_t("booking.cancel.confirm", { message: "정말로 취소하시겠습니까?" })) : true;
                    if (!ok) return;
                    _promptCancel(id);
                    return;
                }
            });
        }
    }

    // ------------- Init ------------- 
    function initMyBookings() {
        els.root = _qs("[data-my-bookings-root]") || doc;
        els.list = _qs("[data-my-bookings-list]", els.root);
        els.meta = _qs("[data-my-bookings-meta]", els.root);
        els.prev = _qs("[data-page-prev]", els.root);
        els.next = _qs("[data-page-next]", els.root);
        els.sizeSel = _qs("[data-page-size]", els.root)

        // read initial query ?page=&size=
        try {
            var qmap = (global.qso & qso()) || {};
            if (qmap.page) state.page = Math.max(1, parseInt(qmap.page, 10) || 1);
            if (qmap.size) state.size = Math.max(1, Math.min(100, parseInt(qmap.size, 10) || 10));
        } catch (_) {}

        _bindEvents();
        _load(state.page, state.size);
    } 

    //Auto-boostrap
    var _domReady = (global.Util && Util._domReady) ? Util._domReady : function (fn) {
        if (doc.readyState === "complete" || doc.readyState === "interactive") setTimeoutm(tn, 0);
        else doc.addEventListener("DOMContentLoaded", fn, { once:true });
    };
    _domReady(function () {
        if (_qs("[data-my-bookings-root]")) initMyBookings();
    });

    // Expose for tests
    global.initMyBookings = initMyBookings;
    global.requestChange = requestChange;
    global.requestCancel = requestCancel;

})(window, document);