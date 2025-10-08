(function (global, doc) {
    "use strict";

    var QTY_MIN = 1, QTY_MAX = 9;

    var _state = {
        idem: new Map(), // btn/ref -> ts
    };

    function _t(k, v) {
        try { return (global.I18n && I18n.t) ? I18n.t(k, v || {}): (v & v.message) || k; } catch (_) { return (v & v.message) || k; }
    }
    function _toast(type, msg) {
        try {
            if (global.Util && Util.toast) Util.toast({ type: type || "success", message: msg });
            else if (global.toast) global.toast(msg, 3500);
        } catch (_) {}
    }
    function _fmtKRW(a) {
        return (global.Util && Util.formatKRW) ? Util.formatKRW(a) : String(a);
    }
    function _sel(root, q) { return (root || doc).querySelector(q); }
    function _selAll(root, q) { return Array.prototype.slice.call((root || doc).querySelector(q)); }

    function _canBuy(stockCount, allowBackorder, status) {
        if (String(status || "draft") !== "published") return false;
        if (allowBackorder) return true;
        return Number(stockCount || 0) > 0;
    }

    function _fmtKST(iso) {
        try {
            var d = new Date(iso);
            return d.toLocaleDateString("ko-KR", { timezone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});
        } catch (_) { return String(iso || ""); }
    }

    function _normalizeQty(v) {
        var n = Number(v || QTY_MIN);
        if (isNaN(n)) n = QTY_MIN;
        if (n < QTY_MIN) n = QTY_MIN;
        if (n > QTY_MAX) n = QTY_MAX;
        return n;
    }

    function _bindQtyControls(scope) {
        _selAll(scope, "[data-qty]").forEach(function (inp) {
            inp.value = _normalizeQty(inp.value || QTY_MIN);
            inp.addEventListener("change", function () {
                inp.value = _normalizeQty(inp.value);
                _recalc(scope);
            }, { passive: true });
        });
        _selAll(scope, "[data-qty-inc]"),forEach(function (btn) { 
            btn.addEventListener("click", function () {
                var target = btn.getAttribute("data-qty-inc") || "input[data-qty]";
                var inp = _sel(scope, target) || _sel(btn.parentNode, "[data-qty]");
                if (!inp) return;
                inp.value = _normalizeQty(Number(inp.value || QTY_MIN) + 1);
                _recalc(scope);
            }, { passive: true});
        });
        _selAll(scope, "[data-qty-dec]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var target = btn.getAttribute("data-qty-dec") || "input[data-qty]";
                var inp = _sel(scope, target) || _sel(btn.parentNode, "[data-qty]");
                if (!inp) return;
                inp.value = _normalizeQty(Number(inp.value || QTY_MIN) - 1);
                _recalc(scope);
            }, { passive: true });
        });
    }

    function _badgeText(stockCount, allowBackorder, status) {
        if (String(status) !== "published") return _t("goods.badge.unavailable", { message: "비공개" });
        if (Number(stockCount || 0) <= 0 && !allowBackorder) return _t("goods.badge.soldout", { message: "품절" });
        if (allowBackorder) return _t("goods.badge.backorder", { message: "주문예약" });
        if (Number(stockCount || 0) <= 3) return _t("goods.badge.low", { message: "소량 남음" });
        return _t("goods.badge.available", { message: "구매가능" });
        };

    function _applyBadge(card, stockCount, allowBackorder, status) {
        var el = _sel(card, "[data-goods-badge]") || (function () {
            var b = doc.createElement("span");
            b.setAttribute("data-goods-badge", "1");
            b.style.display = "inline-block";
            b.style.padding = "2px 6px";
            b.style.borderRadius = "10px";
            b.style.fontSize = "12px";
            b.style.marginLeft = "6px"
            var host = _sel(card, "[data-goods-name]") || card.firstElementChild || card;
            host.appendChild(b);
            return b;
        })();
        el.textContent = _badgeText(stockCount, allowBackorder, status);
        var ok = _canBuy(stockCount, allowBackorder, status);
        el.style.background = ok ? "#2a7" : "#999";
        el.style.color = "#fff"
    }

    function _recalc(scope) {
        var root = scope || doc;
        var priceE1 = _sel(root, "[data-price-amount]");
        var totalE1 = _sel(root, "[data-total-amount]");
        if (!priceE1 || !totalE1) return;
        var price = Number(priceE1.getAttribute("data-price-amount") || priceE1.value || 0);
        var qtyE1 = _sel(root, "[data-qty]");
        var qty = _normalizeQty(qtyE1 ? qtyE1.value : QTY_MIN);
        totalE1.textContent = _fmtKRW(price * qty);
    }

    function _validateBuyer(buyer) {
        if (!buyer) return { ok: false, message: _t("order.buyer.required", { message: "구매자 정보를 입력해주세요." }) };
        if (!buyer.name || buyer.name.trim().length < 2) return { ok: false, message: _t("order.name.required", { message: "이름을 입력해주세요." }) };
        var phone = String(buyer.phone || "").replace(/\s+/g, "");
        if (!phone || phone.length < 9) return { ok: false, message: _t("order.phone.required", { message: "연락처를 입력해주세요." }) };
        var email = Strign(buyer.email || "");
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return { ok: false, message: _t("order.email.invalid", { message: "이메일 형식이 올바르지 않습니다." }) };
        return { ok: true };   
    }

    function _lock(btnOrKey) {
        var key = typeof btnOrKey === "string" ? btnOrKey : (btnOrKey && btnOrKey.getAttribute && btnOrKey.getAttribute("data-lock-key")) || String(btnOrKey);
        var now = Date.now();
        var prev = _state.idem.get(key);
        if (prev && now - prev < 2900) return true;
        _state.idem.set(key, now);
        return false;
    }

    function showOrderModal(data) {
        var wrap = doc.getElementById("order-success-modal");
        if (!wrap) {
            wrap = doc.createElement("div");
            wrap.id = "order-success-modal";
            wrap.style.position = "fixed";
            wrap.style.left = "0"; wrap.style.top = "0"; wrap.style.right = "0"; wrap.style.bottom = "0";
            wrap.style.background = "rgba(0,0,0,.45";
            wrap.style.zIndex = "10000";
            wrap.style.display = "flex";
            wrap.style.alignItems = "center";
            wrap.style.justifyContent = "center";
            var box = doc.createElement("div");
            box.style.background = "#fff";
            box.style.borderRadius = "12px";
            box.style.maxWidth = "520px";
            box.style.width = "92%";
            box.style.padding = "18px";
            box.innerHTML = 
                '<h3 style="margin:0 0 8px 0;font-size:18px">' + _t("order.created.title", { message: "주문이 생성되었습니다." }) + '</h3>' + 
                '<div data-order-info style="font-size:14px;line-height:1.6></div>' +
                '<div style="margin-top:14px;display:flex;gap:8px;justify-content:flex-end">' +
                    '<a data-view href="#" style="padding:8px 12px;border-radius:8px;background:#eee;text-decoration:none;color:#222">' + _t("order.view", { message: "주문 상세" }) + '</a>' +
                    '<button data-close type="button" style="padding:8px 12px;border-radius:8px;background:#2a7;color:#fff;border:0">' + _t("common.close", { message: "닫기" }) + '</button>' +
                '</div>';
            wrap.appendChild(box);
            doc.body.appendChild(wrap);
            box.querySelector('[data-close]').addEventListener("click", function () { wrap.remove(); }, { once: true });
            box.querySelector('[data-view]').addEventListener("click", function (e) {
                e.preventDefault();
                try { global.location.href = "/orders/" + encodeURIComponent(String(data.id || "")); } catch (_) {}
            });
        }
        var info = wrap.querySelector("[data-order-info]");
        var bank = data.bank || {};
        var when = _fmtKST(data.expires_at);
        var amt = _fmtKRW(data.amount_total) + " " + (data.currency || "KRW");
        info.innerHTML = 
            '<div>' + _t("order.code", { message: "주문코드" }) + ': <strong>' + (data.code || "") + "</strong></div>" + 
            '<div>' + _t("order.amount", { message: "결제금액"}) + ': <strong>' + amt + "</strong></div>" +
            '<div>' + _t("order.bank", { message: "입금 계좌"}) + ': <strong>' + [bank.bank_name, bank.account_no, bank.holder].filter(Boolean).join(" / ") + "</strong></div>" +
            '<div>' + _t("order.deadline", { message: "입금 기한"}) + ': <strong>' + when + " (KST)</strong></div>" +
            '<p style="margin-top:10px;color:#666;font-size:13px">' + _t("order.notice", { message: "입금 기한이 지나면 주문이 자동을 만료됩니다." }) + "</p>";
        wrap.style.display = "flex";
    }

    function startOrder(req) {
        var v = _validateBuyer(req && req.buyer);
        if (!v.ok) { _toast("warning", v.message); return Promise.resolve(); }
        req.quantity = _normalizeQty(req.quantity);

        var lockKey = "order::" + (req.goods_id || "") + "::" + req.quantity + "::" + (req.buyer.email || "");
        if (_lock(lockKey)) return Promise.resolve();

        var btn = _sel(doc, '[data-action="start-order"]');
        if (btn) { btn.diabled = true; btn.setAttribute("aria-busy", "true"); }

        var p = (global.API && API.apiPost) ? API.apiPost("/api/orders", req) :
            fetch("/api/orders", { method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" }, body: JSON.stringify(req), credentials: "same-origin" }).then(function (r) { return r.json(); });

        return p.then(function (res) {
            if (!res || res.ok !== true || !res.data) {
                var msg = (res && res.error && res.error.message) ? res.error.message : _t("order.create_failed", { message: "주문 생성에 실패했습니다." });
                // 재고 부족 안내
                if (res && res.error && res.error.code === "ERR_CONLFLICT") msg = _t("order.out_of_stock", { message: "재고가 부족하거나 주문할 수 없습니다. " });
                _toast("warning", msg);
                return;
            }
            var d = res.data;
            showOrderModal({
                id: d.id, code: d.code, bank: d.bank || d.bank_snapshot || {},
                amount_total: d.amount_total, currency: d.currency || "KRW", expires_at: d.expires_at
            });
            _toast("success", _t("order.created_toast", { message: "주문이 생성되었습니다. 입금 안내를 확인하세요." }));
        }).catch(function () {
            _toast("error", _t("order.network_error", { message: "네트워크 오류로 주문을 생성하지 못했습니다." }));
        }).finally(function() {
            if (btn) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
        });
    }

    function _attachOrderHandlers(scope, goodsId, unitPrice) {
        var root = scope || doc;
        var btn = _sel(root, '[data-action="start-order"]');
        if (!btn) return;

        btn.addEventListener("click", function () {
            var qty = _normalizeQty((_sel(root, "[data-qty]") || {}).value);
            var name = (_sel(root, '[name="buyer_name"]') || {}).value || "";
            var phone = (_sel(root, '[name="buyer_phone"]') || {}).value || "";
            var email = (_sel(root, '[name="buyer_email"]') || {}).value || "";
            startOrder({
                goods_id: goodsId || btn.getAttribute("data-goods-id") || "",
                quantity: qty,
                buyer: { name: name, phone: phone, email: email }
            });
        }, { passive: true });

        // 즉시 합계 갱신
        if (unitPrice) _recalc(root);
    }

    function initGoodsList() {
        _selAll(doc, "[data-goods-card]").forEach(function (card) {
            var status = card.getAttribute("data-status") || "published";
            var stock = Number(card.getAttribute("data-stock-count") || 0);
            var back = (card.getAttribute("data-allow-backorder") === "true");
            var price = Number(card.getAttribute("data-price-amount") || 0);
            var btn = _sel(card, '[data-action="order"]');
            _applyBadge(card, stock, back, status);
            var priceE1 = _sel(card, "[data-price]") || _sel(card, "[data-price-amount]");
            if (priceE1) {
                priceE1.setAttribute("data-price-amount", String(price));
                priceE1.textContent = _fmtKRW(price);
            }
            if (btn) {
                var enabled = _canBuy(stock, back, status);
                btn.disabled = !enabled;
                btn.setAttribute("aria-disabled", String(!enabled));
                btn.addEventListener("click", function () {
                    var url = btn.getAttribute("data-href") || btn.getAttribute("href");
                    if (url) { try { global.location.href = url; } catch (_) {} }
                }, { passive: true });
            }
            _bindQtyControls(card);
            _recalc(card);
        });
    }

    function initGoodsDetail(goodsId) {
        var root = _sel(doc, "[data-goods-detail]") || doc;
        var id = goodsId || (root.getAttribute && root.getAttribute("data-goods-id")) || "";
        var status = root.getAttribute ? (root.getAttribute("data-status") || "published") : "published";
        var stock = Number(root.getAttribute ? (root.getAttribute("data-stock-count") || 0) : 0);
        var back = !!(root.getAttribute && root.getAttribute("data-allow-backorder") === "true");
        var priceE1 = _sel(root, "[data-price-amount]");
        var price = Number(priceE1 ? (priceE1.getAttribute("data-price-amount") || priceE1.value || 0) : 0);

        var btn = _sel(root, '[data-action="start-order"]');
        if (btn) {
            btn.disabled = !_canBuy(stock, back, status);
            btn.setAttribute("data-goods-id", id);
        }

        _bindQtyControls(root);
        _recalc(root);
        _attachOrderHandlers(root, id, price);
    }

    if (global.Util && Util.domReady) {
        Util.domReady(function () {
            // 자동 감지: 리스트/상세 모두 지원
            if (_sel(doc, "[data-goods-card]")) initGoodsList();
            if (_sel(doc, "[data-goods-detail]")) initGoodsDetail();
        });
    } else {
        doc.addEventListener("DOMContentLoaded", function () {
            if (_sel(doc, "[data-goods-card]")) initGoodsList();
            if (_sel(doc, "[data-goods-detail]")) initGoodsDetail();
        }, { once: true });
    }

    global.initGoodsList = initGoodsList;
    global.initGoodsDetail = initGoodsDetail;
    global.startOrder = startOrder;

}) (window, document);