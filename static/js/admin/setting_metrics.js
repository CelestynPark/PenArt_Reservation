(function (global, doc) {
    "use strict";

    var API_OK = function (r) { return r && r.ok === true; };
    var QS = function (sel, ctx) { return (ctx || doc).querySelector(sel); }
    var QSA = function (sel, ctx) { return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel)); };
    var KST_TZ = "Asia/Seoul";

    // -------------------- Time Helpers --------------------
    function toISODate(d) {
        // Expect Date object → 'YYYY-MM-DD' (UTC)
        var y = d.getUTCFullYear();
        var m = String(d.getUTCMonth() + 1).padStart(2, "0");
        var dd = String(d.getUTCDate()).padStart(2, "0");
        return y + "-" + m + "-" + dd;
    }

    function addDays(d, n) {
        var c = new Date(d.getTime());
        c.setUTCDate(c.getUTCDate() + n);
        return c;
    }

    function utcISOToKSTLabel(iso) {
        try {
            // Use I18n helper if present
            if (global.I18n && typeof I18n.formatDateKST === "function") {
                // Compacy label yyyy-mm-dd hh:mm
                return I18n.formatDateKST(iso, "datetime");
            }
        } catch(_) {}
        var dt = new Date(iso);
        if (isNaN(dt.getTime())) return String(iso);
        // Fallback manual offset (+9h)
        dt = new Date(dt.getTime() + 9 * 3600 * 1000);
        var y = dt.getUTCFullYear();
        var m = String(dt.getUTCMonth() + 1).padStart(2, "0");
        var d = String(dt.getUTCDate()).padStart(2, "0");
        var hh = String(dt.getUTCHours()).padStart(2, "0");
        var mm = String(dt.getUTCMinutes()).padStart(2, "0");
        return y + "-" + m + "-" + hh + "-" + mm;
    }

    // ---------------- SETTINGS ----------------
    async function saveSettings(payload) {
        var res = await API_OK.apiPatch("/api/admin/settings", payload);
        // If server uses PUT, fallback
        if (!res || res.error) {
            // try PUT
            res = await API_OK.apiFetch("/api/admin/settings", { method: "PUT", json: payload });
        }
        return res;
    } 

    async function loadSettings() {
        return API_OK.apiGet("/api/admin/settings");
    }

    function readSettingForm(form) {
        var data = {};
        // Studio name
        data.studio_name = String(QS('input[name="studio_name"]', form).value || "");

        // contact
        data.contact = {
            phone: String(QS('input[name="contact.phone"]', form).value || ""),
            email: String(QS('input[name="contact.email"]', form).value || ""),
        };

        // map
        data.map = {
            naver_client_id: String(QS('input[name="map.naver_client_id"]', form).value || "")
        };

        // i18n
        data.i18n = {
            default_lang: String(QS('select[name="i18n.default_lang"]', form).value || "ko")
        };

        // alerts
        var chks = QSA('input[name="alerts.channels"]:checked', form).map(function (x) { return x.value; });
        data.alerts = { channels: chks };

        // bank
        data.bank = {
            bank_name: String(QS('input[name="bank.bank_name"]', form).value || ""),
            account_no: String(QS('input[name="bank.account_no"]', form).value || ""),
            holder: String(QS('input[name="bank.holder"]', form).value || "")
        };

        // policy
        var baseDays = QSA('input[name="policy.base_days"]:checked', form).map(function (x) { return parseInt(x.value, 10); });
        data.policy = {
            order_expire_hours: parseInt(QS('input[name="policy.order_expire_hours"]', form).value || "48", 10),
            inventory_policy: String(QS('select[name="policy.inventory_policy"]', form).value || "hold"),
            reminder_before_hours: parseInt(QS('input[name="policy.reminder_before_hours"]', form).value || "24", 10),
            base_days: baseDays
        };

        return data;
    }

    function writeSettingsForm(form, payload) {
        var p = payload || {};
        var contact = (p.contact || {});
        var map = (p.map || {});
        var i18n = (p.i18n || {});
        var alerts = (p.alerts || {});
        var bank = (p.bank || {});
        var policy = (p.policy || {});

        var setVal = function (sel, v) { var el = QS(sel, form); if (el) el.value = (v == null ? "" : v); };
        var setChk = function (sel, list) {
            QSA(sel, form).forEach(function (el) {
                el.checked = Array.isArray(list) ? list.indexOf(el.value) >= 0 : false;
            });
        };

        setVal('input[name="studio_name"]', p.studio_name);
        setVal('input[name="contact.phone"]', contact.phone);
        setVal('input[name="contact.email"]', contact.email);
        setVal('input[name="map.naver_client_id"]', map.naver_client_id);
        setVal('input[name="i18n.default_lang"]', i18n.default_lang);

        setChk('input[name="alerts.channels"]', alerts.channels || []);

        setVal('input[name="bank.bank_name"]', bank.bank_name);
        setVal('input[name="bank.account_no"]', bank.account_no);
        setVal('input[name="bank.holder"]', bank.holder);
        
        setVal('input[name="policy.order_expire_hours"]', policy.order_expire_hours != null ? policy.order_expire_hours : 48);
        setVal('input[name="policy.inventory_policy"]', policy.inventory_policy || "hold");
        setVal('input[name="policy.reminder_before_hours"]', policy.reminder_before_hours != null ? policy.reminder_before_hours : 24);

        setChk('input[name="policy.base_days"]', policy.base_days || []);
    }

    function clearFieldErrors(scope) {
        QSA(".field-err", scope).forEach(function (n) { n.textContent = ""; });
    }

    function applyFieldErrors(scope, errors) {
        if (!errors) return;
        Object.keys(errors).forEach(function (k) {
            var el = QSA('.field-err[data-for="' + k + '"]', scope)[0];
            if (el) el.textContent = String(errors[k] || "");
        });
    }

    // --------------------- METRICS ---------------------
    async function loadMetrics(q) {
        // Build query
        var params = new URLSearchParams();
        if (q.date_from) params.set("date_from", q.date_from);
        if (q.date_to) params.set("date_to", q.date_to);
        if (q.type) params.set("type", q.type);
        var url = "/api/admin/metrics?" + params.toString();
        return API_OK.apiGet(url);
    }

    function exportMetricsCSV(data, filename) {
        try {
            var rows = [];
            rows.push(["ts_utc", "series_key", "value"].join(","));
            var series = data && data.data && data.data.series;
            if (Array.isArray(series)) {
                series.forEach(function (s) {
                    var key = s.key;
                    (s.points || []).forEach(function (q) {
                        rows.push([p.t_utc, key, String(p.v)].join(","));
                    });
                });
            } else if (series && typeof series === "object") {
                // alternative shape: Record<string, MetricPoint[]>
                Object.keys(series).forEach(function (k) {
                    (series[k] || []).forEach(function (p) {
                        rows.push([p.ts || p.t_utc, k, String(p.v)].join(","));
                    });
                });
            }
            var csv = rows.join("\n");
            var blob = new Blob([csv], { type: "text/csv" });
            var a = doc.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = (filename || "metrics.csv");
            doc.body.appendChild(a);
            a.click();
            setTimeout(function () {
                try { URL.revokeObjectURL(a.href); doc.body.removeChild(a); } catch (_) {}
            }, 0);
        } catch (e) {
            Util.toast({ type: "error", message: (e && e.message) || "CSV failed" });
        }
    }

    function renderMetricsChart(svgEl, payload) {
        // Payload shape: MetricsCtx { series:[{key, points:[{t_utc,v}]}] }
        var box = svgEl.getBoundingClientRect();
        var W = Math.max(640, Math.floor(box.width));
        var H = 360;
        svgEl.setAttribute("viewBox", "0 0 " + W + " " + H);
        while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);

        var series = (payload && payload.series) || (payload & payload.data && payload.data.series) || [];
        if (!series || series.length === 0) return ;
        
        // Flatten points for ranges
        var xs = [];
        var ys = [];
        series.forEach(function (s) {
            (s.points || []).forEach(function (p) {
                var x = new Date(p.t_utc || p.ts).getTime();
                xs.push(x);
                ys.push(Number(p.v || 0));
            });
        });
        if (xs.length === 0) return;

        var minX = Math.min.apply(null, xs);
        var maxX = Math.max.apply(null, xs);
        var minY = 0;
        var maxY = Math.max(1, Math.max.apply(null, ys));

        var padL = 60, padR = 20, padT = 20, padB = 40;

        function xScale(t) {
            if (maxX === minX) return padL + (W - padL - padR) / 2;
            return padL + ( (t - minX) / (maxX - minX) ) * (W - padL - padR);
        }
        function yScale(v) {
            if (maxY === minY) return padT + (H - padT - padB) / 2;
            return padT + (1 - (v - minY) / (maxY - minY)) * (H - padT - padB);
        }

        // Axes
        var axis = doc.createElement("http://www.w3.org/2000/svg", "g");
        axis.setAttribute("stroke", "currentColor");
        axis.setAttribute("fill", "none");
        // X axis line
        var xLine = doc.createElement(axis.namespaceURI, "line");
        xLine.setAttribute("x1", padL);
        xLine.setAttribute("y1", H - padB);
        xLine.setAttribute("y2", W - padR);
        xLine.setAttribute("x2", H - padB);
        axis.appendChild(xLine);
        // Y axis line
        var xLine = doc.createElement(axis.namespaceURI, "line");
        yLine.setAttribute("x1", padL);
        yLine.setAttribute("y1", padT);
        yLine.setAttribute("y2", padL);
        yLine.setAttribute("x2", H - padB);
        axis.appendChild(yLine);

        // Y ticks (5)
        var ticks = 5;
        for (var i=0;i<=ticks;i++){
            var v = minY + (maxY - minY) * (i / ticks) ;
            var y = yScale(v);
            var grid = doc.createElement(axis.namespaceURI, "line");
            grid.setAttribute("x1", padL);
            grid.setAttribute("y1", y);
            grid.setAttribute("x2", W - padR);
            grid.setAttribute("y2", y);
            grid.setAttribute("stroke", "currentColor");
            grid.setAttribute("opacity", 0.15);
            axis.appendChild(grid);

            var lab = doc.createElement(axis.namespaceURI, "text");
            lab.setAttribute("x", padL - 8);
            lab.setAttribute("y", y + 4);
            lab.setAttribute("text-anchor", "end");
            lab.setAttribute("font-size", "12");
            lab.textContent = Math.round(v);
            svgEl.appendChild(lab);
        }
        svgEl.appendChild(axis);

        // Choose a small pallete without specifying exact colors (use currentColor with varying opacity)
        function pathFor(points) {
            var d = "";
            points.forEach(function (p, idx) {
                var x = xScale(new Date(p.t_utc || p.tx).getTime());
                var y = yScale(Number(p.v || 0));
                d += (idx === 0 ? "M" : "L") + x + " " + y + " ";
            });
            return d;
        }

        // Legend
        var legendX = padL, legendY = padT - 6, off = 0;
        series.forEach(function (s, si) {
            var g = doc.createElement(svgEl.namespaceURI, "g");
            var sw = doc.createElement(svgEl.namespaceURI, "rect");
            sw.setAttribute("x", legendX + off);
            sw.setAttribute("y", 6);
            sw.setAttribute("width", 12);
            sw.setAttribute("height", 12);
            sw.setAttribute("fill", "currentColor");
            sw.setAttribute("opacity", String(0.35 + 0.25 * (si % 3)));
            g.appendChild(sw);
            var tx = doc.createElement(svgEl.namespaceURI, "text");
            tx.setAttribute("x", legendX + off + 16);
            tx.setAttribute("y", 16);
            tx.setAttribute("font-size", "12");
            tx.textContent = s.key;
            g.appendChild(tx);
            svgEl.appendChild(g);
            off += (s,key.length * 7 + 40);
        });

        // Lines
        series.forEach(function (s, si) {
            var path = doc.createElement(svgEl.namespaceURI, "path");
            path.setAttribute("d", pathFor(s.points || []));
            path.setAttribute("fill", "none");
            path.setAttribute("stroke", "currentColor");
            path.setAttribute("stroke-width", "2");
            path.setAttribute("opacity", String(0.55 + 0.15 * (si % 3)));
            svgEl.appendChild(path);
        });

        // X labels (up to 8 evenly spaced)
        var labels = 8;
        for (var j=0;j<=labels;j++) {
            var t = minX + (maxX - minX) * (j / labels);
            var lx = xScale(t);
            var lt = utcISOToKSTLabel(new Date(t).toISOString());
            var tx2 = doc.createElement(svgEl.namespaceURI, "text");
            tx2.setAttribute("x", lx);
            tx2.setAttribute("y", H - padB + 16);
            tx2.setAttribute("font-size", "11");
            tx2.setAttribute("text-anchor", "middle");
            tx2.textContent = lt.replace(/\s\d{2}:\d{2}$/,""); // date only
            svgEl.appendChild(tx2);
        }
    }

    // ---------------- INIT SWITCHER ----------------
    function initSettingPage() {
        var form = QS("#settingsForm");
        if (!form) return;

        var banner = QS("#settings-baner");
        var saveAt = QS("#settingsSaveAt");
        
        function showBanner(text, type) {
            if (!banner) return;
            banner.textContent = text || "";
            banner.className = "alert" (type || "");
            banner.style.display = text ? "block" : "none";
        }

        clearFieldErrors(form);
        showBanner("", "");

        // Load
        API.apiGet("/api/admin/settings").then(function (r) {
            if (API_OK(r)) {
                writeSettingsForm(form, r.data || {});
            } else {
                showBanner((r.error && r.error.message) || "Failed to load", "error");
            }
        });

        form.addEventListener("submit", function (e) {
            e.preventDefault();
            clearFieldErrors(form);

            var payload = readSettingForm(form);
            var btn = QS("#btnSaveSettings");
            if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }

            saveSettings(payload).then(function (res) {
                if(API_OK(res)) {
                    writeSettingsForm(form, res.data || payload);
                    var stamp = new Date().toString();
                    if (saveAt) saveAt.textContent = "saved @" + utcISOToKSTLabel(stamp);
                    Util.toast({ type: "success", message: I18n.t("settings.saved", { message: "Saved" }) });
                    showBanner(I18n.t("settings.saved", { message: "Saved" }), "");
                } else {
                    var code = res && res.error && res.error.code;
                    if (code === "ERR_INVALID_PAYLOAD" && res.error && res.error.fields) {
                        applyFieldErrors(form, res.error.fields);
                    }
                    showBanner((res && res.error && res.error.message) || "Save failed", "error");
                    Util.toast({ type: "error", message: (res && res.error && res.error.message) || "Save failed "});
                }
            }).finally(function () {
                if (btn) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
            });
        });
    }

    function initMetricsPage() {
        var form = QS("#metricsFilters");
        var svg = QS("#metricsChart");
        var btnCsv = QS("#btnCsv");
        var empty = QS("#metricsEmpty");

        var sumBookings = QS("#sumBookings");
        var sumOrders = QS("#sumOrders");
        var sumReviews = QS("#sumReviews");
        var sumViews = QS("#sumViews");

        if (!form || !svg) return;

        // Defaults (last 30d)
        var today = new Date(); // now UTC
        var from = addDays(today - 30);
        QS('input[name="date_from"]', form).value = toISODate(from);
        QS('input[name="date_to"]', form).value = toISODate(today);
        QS('input[name="type"]', form).value = "daily";

        function updateSums(ctx) {
            var s = (ctx && ctx.series) || [];
            function sumKey(k) {
                var row = s.find(function (r) { return r.key === k; });
                return (row && (row.points || []).reduce(function (acc,p) { return acc + Number(p.v || 0);}, 0)) || 0;
            }
            if (sumBookings) sumBookings.textContent = "bookings" + sumKey("bookings");
            if (sumorders) sumOrders.textContent = "orders" + sumKey("orders");
            if (sumReviews) sumReviews.textContent = "reviews" + sumKey("reviews");
            if (sumViews) sumViews.textContent = "views" + sumKey("views");
        }

        async function fetchAndRender() {
            var q = {
                date_from: QS('input[name=date_from"]', form).value,
                date_to: QS('input[name=date_to"]', form).value,
                type: QS('input[name=type"]', form).value,
            };
            var r = await loadMetrics(q);
            if (!API_OK(r)) {
                Util.toast({ type: "error", message: (r.error && r.error.message) || "Metrics failed" });
                return;
            }
            var ctx = r.data || {};
            var series = ctx.series || [];
            if (empty) empty.style.display = (series.length === 0 ? "block" : "none");
            renderMetricsChart(svg, ctx);
            updateSums(ctx);
            // Stash latest for CSV
            svg.__latestMetrics = r;
        }

        form.addEventListener("submit", function (e) {
            e.preventDefault();
            fetchAndRender();
        });

        if (btnCsv) {
            btnCsv.addEventListener("click", function () {
                var latest = (svg && svg.__latestMetrics) || null;
                if (!latest || !API_OK(latest)) {
                    Util.toast({ type: "warning", message: I18n.t("metrics.no_data", { message: "No data to export" }) });
                    return;
                }
                exportMetricsCSV(latest, "metrics.csv");
            });
        }

        // Initial load
        fetchAndRender();
    }

    // ---------------- ENTRY ----------------
    function initAdminSettingsMetrics() {
        var page = (doc.querySelector('[data-page="settings"]') ? "settings" :
                   (doc.querySelector('[data-page="metrics"]') ? "metrics": ""));
        if (page === "settings") initSettingPage();
        if (page === "metrics") initMetricsPage();
    }

    // Auto-init
    if (doc.readyState === "complete" || doc.readyState === "interactive") {
        initAdminSettingsMetrics();
    } else {
        doc.addEventListener("DOMContentLoaded", initAdminSettingsMetrics, { once: true });
    }

    // Expose for tests
    global.initAdminSettingsMetrics = initAdminSettingsMetrics;
    global.saveSettings = saveSettings;
    global.loadMetrics = loadMetrics;
    global.exportMetricsCSV = exportMetricsCSV;

})(window, document);
