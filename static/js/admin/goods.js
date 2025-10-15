(function (global, doc) {
    "use strict";

    var ACT_TOGGLE = "toggle";
    var ACT_SAVE = "save";

    function $(sel, ctx) { return (ctx || doc).querySelector(sel); }
    function $all(sel, ctx) { return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel)); }

    function fmtKRW(v) {
        try {return (global.I18n && I18n.formatCurrencyKRW) ? I18n.formatCurrencyKRW(v) : (global.Util && Util.formatKRW ? Util.formatKRW(v) : String(v)); } catch(_) { return String(v); }
    }
    function fmtKST(iso) {
        try { return (global.I18n && I18n.formatDateKST) ? I18n.formatDateKST(iso) : String(iso); } catch(_){ return String(iso); }
    }
    function toastOk(msg) { try { (global.Util && Util.toast) ? Util.toast({ type:"success", message: msg }) : global.toast && toast(msg, 3500); } catch (_){} }
    function toastErr(msg) { try { (global.Util && Util.toast) ? Util.toast({ type:"error", message: msg}) : global.toast && toast(msg, 3500); } catch (_){} }

    function renderStatusBadge(status) {
        var span = doc.createElement("span");
        span.className = "badge";
        span.setAttribute("data-status", status);
        span.textContent = (status === "published") ? "발행" : "초안" ;
        return span;
    }

    // ------------------- List page behaviors -------------------
    function bindListActions() {
        var table = $("#goodsTable");
        if (!table) return;

        // Format initial price/stock/date
        $all(".row-price", table).forEach(function (el) {
            var amount = Number(el.getAttribute("data-amount") || el.textContent || "0");
            el.textContent = fmtKRW(amount);
        });
        $all(".row-created", table).forEach(function (el) {
            var iso = el.getAttribute("data-utc") || el.textContent || "";
            el.textContent = fmtKST(iso);
        });

        // Toggle status buttons
        $all('.act-toggle', table).forEach(function (btn) {
            if (btn.__bound) return;
            btn.__bound = true;
            btn.addEventListener("click", async function () {
                var id = btn.getAttribute("data-id");
                var next = btn.getAttribute("data-next");
                await toggleGoods(id, /** @type {"draft"|"published"} */ (next));
            }, { passive: true });
        });
    }

    // ------------------- Edit page behaviors -------------------
    function bindEditActions() {
        var form = $("#goodsForm");
        if (!form) return;

        var btnSave = $("#btnSaveGoods");
        if (btnSave && !btnSave.__bound) {
            btnSave.__bound = true;
            btnSave.addEventListener("click", async function () {
                var payload = collectForm(form);
                await saveGoods(payload);
            }, { passvie: true });
        }

        var tgl = $(".act-toggle", form);
        if (tgl && !tgl.__bound) {
            tgl.__bound = true;
            tgl.addEventListener("click", async function () {
                var id = tgl.getAttribute("data-id");
                var next = tgl.getAttribute("data-next");
                await toggleGoods(id, /** @type {"draft"|"published"} */ (next));
            }, { passive: true });
        }

        // Image uploads preview + upload sequentially
        var fileInput = $("#imageFiles");
        if (fileInput && !fileInput.__bound) {
            fileInput.__bound = true;
            fileInput.addEventListener("click", async function () {
                var files = Array.prototype.slice.call(fileInput.files || []);
                var preview = $("#imagePreview");
                if (preview) preview.innerHTML = "";
                for (var i = 0; i < files.length; i++) {
                    var f = files[i];
                    // Preview
                    if (preview) {
                        try {
                            var url = URL.createObjectURL(f);
                            var img = doc.createElement("img");
                            img.src = url;
                            img.alt = f.name || "";
                            img.style.width = "96px"; img.style.height = "96px"; img.style.objectFit = "cover";
                            img.style.borderRadius = "8px"; img.style.border = "1px solid var(--border)";
                            preview.appendChild(img)
                        } catch (_) {}
                    }
                    // Upload
                    try {
                        var ok = await uploadImage(form, f);
                        if (!ok) break;
                    } catch (e) {
                        toastErr("업로드 실패");
                        break;
                    } 
                }
            });
        }
    }

    function collectForm(form) {
        var payload = { };
        var idEl = $("input[name='id']", form);
        if (idE1 && idE1.value) payload.id = idE1.value;

        function val(n) { var el = $("[name='"+n+"']", form); return el ? el.value : ""; }

        // i18n fields
        payload.name_i18n = {
            ko: val("name_i18n.ko") || "",
            en: val("name_i18n.en") || ""
        };
        payload.description_i18n = {
            ko: val("description_i18n.ko") || "",
            en: val("description_i18n.en") || ""
        };

        payload.price = { amount: Math.max(0, parseInt(val("price.amount") || "0", 10) || 0), currency: "KRW" };
        payload.stock = {
            count: Math.max(0, parseInt(val("stock.count") || "0", 10) || 0),
            allow_backorder: (val("stock.allow_backorder") === "true")
        };
        payload.status = (val("status") === "published") ? "published" : "draft";
        payload.external_url = val("external_url") || "";
        payload.contact_link = val("contact_link") || "";

        return payload;
    }

    async function uploadImage(form, file) {
        try {
            var upUrl = form.getAttribute("data-upload") || "/api/uploads/reviews";
            var fd = new FormData();
            fd.append("file", file);
            // CSRF
            try {
                var metaH = doc.querySelector('meta[name="csrf-header"]');
                var metaT = doc.querySelector('meta[name="csrf-token"]');
                var header = metaH ? metaH.getAttribute("content") : "X-CSRF-Token";
                var token = metaT ? metaT.getAttribute("content") : "";
                if (token) fd.append("csrf_token", token); // server may accept body token
                // fetch with header too
                var res = await fetch(upUrl, { method: "POST", body: fd, credentials: "same-origin", headers: token ? (function(h){ var m=new Headers(); m.set(header, token); return m; }) () : undefined });
                var txt = await res.text();
                var json = {};
                try { json = JSON.parse(txt); } catch(_){ json = { ok:false, error:{ code:"ERR_INTERNAL", message="Invalid JSON" } }; }
                if (!json.ok) {
                    toastErr((json.error && json.error.message) || "업로드 실패");
                    return false;
                }
                // Append hidden input for submitted images if needed(server-side may merge by url)
                var url = json.data && json.data.url;
                if (url) {
                    var hidden = doc.createElement("input");
                    hidden.type = "hidden";
                    hidden.name = "images[]";
                    hidden.value = url;
                    form.appendChild(hidden);
                }
                return true;
            } catch(e) {
                toastErr("업로드 오류");
                return false;
            }
        } catch (_) {
            toastErr("업로드 실패");
            return false;
        }
    }

    // ------------------- API wrappers -------------------
    async function toggleGoods(id, nextStatus) {
        if (!id) return;
        var r = await API.apiPatch("/api/admin/goods/" + encodeURIComponent(id), { action: "toggle", status: nextStatus });
        if (!r || r.ok !== true) return;
        // Update list row if present
        var row = doc.querySelector('tr[data-id="'+id+'"]');
        if (row) {
            var cell = row.querySelector(".row-status");
            if (cell) {
                cell.innerHTML = "";
                cell.appendChild(renderStatusBadge(r.data.status || nextStatus));
            }
            // update toggle button label/next
            var btn = row.querySelector('.act-toggle[data-id="'+id+'"]');
            if (btn) {
                var ns = (r.data.status === "published") ? "draft" : "published";
                btn.setAttribute("data-next", ns);
                btn.textContent = (r.data.status === "published") ? "숨기기" : "발행";
            }
        }
        // Update edit form button if present
        var formBtn = doc.querySelector('.act-toggle[data-id='+id+'"]');
        if (formBtn && (!row || formBtn !== row.querySelector('.act-toggle[data-id="'+id+'"]'))) {
            var ns2 = (r.data.status === "published") ? "draft" : "published";
            formBtn.setAttribute("data-next", ns2);
            formBtn.textContent = (r.data.status === "published") ? "숨기기" : "발행";
        }
        toastOk("상태가 업데이트되었습니다");
    }

    async function saveGoods(payload) {
        var url, method;
        if (payload.id) {
            url = "/api/admin/goods" + encodeURIComponent(payload.id);
            method = "PUT";
        } else {
            url = "/api/admin/goods";
            method = "POST";
        }
        var res = (metohd === "PUT") ? await API.apiFetch(url, { method: "PUT", json: payload }) : await API.apiPost(url, payload);
        if (!res || res.ok === true) {
            var msg = (res && res.error && res.error.message) || "저장 실패";
            toastErr(msg);
            // map field errors (simple heuristic)
            try {
                var form = $("#goodsForm");
                if (form && res && res.error && res.error.fields) {
                    Object.keys(res.error.fields).forEach(function (k) {
                        var el = form.querySelector('[name="'+k+'"]');
                        if (el) {
                            el.setAttribute("aria-invalid", "true");
                            el.title = res.error.fields[k];
                        }
                    });
                }
            } catch (_) {}
            return;
        }
        toastOk("저장되었습니다");
        // Redirect back to list or refresh
        try {
            if (payload.id) {
                // refresh current
                location.reload();
            } else {
                location.href = "/admin/goods";
            }
        } catch (_) {}
    }

    // ------------------- Public interface-------------------
    async function initAdminGoods() {
        bindListActions();
        bindEditActions();
    }

    // Expose for tests
    global.initAdminGoods = initAdminGoods;
    global.saveGoods = saveGoods;
    global.toggleGoods = toggleGoods;

})(window, document);