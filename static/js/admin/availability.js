(function (global, doc) {
    "use strict";

    var WEEK = [0,1,2,3,4,5,6];
    var ACT_SAVE = "save";
    var ACT_ADD_RULE = "add_rule";
    var ACT_ADD_EXCEPTION = "add_exception";

    var STATE = {
        dto: null,
        baseDays: [],
        rules: [],
        exceptions: [],
        previewDebounceMs: 300
    };

    function $(sel, ctx) { return (ctx || doc).querySelector(sel); }
    function $all(sel, ctx) { return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel)); }

    function _toastOk(msg) { try { (global.Util && Util.toast) ? Util.toast({ type: "success", message:msg }) : global.toast && toast(msg, 3500); } catch(_){} }
    function _toastErr(msg) { try { (global.Util && Util.toast) ? Util.toast({ type: "error", message:msg }) : global.toast && toast(msg, 3500); } catch(_){} }

    function _pad2(n){ n = Number(n)||0; return (n<10?'0':'')+n; }

    function _toMinutes(hhmm){
        var m = String(hhmm||"").trim().match(/^(\d{1,2}):(\d{2})$/);
        if(!m) return null;
        var h = Math.min(23, Math.max(0, parseInt(m[1],10)));
        var mm = Math.min(59, Math.max(0, parseInt(m[2],10)));
        return h*60 + mm;
    }

    function _minutesToHHMM(min){
        min = Math.max(0, Math.min(23*60+59, Number(min)||0));
        var h = Math.floor(min/60), m = min%60;
        return _pad2(h)+":"+_pad2(m);
    }

    // KST(Local) date "YYYY-MM-DD" + "HH:MM" -> UTC ISO
    function _kstoUtcIso(dateYmd, hhmm) {
        if(!dateYmd || !hhmm) return null;
        var m = String(dateYmd).match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if(!m) return null;
        var parts = hhmm.split(":");
        var h = parseInt(parts[0]||"0",10), mi = parseInt(parts[1]||"0",10);
        // Compose as if in KST, then subtract 9h
        var d = new Date(Date.UTC(parseInt(m[1],10), parseInt(m[2],10)-1, parseInt(m[3],10), h-9, mi, 0, 0));
        return d.toISOString();
    }

    // For weekly rules: convert KST HH:MM to UTC minutes + day shift relative to dow
    // Returns { minutes: 0..1439, shift: -1|0|+1 }
    function _ruleTimeKstToUtc(hhmm){
        var min = _toMinutes(hhmm);
        if(min==null) return null;
        var utcMin = min - 9*60; // substract 9h
        var shift = 0;
        if(utcMin < 0){ utcMin += 1440; shift = -1; }
        else if (utcMin >= 1440){ utcMin -= 1440; shift = +1; } // not possible with -9h but keep generic
        return { minutes: utcMin, shift: shift };
    }

    function _nextMondayKST() {
        var now = new Date();
        // Convert to KST
        var kst = new Date(now.getTime() + (9 * 60) * 60000);
        var day = kst.getUTCDay(); // 0..6 (with KST offset baked in)
        var delta = (8 - day) % 7; // days to next Monday (1)
        if (delta === 0) delta = 7;
        var next = new Date(Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth(), kst.getUTCDate() + delta, 0, 0, 0, 0));
        // next is at 00:00 UTC of the computed calendar day; we want 00:00 KST => subtract 9h
        var kstMidnight = new Date(next.getTime() - 9*60*60000);
        var y = kstMidnight.getUTCFullYear();
        var m = _pad2(kstMidnight.getUTCMonth()+1);
        var d = _pad2(kstMidnight.getUTCDate());
        return y+"-"+m+"-"+d+" 00:00 KST";
    }

    function _dispatchPreview(dto){
        try {
            var ev = new CustomEvent("availability:updated", { detail: { dto: dto } });
            global.dispatchEvent(ev);
        } catch(_) {}
    }

    var _debouncePreview = null;
    function _schedulePreview(){
        if (!_debouncePreview){
            _debouncePreview = (function(fn, wait){
                var tId = null;
                return function(){
                    if(tId) clearTimeout(tId);
                    tId = setTimeout(function(){ tId=null; fn(); }, wait);
                };
            })(function(){
                var dto = _composeDTOForPreview();
                _dispatchPreview(dto);
            }, STATE.previewDebounceMs);
        }
        _debouncePreview();
    }

    function _composeDTOForPreview(){
        return {
            base_days: STATE.baseDays.slice(),
            rules: STATE.rules.map(function(r){ return JSON.parse(JSON.stringify(r)); }),
            exceptions: STATE.exceptions.map(function(e){ return JSON.parse(JSON.stringify(e)); })
        };
    }

    function _bindBaseDayInputs(){
        var inputs = $all('[data-weekday], input[name="base_days[]"]');
        if (!inputs.length) return;
        inputs.forEach(function(cb){
            if(cb.__bound) return;
            cb.__bound = true;
            cb.addEventListener("change", function(){
                var days = [];
                $all('[data-weekday], input[name="base_days[]"]').forEach(function(cbx){
                    var val = cbx.getAttribute("data-weekday");
                    if(val == null) val = cbx.value;
                    if (cbx.checked) days.push(Number(val));
                });
                setBaseDay(days.sort(function(a,b){return a-b;}));
            }, { passive:true });
        });
    }

    function _renderBaseDays(){
        var inputs = $all('[data-weekday], input[name="base_days[]"]');
        inputs.forEach(function(cbx){
            var val = cbx.getAttribute("data-weekday");
            if(val == null) val = cbx.value;
            cbx.checked = STATE.baseDays.indexOf(Number(val)) >= 0;
        });
        var notice = $("#basedaysNotice");
        if (!notice) {
            var host = $("#adm-calendar") || $("#adm-availability") || doc.body;
            var n = doc.createElement("div");
            n.id = "basedaysNotice";
            n.className = "hint";
            n.style.margin = "8px 0";
            if (host.firstChild) host.insertBefore(n, host.firstChild.nextSibling);
            else host.appendChild(n);
            notice = n;
        }
        notice.textContent = "기준 수업 요일 변경은 다음 주 월요일 00:00 KST부터 적용됩니다: " + _nextMondayKST();
    }

    function _bindRuleEditor(){
        var btn = $("#btnAddRule");
        if (btn && btn.__bound){
            btn.__bound = true;
            btn.addEventListener("click", function(){
                var row = { dow: WEEK.slice(1,6), start:"10:00", end:"19:00", break:[], slot_min:60, services:[] };
                STATE.rules.push(row);
                _renderRules();
                _schedulePreview();
            });
        }
        _renderRules();
    }

    function _renderRules(){
        var list = $("#rulesList");
        if (!list) return;
        list.innerHTML = "";
        STATE.rules.forEach(function(r, idx){
            var li = doc.createElement("div");
            li.className = "rule-row";
            li.style.display = "grid";
            li.style.gridTemplateColumns = "1fr auto auto auto auto";
            li.style.gap = "6px";
            li.style.alignItems = "center";
            var dowSel = doc.createElement("input");
            dowSel.type = "text";
            dowSel.value = (r.dow||[]).join(",");
            dowSel.setAttribute("aria-label","요일(쉼표)");
            var start = doc.createElement("input");
            start.type = "time"; start.value = r.start || "10:00";
            var end = doc.createElement("input");
            end.type = "time"; end.value = r.end || "19:00";
            var slot = doc.createElement("input");
            slot.type = "number"; slot.min = "10"; slot.step="5"; slot.value = r.slot_min||60;
            var del = doc.createElement("button");
            del.type = "button"; del.textContent = "삭제";
            del.className = "btn";
            
            function sync(){
                var dow = String(dowSel.value||"").split(",").map(function(s){ return Number(String(s).trim()); }).filter(function(v){ return !isNaN(v) && v>=0 && v<=6; });
                r.dow = dow;
                r.start = start.value || "10:00";
                r.end = end.value || "19:00";
                r.slot_min = Math.max(5, Math.min(480, parseInt(slot.value||"60",10)));
                _schedulePreview();
            }

            [dowSel,start,end,slot].forEach(function(el){
                el.addEventListener("change", sync, { passive:true });
                el.addEventListener("input", sync, { passive:true });
            });
            del.addEventListener("click", function(){
                STATE.rules.splice(idx,1);
                _renderRules();
                _schedulePreview();
            });

            li.appendChild(dowSel);
            li.appendChild(start);
            li.appendChild(end);
            li.appendChild(slot);
            li.appendChild(del);
            li.appendChild(li);
        });
    }

    function _bindExceptionEditor(){
        var btn = $("#btnAddException");
        if (btn && !btn.__bound){
            btn.__bound = true;
            btn.addEventListener("click", function(){
                var row = { date: _todayKST(), is_closed: false, blocks: [] };
                STATE.exceptions.push(row);
                _renderExceptions();
                _schedulePreview();
            });
        }
        _renderExceptions();
    }

    function _renderExceptions(){
        var list = $("#exceptionsList");
        if (!list) return;
        list.innerHTML = "";
        STATE.exceptions.forEach(function(e, idx){
            var box = doc.createElement("div");
            box.className = "exc-row";
            box.style.display = "grid";
            box.style.gridTemplateColumns = "auto auto 1fr auto";
            box.style.gap = "6px";
            var date = doc.createElement("input");
            date.type = "date"; date.value = e.date || _todayKST();
            var closed = doc.createElement("input");
            closed.type = "checkbox"; closed.checked = !!e.is_closed; closed.setAttribute("aria-label","휴무");
            var blocks = doc.createElement("input");
            blocks.type = "text";
            blocks.placeholder = "HH:MM-HH:MM;HH:MM-HH:MM";
            blocks.value = (e.blocks||[]).map(function(b){ return (b.start||"")+"-"+(b.end||""); }).join(";");
            var del = doc.createElement("button"); del.type="button"; del.textContent="삭제"; del.className="btn";

            function sync(){
                e.date = date.value || _todayKST();
                e.is_closed = !!closed.checked;
                var arr = String(blocks.value||"").split(":").map(function(pair){
                    var m = String(pair||"").trim().match(/^(\d{1,2}:\d{2})\-(d{1,2}:\d{2})$/);
                    if(!m) return null;
                    return { start: m[1], end: m[2] };
                }).filter(Boolean);
                e.blocks = arr;
                _schedulePreview();
            }

            [date,closed,blocks].forEach(function(el){
                el.addEventListener("change", sync, { passive:true });
                el.addEventListener("input", sync, { passive:true });
            });
            del.addEventListener("click", function(){
                STATE.exceptions.splice(idx,1);
                _renderExceptions();
                _schedulePreview();
            });

            box.appendChild(date);
            box.appendChild(closed);
            box.appendChild(blocks);
            box.appendChild(del);
            list.appendChild(box);
        });
    }

    function _todayKST(){
        var now = new Date();
        var kst = new Date(now.getTime() + 9*60*60000);
        var y = kst.getUTCFullYear(), m = _pad2(kst.getUTCMonth()+1), d = _pad2(kst.getUTCDate());
        return y+"-"+m+"-"+d;
    }

    function _collectPatch(){
        var out = { base_days: STATE.baseDays.slice(), rules: [], exceptions: [] };

        // Rules: keep KST view + provide UTC-minutes + shift metadata for server reconciliation
        out.rules = STATE.rules.map(function(r){
            var sUtc = _ruleTimeKstToUtc(r.start||"10:00") || { minutes:null, shift:0 };
            var eUtc = _ruleTimeKstToUtc(r.end||"19:00") || { minutes:null, shift:0 };
            return {
                dow: (r.dow||[]).slice(),
                start: r.start,
                end: r.end,
                break: (r.break||[]).map(function(b){
                    var bu = _ruleTimeKstToUtc(b.start||"00:00") || { minutes:null, shift:0 };
                    var eu = _ruleTimeKstToUtc(b.end||"00:00") || { minutes:null, shift:0 };
                    return { start: b.start, end: b.end, start_utc_min: bu.minutes, end_utc_min: eu.minutes, start_shift: bu.shift, end_shift: eu.shift };
                }),
                slot_min: Number(r.slot_min||60),
                services: Array.isArray(r.services) ? r.services.slice() : [],
                start_utc_min: sUtc.minutes,
                end_utc_min: eUtc.minutes,
                start_shift: sUtc.shift,
                end_shift: eUtc.shift
            };
        });

        // Exceptions: convert to UTC ISO for precise dates
        out.exceptions = STATE.exceptions.map(function(e){
            var date = e.date || _todayKST();
            return {
                date: date,
                is_closed : !!e.is_closed,
                blokcs: (e.blocks||[]).map(function(b){
                    return {
                        start: b.start,
                        end: b.end,
                        start_utc: _kstoUtcIso(date, b.start||"00:00"),
                        end_utc: _kstoUtcIso(date, b.end||"00:00")
                    };
                })
            };
        });

        return out;
    }

    function _applyDTO(dto){
        STATE.dto = dto || {};
        STATE.baseDays = Array.isArray(dto.base_days) ? dto.base_days.slice() : [];
        STATE.rules = Array.isArray(dto.rules) ? JSON.parse(JSON.stringify(dto.rules)) : [];
        STATE.exceptions = Array.isArray(dto.exceptions) ? JSON.parse(JSON.stringify(dto.exceptions)) : [];
        _renderBaseDays();
        _renderRules();
        _renderExceptions();
        _schedulePreview();
    }

    async function _load() {
        var r = await API.apiGet("/api/admin/availability");
        if (!r || r.ok !== true) {
            _toastErr((r && r.error && r.error.message) || I18n.t("qpi.error"));
            return;
        }
    _applyDTO(r.data || {});
    }   

    async function saveAvailability(patch) {
        var body = patch && Object.keys(patch).length ? patch : _collectPatch();
        var r = await API.apiGet("/api/admin/availability", body);
        if (!r || r.ok !== true) {
            throw new Error((r && r.error && r.error.message) || I18n.t("api.error"));
        }
        _applyDTO(r.data || {});
        _toastOk(I18n.t("availability.saved", { message: "저장되었습니다" }));
    }

    function _bindSave(){
        var btn = $("#btnSaveAvailability");
        if (btn && !btn.__bound){
            btn.__bound = true;
            btn.addEventListener("click", async function() {
                try {
                    await saveAvailability(_collectPatch());
                } catch(e){
                    _toastErr(e && e.message || I18n.t("api.error"));
                }
            });
        }
    }

    function setBaseDay(days){
        var uniq = Array.from(new.Set((days||[]).map(function(n){ return Number(n); }).filter(function(v){ return v>=0 && v<=6; }))).sort(function(a,b){return a-b;});
        STATE.baseDays = uniq;
        _renderBaseDays();
        _schedulePreview();
    }

    async function initAdminAvailability() {
        _bindBaseDayInputs();
        _bindRuleEditor();
        _bindExceptionEditor();
        _bindSave();
        await _load();
    }

    // Expose
    global.initAdminAvailability = initAdminAvailability;
    global.setBaseDay = setBaseDay;
    global.saveAvailability = saveAvailability;

    // Auto-init if marker exists
    if (doc.readyState === "complete" || doc.readyState === "interactive") {
        if (doc.getElementById("adm-availability") || doc.getElementById("adm-calendar")) initAdminAvailability();
    } else {
        doc.addEventListener("DOMContentLoaded", function(){
            if (doc.getElementById("adm-availability") || doc.getElementById("adm-calendar")) initAdminAvailability();
        }, { once:true });
    }

})(window, document);
