// Heartbeat that lets the editor stop by itself once its last page on the host closes
const id = (() => {
  const make = () => Math.random().toString(36).slice(2) + Date.now().toString(36);
  try {
    const v = sessionStorage.getItem('ce-page') || make();
    sessionStorage.setItem('ce-page', v);
    return v;
  } catch (err) { return make(); }
})();

function send(closing = false) {
  const body = JSON.stringify({ id, closing });
  if (closing && navigator.sendBeacon) {
    navigator.sendBeacon('/api/alive', body);
    return Promise.resolve();
  }
  return fetch('/api/alive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
    .then((r) => {
      if (r.status === 403) { location.reload(); return {}; }
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
}

// A page shown again may not reach the editor at once while the network wakes up
const WAKING = 10000;
let resumed = 0;

const NOTE_CSS = 'position:fixed;top:8px;left:50%;transform:translateX(-50%);z-index:90;max-width:min(520px,92vw);'
  + 'background:var(--panel,#2b2d31);color:var(--text,#e4e4e7);border:1px solid var(--line,#3b3d43);'
  + 'border-left:3px solid var(--warn,#e0b35a);border-radius:4px;padding:8px 12px;font:14px/1.4 system-ui,sans-serif;'
  + 'box-shadow:0 10px 30px rgba(0,0,0,.45)';
let reconnecting = null;
function showReconnecting(on) {
  if (on && !reconnecting) {
    reconnecting = document.createElement('div');
    reconnecting.style.cssText = NOTE_CSS;
    reconnecting.textContent = 'Reconnecting to the editor…';
    document.body.appendChild(reconnecting);
  } else if (!on && reconnecting) {
    reconnecting.remove();
    reconnecting = null;
  }
}

let warning = null;
function showWarning() {
  const s = Math.max(0, Math.round((warning.end - Date.now()) / 1000));
  warning.el.textContent = s ? `Shutting down in ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}: `
    + "the editor was closed on the host computer. Reopen it there to stay connected." : 'The editor is shutting down…';
}
function warn(stopsIn) {
  if (stopsIn == null) {
    if (warning) { clearInterval(warning.timer); warning.el.remove(); warning = null; }
    return;
  }
  if (!warning) {
    const el = document.createElement('div');
    el.style.cssText = NOTE_CSS;
    document.body.appendChild(el);
    warning = { el, end: 0, timer: setInterval(showWarning, 1000) };
  }
  warning.end = Date.now() + stopsIn * 1000;
  showWarning();
}

export function keepAlive(onLost) {
  let failures = 0, lost = false, soon = null;
  const beat = () => send().then((reply) => {
    failures = 0;
    showReconnecting(false);
    warn(reply && reply.stopsIn);
    clearTimeout(soon);
    if (reply && reply.stopsIn != null) soon = setTimeout(beat, 10000);
  }).catch(() => {
    if (lost) return;
    failures += 1;
    const waking = Date.now() - resumed < WAKING;
    if (failures >= 2 && !waking) {
      lost = true;
      showReconnecting(false);
      onLost();
      return;
    }
    if (waking && failures >= 2) showReconnecting(true);
    setTimeout(beat, 3000);
  });
  const wake = () => { resumed = Date.now(); beat(); };
  beat();
  setInterval(beat, 30000);
  // Timers stop while a phone sleeps with the page on screen: a long gap is a wake-up too
  let tick = Date.now();
  setInterval(() => { const now = Date.now(); if (now - tick > 20000) wake(); tick = now; }, 5000);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') wake(); });
  window.addEventListener('pagehide', () => send(true));
  window.addEventListener('pageshow', (e) => { if (e.persisted) wake(); });    // back from the browser's page cache
  return { check: beat };
}

export function showStopped(extra = '') {
  if (document.getElementById('stopped')) return;
  warn(null);
  const d = document.createElement('div');
  d.id = 'stopped';
  d.style.cssText = 'position:fixed;inset:0;z-index:100;background:rgba(20,21,24,.94);color:var(--text,#e4e4e7);'
    + 'display:flex;align-items:center;justify-content:center;padding:24px;font:15px/1.5 system-ui,sans-serif';
  d.innerHTML = '<div style="max-width:440px"><div style="font-size:18px;font-weight:600;margin:0 0 10px">Can\'t reach the editor</div>'
    + '<p style="margin:0 0 10px">It was closed on the host computer, or this device lost its connection to it. '
    + 'This page reconnects by itself once the editor runs and can be reached.</p>'
    + '<p style="margin:0;color:var(--dim,#9ea1a8)"></p></div>';
  d.querySelector('p:last-child').textContent = extra;
  document.body.appendChild(d);
  const retry = setInterval(async () => {
    try {
      const r = await fetch('/api/ping', { cache: 'no-store' });
      if (r.ok) { clearInterval(retry); location.reload(); }
    } catch (err) {}
  }, 3000);
}
