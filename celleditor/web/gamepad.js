// Game controllers: the Gamepad API's standard mapping (button names here are Xbox's)

const A = 0, B = 1, X = 2, Y = 3, LB = 4, RB = 5, LT = 6, RT = 7, BACK = 8, START = 9, R3 = 11;
const UP = 12, DOWN = 13, LEFT = 14, RIGHT = 15, HOME = 16;
const TRIGGER = 0.5;
const LOOK_SPEED = 2.6;                 // radians a second at full tilt
const REPEAT_DELAY = 350, REPEAT_EVERY = 125;
const AIM_EVERY = 100;

const CSS = `
#pad-hints { position: fixed; right: 12px; top: 52px; z-index: 15; display: none; background: var(--float);
             border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; box-shadow: var(--shadow);
             max-width: 300px; box-sizing: border-box; font-size: 12px; pointer-events: none; }
body.pad #pad-hints { display: block; }
body.pad #pad-hints.off { display: none; }
#pad-hints .ph-title { font-weight: 600; margin-bottom: 6px; }
#pad-hints .ph-title span { font-weight: 400; color: var(--dim); }
#pad-hints dl { display: grid; grid-template-columns: auto 1fr; gap: 5px 10px; margin: 0; align-items: center; }
#pad-hints dt { display: flex; gap: 3px; white-space: nowrap; }
#pad-hints dd { margin: 0; color: var(--dim); }
.pb { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 18px; padding: 0 4px;
      box-sizing: border-box; border-radius: 9px; font: 600 10.5px/1 system-ui, sans-serif; color: #fff;
      background: #4a4d55; border: 1px solid rgba(255, 255, 255, .15); }
.pb.a { background: #3f8f3f; } .pb.b { background: #b84040; } .pb.x { background: #3a6fc0; } .pb.y { background: #b8902a; }
.pb.sh { border-radius: 4px; }
#pad-aim { position: fixed; left: 50%; top: calc(50% + 12px); transform: translateX(-50%); z-index: 1; display: none;
           pointer-events: none; font-size: 12px; color: #fff; text-shadow: 0 1px 2px #000, 0 0 4px #000; white-space: nowrap; }
body.pad #pad-aim.on { display: block; }
body.docked:not(.touch):not(.panel-hidden) #pad-aim { left: calc(50% + var(--pw) / 2); }
#ctxmenu .mi.pad-focus { background: var(--accent-soft); }
#pad-menu { position: fixed; left: 50%; top: 50%; transform: translate(-50%, -50%); z-index: 20; display: none;
            min-width: 280px; max-height: 80vh; overflow-y: auto; background: var(--panel); border: 1px solid var(--line);
            border-radius: 6px; padding: 4px; box-shadow: var(--shadow); }
body.docked:not(.touch):not(.panel-hidden) #pad-menu { left: calc(50% + var(--pw) / 2); }
#pad-menu.open { display: block; }
#pad-menu .pm-title { padding: 6px 12px 4px; color: var(--dim); font-size: 11.5px; }
#pad-menu .pm-row { display: flex; justify-content: space-between; gap: 18px; padding: 6px 12px; border-radius: 3px;
                    cursor: pointer; white-space: nowrap; }
#pad-menu .pm-row.on { background: var(--accent-soft); }
#pad-menu .pm-row .v { color: var(--dim); }
#pad-menu .sep { height: 1px; background: var(--line); margin: 4px 6px; }
.pb.pad-key { display: none; vertical-align: middle; flex: none; }
body.pad .pb.pad-key { display: inline-flex; }`;

const ZERO = { x: 0, y: 0, z: 0, fast: 1 };
let api = null, connected = false, warned = false, active = false;
let prev = [], held = new Map(), aimAt = 0, lastView = '', lastAim = null, hintKey = '';
let menu = null, ctx = { first: null, at: 0 }, regrab = false;
const DIR = { [UP]: 'up', [DOWN]: 'down', [LEFT]: 'left', [RIGHT]: 'right' };
const settings = { look: 1, invert: false, deadzone: 0.2, swap: false, hidePanel: true };
try { Object.assign(settings, JSON.parse(localStorage.getItem('ce-pad') || '{}')); } catch (err) { /* private mode */ }
const saveSettings = () => { try { localStorage.setItem('ce-pad', JSON.stringify(settings)); } catch (err) { /* private mode */ } };

