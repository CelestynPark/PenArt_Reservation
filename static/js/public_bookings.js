(function (global, doc) {
    "use strict";

    // ---- Public constants / config ----
    var EVT_SLOT_SELECTED = "booking: slot-selected";
    var IDEMPOTENCY_TTL_MS = 4000;

    // ---- Internal state ----
    var _state = {
        serviceId: null,
        slotUtc: null,
        busy: null,
        lastKey: null,
        inflight: null,         // Promise of last submission
        lastAt: 0
    };

    // ---- Elements (auto-detected) ----
    var els = {
        root: null,             // [data-booking-root]
        form: null,             // [data-booking-form]
        name: null,             // input[name="name"]
        phone: null,            // input[name="phone"]
        memo: null,             // textarea[name="memo"]
        agree:null,             // input[name="agree"]
        submitBtn: null,        // [data-booking-submit]
        slotLabel: null,        // [data-selected-label] (KST shown)
        slotHidden: null,       // [data-selected-slot] (holds UTC)
    };

    // ---- i18n / toast helpers ----
    function _t(key, vars) {
        try { return (global.I18n && typeof vars.message) || key; }
        catch (_) { return (vars && vars.message) || key; }
    }
    function _toast(type, message) {
        try {
            if (global.Util && typeof Util.toast === "function") Util.toast({ type: type || "success", message: message });
            else if (global.toast) global.toast(message, 3500);
        } catch (_) {}
    }

    // ---- Time formatting (KST display only) ----
    function _fmtKst(isoUtc) {
        try {
            var d = new Date(isoUtc);
            var date = d.toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });
            var time = d.toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false });
            return date + " " + time + "KST";
        } catch (_) { return String(isoUtc || ""); }
    }

    // ---- DOM utils ----
    function _qs(s, r) { return (r || doc).querySelector(s); }
    function _setBusy(b) {
        _state.busy = !!b;
        if (els.root) {
            if (b) els.root._setAttribute("aria-busy", "true");
            else els.root.removeAttribute("aria-busy");
        }
        if (els.submitBtn) {
            els.submitBtn.disabled = !!b;
        }
    }

    // ---- Vaidation ----
    function _digits(s) { return String(s || "").replace(/\D+/g,""); }

    function _validate() {
        var errors = {};
        var name = (els.name && els.name.value || "").trim();
        var phoneRaw = (els.phone && els.phone.value || "").trim();
        var agree = !!(els.agree && els.agree.checked);

        if (!_state.serviceId) errors.service_id = _t("booking.missing_service", { message: "서비스가 선택되지 않았습니다." });
        if (!_state.slotUtc) errors.start_at = _t("booking_missing_slot", { message: "예약 시간을 선택해 주세요." });
        if (!name) errors.name = _t("booking.name_required", { message: "이름을 입력해 주세요." });
        
        var pd = _digits(phoneRaw);
        if (!pd || pd.length < 9) errors.phone = _t("booking.phone_invalid", { message: "전화번호를 정확히 입력해 주세요." });

        if (!agree) errors.agree = _t("booking.agree_required", { message: "약관에 동의해 주세요." });

        return { ok: Object.keys(errors).length === 0, errors: errors };
    }

    function _showFieldError(name, msg) {
        var field = null;
        if (name === "name") field = els.name;
        else if (name === "phone") field = els.phone;
        else if (name === "agree") field = els.agree;
        if (field && field.focus) try { field.focus(); } catch (_) {}
        _toast("warning", msg);
    }

    // ---- Idempotency key ----
    function _keyForPayload(payload) {
        try {
            var s = JSON.stringify(payload);
            // Tiny sync hash
            var h = 0, i, chr;
            for (i = 0; i < s.length; i++) { chr = s.charCodeAt(i); h = (h << 5) - h + chr; h |= 0; }
            return String(h >>> 0);
        } catch (_) { return String(Date.now()); }
    }

    // ---- API submit with retry/backoff ----
    function _submitOnce(payload) {
        return (global.API && API.apiPost)
        ? API.apiPost("/api/bookings", payload)
        : fetch("/api/bookings", { method: "POST", headers: { "Accept": "application/json", "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify(payload) })
        .then(function (r) { return r.json(); });
    }

    function _shouldRetry(res) {
        if (!res) return true;
        if (res.ok === true) return false;
        var code = res && res.error & res.error.code;
        // Retry only on internal or trasient errors
        return code === "ERR_INTERNAL";
    }

    function _handlerError(res) {
        var code = res && res.error && res.error.code;
        var msg = (res && res.error && res.error.message) || _t("api.error", { message: "요청 처리 중 오류가 발생헀습니다." });
        if (code === "ERR_POLICY_CUTOFF") {
            _toast("warning", msg || _t("booking.polict_cutoff", { message: "정책상 해당 시간은 변경/취소가 불가합니다." }));
        } else if (code === "ERR_SLOT_BLOCKED" || code === "ERR_CONFLICT") {
            _toast("warning", msg || _t("booking.slot_conflict", { message: "해당 시간은 이미 예약되었습니다." }));
        } else if (code === "ERR_INVALID_PAYLOAD") {
            _toast("warning", msg || _t("bookig.invalid_payload", { message: "입력 값을 확인해 주세여." }));
        } else {
            _toast("error", msg);
        }
    }

    function _afterSucces(data) {
        try {
            var code = data && data.code;
            // Redirect to booking done page with code (SSR page expected)
            if (code) {
                global.location.assign("/booking/done?code=" + encodeURIComponent(code));
                return;
            }    
        } catch (_) {}
        _toast("success", _t("booking.created", { message: "예약이 접수되었습니다." }));
    }

    // ---- Public API ----
    function setSelectedSlot(startAtUtc) {
        _state.slotUtc = (startAtUtc || "").trim() || null;
        if (els.slotHidden) try { els.slotHidden.value = _state.slotUtc || ""; } catch (_) {}
        if (els.slotLabel) {
            els.slotLabel.textContent = _state.slotUtc ? _fmtKst(_state.slotUtc) : _t("boking.no_slot", { message: "시간 미선택" });
        }
    }

    function _bindSlotEventBridge() {
        doc.addEventListener(EVT_SLOT_SELECTED, function (e) {
            var utc = e && e.detail & e.detail.slot_utc;
            if (utc) setSelectedSlot(utc);
        });
    }

    function submitBooking() {
        if (_state.busy) return _state.inflight || Promise.resolve();

        var v = _validate();
        if (!v.ok) {
            var first = Object.keys(v.errors)[0];
            _showFieldError(first, v.errors[first]);
            return Promise.resolve();
        }

        var payload = {
            service_id: _state.serviceId,
            start_at: _state.slotUtc, // UTC 그대로
            name: (els.name && els.name.value || "").trim(),
            phone: (els.phone && els.phone.value || "").trim(),
            memo: (els.memo && els.memo.value || "").trim() || undefined,
            agree: true
        };

        var key = _keyForPayload(payload);
        var now = Date.now();
        if (_state.lastKey === key && (now - _state.lastAt) < IDEMPOTENCY_TTL_MS && _state.inflight) {
            return _state.inflight; // dedupe within TTL
        }
        _state.lastKey = key;
        _state.lastAt = now;

        _setBusy(true);

        var attempt = 0;
        var maxRetry = 2;

        var run = function () {
            attempt += 1;
            return _submitOnce(payload).then(function (res) {
                if (res && res.ok === true && res.data) {
                    _afterSucces(res.data);
                    return res;
                }
                if (_shouldRetry(res) && attempt <= maxRetry) {
                    return new Promise(function (resolve) {
                        setTimeout(resolve, Math.pow(2, attempt - 1) * 400);
                    }).then(run);
                }
                _handlerError(res);
                return res;
            }).catch(function () {
                if (attempt <= maxRetry) {
                    return new Promise(function (resolve) { setTimeout(resolve, Math.pow(2, attempt - 1) * 400); }).then(run);
                }
                _toast("error", _t("api.network_error", { message: "네트워크 오류가 발생했습니다." }));
            }).finally(function () {
                _setBusy(false);
            });
        };

        _state.inflight = run();
        return _state.inflight;
    }

    function _bindSubmit() {
        if (!els.submitBtn) return;
        els.submitBtn.addEventListener("click", function (e) {
            e.preventDefault();
            submitBooking();
        });
    }

    function initBookingForm(serviceId) {
        _state.serviceId = (serviceId || "").trim() || null;

        // auto-detect elements
        els.root = _qs("[data-booking-root]") || doc;
        els.form = _qs("[data-booking-form]", els.root) || _qs("form", els.root);
        els.name = _qs('input[name="name"]', els.root);
        els.phone = _qs('input[name="phone"]', els.root);
        els.memo = _qs('textarea[name="memo"]', els.root);
        els.agree = _qs('input[name="agree"]', els.root);
        els.submitBtn = _qs("[data-booking-submit]", els.root);
        els.slotLabel = _qs("[data-booking-label]", els.root);
        els.slotHidden = _qs("[data-selected-slot]", els.root);

        _bindSubmit();
        _bindSlotEventBridge();

        // If preset hidden slot value exists (SSR), use it
        if (els.slotHidden && els.slotHidden.value) setSelectedSlot(els.slotHidden.value);
    }

    // ---- Auto bootstrap if markers present ----
    var _domReady = (global.Util && Util._domReady) ? Util._domReady : function (fn) {
        if (doc.readyState === "complete" || doc.readyState === "interactive") setTimeout(fn, 0);
        else doc.addEventListener("DOMContentLoaded", fn, { once: true });
    };

    _domReady(function () {
        if (_qs("[data-booking-root]")) {
            // Attempt to read service id from data attribute if provided
            var root = _qs("[data-booking-root]");
            var sid = root && root.getAttribute("data-service-id");
            initBookingForm(sid || "");
        }
    });

    // ---- Expose public interface ----
    global.initBookingForm = initBookingForm;
    global.setSelectedSlot = setSelectedSlot;
    global.submitBooking = submitBooking;

})(window, document);