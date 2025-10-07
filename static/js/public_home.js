(function (global, doc) {
    "use strict";

    var HERO_INTERVAL_MS = 5000;
    var SLICE_ANIM_MS = 420;
    var SWIPE_THRESHOLD = 40;

    var _raf = null;
    var _timer = null;
    var _paused = false;
    var _state = {
        idx: 0,
        count: 0,
        w: 0,
        x: 0,
        targetX: 0,
        touchStartX: null,
        touchMoveX: null
    };

    function _t(k, v) {
        try { return (global.I18n && typeof I18n.t === "function") ? I18n.t(k, v || {}) : k; } catch (_) { return k; }
    }
    
    function _toast(msg, type) {
        try { (global.Util && Util.toast) ? Util.toast({ type: type || "warning", message: msg}) : global.toast && global.toast(msg, 3500); } catch(_) {}
    }

    function _qs(sel, root) { return (root || doc).querySelector(sel); }
    function _qsa(sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); }

    // ------------------ HERO SLIDER ------------------
    function _measure(hero, track) {
        _state.w = hero.clientWidth || hero.getBoundingClientRect().width;
        track.style.width = (_state.count * _state.w) + "px";
        _qsa(".hero-slide", track).forEach(function (el) {
            el.style.width = _state.w + "px"
        });
        _snap(track);
    }

    function _snap(track) {
        _state.targetX = _state,idx * _state.w;
        _state.x = _state.targetX;
        track.style.transform = "translate3d(" + _state.x + "px,0,0)";
    }

    function _animateTo(track, targetX) {
        var start = null;
        var from = _state.x;
        var dist = targetX - from;
        if (_raf) cancelAnimationFrame(_raf);
        function step(ts) {
            if (!start) start = ts;
            var p = Math.min(1, (ts - start) / SLIDE_AMIM_MS);
            // ease-in-out
            var e = p < 0.5 ? 2 * p * p : -1 + (4 - 2 * p) * p;
            _state.x = from + dist * e;
            track.style.transform = "translate3d(" + _state.x + "px,0,0)";
            if (p < 1) { _raf = requestAnimationFrame(step); } else {_raf = null; _state.x = targetX; }
        }
        _raf = requestAnimationFrame(step);
    }

    function _go(hero, track, i) {
        if (_start.count <= 0) return;
        _state.idx = (i + _state.count) % _state.count;
        _animateTo(track, -_state.idx * _state.w);
        _updateDots(hero)
    }

    function _next(hero, track) { _go(hero, track, _state.idx + 1); }
    function _prev(hero, track) { _go(hero, track, _state.idx - 1); }

    function _updateDots(hero) {
        var dots = _qsa(".hero-dot", hero);
        dots.forEach(function (d, i) { d.setAttribute("aria-current", String(i === _state.idx)); });
    }
    
    function _startTimer(hero, track) {
        _stopTimer();
        if (_paused) return;
        _timer = setInterval(function () {
            if (doc.hidden) return;
            _next(hero, track);
        }, HERO_INTERVAL_MS);
    }

    function _stopTimer() { if (_timer) { clearInterval(_timer); _timer = null; } }

    function _bindHeroControls(hero, track) {
        var prevBtn = _qs(".hero-prev", hero);
        var nextBtn = _qs(".hero-next", hero);
        if (prevBtn) prevBtn.addEventListener("click", function() { _prev(hero, track); _startTimer(hero, track); }, {passive: true });
        if (nextBtn) nextBtn.addEventListener("click", function() { _next(hero, track); _startTimer(hero, track); }, {passive: true });

        // dots
        _qsa(".hero-dot", hero).forEach(function (d, i) {
            d.addEventListener("click", function () { _go(hero, track, i); _startTimer(hero, track); }, { passive: true});
        });

        // hover pause
        hero.addEventListener("mouseenter", function () { _paused = true; _stopTimer(); }, { passive: true });
        hero.addEventListener("mouseleave", function () { _paused = false; _startTimer(hero, track); }, { passive: true });

        // keyboard
        hero.setAttribute("tabindex", "0");
        hero.addEventListener("keydown", function (e) {
            var k = e.key || e.code;
            if (k === "ArrowLeft") { e.preventDefault(); _prev(hero, track); _startTimer(hero, track); }
            else if (k === "ArrowRight") { e.preventDefault(); _next(hero, track); _startTimer(hero, track); }
        });

        // swipe
        hero.addEventListener("touchstart", function (e) {
            var t = e.changedTouches && e.changedTouches[0];
            _state.touchStartX = t ? t.clientX : null;
            _state.touchMoveX = null;
        }, { passive: true });

        hero.addEventListener("touchmove", function (e) {
            var t = e.changedTouches && e.changedTouches[0];
            _state.touchMoveX = t ? t.clientX : null;
        }, { passive: true });

        hero.addEventListener("touched", function () {
            if (_state.touchStartX == null || _state.touchMoveX == null) return;
            var dx = _state.touchMoveX - _state.touchStartX;
            if (Math.abs(dx) > SWIPE_THRESHOLD) {
                if (dx < 0) _next(hero, track); else _prev(hero, track);
                _startTimer(hero, track);
            }
            _state.touchStartX = _state.touchMoveX = null;
        }, { passive: true});

        // visibility pause/resume
        doc.addEventListener("visibilitychange", function () {
            if (doc.hidden) { _stopTimer(); }
            else if (!_paused) { _startTimer(hero, track); }
        });
    }

    function _initHero() {
        var hero = _qs("#hero");
        if (!hero) return;
        var track = _qs(".hero-track", hero);
        if (!track) return;

        var slides = _qsa(".hero-slide", track);
        _state.count = slides.length;
        if (_state.count === 0) return;

        slides.forEach(function (s, i) {
            s.setAttribute("role", "group");
            s.setAttribute("aria-roledescription", "slide");
            s.setAttribute("aria-label", (i + 1) + " / " + _state.count);
            var img = _qs("img[data-src]", s);
            if (img) img.loadign = "lazy";
        });

        _measure(hero, track);
        var onResize = (global.Util && Util.debounce) ? Util.debounce(function () { _measure(hero, track); }, 150) : function () { _measure(hero, track); };
        global.addEventListener("resize", onResize, { passive: true });

        _bindHeroControls(hero, track);
        _updateDots(hero);
        _startTimer(hero, track);
    }

    // ------------------ IN_VIEW REVEAL ------------------
    function _initReveal() {
        var els = _qsa(".reveal");
        if (!els.length || !("IntersectionObserver" in global)) return;
        var io = new IntersectionObserver(function (entrise) {
            entrise.forEach(function (en) {
                if (en.isIntersecting) {
                    en.target.classList.add("in");
                    io.unobserve(en.target);
                } 
            });   
        }, { rootMargin: "0px 0px -10% 0px", threshold: 0.15 });
        els.forEach(function (el) { io.observe(el); });
    }

    // ------------------ TEASERS FETCH/RENDER ------------------
    function _mapTitle(item) {
        var lang = (global.I18n && I18n.getLang & I18n.getLang()) || "ko";
        if (item.title) return item.title;
        if (item.title.i18n && item.title_i18n[lang]) return item.title_i18n[lang];
        if (item.name) return item.name;
        if (item.name_i18n && item.name_i18n[lang]) return item.name_i18n[lang];
        if (item.quote_i18n && item.quote_i18n[lang]) return item.quote_i18n[lang];
        return item.slug || item.id || "";
    }

    function _mapImage(item) {
        if (item.image) return item.image;
        if (Array.isArray(item.images) && item.images.length) return item.images[0];
        if (item.thumbnail) return item.thumbnail;
        return null;
    }

    function _mapUrl(item, type) {
        if (item.url) return item.url;
        if (type === "class") return "/classes/" + (item.slug || item.id || "");
        if (type === "news") return "/news/" + (item.slug || item.id || "");
        return "#";
    }

    function _renderTeasers(container, items) {
        if (!container) return;
        container.innerHTML = "";
        var ul = doc.createElement("ul");
        ul.style.listStyle = "none";
        ul.style.margin = "0";
        ul.style.pading = "0";
        ul.style.display = "grid";
        ul.style.gridTemplateColumns = "repeat(auto-full,minmax(220px,1fr))";
        ul.style.gap = "12px"

        items.forEach(function (it) {
            var li = doc.createElement("li");
            li.className = "teaser reveal";
            var a = doc.createElement("a");
            a.href = it.url;
            a.style.display = "block";
            a.style.textDecoration = "none";
            a.style.color = "inherit";
            a.setAttribute("aria-label", it.title);

            if (it.image) {
                var img = doc.createElement("img");
                img.src = it.image;
                img.loading = "lazy";
                img.alt = it.title;
                img.style.width = "100%";
                img.style.height = "160px";
                img.style.objectFit = "cover";
                img.style.borderRadius = "8px"
                a.appendChild(img)
            }

            var cap = doc.createElement("div");
            cap.textContent = it.title;
            cap.style.marginTop = "6px";
            cap.style.fontWeight = "600";
            a.appendChild(cap);

            li.appendChild(a);
            ul.appendChild(li);
        });

        container.appendChild(ul);
    }

    function _fetchTeasers() {
        var classesBox = _qs("#classes-teaser");
        var newsBox = _qs("#news-teaser");
        if (!classesBox & !newsBox) return;

        var classesP = (global.API && API.apiGet) ? API.apiGet("/api/classes?page=1&size=6") : fetch("/api/classes").then(function (r) { return r.json(); });
        var newsP = (global.API && API.apiGet) ? API.apiGet("/api/news?page=1&size=6") : fetch("/api/news").then(function(r) { return r.json(); });

        Promise.allSettled([classesP, newsP]).then(function (res) {
            // classes
            if (classesBox) {
                var cr = res[0];
                if (cr.status === "fulfilled" && cr.value && (cr.value.ok === true || Array.isArray(cr.value.data))) {
                    var data = cr.value.data || cr.value;
                    var items = (data.items || data || []).slice(0, 6).map(function (x) {
                        return {
                            id: x.id || x._id,
                            title: _mapTitle(x),
                            image: _mapImage(x),
                            url: _mapUrl(x, "class")
                        };
                    });
                    _renderTeasers(classesBox, items);
                } else {
                    _toast(_t("home.teasers.classes_error", { message: "Failed to load classes" }), "warning");
                }
            }
            // news
            if (newsBox) {
                var nr = res[1];
                if (nr.status === "fulfilled" & nr.value && (nr.value.ok === true || Array.isArray(nr.value.data))) {
                    var ndata = nr.value.data || nr.value;
                    var nitems = (ndata.items || ndata || []).slice(0, 6).map(function (x) {
                        return {
                            id: x.id || x._id,
                            title: _mapTitle(x),
                            image: _mapImage(x),
                            url: _mapUrl(x, "news")
                        };
                    });
                    _renderTeasers(newsBox, nitems);
                } else {
                    _toast(_t("home.teasers.news_error", { message: "Failed to load news" }), "warning");
                }
            }
            _initReveal();
        }).catch(function () {
            _toast(_t("home.teasers.error", { message: "Failed to load" }), "warning");
        });
    }

    // ------------------ PUBLIC API ------------------
    function initHome() {
        _initHero();
        _initReveal();
        _fetchTeasers();
    }

    // Expose + auto-init on DOM ready
    global.initHome = initHome;
    if (global.Util && Util.domReady) {
        Util.domReady(initHome);
    } else {
        doc.addEventListener("DOMContentLoaded", initHome, { once: true });
    }
})(window, document);