export function setupGamepad(a) {
  api = a;
  api.state.pad = { ...ZERO };
  const st = document.createElement('style');
  st.textContent = CSS;
  document.head.appendChild(st);
  for (const id of ['pad-hints', 'pad-aim', 'pad-menu']) {
    const el = document.createElement('div');
    el.id = id;
    document.body.appendChild(el);
  }
  pickerKeys();
  addEventListener('gamepadconnected', () => { connected = true; });
  addEventListener('gamepaddisconnected', () => { connected = [...navigator.getGamepads()].some(Boolean); });
  const off = () => { if (active) setActive(false); };
  addEventListener('mousemove', (e) => { if (Math.abs(e.movementX) + Math.abs(e.movementY) > 2) off(); });
  for (const ev of ['mousedown', 'keydown', 'wheel', 'touchstart']) addEventListener(ev, off, { passive: true });
  addEventListener('pointerdown', (e) => { if (menu && !e.target.closest('#pad-menu')) closeMenu(); }, true);
  addEventListener('keydown', (e) => { if (menu && e.key === 'Escape') closeMenu(); });
  return { update };
}

// The object list's buttons on its own controls, shown in controller mode.
function pickerKeys() {
  const key = (t, cls = '') => {
    const k = document.createElement('span');
    k.className = `pb pad-key ${cls}`;
    k.textContent = t;
    return k;
  };
  const type = document.getElementById('pk-type');
  type.before(key('LB', 'sh'));
  type.after(key('RB', 'sh'));
  document.getElementById('pk-type-label').before(key('☰', 'sh'));
  document.getElementById('pk-views').prepend(key('X', 'x'));
  for (const [id, t, cls] of [['pk-pv-use', 'A', 'a'], ['pk-pv-fav', 'Y', 'y'], ['pk-cancel', 'B', 'b']]) {
    document.getElementById(id).before(key(t, cls));
  }
}

function standardPad() {
  for (const p of navigator.getGamepads()) {
    if (!p || !p.connected) continue;
    if (p.mapping === 'standard') return p;
    if (!warned) {
      warned = true;
      api.status(`The browser doesn't know the button layout of this controller (${p.id}).`, true);
    }
  }
  return null;
}

function stick(x, y) {
  const l = Math.hypot(x, y);
  const dz = settings.deadzone;
  if (l < dz) return [0, 0];
  const k = Math.min(1, (l - dz) / (1 - dz)) / l;
  return [x * k, y * k];
}

function setActive(on) {
  active = on;
  document.body.classList.toggle('pad', on);
  if (!on) {
    api.state.pad = { ...ZERO };
    held.clear();
    lastAim = null;
    lastView = '';
    document.getElementById('pad-aim').classList.remove('on');
  }
  api.active(on, settings.hidePanel);
  hintKey = '';
}

