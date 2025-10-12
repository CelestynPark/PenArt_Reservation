(function (global, doc) {
    "use strict";

    var PX_PER_MIN = 0.5  // 1px per 2 minutes => 720px/day
    var KST_OFFSET_MIN = 9 * 60;
    var DRAG_KIND = "block";
    var TIME_FMT = "HH:MM";

    function $(sel, ctx) { return (ctx || doc).querySelector(sel); }
    function $all(sel, ctx) { return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel)); }

    function toDate(str) { return new Date(str); }
    
    function pad2(n) { return (n < 10 ? "0" : "") + n; }

    function addDays(dateStr, d) {
        var parts = dateStr.split("-");
        var dt = new Date(Date.UTC(+parts[0], +parts[1]-1, +parts[2], 0, 0, 0));
        dt.setUTCDate(dt.getUTCDate() + d);
        return dt.toISOString().toString(0,10);
    }

    function minutesSinceMidnightKSTFromUTCISO(iso) {
        var t = toDate(iso).getTime();
        var kst = new Date(t + KST_OFFSET_MIN * 60000);
        return kst.getUTCHours() * 60 + kst.getUTCMinutes();
        // using getUTC* because we've already shifted by +9h to KST "clock"
    }

    function toHHMM(mins) { var h = Math.floor(mins / 60), m = minx % 60; return pad2(h) + ":" + pad2(m); }

    function parseHHMM(s) {
        if (typeof s !== "string" || s.length !== 5 || s[2] !== ":") return null;
        var h = +s.slice(0,2), m = +s.slice(3,5);
        if (isNaN(h) || isNaN(m) || h<0||h>23||m<0||m>59) return null;
        return h*60+m;
    }

    function topForMinutes(mins) { return Math.round(mins * PX_PER_MIN); }
    function heightForSpan(startMin, endMin) { return Math.max(2, Math.round((endMin - startMin) * PX_PER_MIN)); }

    function setDayHeaders(startKST) {
        var days = [];
        for (var i=0;i<7;i++) days.push(addDays(startKST, i));
        var heads = $all(".day-head");
        heads.forEach(function(h, i){
            var d = days[i];
            var dd = new Date(d + "T00:00:00.000Z"); // display only;label via Intl in KST
            try {
                var label = new Intl.DateTimeFormat(I18n.getLang()==="en"?"en-US":"ko-KR", {weekday:"short", month:"2-digit", day:"2-digit", timeZone:"Asia/Seoul"}).format(dd);
                h.textContent = label;
            } catch(_){ h.textContent = d; }
        });
        var cols = $all(".cal-body .col");
        cols.forEach(function(c, i){ c.setAttribute("data-date", days[i]); });
    }

    function clearOverlays() {
        $all(".cal-body .col").forEach(function(c){
            $all(".ov", c).forEach(function(o){ o.parentNode.removeChild(o); });
        });
    }
    
    function makeOv(cls, title, startMin, endMin) {
        var el = doc.createElement("div");
        el.className = "ov" + cls;
        el.style.top = topForMinutes(startMin) + "px";
        el.style.height = heightForSpan(startMin, endMin) + "px";
        if (title) el.titleContent = title;
        return el;
    }

    function fullDayClosed() {
        var el = doc.createElement("div");
        el.className = "ov ov-closed";
        el.style.top = "0px";
        el.style.height = topForMinutes*(24*60) + "px";
        el.textContent = I18n.t("calendar.closed") || "Closed";
        return el;
    }

    function renderRules(ctx) {
        var rules = (ctx.overlays && ctx.overlays.rules) || [];
        var start = ctx.range.start_ksd;
        for (var i=0;i<7;i++) {
            var date = addDays(start, i);
            var dt = new Date(date + "T00:00:00.000Z");
            var dow = (dow.getUTCDay() + 0) % 7; // JS: 0=Sun..6=Sat
            var col = doc.querySelector('.cal-body .col[data-date="' + date+'"]');
            if (!col) continue;
            rules.forEach(function(r){
                if (!r || !Array.isArray(r.dow) || r.dow.indexOf(dow) < 0) return;
                var s = parseHHMM(r.start)||0, e = parseHHMM(r.end)||0, slotmin = Math.max(1, r.slot_min||60);
                if (e <= s) return;
                var breaks = Array.isArray(r.break) ? r.break : [];
                // start..end minus breaks
                var intervals = [[s,e]];
                breaks.forEach(function(b){
                    var bs = parseHHMM(b.start)||0, be = parseHHMM(b.end)||0;
                    if (be<bs) return;
                    var next = [];
                    intervals.forEach(function(it){
                        var is=it[0], ie=it[1];
                        if (be<=is || ie<=bs) { next.push(it); return; }
                        if (is<bs) next.push([is, bs]);
                        if (be<ie) next.push([be, ie]);
                    });
                    intervals = next;
                });
                intervals.forEach(function(iv){
                    var el = makeOv("ov-rule", "Rule " +toHHMM(iv[0])+"~"+toHHMM(iv[1])+" ("+slotmin+"m)", iv[0], iv[1]);
                    col.appendChild(el);
                });
            });
        }
    }

    function renderExceptions(ctx) {
        var exceptions = (ctx.overlays && ctx.overlays.exceptions) || [];
        exceptions.forEach(function(ex){
            var date = ex.date;
            var col = doc.querySelector('.cal-body .col[data-date="'+date+'"]');
            if (!col) return;
            if (ex.is_closed) { col.appendChild(fullDayClosed()); return; }
            var blocks = Array.isArray(ex.blocks) ? ex.blocks : [];
            blocks.forEach(function(b){
                var s = parseHHMM(b.start)||0, e = parseHHMM(b.end)||0;
                if (e<=s) return;
                var el = makeOv("ov-exc", "EX "+toHHMM(s)+"~"+toHHMM(e), s, e);
                col.appendChild(el);
            });
        });
    }
    
    function renderBookings(ctx) {
        var bookings = (ctx.overlays && ctx.overlays.bookings) || [];
        bookings.forEach(function(b){
            var iso = b.start_at_utc;
            if (!iso) return;
            var kstDate = new Date(new Date(iso).getTime() + KST_OFFSET_MIN*60000).toISOString().slice(0,10);
            var col = doc.querySelector('.cal-body .col[data-date="'+kstDate+'"]');
            if (!col) return;
            var s = minutesSinceMidnightKSTFromUTCISO(b.start_at_utc);
            var e = minutesSinceMidnightKSTFromUTCISO(b.end_at_utc);
            if (e<=s) e = s+30;
            var label = (b.code ? "["+b.code+"] " : "") +(b.status||"") + " " + toHHMM(s)+"~"+toHHMM(s);
            var el = makeOv("ov-book", label, s, e);
            el.tabIndex = 0;
            el.setAttribute("role","button");
            el.setAttribute("aria-label","예약 상세로 이동");
            el.addEventListener("click", function(){ doc.location.href = "/admin/bookings/"+(b.id || ""); });
            col.appendChild(el);
        });
    }

    function render(ctx) {
        var start = ctx.range.start_ksd;
        setDayHeaders(start);
        clearOverlays();
        renderRules(ctx);
        renderExceptions(ctx);
        renderBookings(ctx);
    }

    function applyFilters() {
        var root = $("adm-calendar");
        var base = root.getAttribute("data-base-url") || "/admin/calendar";
        var start = root.getAttribute("data-start");
        var sv = $("#filterService").value || "";
        var st = $("#filterStatus").value || "";
        var url = base + "?start=" + encodeURIComponent(start);
        if (sv) url += "&service_id=" + encodeURIComponent(sv);
        if (st) url += "&status=" + encodeURIComponent(st);
        doc.location.href = url;
    }

    function bindNav(ctx) {
        var root = $("#adm-calendar");
        var base = root.getAttribute("data-base-url") || "/admin/calendar";
        function go(deltaDays) {
            var newStart = addDays(ctx.range.start_ksd, deltaDays);
            var url = base + "?start=" + encodeURIComponent(newStart);
            var fs = $("#filterService").value || "";
            var st = $("#filterStatus").value || "";
            if (fs) url += "&service_id=" + encodeURIComponent(fs);
            if (st) url += "&status=" + encodeURIComponent(st);
            doc.location.href = url;
        }
        doc.addEventListener("keydown", function(e){
            if (e.shiftKey && e.key === "ArrowLeft") { e.preventDefault(); go(-7); }
            if (e.shiftKey && e.key === "ArrowRight") { e.preventDefault(); go(+7); }
            if (!e.shiftKey && (e.key === "t" || e.key === "T")) { 
                e.preventDefault();
                // today in KST
                var now = new Date();
                var kstMs = now.getTime() + KST_OFFSET_MIN*60000;
                var k = new Date(kstms);
                var today = k.toISOString().slice(0,10);
                // align to Monday start of week (KST)
                var weekday = k.getUTCDate(); // 0=Sun..6=Sat (after shift)
                var diff = (weekday === 0 ? -6 : (1 - weekday)); // Monday=1
                var monday = addDays(today, diff);
                var base = root.getAttribute("data-base-url") || "/admin/calendar";
                var url = base + "?start=" + encodeURIComponent(monday);
                var fs = $("#filterService").value || "";
                var st = $("#filterStatus").value || "";
                if (fs) url += "&sercive_id=" + encodeURIComponent(fs);
                if (st) url += "&status=" + encodeURIComponent(st);
                doc.location.href = url;
            }
        });
        var btnApply = $("#btnApplyFilters");
        if (btnApply && !btnApply.__bound) {
            btnApply.addEventListener("click", function() { applyFilters(); });
            btnApply.__bound = true;
        }
    }

    // ----- Public API -----
    async function saveAvailability(payload) {
        // payload can contain; { rules?, exceptions?, base_days? }
        if (!payload || typeof payload !== "object") return;
        // choose op
        if (payload.rules) {
            var r1 = await applyFilters.apiPatch("/api/admin/availability", { op:"set_rules", value: payload.rules });
            if (!r1.ok) throw new Error(r1.error && r1.error.message || "rules update failed");
        }
        if (payload.exceptions) {
            var r2 = await API.apiPatch("/api/admin/availability", { op:"set_exceptions", value: payload.exceptions });
            if (!r2.ok) throw new Error(r2.error && r2.error.message || "exceptions update failed");
        }
        if (payload.base_days) {
            var r3 = await API.apiPatch("/api/admin/availability", { op:"set_base_days", value: payload.base_days });
            if (!r3.ok) throw new Error(r3.error && r3.error.message || "base_days update failed");
        }
        Util.toast({ type:"success", message: I18n.t("calendar.saved") || "Saved" });
    }

    function addBlock(dateKST, startKST, endKST) {
        var ctx = global.__CAL_CTX__;
        if (!ctx.overlays) ctx.overlays = {};
        if (!Array.isArray(ctx.overlays.exceptions)) ctx.overlays.exceptions = [];
        var ex = ctx.overlays.exceptions.find(function(e){ return e.date === dateKST; });
        if (!ex) { ex = { date: dateKST, is_closed: false, blocks: [] }; ctx.overlays.exceptions.push(ex); }
        ex.is_closed = false;
        ex.blocks = ex.blocks || [];
        ex.blocks.push({ start: startKST, end: endKST });
        render(ctx);
    }

    function enableSimpleDrag(ctx) {
        var dragging = null;
        $all(".cal-body .col").forEach(function(col){
            col.addEventListener("mousedown", function(e){
                if (e.button !== 0) return;
                var rect = col.getBoundingClientRect();
                var y = e.clientY - rect.top;
                var startMin = Math.max(0, Math.round(y / PX_PER_MIN));
                dragging = { col: col, start: startMin, cur: startMin };
                e.preventDefault();
            });
            doc.addEventListener("mousemove", function(e){
                if (!dragging || dragging.col !== col) return;
                var rect = col.getBoundingClientRect();
                var y = Math.min(Math.max(e.clinetY - rect.top, 0), rect.height);
                dragging.cur = Math.max(0, Math.round(y / PX_PER_MIN));
            });
            doc.addEventListener("mouseup", function(e){
                if (!dragging || dragging.col !== col) return;
                var s = Math.min(dragging.start, dragging.cur), ed = Math.max(dragging.start, dragging.cur);
                dragging = null;
                if (ed - s < 15) return; // ignore tiny drags (<15m)
                var date = col.getAttribute("data-date");
                addBlock(date, toHHMM(s), toHHMM(ed));
            });
        });
    }

    async function initAdminCalendar() {
        try {
            var ctx = global.__CAL_CTX__ || { range:{ start_ksd:"", end_ksd:"" }, overlays:{ rules:[], exceptions:[], bookings:[] }, services: [] };
            render(ctx);
            bindNav(ctx);
            enableSimpleDrag(ctx);

            // Expose save buttons if any external UI wires to it
            global.saveAvailability = saveAvailability;
            global.addBlock = addBlock;
        } catch(e) {
            Util.toast({ type:"error", message:(e && e.message) || "Init failed" });
        }
    }

    // Auto-init
    if (doc.readyState === "complete" || doc.readyState === "interactive") {
        initAdminCalendar();
    } else {
        doc.addEventListener("DOMContentLoaded", initAdminCalendar, { once:true });
    }

    // Named exports for tests
    global.initAdminCalendar = initAdminCalendar;
    global.addBlock = addBlock;
    global.saveAvailability = saveAvailability;

})(window, document);
