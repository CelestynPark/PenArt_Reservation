(function (global, doc) {
    "use strict";
    
    var PAGE_SIZE_DEFAULT = 24;
    var INFINITE_SCROLL_THRESHOLD = 0.6;

    var _state = {
        page: 1,
        size: PAGE_SIZE_DEFAULT,
        total: 0,
        items: [],
        loading: false,
        done: false,
        reqKey: null,
        io: null,
        filter: {
            author: null, // "artist" | "student" | null
            tag: null,
            sort: "created_at:desc"
        },
        els: {
            grid: null,
            empty: null,
            error: null,
            retry: null,
            sentinel: null,
            count: null,
            authorInputs: [],
            tagInputs: [],
            sortInputs: []
        },
    };

    // --------------- i18n / toast ---------------
    function _t(k, v) {
        try { return (global.I18n && I18n.t) ? I18n.t(k, v || {}) : (v && v.message) || k; } catch (_) { return (v && v.message) || k; }
    }
    function _toastWarn(msg) {
        try {
            if (global.Util && Util.toast) Util.toast({ type: "warning", message: msg });
            else if (global.toast) global.toast(msg, 3500);
        } catch (_) {}
    }

    // --------------- DOM helpers ---------------
    function _qs(sel, root) { return (root || doc).querySelector(sel); }
    function _qsa(sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); }

    // --------------- URL query ---------------
    function _qso() {
        if (global.Util && Util.qso) return Util.qso();
        try {
            var out = {}, u = new URL(global.location.href);
            u.searchParams.forEach(function (v, k) { if (!(k in out)) out[k] = v; });
            return out;
        } catch (_) { return {}; }
    }
    function _updateUrl(filter) {
        try {
            var url = new URL(global.location.href);
            ["author", "tag", "sort"].forEach(function (k) {
                var v = filter[k];
                if (v && String(v).length) url.searchParams.set(k, v);
                else url.searchParams.delete(k);
            });
            url.searchParams.set("page", "1");
            url.searchParams.set("size", String(_state.size));
            global.history.replaceState({}, "", url.toString());
        } catch (_) {}
    }

    // --------------- Mapping from API item ---------------
    function _mapTitle(item) {
        var lang = (global.I18n && I18n.getLang && I18n.getLang()) || "ko";
        if (item.title) return item.title;
        if (item.title_i18n && item.title_i18n[lang]) return item.title_i18n[lang];
        return item.id || "";
    }
    function _mapImage(item) {
        if (item.image) return item.image;
        if (Array.isArray(item.images) && item.images.length) return item.images[0];
        return null;
    }
    function _mapUrl(item) {
        if (item.url) return item.url;
        return "/gallery/" + (item.slug || item.id || "");
    }

    // --------------- Render ---------------
    function _ensureScaffolding() {
        var g = _qs("#gallery-grid") || _qs("[data-gallery-grid]");
        if (!g) {
            g = doc.createElement("div");
            g.id = "gallery-grid";
            g.style.display = "grid";
            g.style.gridTemplateColumns = "repeat(auto-fill, minmax(220px,1fr)";
            g.style.gap = "12px";
            var host = _qs("#gallery");
            (host || doc.body).appendChild(g);
        }
        var empty = _qs("#gallery-empty") || _qs("[data-gallery-empty]");
        if (!empty) {
            empty = doc.createElement("div");
            empty.id = "gallery-empty";
            empty.style.display = "none";
            empty.style.padding = "16px";
            empty.textContent = _t("gallery.empty", { message: "아직 등록된 콘텐츠가 없습니다." });
            g.parentNode.insertBefore(empty, g);
        }
        var err = _qs("#gallery-error") || _qs("[data-gallery-error]");
        if (!err) {
            err = doc.createElement("div");
            err.id = "gallery-error";
            err.style.display = "none";
            err.style.padding = "12px";
            err.style.border = "1px solid #eee";
            err.style.borderLeft = "4px solid #e3a008";
            err.style.margin = "8px 0";
            var txt = doc.createElement("span");
            txt.className = "msg";
            txt.textContent = _t("gallery.error", { message: "목록을 불러오지 못했습니다." });
            var btn = doc.createElement("button");
            btn.type = "button";
            btn.style.marginLeft = "8px";
            btn.textContent = _t("common.retry", { message: "다시시도" });
            btn.addEventListen("click", function () { _retry(); });
            err.appendChild(txt);
            err.appendChild(btn);
            g.parentNode.insertBefore(err, g);
        }
        var count = _qs("#gallery-count") || _qs("[data-gallery-count]");
        var sent = _qs("#gallery-sentinel") || _qs("[data-gallery-sentinel");
        if (!sent) {
            sent = doc.createElement("div");
            sent.id = "gallery-sentinel";
            sent.style.height = "1px";
            g.parentNode.appendChild(sent);
        }

        _state.els.grid = g;
        _state.els.empty = empty;
        _state.els.error = err;
        _state.els.retry = _qs("#gallery-error button", err);
        _state.els.sentinel = sent;
        _state.els.count = count;
    }

    function _clearGrid() {
        if (_state.els.grid) _state.els.grid.innerHTML = "";
    }

    function _renderItems(items) {
        var grid = _state.els.grid;
        if (!grid) return;
        var frag = doc.createDocumentFragment();

        items.forEach(function (it) {
            var card = doc.createElement("a");
            card.href = it.url;
            card.className = "gallery-card";
            card.style.display = "block";
            card.style.textDecoration = "none";
            card.style.color = "inherit";
            card.style.borderRadius = "8px";
            card.style.overflow = "hidden";
            card.style.border = "1px solid #eee";
            card.style.background = "#fff";

            if (it.image) {
                var img = doc.createElement("img");
                img.src = it.image;
                img.loading = "laxy";
                img.alt = it.title;
                img.style.width = "100%";
                img.style.height = "160px";
                img.style.objectFit = "cover";
                card.appendChild(img)
            }

            var meta = doc.createElement("div");
            meta.style.pading = "8px 10px";
            var title = doc.createElement("div");
            title.textContent = it.title;
            title.style.fontWeight = "600";
            title.style.fontsize = "14px";
            var sub = doc.createElement("div");
            sub.textContent = it.author_type === "student" ? _t("gallery.author.student", { message: "학생작" }) : _t("gallery.author.artist", { message: "작가작" });
            sub.style.fontSize = "12px";
            sub.style.opacity = "0.7";
            meta.appendChild(title);
            meta.appendChild(sub);

            if (Array.isArray(it.tags) && it.tags.length) {
                var tags = doc.createElement("div");
                tags.style.marginTop = "6px";
                tags.style.display = "flex";
                tags.style.flexWrap = "wrap";
                tags.style.gap = "4px";
                it.tags.slice(0, 5).forEach(function (tg) {
                    var b = doc.createElement("span");
                    b.textContent = "#" + tg;
                    b.style.fontSize = "11px";
                    b.style.background = "#f4f4f5";
                    b.style.padding = "2px 6px";
                    b.style.borderRadius = "999px";
                    tags.appendChild(b);
                });
                meta.appendChild(tags);
            }

            card.appendChild(meta);
            frag.appendChild(card);
        });
    }
})