function update(dt) {
  const p = connected && document.hasFocus() ? standardPad() : null;
  if (!p) {
    if (active) api.state.pad = { ...ZERO };
    prev = [];
    return;
  }
  const b = p.buttons.map((x) => x.pressed), v = p.buttons.map((x) => x.value);
  b[HOME] = false;            // macOS can take it for its game overlay
  if (settings.swap) { [b[LT], b[RT]] = [b[RT], b[LT]]; [v[LT], v[RT]] = [v[RT], v[LT]]; }
  const [lx, ly] = stick(p.axes[0], p.axes[1]);
  const [rx, ry] = stick(p.axes[2], p.axes[3]);
  if (!active && (b.some(Boolean) || lx || ly || rx || ry)) setActive(true);
  if (!active) { prev = b; return; }
  const pressed = (i) => b[i] && !prev[i];
  const s = api.state;
  const lt = v[LT] > TRIGGER;
  const dirs = [...b];
  dirs[UP] ||= ly < -0.5; dirs[DOWN] ||= ly > 0.5; dirs[LEFT] ||= lx < -0.5; dirs[RIGHT] ||= lx > 0.5;

  if (menu) {
    s.pad = { ...ZERO };
    repeat(dirs, false, (i, _, first) => menuStep(i, first));
    if (pressed(A)) menuChoose();
    else if (pressed(B)) menuBack();
    else if (pressed(START)) closeMenu();
    prev = b;
    hints('menu');
    return;
  }
  if (api.picker.open()) {
    s.pad = { ...ZERO };
    repeat(dirs, false, (i) => api.picker.move(i === LEFT ? -1 : i === RIGHT ? 1 : 0, i === UP ? -1 : i === DOWN ? 1 : 0));
    if (pressed(A)) api.picker.pick();
    else if (pressed(B)) api.closeTop();
    else if (pressed(X)) api.picker.toggleView();
    else if (pressed(START)) openCategories();
    if (pressed(LB)) api.picker.category(-1);
    if (pressed(RB)) api.picker.category(1);
    if (pressed(Y)) api.picker.favourite();
    prev = b;
    hints('picker');
    return;
  }
  const rows = ctxRows();
  if (rows) {
    s.pad = { ...ZERO };
    repeat(dirs, false, (i, _, first) => {
      if (i === UP || i === DOWN) ctx.at = (ctx.at + (i === DOWN ? 1 : -1) + rows.length) % rows.length;
      else rows[ctx.at]?.padAdjust?.(i === RIGHT ? 1 : -1, first);
      paintCtx(rows);
    });
    if (pressed(A)) { regrab = false; rows[ctx.at]?.click(); }
    else if (pressed(B) || pressed(X)) {
      api.closeTop();
      if (regrab && s.selection.length) api.carry.start();
      regrab = false;
    }
    prev = b;
    hints('ctx');
    return;
  }
  if (api.blocked()) {
    s.pad = { ...ZERO };
    held.clear();
    if (pressed(B)) api.closeTop();
    prev = b;
    hints('blocked');
    return;
  }

  const trigger = (i) => Math.max(0, (v[i] - 0.05) / 0.95);
  const carrying = !!s.carry;
  s.pad = { x: lx, y: -ly, z: (b[RB] ? 1 : 0) - (b[LB] ? 1 : 0),
            fast: carrying ? 1 : 1 + 3 * trigger(RT) };
  if (rx || ry) {
    const k = LOOK_SPEED * settings.look * dt;
    api.look(Math.sign(rx) * rx * rx * k, (settings.invert ? 1 : -1) * Math.sign(ry) * ry * ry * k);
  }

  if (carrying) {
    api.carry.distance((trigger(RT) - trigger(LT)) * dt);
    if (viewChanged(0)) api.carry.to();
    repeat(b, false, (i) => api.carry.step(i === UP ? -1 : i === DOWN ? 1 : 0, i === RIGHT ? 1 : i === LEFT ? -1 : 0));
    if (pressed(A)) {
      if (!api.carry.drop()) api.carry.finish();
      api.select(null);
    } else if (pressed(B)) { api.carry.finish(); api.select(null); }
    else if (pressed(X)) {
      const o = s.selected;
      api.carry.finish();
      regrab = true;
      api.actions(o);
    } else if (pressed(R3)) api.carry.centre();
    else if (pressed(Y)) api.carry.free();
    prev = b;
    hints(s.carry ? 'carry' : 'none');
    return;
  }

  if (s.fine) {
    document.getElementById('pad-aim').classList.remove('on');
    repeat(b, lt, (i, withLt) => api.fine.step(DIR[i], withLt));
    if (pressed(A) || pressed(B)) api.fine.end();
    prev = b;
    hints(s.fine ? 'fine' : 'none', lt);
    return;
  }
  if (pressed(BACK)) { if (lt) api.redo(); else api.undo(); }
  let mode;
  if (s.destPick) {
    mode = 'dest';
    if (pressed(A)) api.dest(true);
    else if (pressed(B)) api.dest(false);
  } else if (s.placing) {
    mode = 'placing';
    if (viewChanged(AIM_EVERY)) api.marker();
    if (pressed(A)) api.place();
    else if (pressed(B)) api.stopPlacing();
  } else {
    const now = performance.now();
    if (viewChanged(AIM_EVERY) || now - aimAt > 500) {
      aimAt = now;
      lastAim = api.aim();
      const label = document.getElementById('pad-aim');
      label.textContent = lastAim ? lastAim.userData.ref.src : '';
      label.classList.toggle('on', !!lastAim);
    }
    if (pressed(A)) {
      const o = api.aim();
      document.getElementById('pad-aim').classList.remove('on');
      if (lt) {
        if (o) {
          api.select(o, true);
          const n = s.selection.length;
          api.status(n ? `${n} object${n > 1 ? 's' : ''} selected.` : 'Nothing selected.');
        }
      } else {
        if (o && !s.selection.length) api.select(o);
        if (s.selection.length) api.carry.start();
      }
    } else if (pressed(X)) {
      const o = s.selection.length ? s.selected : api.aim();
      if (o) api.actions(o);
    }
    if (pressed(B) && s.selection.length) api.select(null);
    if (pressed(Y)) { if (s.selection.length) api.group(); else api.add(); }
    if (pressed(START)) openMenu();
    regrab = false;
    mode = s.selection.length ? 'selection' : 'none';
  }
  prev = b;
  hints(mode, lt);
}

