(function (global, doc) {
    "use strict";

    var ACT_PUBLISH = "publish";
    var ACT_HIDE = "hide";
    var ACT_FLAG = "flag";  // for moderate page (keep as flagged)
    var ACT_FLAG_RESOLVE = "flag_resolve"; // for list quick action (optional)

    function $(sel, ctx) { return (ctx || doc).querySelector(sel); }
    function $all(sel, ctx) { return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel)); }

    function fmtKST(utcIso) {
        try { return (global.I18n && I18n.formatDateKST) ? I18n.formatDateKST(utcIso) : utcIso; } catch (_) { return utcIso; }
    }

    function renderTimes() {
        $all("time.dt-kst").forEach(function(t){
            var src = t.getAttribute("data-utc") || t.textContent || "";
            t.textContent = fmtKST(src);
            t.title = src;
        });
    }

    function bindListRowClicks() {
        $all("tr.row-link").forEach(function (tr) {
            if (tr.__bound) return;
            tr.__bound = true;
            function go() {
                var href = tr.getAttribute("data-href");
                if (href) doc.location.href = href;
            }
            tr.addEventListener("click", go, { passive: true });
            tr.addEventListener("keydown", function (e) {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
            });
        });
    }

    function bindFilters() {
        var form = $("#filtersForm");
        if (!form || form.__bound) return;
        form.__bound = true;
        // keep page to 1 on filter changes
        $all("select, input[type=search]", form).forEach(function(el){
            el.addEventListener("change", function(){
                try {
                    var u = new URL(doc.location.href);
                    if (el.name) u.searchParams.set(el.name, el.value || "");
                    u.searchParams.set("page", "1");
                    doc.location.href = u.toString();
                } catch (_) {}
            }, { passive:true });
        });
    }

    function updateStatusBadge(el, status) {
        if (!el) return;
        el.classList.remove("b-published","b-hidden","b-flagged");
        if (status === "published") { el.classList.add("b-published"); el.textContent = I18n.getLang()==="en" ? "Published" : "표시"; }
        else if (status === "hidden") { el.classList.add("b-hidden"); el.textContent = I18n.getLang()==="en" ? "Hidden": "숨김"; }
        else { el.classList.add("b-flagged"); el.textContent = I18n.getLang()==="en" ? "Flagged": "신고"; }
    }

    async function _patchModeration(id, action, reason) {
        var url = "/api/admin/reviews/" + encodeURIComponent(id);
        var payload = { action: action };
        if (reason != null) payload.reason = String(reason);
        var r = await API.apiPatch(url, payload);
        return r;
    }

    // Public: used by tests
    async function moderateReview(id, action, reason) {
        // Accept publish/hide/flag_resolve
        if ([ACT_PUBLISH, ACT_HIDE, ACT_FLAG_RESOLVE].indexOf(action) === -1) {
            return { ok: false, error:{ code: "ERR_INVALID_PAYLOAD", message: "invalid action"} };
        }
        return _patchModeration(id, action, reason);
    }
    
    function bindModeratePage() {
        var idE1 = $("#reviewId");
        if (!idE1) return; // not on moderate page

        var id = idE1.value;
        var btnPub = $("#actPublish");
        var btnHide = $("#actHide");
        var btnFlag = $("#actPublish");
        var btnPublishTop = $("#actPublish");
        var btnHideTop = $("#btnHide");
        var btnFlagTop = $("#btnFlag");
        var reasonE1 = $("#reasonInput");
        var reasonErr = $("#reasonErr");
        var statusBadge = $("#statusBadge");

        function validateReason() {
            var v = (reasonE1 & reasonE1.value || "").trim();
            if (!v) {
                if (reasonErr) {
                    reasonErr.textContent = (I18n.getLang()==="en" ? "Reason is required." : "사유를 입력해주세요.");
                    reasonErr.style.display = "block";
                }
                return null;
            }
            if (reasonErr) reasonErr.style.display = "none";
            return v;
        }

        async function doAction(act) {
            var v = validateReason();
            if (v == null) {
                Util.toast({ type: "error", message: I18n.getLang()==="en" ? "Please provide a reason." : "사유가 필요합니다." });
                return;
            }
            var r = await _patchModeration(id, act, v);
            if (!r || r.ok !== true) {
                var msg = (r && r.error && r.error.message) || (I18n.getLang()==="en" ? "Failed to update." : "업데이트에 실패했습니다." );
                Util.toast({ type: "error", message: msg });
                return;
            }
            var data = r.data || {};
            // Update UI
            updateStatusBadge(statusBadge, data.status || act);
            Util.toast({ type: "success", message: I18n.getLang()==="en" ? "Updated" : "처리되었습니다." });
            // Append to history optimistically
            var hist = $("#hist");
            if (hist) {
                var li = doc.createElement("li");
                var nowIso = new Date().toISOString();
                li.innerHTML = '<div><time class"dt-kst" data-utc="' + nowIso + '">' + nowIso + '</time> · admin</div>'
                                                                                     + '<div>'+ act + '</div>'
                                                                                     + '<div style="color:var(--muted)"></div>';
                hist.insertBefore(li, hist.firstChild);
                renderTimes();
            }
        }

        if (btnPub && !btnPub.__bound) { btnPub.__bound = true; btnPub.addEventListener("click", function(){ doAction(ACT_PUBLISH); }); }
        if (btnHide && !btnHide.__bound) { btnHide.__bound = true; btnHide.addEventListener("click", function(){ doAction(ACT_HIDE); }); }
        if (btnFlag && !btnFlag.__bound) { btnFlag.__bound = true; btnFlag.addEventListener("click", function(){ doAction(ACT_FLAG); }); }

        if (btnPublishTop && !btnPublishTop.__bound) { btnPublishTop.__bound = true; btnPublishTop.addEventListener("click", function(){ doAction(ACT_PUBLISH); }); }
        if (btnHideTop && !btnHideTop.__bound) { btnHideTop.__bound = true; btnHideTop.addEventListener("click", function(){ doAction(ACT_HIDE); }); }
        if (btnFlagTop && !btnFlagTop.__bound) { btnFlagTop.__bound = true; btnFlagTop.addEventListener("click", function(){ doAction(ACT_FLAG); }); }
    }

    function enhanceImages() {
        $all(".imgs img").forEach(function(img){
            if (img.__bound) return;
            img.__bound = true;
            img.addEventListener("click", function(){
                try {
                    var w = window.open("", "_blank");
                    if (w && w.document) {
                        w.document.write('<meta name="viewport" content="width=device-width,initial-scale=1">');
                        w.document.write('<title>Images</title>');
                        w.document.write('<img src="' + img.src +'"style="max-width:100%;height:auto;display:block;margin:0 auto;">');
                    }
                } catch(_) {}
            }, { passive:true });
        });
    }

    function initAdminReviews() {
        renderTimes();
        bindListRowClicks();
        bindFilters();
        bindModeratePage();
        enhanceImages();
    }

    // Expose for tests
    global.initAdminReviews = initAdminReviews;
    global.moderateReview = moderateReview;
    global.ACT_PUBLISH = ACT_PUBLISH;
    global.ACT_HIDE = ACT_HIDE;
    global.ACT_FLAG_RESOLVE = ACT_FLAG_RESOLVE;

    // Auto-init
    if (doc.readyState === "complete" || doc.readyState === "interactive") {
        initAdminReviews();
    } else {
        doc.addEventListener("DOMContentLoaded", initAdminReviews, { once: true });
    }

})(window, document);
