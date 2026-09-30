// The "Open on another device" window: the address and QR code other devices open

async function info() {
  try {
    const r = await fetch('/api/phone', { cache: 'no-store' });
    return r.ok ? await r.json() : { here: false };
  } catch (err) { return { here: false }; }
}

export async function phoneButton(button) {
  if (!(await info()).here) return;
  button.style.display = '';
  button.addEventListener('click', () => showPhone());
}

const CSS = `
#phone-win .dim { color: var(--dim); font-size: 12.5px; }
#phone-win .qr { width: 220px; height: 220px; margin: 4px auto 12px; display: block; border-radius: var(--radius); overflow: hidden; }
#phone-win .qr svg { width: 100%; height: 100%; display: block; }
#phone-win code { font: 12.5px ui-monospace, Menlo, monospace; background: var(--field); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 6px 8px; display: block; word-break: break-all; user-select: all; margin: 0 0 10px; }
#phone-win b.code { letter-spacing: .12em; }
#phone-win .bad { color: var(--bad); }`;

export async function showPhone({ title = 'Open on another device', extra = null } = {}) {
  const first = await info();
  if (!document.getElementById('phone-css')) {
    const st = document.createElement('style');
    st.id = 'phone-css';
    st.textContent = CSS;
    document.head.appendChild(st);
  }
  document.getElementById('phone-win')?.remove();
  const bg = document.createElement('div');
  bg.id = 'phone-win';
  bg.className = 'dialog-bg';
  const win = document.createElement('div');
  win.className = 'dialog';
  bg.appendChild(win);
  document.body.appendChild(bg);
  const close = () => { bg.remove(); document.removeEventListener('keydown', onKey, true); };
  const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  document.addEventListener('keydown', onKey, true);
  bg.addEventListener('click', (e) => { if (e.target === bg) close(); });

  const add = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    win.appendChild(e);
    return e;
  };
  const buttons = (...list) => {
    const bar = add('div', 'bar');
    for (const [label, fn, primary] of list) {
      const b = document.createElement('button');
      b.textContent = label;
      if (primary) b.className = 'primary';
      b.addEventListener('click', () => fn(b));
      bar.appendChild(b);
    }
  };
  const turn = async (on, button) => {
    button.disabled = true;
    button.textContent = on ? 'Turning on…' : 'Turning off…';
    try {
      await fetch('/api/phone', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ on }) });
    } catch (err) {}
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 300));
      const now = await info();
      if (now.here && now.on === on) return render(now);
    }
    render(await info(), `Couldn't turn it ${on ? 'on' : 'off'}.`);
  };

  const askNewCode = () => {
    win.innerHTML = '';
    add('h3', '', 'Generate new access code?');
    add('p', '', 'The previous code will expire immediately. Any connected devices will need to scan or enter the new code. '
      + 'This computer is not affected.');
    buttons(['Cancel', async () => render(await info())], ['Generate new code', (b) => newCode(b), true]);
  };
  const newCode = async (button) => {
    button.disabled = true;
    const old = (await info()).code;
    try {
      await fetch('/api/phone', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ newCode: true }) });
    } catch (err) {}
    const now = await info();
    render(now, now.code === old ? "Couldn't generate a new code." : null);
  };

  const render = (p, problem) => {
    win.innerHTML = '';
    add('h3', '', title);
    if (problem) add('p', 'bad', problem);
    if (!p.on) {
      add('p', '', 'Edit on a phone, a tablet or another computer on the same network as this one. Once this '
        + 'is on, they can join whenever the editor runs.');
      if (p.system === 'win32') add('p', 'dim', 'Windows may ask whether to allow the editor on networks: allow it.');
      if (p.system === 'darwin') add('p', 'dim', 'If macOS asks whether to accept incoming network connections, choose Allow.');
      buttons(['Cancel', close], ['Turn on', (b) => turn(true, b), true]);
      return;
    }
    if (!p.address) {
      add('p', '', "This computer isn't connected to a network. Connect it to the same Wi-Fi as the other device.");
    } else {
      const qr = add('div', 'qr');
      qr.innerHTML = p.qr;
      add('p', '', "Scan it with a phone's camera, or open this address on the device:");
      add('code', '', p.url);
      const other = add('p', 'dim');
      other.append(`Or open ${p.address} and enter the code `);
      other.appendChild(Object.assign(document.createElement('b'), { className: 'code', textContent: p.code }));
      other.append('.');
    }
    add('p', 'dim', 'Keep the editor open on this computer too: other devices alone don\'t keep it running.');
    if (p.blocked) add('p', 'bad', `macOS's firewall stopped a device from connecting. Allow ${p.blocked} in `
      + 'System Settings › Network › Firewall › Options.');
    else add('p', 'dim', "Cannot connect? Ensure both devices are on the same Wi-Fi network and the firewall allows the editor.");
    buttons(['New code…', askNewCode], ['Turn off', (b) => turn(false, b)],
      ...(extra ? [[extra[0], () => { close(); extra[1](); }]] : []), ['Close', close, true]);
  };
  render(first);
}