function viewChanged(every) {
  const now = performance.now();
  if (now - aimAt < every) return false;
  const v = api.viewKey();
  if (v === lastView) return false;
  lastView = v;
  return true;
}

// A held direction repeats; fn gets whether it is the first press.
function repeat(b, lt, fn) {
  const now = performance.now();
  for (const i of [UP, DOWN, LEFT, RIGHT]) {
    if (!b[i]) { held.delete(i); continue; }
    let h = held.get(i);
    if (!h) {
      h = { next: now + REPEAT_DELAY, lt };
      held.set(i, h);
      fn(i, h.lt, true);
    } else if (now >= h.next) {
      h.next = now + REPEAT_EVERY;
      fn(i, h.lt, false);
    }
  }
}

// --- Context menu ----------------------------------------------------------

function ctxRows() {
  const m = document.getElementById('ctxmenu');
  if (!m.classList.contains('open')) { ctx.first = null; return null; }
  const rows = [...m.querySelectorAll('.mi:not(.off)')];
  if (!rows.length) return null;
  if (rows[0] !== ctx.first) {
    ctx.first = rows[0];
    ctx.at = 0;
    paintCtx(rows);
  }
  return rows;
}

function paintCtx(rows) {
  rows.forEach((r, i) => r.classList.toggle('pad-focus', i === ctx.at));
}

// --- Start menu ------------------------------------------------------------

const onOff = (v) => (v ? 'On' : 'Off');

function mainRows() {
  const s = api.state, o = api.options;
  const leave = (fn) => () => { closeMenu(); fn(); };
  return [
    { label: 'Save', act: leave(api.save) },
    { label: 'Undo', act: api.undo },
    { label: 'Redo', act: api.redo },
    { label: 'History…', act: leave(api.history) },
    null,
    { label: 'Lock walls', value: () => onOff(o.lock()), act: o.toggleLock },
    { label: 'Simulate lighting', value: () => onOff(o.light()), act: o.toggleLight },
    { label: 'Snap to steps', value: () => onOff(o.snap()), act: o.toggleSnap },
    { label: 'Move step', value: () => `${s.moveStep} units`, adjust: api.moveStep },
    { label: 'Rotation step', value: () => `${s.rotStep}°`, adjust: o.rotStep },
    { label: 'Fly speed', value: () => `${s.speed}`, adjust: o.speed },
    { label: 'Panel', value: () => (o.panel() ? 'Shown' : 'Hidden'), act: o.togglePanel },
    null,
    { label: 'Controller', sub: ['Controller', padRows] },
    { label: 'Controls…', act: leave(api.guide) },
  ];
}

function padRows() {
  const set = (k, v) => { settings[k] = v; saveSettings(); };
  const round = (v) => Math.round(v * 100) / 100;
  return [
    { label: 'Look speed', value: () => `${settings.look.toFixed(2)}x`,
      adjust: (d) => set('look', round(Math.max(0.25, Math.min(3, settings.look + d * 0.25)))) },
    { label: 'Invert vertical look', value: () => onOff(settings.invert), act: () => set('invert', !settings.invert) },
    { label: 'Stick deadzone', value: () => settings.deadzone.toFixed(2),
      adjust: (d) => set('deadzone', round(Math.max(0.05, Math.min(0.5, settings.deadzone + d * 0.05)))) },
    { label: 'Swap LT and RT', value: () => onOff(settings.swap), act: () => set('swap', !settings.swap) },
    { label: 'Auto-hide panel', value: () => onOff(settings.hidePanel),
      act: () => { set('hidePanel', !settings.hidePanel); api.hidePanel(settings.hidePanel); } },
  ];
}

