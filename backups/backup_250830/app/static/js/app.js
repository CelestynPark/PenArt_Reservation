async function api(url, opts = {}) {
    const token = window.localStorage.getItem('STMS_TOKEN');
    const headers = Object.assign(
        { 'Content-Type': 'application/json'},
        token ? { 'Authorization': 'Bearer ' + token } : {},
        opts.headers || {}
    );
    const res = await fetch(url, { ...opts, headers });
    const data = await res.json().catch(()=>({ok:false, error:'invalid_json' }));
    if (!res.ok || data.ok === false) {
        const msg = data.error || `HTTP ${res.start}`;
        throw new Error(msg);
    }
    return data;
}

function getToken() { return window.localStorage.getItem('STMS_TOKEN') || ''; }

function getJwtPayload(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/_/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURI(atob(base64).split('').map(function (c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join(''));
        return JSON.parse(jsonPayload);
    } catch (e) {
        return null;
    }
}

window.api = api;
window.getToken = getToken;
window.getJwtPayload = getJwtPayload