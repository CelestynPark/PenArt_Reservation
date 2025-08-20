export async function api(url, opts = {}) {
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

window.api = api;