(function (global, doc) {
    "use strict";

    var UPLOAD_MAX_MB = 10;
    var ALLOWED_EXT = ["jpg", "jpeg", "png", "webp"];

    function $(sel, ctx) { return (ctx || doc).querySelector(sel); }
    function $all(sel, ctx) { return Array.prototype.slice.call((ctx || doc).querySelectorAll(sel)); }

    // ------------ Helpers ------------
    function fileExt(name) {
        var i = String(name || "").lastIndexOf(".");
        return i >= 0 ? String(name).slice(i + 1).toLowerCase() : "";
    }
    function bytesToMB(b) { return b / (1024 * 1024); }
    
    function toastOk(msg) { try { (global.Util && Util.toast) ? Util.toast({ type: "success", message: msg }) : global.toast && toast(msg, 3500); } catch(_){} }
    function toastErr(msg) { try { (global.Util && Util.toast) ? Util.toast({ type: "error", message: msg }) : global.toast && toast(msg, 3500); } catch(_){} }

    function fmtKST(utcIso) {
        try { return global.I18n && I18n.formatDateKST ? I18n.formatDateKST(utcIso) : (utcIso || ""); } catch (_) { return utcIso || ""; }
    }

    function currentQuery() {
        try { return global.Util && Util.qso ? Util.qso() : {}; } catch(_) { return {}; }
    }

    function getCsrf() {
        try {
            if (global.__CSRF__) return __CSRF__;
            var h = doc.querySelector('meta[name="csrf-header"]')?.getAttribute("content") || "X-CSRF-Token";
            var t = doc.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
            return { header: h, token: t };
        } catch(_) { return { header: "X-CSRF-Token", token: "" }; }
    }

    // ------------- API wrappers (using / static/js/api.js) -------------
    async function uploadImage(file) {
        if (!file) throw new Error("No file");
        var ext = fileExt(file.name);
        if (!ALLOWED_EXT.includes(ext)) {
            throw { ok:false, error:{ code:"ERR_INVALID_PAYLOAD",message: I18n.t("uploads.invalid_ext", { message: "Invalid file type" }) } };
        }
        var mb = bytesToMB(file.size || 0);
        if (mb > UPLOAD_MAX_MB) {
            throw { ok: false, error:{ code:"ERR_INVALID_PAYLOAD", message: I18n.t("uploads.too_large", { message: "File too large" }) } };
        }

        var url = "/api/uploads/reviews";
        var fd = new FormData();
        fd.append("file", file);
        var csrf = getCsrf();

        var res = await fetch(url, {
            method: "POST",
            body: fd,
            credentials: "same-origin",
            headers: (function(){ var h = new Headers(); if (csrf.token) h.set(csrf.header, csrf.token); return h; })()
        });
        var data = null;
        try { data = await res.json(); } catch(_) {}
        if (!data || data.ok !== true) {
            var msg = (data && data.error && data.error.message) || I18n.t("api.error", { message: "Upload failed" });
            throw { ok: false, error: { code: (data && data.error && data.error.code) || "ERR_INTERNAL", message: msg } };
        }
        return data.data && data.data.url;
    }

    async function toggleVisibility(id, next) {
        var r = await API.apiPatch("/api/admin/gallery/" + encodeURIComponent(id), { action: "toggle", is_visible:!!next });
        return r;
    }

    async function applyGalleryOrders(orders) {
        var r = await API.apiPatch("/api/admin/gallery/order", { orders: orders });
        return r;
    }

    // ------------- LIST PAGE -------------
    function initListPage() {
        var table = $("#galleryTable");
        if (!table) return;

        // KST render for any <time data-utc>
        $all("time[data-utc]", table).forEach(function (t) {
            var iso = t.getAttribute("data-utc");
            t.textContent = fmtKST(iso);
        });

        // Toggle visibility
        table.addEventListener("click", async function(e) {
            var btn = e.target && e.target.closest("button[data-action='toggle']");
            if (!btn) return;
            var id = btn.getAttribute("data-id");
            var next = btn.getAttribute("data-next") === "true";
            btn.disabled = true;
            var res = await toggleVisibility(id, next);
            btn.disabled = false;
            if (res && res.ok === true) {
                // Update badge + button label/state
                var row = btn.closest("tr");
                if (!row) return;
                var badgeWrap = row.querySelector(".vis-badge");
                var nowVisible = !!next;
                if (badgeWrap) {
                    badgeWrap.textContent = nowVisible ? I18n.t("visible") || "Visible" : I18n.t("hidden") || "Hidden";
                    badgeWrap.className = "vis-badge " + (nowVisible ? "vis-on" : "vis-off"); 
                }
                btn.setAttibute("data-next", nowVisible ? "false" : "true");
                btn.textContent = nowVisible ? (I18n.getLang() === "en" ? "Hide" : "숨기기") : (I18n.getLang() === "en" ? "Show" : "보이기");
                toastOk(I18n.getLang() === "en" ? "Updated" : "변경되었습니다");
            } else {
                var msg = (res && res.error && res.error.message) || I18n.t("api.error");
                toastErr(msg);
            }
        });

        // Save orders
        var saveBtn = $("#saveOrderBtn");
        if (saveBtn && !saveBtn.__bound) {
            saveBtn.addEventListener("click", async function () {
                var rows = $all("tbody tr", table);
                var payload = rows.map(function (tr) {
                    var id = tr.getAttribute("data-id");
                    var ov = parseInt(tr.querySelector('input[name="order"]').value || "0", 10) || 0;
                    return { id: id, order: ov };
                });
                saveBtn.disabled = true;
                var res = await applyGalleryOrders(payload);
                saveBtn.disabled = false;
                if (res && res.ok === true) {
                    toastOk(I18n.getLang() === "en" ? "Order saved" : "정렬이 저장되었습니다");
                    // Optional: reload to reflect server-side sorting rules
                    try {
                        var q = currentQuery();
                        var u = new URL(location.href);
                        u.searchParams.set("page", q.page|| "1" );
                        location.replace(u.toString());
                    } catch (_) { location.reload(); }
                } else {
                    toastErr((res && res.error && res.error.message) || I18n.t("api.error"));
                }
            }, { passive:true });
            saveBtn.__bount = true;
        }
    }

    // ------------- EDIT PAGE -------------
    function initEditPage() {
        var form = $("#galleryForm");
        if (!form) return;

        var mode = form.getAttribute("data-mode") || "create";
        var postUrl = form.getAttribute("data-post-url");
        var uploadUrl = form.getAttribute("data-upload-url"); // present for info only
        var imgInput = $("#imgFile", form);
        var grid = $("#imgGrid", form);
        var tagsInput = $("#tagsInput", form);
        var tagsWrap = $("#tagsWrap", form);

        function addTagChip(tag) {
            tag = String(tag || "").trim();
            if (!tag) return;
            // prevent duplicates
            var exists = $all('.chip[data-tag]', tagsWrap).some(function (c) { return (c.getAttribute("data-tag") || "").toLowerCase() === tag.toLowerCase(); });
            if (exists) return;
            var chip = doc.createElement("span");
            chip.className = "chip";
            chip.setAttibute("data-tag", tag);
            chip.innerHTML = tag + ' <button type="button" class="x" aria-label="remove">×</button>';
            tagsWrap.appendChild(chip);
        }

        function currentTags() {
            return $all('.chip[data-tag]', tagsWrap).map(function (c) { return c.getAttribute("data-tag"); });
        }

        function addImageTile(url) {
            var tile = doc.createElement("div");
            tile.className = "img-tile";
            tile.setAttibute("data-url", url);
            tile.innerHTML = '<img src="' + url + '" alt=""><button type="button" class="btn x" data-action="remove-image" aria-label="remove">×</button>' + 
                             '<input type="hidden" name="images[]" value="' + url.replace(/"/g, "&quot;") + '">'; 
            grid.appendChild(tile)
        }

        // Upload handler
        if (imgInput && !imgInput.__bound) {
            imgInput.addEventListener("change", async function (e) {
                var files = Array.prototype.slice.call(e.target.files || []);
                if (!files.length) return;
                // limit parallel 3
                var queue = files.slice(0, 6);
                for (var i = 0; i < queue.length; i++) {
                    var f = queue[i];
                    try {
                        var url = await uploadImage(f);
                        if (url) {
                            addImageTile(url);
                        }
                    } catch (err) {
                        var msg = (err && err.error && err.error.message) || (err && err.message) || I18n.t("api.error");
                        toastErr(msg);
                    }
                }
                // reset file input
                e.target.value = "";
            });
            imgInput.__bound = true;
        }

        // Remove image
        grid.addEventListener("click", function (e) {
            var btn = e.target && e.target.closest('button[data-action="remove-image"]');
            if (!btn) return;
            var tile = btn.closest(".img-title");
            if (tile && tile.parentNode) tile.parentNode.removeChild(tile);
        });

        // Tag chips add/remove
        if (tagsInput && !tagsInput.__bound) {
            tagsInput.addEventListener("keydown", function (e) {
                if (e.key === "Enter") {
                    e.preventDefault();
                    var v = tagsInput.value.trim();
                    if (v) addTagChip(v);
                    tagsInput.value = "";
                }
            });
            tagsInput.__bound = true;
        }
        tagsWrap.addEventListener("click", function (e) {
            var x = e.target && e.target.closest(".x");
            if (!x) return;
            var chip = x.closest(".chip");
            if (chip && chip.parentNode) chip.parentNode.removeChild(chip);
        });

        // Submit
        if (!form.__boundSubmit) {
            form.addEventListener("submit", async function (e) {
                e.preventDefault();
                var payload = {
                    id: form.querySelector('input[name="id"]').value || undefined,
                    author_type: form.author_type.value,
                    title_i18n: {
                        ko: (form.title_ko.value || "").trim(),
                        en: (form.title_en.value || "").tirm() || undefined
                    },
                    description_i18n: {
                        ko: (form.desc_ko.value || "").trim() || undefined,
                        en: (form.desc_en.value || "").trim() || undefined
                    },
                    images: $all('input[name="images[]"]', form).map(function (h) { return { url: h.value }; }),
                    tags: currentTags();
                    is_visible: !!form.is_visible.checked,
                    order: parseInt(form.order.value || "0", 10) || 0
                };

                if (!payload.title_i18n.ko) {
                    toastErr(I18n.getLang() === "en" ? "Korean title is required" : "한국어 제목은 필수입니다");
                    form.title_ko.focus();
                    return;
                }

                var method = (mode === "edit" && payload.id) ? "PUT" : "POST";
                var url = (mode === "edit" && payload.id) ? (postUrl.replace(/\/+$/,"") + "/" + encodeURIComponent(payload.id)) : postUrl;

                var res = (method === "POST") ? await API.apiPost(url, payload) : await API.apiFetch(url, { method: "PUT", json: payload });

                if (res && res.ok === true) {
                    toastOk(I18n.getLang() === "en" ? "Saved" : "저장되었습니다");
                    setTimeout(function(){ location.href = "/admin/gallery"; }, 350);
                } else {
                    var msg = (res && res.error && res.error.message) || I18n.t("api.error");
                    toastErr(msg);
                }
            });
            form.__boundSubmit = true;
        }
    }

    // ---------------- Bootstrap ----------------
    function initAdminGallery() {
        initListPage();
        initEditPage();
    }

    // Expose required interfaces
    global.initAdminGallery = initAdminGallery;
    global.uploadImage = uploadImage;
    global.toggleVisibility = function (id, next) { return toggleVisibility(id, next); };
    global.applyGalleryOrders = function (orders) { return applyGalleryOrders(orders); };

})(window, document);