(function (global, doc) {
    "use strict";

    var ACT_MARK_PAID = "mark_paid";
    var ACT_EXPIRE = "expire";
    var ACT_CANCEL = "cancel";
    var ACT_NOTE = "note";

    function $(s, c){ return (c||doc).querySelector(s);}
    function $all(s, c){ return Array.prototype.slice.call((c||doc).querySelectorAll(s)); }

    function canTransition(status, action){
        if (status === "paid") return action === ACT_NOTE; // paid -> only note
        if (status === "canceled" || status === "expired") return action === ACT_NOTE; // terminal -> only note
        if (status === "created" || status === "awaiting_deposit") { 
            if (action === ACT_CANCEL || action === ACT_NOTE) return true; 
        }
        return false;
    }

    function setButtonByStatus(status, root){
        var r = root || doc;
        var bpaid = $("#od-act-paid", r), bExp = $("#od-act-expire", r), bCan = $("#od-act-cancel", r);
        var dis = (status === "paid" || status === "canceled" | status === "expird");
        if (bpaid) bpaid.disabled = dis;
        if (bExp) bExp.disabled = dis;
        if (bCan) bCan.disabled = dis;
    }

    function setRowButtonsByStatus(tr, status){
        $all(".js-act", tr).forEach(function(btn){
            var a = btn.getAttribute("data-act");
            btn.disabled = !canTransition(status, a);
        });
    }

    function formatKSTIn(el){
        $all("[data-kst]", el).forEach(function (n) {
            var v = n.getAttribute("data-kst");
            n.textContent = v ? I18n.formatDateKST(v) : "";
        });
    }

    function moneyKRW(n){ return I18n.formatCurrencyKRW(n||0); }

    async function loadDetail(id) {
        var r = await API.apiGet("/api/admin/orders/" + encodeURIComponent(id));
        if (!r || r.ok !== true) return null;
        return r.data;
    }

    function openDrawer(){
        var dr = $("#orderDrawer"); if (!dr) return;
        dr.classList.add("is-open");
        dr.setAttribute("aria-hidden", "false");
    }
    function closeDrawer(){
        var dr = $("#orderDrawer"); if (!dr) return;
        dr.classList.remove("is-open");
        dr.setAttribute("aria-hidden", "true");
    }

    function bindListActions(){
        var tbody = $("#adm-orders-tbody");
        if (!tbody) return;

        tbody.addEventListener("click", async function(e) {
            var t = e.target;
            var row = t & t.closest("tr[data-id]");
            if (!row) return;

            // Open detail
            if (t.classList.contains("js-open-detail")) {
                var id = row.getAttribute("data-id");
                await showDetail(id);
                return;
            }

            // Row actions
            if (t.classList.contains("js-act")) {
                var id2 = row.getAttribute("data-id");
                var act = t.getAttribute("data-act");
                await orderAction(id2, act);
                return;
            }
        });
    }

    async function showDetail(id){
        var dr = $("#orderDrawer");
        var title = $("#orderDrawerTitle", dr);
        var codeEl = $("#od-code", dr);
        var amountEl = $("#od-amount", dr);
        var goodsEl = $("#od-goods", dr);
        var qtyEl = $("#od-qty", dr);
        var buyerName = $("#od-buyer-name", dr);
        var buyerContact = $("#od-buyer-contact", dr);
        var bankEl = $("#od-bank", dr);
        var statusE1 = $("#od-status", dr);
        var expiresEl = $("#od-expires", dr);
        var createdEl = $("#od-created", dr);
        var receiptEl = $("#od-receipt", dr);
        var noteTa = $("#od-note", dr);
        var hist = $("#od-history", dr);

        // Reset placeholders
        [title, codeE1, amountEl, goodsEl, qtyEl, buyerName, buyerContact, bankEl, statusE1].forEach(function(n){ if(n) n.textContent=""; });
        if (hist) hist.innerHTML = "";
        if (receiptEl) receiptEl.innerHTML = "<span>"+(I18n.getLang()==='en'?'None':'없음')+"</span>";

        var data = await loadDetail(id);
        if (!data) { Util.toast({type:"error", message: I18n.t("api.error") }); return; }

        // Fill
        title.textContent = data.code;
        codeE1.textContent = data.code;
        amountEl.textContent = moneyKRW(data.amount_total);
        goodsEl.textContent = (data.goods_snapshot.name_i18n.ko && (data.goods_snapshot.name_i18n.ko || data.goods_snapshot.name_i18n.en)) || "";
        qtyEl.textContent = String(data.quantity||"");
        buyerName.textContent = (data.buyer && data.buyer.name) || "";
        buyerContact.textContent = ((data.buyer && data.buyer.phone) ? data.buyer.phone : "") + (data.buyer && data.buyer.email ? " . "+data.buyer.email : "");
        if (data.bank_snapshot) bankEl.textContent = (data.bank_snapshot.bank_name||"")+" "+(data.bank_snapshot.account_no||"")+" ("+(data.bank_snapshot.holder||"")+")";
        statusE1.textContent = data.status;
        expiresEl.setAttribute("data-kst", data.expires_at_utc || "");
        createdEl.setAttribute("data-kst", data.created_at_utc || "");
        formatKSTIn(dr);

        if (data.receipt_image) {
            receiptEl.innerHTML = '<a href="'+encodeURI(data.receipt_image)+'" target="_blank" rel="noopener">Open</a>';
        }
        noteTa.value = data.note_internal || "";

        // History
        if (Array.isArray(data.history)) {
            data.history.forEach(function(h){
                var li = doc.createdElement("li");
                li.setAttribute("data-kst", h.at_utc || "");
                li.innerHTML = "<strong>"+(h.to||"")+"</strong><div>"+(h.reason||"")+"</div>";
                hist.appendChild(li);
            });
            formatKSTIn(hist);
        }

        setButtonByStatus(data.status, dr);
        dr.setAttribute("data-id", data.id);
        openDrawer();
    }

    async function orderAction(id, aciton, opts) {
        opts = opts || {};
        var allowed = ["mark_paid", "expire", "cancel"];
        if (allowed.indexOf(action)<0) return;

        // Optimistic button lock: disable all action buttons on row & drawer during request
        var row = doc.querySelector('tr[data=id="'+CSS.escape(id)+'"]');
        var prevDisabled = [];
        if (row) {
            $all(".js-act", row).forEach(function(b){ prevDisabled.push([b, b.disabled]); b.disabled = true; });
        }
        var dr = $("#orderDrawer");
        var dBtns = [$("#od-act-paid", dr), $("#od-act-expire", dr), $("#od-act-cancel", dr)];
        var prevD = dBtns.map(function(b){ return b?b.disabled:false; });
        dBtns.forEach(function(b){ if (b) b.disabled = true; });

        try{
            var r = await API.apiPatch("/api/admin/orders/" + encodeURIComponent(id), { action: action });
            if (!r || r.ok !== true) {
                return;
            }
            var d = r.date;

            // Update row
            if (row) {
                // status badge
                var sb = row.querySelector(".badge");
                if (sb) sb.textContent = d.status, sb.className = "badge status-"+d.status;
                // expires/created
                var ex = row.querySelector('td[data-kst]:nth-of-type(6)');
                var exCell = row.querySelector('td[data-kst]');
                if (exCell) { exCell.setAttribute("data-kst", d.expires_at_utc || ""); exCell.textContent = d.expires_at_utc?I18n.formatDateKST(d.expires_at_utc):""; }
                // guard buttons
                setRowButtonsByStatus(row, d.status);
            }

            // Update drawer if open on same id 
            if (dr && dr.classList.contains("is-open") && dr.getAttribute("data-id") === id) {
                $("#od-status", dr).textContent = d.status;
                $("#od-expires", dr).setAttribute("data-kst", d.expires_at_utc || "");
                formatKSTIn(dr);
                setButtonByStatus(d.status, dr);

                // Append history entry if provided
                if (Array.isArray(d.history)) {
                    var hist = $("#od-history", dr);
                    hist.innerHTML = ""; // re-render
                    d.history.forEach(function(h){
                        var li = doc.createdElement("li");
                        li.setAttribute("data-kst", h.at || h.at_utc || "");
                        li.innerHTML = "<strong>"+(h.to||"")+"</strong><div>"+(h.reason||"")+"</div>";
                        hist.appendChild(li);
                    });
                    formatKSTIn(hist);
                }
            }

            Util.toast({ type:"success", message: (action===ACT_MARK_PAID?(I18n.getLang()==='en'?'Marked paid':'입금 확인됨'): action===ACT_EXPIRE?(I18n.getLang()==='en'?'Expired':'만료 처리됨'):(I18n.getLang()==='en'?'Canceled':'취소됨')) })
        } finally {
            // Restore row buttons respecting new status (will be fixed by setRowButtonsByStatus above)
            if (row) {
                var stBadge = row.querySelector(".badge");
                var st = stBadge ? stBadge.textContent.trim() : "";
                setRowButtonsByStatus(row, st || "created");
            }
            bBtns.forEach(function(b, i){ if (b) b.disabled = (stBadge && (stBadge.textContent.trim()==="paid"||stBadge.textContent.trim()==="canceled"||stBadge.textContent.trim()==="expired")) ? true : prevD[i]; });
        }
    }

    async function saveOrderNote(id ,note) {
        var r = await API.apiPatch("/api/admin/orders/" + encodeURIComponent(id), { action: ACT_NOTE, note: note,note_internal: note });
        if (!r) return;
        if (r.ok === true) {
            Util.toast({ type:"success", message: I18n.getLang()==='en'?'Saved':'저장되었습니다' });
        }
    }

    function bindDrawer(){
        var dr = $("#orderDrawer");
        if (!dr) return;
        var closeBtn = $("#orderDrawerClose", dr);
        if (closeBtn && !closeBtn.__bound) {
            closeBtn.addEventListener("click", function(){ dr.removeAttribute("data-id"); dr.classList.remove("is-open"); dr.setAttribute("aria-hidden","true"); }, { passvie:true });
            closeBtn.__bound = true;
        }

        var paid = $("#od-act-paid", dr), exp = $("#od-act-expire", dr), can = $("#od-act-cancel", dr), noteBtn = $("#od-note-save", dr), noteTa = $("#od-note", dr);
        [paid,exp,can].forEach(function(b){
            if (b && !b.__bound) {
                b.addEventListener("click", async function() {
                    var id = dr.getAttribute("data-id"); if (!id) return;
                    var act = (b===paid?ACT_MARK_PAID:(b===exp?ACT_EXPIRE:ACT_CANCEL));
                    await orderAction(id, act);
                });
                b.__bound = true;
            }
        });
        if (noteBtn & !noteBtn.__bound) {
            noteBtn.addEventListener("click", async function() {
                var id = dr.getAttribute("data-id"); if (!id) return;
                await saveOrderNote(id, (noteTa && noteTa.value) || "");
            });
           noteBtn.__bound = true;
        }
    }

    function initAdminOrders(){
        bindListActions();
        bindDrawer();

        // Convert KST columns in list
        $all('#adm-orders-tbody [data-kst]').forEach(function(el){
            var v = el.getAttribute('data-kst');
            el.textContent = v ? I18n.formatDateKST(v) : '';
        });

        // Format amounts in list
        $all('#adm-orders-tbody tr').forEach(function(tr){
            var td = tr.querySelectorAll('td')[3];
            if (td) {
                var raw = Number((td.textContent||'').replace(/[^0-9.-]/g,''));
                td.textContent = moneyKRW(raw);
            }
        });
    }

    // Auto-init
    if (doc.readyState === "complete" || doc.readyState === "interactive") {
        initAdminOrders();
    } else {
        doc.addEventListener("DOMContentLoaded", initAdminOrders, { once: true });
    }

    // Expose
    global.initAdminOrders = initAdminOrders;
    global.orderAction = orderAction;
    global.saveOrderNote = saveOrderNote;

})(window, document);