function openMenu() {
  menu = { stack: [] };
  pushMenu('Menu', mainRows);
}

// The picker's category list (its dropdown) as a menu.
function openCategories() {
  menu = { stack: [] };
  const rows = () => api.picker.categories().map((label, i) => ({ label, act: () => { closeMenu(); api.picker.setCategory(i); } }));
  pushMenu('Category', rows, api.picker.categoryAt());
}

function pushMenu(title, make, at = null) {
  const rows = make();
  menu.stack.push({ title, make, rows, at: at ?? rows.findIndex(Boolean) });
  renderMenu();
}

function closeMenu() {
  menu = null;
  held.clear();
  document.getElementById('pad-menu').classList.remove('open');
  hintKey = '';
}

function menuBack() {
  menu.stack.pop();
  if (!menu.stack.length) closeMenu(); else renderMenu();
}

function menuStep(i, first) {
  const top = menu.stack[menu.stack.length - 1];
  if (i === UP || i === DOWN) {
    const n = top.rows.length;
    let at = top.at;
    do at = (at + (i === DOWN ? 1 : -1) + n) % n; while (!top.rows[at]);
    top.at = at;
  } else {
    const row = top.rows[top.at];
    if (row.adjust) row.adjust(i === RIGHT ? 1 : -1, first);
    else if (row.act && row.value && first) row.act();
  }
  renderMenu();
}

function menuChoose(at = null) {
  const top = menu.stack[menu.stack.length - 1];
  const row = top.rows[at ?? top.at];
  if (!row) return;
  if (row.sub) pushMenu(...row.sub);
  else if (row.act) { row.act(); if (menu) renderMenu(); }
  else if (row.adjust) { row.adjust(1, true); renderMenu(); }
}

function renderMenu() {
  const el = document.getElementById('pad-menu');
  const top = menu.stack[menu.stack.length - 1];
  el.innerHTML = '';
  const title = document.createElement('div');
  title.className = 'pm-title';
  title.textContent = top.title;
  el.appendChild(title);
  top.rows.forEach((row, i) => {
    const d = document.createElement('div');
    if (!row) { d.className = 'sep'; el.appendChild(d); return; }
    d.className = 'pm-row' + (i === top.at ? ' on' : '');
    const v = row.value ? row.value() : row.sub ? '›' : '';
    d.innerHTML = '<span></span><span class="v"></span>';
    d.firstChild.textContent = row.label;
    d.lastChild.textContent = row.adjust ? `‹ ${v} ›` : v;
    d.addEventListener('click', () => { top.at = i; menuChoose(i); });
    el.appendChild(d);
  });
  el.classList.add('open');
  el.querySelector('.pm-row.on')?.scrollIntoView({ block: 'nearest' });
}

// --- Hints -----------------------------------------------------------------

const pb = (t, cls = '') => `<span class="pb ${cls}">${t}</span>`;
const SH = (t) => pb(t, 'sh');

