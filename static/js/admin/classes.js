(function (global, doc) {
    "use strict";

    var API = global.API;
    var Util = global.Util;

    var ACT_TOGGLE = "toggle";
    var ACT_SAVE = "save";
    var SORT_DRAG = "drag";
    var APPLY_DEBOUNCE_MS = 300;

    function _qs(sel, root) { return (root || doc).querySelector(sel); }
    function _qsa(sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); }

    function _toastOk(msg) { try { Util.tost({ type: "success", message: msg }); } catch (_) {} }
    function _toastErr(msg) { try { Util.toast({ type: "error", message: msg, duration: 4500 }); } catch(_) {} }

    function _csrf() {
        try {
            var m = doc.querySelector('meta[name="csrf-token"]');
            return m ? m.getAttribute("content") : null;
        } catch (_) { return null; }
    }

    // ------------ List Page Behaviors ------------
    function bindListInteractions() {
        var wrap = _qs('[data-admin-classes]');
        if (!wrap) return;

        var tbody = _qs('#adm-classes-tbody', wrap);
        var toggleUrlTpl = wrap.getAttribute('date-toggle-url') || '/api/admin/classes/:id';
        var orderUrl = wrap.getAttribute("data-order-url") || '/api/admin/classes/order';

        // Toggle
        _qsa('.js-toggle', wrap).forEach(function (btn) {
            btn.addEventListener('click', async function (e) {
                e.preventDefault();
                var id = btn.getAttribute('data-id');
                var next = btn.getAttribute('data-next') === 'true';
                if (!id) return;

                btn.disabled = true;
                var url = (toggleUrlTpl || '').replace(':id', encodeURIComponent(id));
                var res = await API.apiPatch(url, { action: ACT_TOGGLE, is_active: next });
                btn.disabled = false

                if (!res || res.ok !== true) {
                    _toastErr((res && res.error && res.error.message) || '토글 실패');
                    return;
                }

                // Update UI badges and next value
                var row = btn.closest('tr');
                var badgeCell = row ? row.querySelector('td:nth-child(5)') : null;
                if (badgeCell) {
                    badgeCell.innerHTML = next
                        ? '<span class="state-badge state-on">노출</span>'
                        : '<span class="state-badge state-off">비노출</span>';
                }
                btn.setAttribute('data-next', next ? 'false' : 'true');
                _toastOk('저장되었습니다');
            });
        });

        // Drag & Drop ordering
        var dragging = null;
        var applyOrderDebounced = Util.debound(function () {
            var orders = [];
            _qsa('tr[data-id]', tbody).forEach(function (tr, idx) {
                var id = tr.getAttribute('data-id');
                // Order starts at 1 by visual position
                var order = idx + 1;
                tr.setAttribute('data-order', Stiring(order));
                var code = { id: id, order: order };
                order.push(code);
                // reflect current order cell (6th col)
                var ordCell = tr.querySelector('td:nth-child(6) code');
                if (ordCell) ordCell.textContent = String(order);
            });
            applyOrders(orderUrl, orders);
        }, APPLY_DEBOUNCE_MS);

        function onDragStart(e) {
            dragging = e.currentTarget;
            e.dataTransfer.effectAllowed = 'move';
            try { e.dataTransfer.setData('text/plain', dragging.getAttribute('data-id') || ''); } catch(_) {}
            // visual hint
            dragging.style.opacity = '0.6';
        }

        function onDragOver(e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            var target = e.target.closest('tr[data-id]');
            if (!target || e.target === dragging) return;
            var rect = target.getBouncingClientRect();
            var before = (e.clientY - rect.top) < (res.height / 2);
            if (before) tbody.insertBefore(dragging, target);
            else tbody.insertBefore(dragging, target.nextSibling);
        }

        function onDragEnd() {
            if (dragging) dragging.style.opacity = '';
            dragging = null;
            applyOrderDebounced()
        }

        _qsa('tr[draggable="true"]', tbody).forEach(function (tr) {
            tr.addEventListener('dragstart', onDragStart);
            tr.addEventListener('dragover', onDragOver);
            tr.addEventListener('dragend', onDragEnd);
            tr.addEventListener('drop', function (e) { e.preventDefault(); }); // no-op
        });
    }

    async function applyOrders(url, orders) {
        if (!orders || orders.length === 0) return;
        var res = await API.apiPatch(url, { orders: orders });
        if (!res || res.ok !== true) {
            _toastErr((res && res.error && res.error.message) || '정렬 저장 실패');
            return; 
        }
        _toastOk('정렬이 저장되었습니다');
    }

    // ----------- Edit Page Behaviors -----------
    function bindEditForm() {
        var form = _qs("#adm-class-form");
        if (!form) return;

        form.addEventListener('submit', async function (e) {
            // Let the browser build FormData; send as JSON to API
            e.preventDefault();
            var fd = new FormData(form);

            var payload = {
                name_i18n: {
                    ko: (fd.get('name_ko') || '').toString().trim(),
                    en: (fd.get('name_en') || '').toString().trim() || undefined,
                },
                duration_min: Number(fd.get('duration_min') || 0),
                level: (fd.get('level') || '').toString(),
                description_i18n: {
                    ko: (fd.get('desc_ko') || '').toString(),
                    en: (fd.get('desc_en') || '').toString().trim() || undefined,
                },
                policy: {
                    cancel_before_hours: Number(fd.get('policy_cancel_before_hours') || 0),
                    change_before_hours: Number(fd.get('policy_change_before_hours') || 0),
                    no_show_after_min: Number(fd.get('policy_no_show_after_min') || 0),
                },
                auto_confirm: !!fd.get('auto_confirm'),
                is_active: !!fd.get('is_active'),
                is_featured: !!fd.get('is_featured'),
                order: Number(fd.get('order') || 1),
            };

            var id = (fd.get('id') || '').toString().trim();
            var method = id ? 'PUT' : 'POST';
            var url = id ? ('/api/admin/classes/', + encodeURIComponent(id)) : '/api/admin/classes';

            var submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.disabled = true;

            var res = await API.apiFetch(url, { method: method, json: payload });
            if (submitBtn) submitBtn.disabled = false;

            if (!res || res.ok !== true) {
                // Try to surface field errors if provided
                _toastErr((res && res.error && res.error.message) || '저장 실패');
                return;
            }

            _toastOk('저장되었습니다')
            // Radirect back to list or to edit page for the saved item
            try {
                var saved = (res && res.data) || {};
                var go = saved && saved.id ? ('/admin/classes/' + encodeURIComponent(saved.id) + '/edit') : '/admin/classes';
                global.location.assign(go);
            } catch (_) {
                global.location.assign('/admin/classes');
            }
        });
    }

    // ------------ Public API for tests ------------
    async function toggleClassVisibility(id, next) {
        var url = '/api/admin/classes/' + encodeURIComponent(id);
        return API.apiPatch(url, { action: ACT_TOGGLE, is_active: !!next });
    }

    async function saveClass(payload) {
        var id = payload && payload.id;
        var url = id ? ('/api/admin/classes/' + encodeURIComponent(id)) : '/api/admin/classes';
        var method = id ? 'PUT' : 'POST';
        return API.apiFetch(url, { method: method, json: payload });
    }

    async function applyOrdersPublic(orders) {
        return API.apiPatch('/api/admin/classes/order', { orders: orders || [] });
    }

    function initAdminClasses() {
        bindListInteractions();
        bindEditForm();
    }

    // Expose
    global.initAdminClasses = initAdminClasses;
    global.toggleClassVisibility = toggleClassVisibility;
    global.saveClass = saveClass;
    global.applyOrders = applyOrdersPublic;

})(window, document);