function hints(mode, lt = false) {
  const s = api.state;
  const key = [mode, lt, api.groupAction(), menu?.stack[menu.stack.length - 1].title, s.moveStep, s.rotStep, !!lastAim, s.carry?.objs.length, lastAim && s.selection.includes(lastAim), s.selection.length, s.carry?.free, s.carry?.added ? 1 : 0, menu?.stack.length,
               mode === 'picker' && api.picker.categoryName() + api.picker.grid()].join('|');
  if (key === hintKey) return;
  hintKey = key;
  // The object list shows its buttons on its own controls.
  document.getElementById('pad-hints').classList.toggle('off', mode === 'picker');
  const rows = [];
  const row = (k, what) => rows.push(`<dt>${k}</dt><dd>${what}</dd>`);
  const fly = () => {
    row(pb('LS'), 'Fly');
    row(pb('RS'), 'Look around');
    row(SH('LB') + SH('RB'), 'Down / up');
    row(SH('RT'), 'Faster');
  };
  let title = 'Controller';
  if (mode === 'blocked') {
    row(pb('B', 'b'), 'Close');
  } else if (mode === 'menu' || mode === 'ctx') {
    const top = mode === 'menu' && menu.stack[menu.stack.length - 1];
    title = top ? top.title : 'Actions';
    row(SH('↑↓'), 'Choose');
    if (top ? top.rows.some((r) => r?.adjust || r?.value) : ctxRows()?.some((r) => r.padAdjust)) row(SH('←→'), 'Change');
    row(pb('A', 'a'), 'Select');
    row(pb('B', 'b'), mode === 'menu' && menu.stack.length > 1 ? 'Back' : 'Close');
  } else if (mode === 'picker') {
    title = 'Add object';
    row(SH('↑↓←→') + pb('LS'), 'Choose');
    row(pb('A', 'a'), 'Add');
    row(SH('☰'), `Category: ${api.picker.categoryName()}`);
    row(SH('LB') + SH('RB'), 'Previous / next category');
    if (api.picker.views()) row(pb('X', 'x'), api.picker.grid() ? 'List view' : 'Grid view');
    row(pb('Y', 'y'), 'Favourite');
    row(pb('B', 'b'), 'Cancel');
  } else if (mode === 'carry') {
    const several = s.carry.objs.length > 1;
    title = s.carry.added ? 'Placing' : several ? `Carrying ${s.carry.objs.length} objects` : 'Carrying';
    row(pb('LS') + pb('RS'), 'Move');
    row(SH('LT') + SH('RT'), 'Closer / farther');
    row(pb('RS'), 'Click: snap to crosshair');
    row(pb('A', 'a'), 'Drop onto surface');
    row(pb('B', 'b'), 'Let go');
    row(pb('X', 'x'), 'Actions');
    row(SH('↑↓'), `Tilt (${s.rotStep}°)`);
    row(SH('←→'), `Rotate (${s.rotStep}°)`);
    if (!several) row(pb('Y', 'y'), `Free float: ${s.carry.free ? 'On' : 'Off'}`);
  } else if (mode === 'dest') {
    title = 'Door destination';
    fly();
    row(pb('A', 'a'), 'Set the arrival point here');
    row(pb('B', 'b'), 'Cancel');
  } else if (mode === 'placing') {
    title = 'Placing';
    fly();
    row(pb('A', 'a'), 'Place at the crosshair');
    row(pb('B', 'b'), 'Cancel');
  } else if (lt && mode !== 'fine') {
    const n = s.selection.length;
    title = 'Multi-select' + (n ? ` <span>· ${n} selected</span>` : '');
    if (lastAim) row(pb('A', 'a'), s.selection.includes(lastAim) ? 'Remove from the selection' : 'Add to the selection');
    row(SH('⧉'), 'Redo');
  } else if (mode === 'fine' && lt) {
    title = `Fine tune · ${SH('LT')} held`;
    row(SH('↑↓'), `Raise / lower (${s.moveStep} units)`);
    row(SH('←→'), `Rotate (${s.rotStep}°)`);
  } else if (mode === 'fine') {
    title = 'Fine tune';
    row(SH('↑↓←→'), `Move (${s.moveStep} units)`);
    row(SH('LT'), 'Hold: raise, lower, rotate');
    fly();
    row(pb('B', 'b'), 'Done');
  } else if (mode === 'selection') {
    const n = s.selection.length;
    title = `${n} selected`;
    row(pb('A', 'a'), 'Grab');
    const g = { group: 'Group', ungroup: 'Ungroup', remove: 'Remove from group' }[api.groupAction()];
    if (g) row(pb('Y', 'y'), g);
    row(pb('X', 'x'), 'Actions');
    row(pb('B', 'b'), 'Clear the selection');
    row(SH('LT') + pb('A', 'a'), 'Add or remove');
    row(SH('⧉'), 'Undo');
  } else {
    fly();
    if (lastAim) row(pb('A', 'a'), 'Grab');
    if (lastAim) row(pb('X', 'x'), 'Actions');
    row(pb('Y', 'y'), 'Add object');
    row(SH('⧉'), 'Undo');
    row(SH('☰'), 'Menu');
    row(SH('LT'), 'Hold to multi-select');
  }
  document.getElementById('pad-hints').innerHTML = `<div class="ph-title">${title}</div><dl>${rows.join('')}</dl>`;
}
