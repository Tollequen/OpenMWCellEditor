// New cells: the window that makes an interior cell, or changes one made in this project
import { choose, withChooser } from './choose.js';

let api = null;

export function setupCells(a) {
  api = a;
  return { create, edit, list, entry };
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

const BLANK = { name: '', ambient: [62, 50, 38], sun: [81, 40, 0], fog: [107, 56, 35], fog_density: 1, water: null,
                no_sleep: false, like_exterior: false };
const FIELDS = Object.keys(BLANK);
const hex = (c) => '#' + c.map((v) => Math.max(0, Math.min(255, v | 0)).toString(16).padStart(2, '0')).join('');
const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

// a new cell's entry in the edits, by the cell's name
function entry(name) {
  return Object.values(api.state.edits.cells || {}).find((c) => c.new && c.name === name) || null;
}

// the cell list with the edits' new cells first
function list() {
  const fresh = Object.values(api.state.edits.cells || {}).filter((c) => c.new)
    .map((c) => ({ name: c.name, exterior: false, new: true })).sort((a, b) => a.name.localeCompare(b.name));
  return [...fresh, ...api.state.data.cells.filter((c) => !c.new)];
}

async function check(name, taken) {
  const res = await fetch('/api/cell/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                  body: JSON.stringify({ name, taken }) });
  return res.json();
}

function create() { open(null); }
function edit(name) { const c = entry(name); if (c) open(c); }

function open(old) {
  const f = JSON.parse(JSON.stringify(old || BLANK));
  const bg = el('div', 'dialog-bg');
  bg.innerHTML = `<div class="dialog cell-dialog"><h3></h3><p class="dim cl-sub"></p><div class="cl-form"></div>
    <div class="npc-hint cl-note"></div>
    <div class="bar"><button class="cl-delete danger">Delete cell…</button><span class="spacer"></span>
      <button class="cl-cancel">Cancel</button><button class="primary cl-done"></button></div></div>`;
  document.body.appendChild(bg);
  const q = (c) => bg.querySelector(c);
  const form = q('.cl-form');
  const close = () => bg.remove();
  const note = (t) => { q('.cl-note').textContent = t || ''; };
  q('h3').textContent = old ? old.name : 'New cell';
  q('.cl-sub').textContent = old ? 'A cell made in this project: its light and water.' : 'A new interior cell in your plugin.';
  q('.cl-done').textContent = old ? 'Done' : 'Create';
  q('.cl-delete').style.display = old ? '' : 'none';

  const row = (label, control) => {
    const l = form.appendChild(el('label', 'opt'));
    l.appendChild(el('span', null, label));
    l.appendChild(control);
    return control;
  };
  const build = () => {
    form.innerHTML = '';
    if (!old) {
      const t = el('input');
      t.type = 'text';
      t.readOnly = true;
      t.value = f.template || '';
      t.placeholder = 'None';
      t.title = 'Start from an existing cell\'s light and water';
      const l = form.appendChild(el('label', 'opt'));
      l.appendChild(el('span', null, 'Use template'));
      l.appendChild(withChooser(t, (cur) => choose({
        title: 'Choose a cell to take the settings from', current: cur, none: 'No template',
        items: list().filter((c) => !c.exterior).map((c) => ({ id: c.name })) }), useTemplate));
      const n = row('Name', el('input'));
      n.type = 'text';
      n.maxLength = 63;
      n.value = f.name;
      n.placeholder = 'e.g. Balmora, Old Cellar';
      n.addEventListener('input', () => { f.name = n.value; note(''); });
    }
    const outside = el('input');
    outside.type = 'checkbox';
    outside.checked = f.like_exterior;
    for (const [k, label] of [['ambient', 'Ambient light'], ['sun', 'Sunlight'], ['fog', 'Fog colour']]) {
      const c = row(label, el('input'));
      c.type = 'color';
      c.value = hex(f[k]);
      c.disabled = f.like_exterior;
      c.addEventListener('input', () => { f[k] = rgb(c.value); });
    }
    const d = row('Fog density', el('input'));
    d.type = 'number';
    Object.assign(d, { min: 0, max: 1, step: 0.05, value: f.fog_density, disabled: f.like_exterior });
    d.addEventListener('input', () => { f.fog_density = Math.max(0, Math.min(1, Number(d.value) || 0)); });
    const lo = form.appendChild(el('label', 'check'));
    lo.append(outside, ' Behaves like an exterior (sky and weather light it)');
    outside.addEventListener('change', () => { f.like_exterior = outside.checked; build(); });
    const lw = form.appendChild(el('label', 'check'));
    const w = lw.appendChild(el('input'));
    w.type = 'checkbox';
    w.checked = f.water != null;
    lw.append(' Has water');
    const level = row('Water level', el('input'));
    level.type = 'number';
    Object.assign(level, { step: 8, value: f.water ?? 0, disabled: f.water == null });
    level.title = 'The height of the water surface (the floor grid is at 0)';
    w.addEventListener('change', () => { f.water = w.checked ? Number(level.value) || 0 : null; level.disabled = !w.checked; });
    level.addEventListener('input', () => { if (f.water != null) f.water = Number(level.value) || 0; });
    const ls = form.appendChild(el('label', 'check'));
    const s = ls.appendChild(el('input'));
    s.type = 'checkbox';
    s.checked = f.no_sleep;
    ls.append(' Sleeping here is illegal');
    s.addEventListener('change', () => { f.no_sleep = s.checked; });
  };
  const useTemplate = async (name) => {
    const from = name ? (entry(name) || (await check(name, [])).settings) : BLANK;
    if (!from) { note(`${name}'s settings couldn't be read.`); return; }
    for (const k of FIELDS) if (k !== 'name') f[k] = JSON.parse(JSON.stringify(from[k] ?? BLANK[k]));
    f.template = name || '';
    build();
  };
  build();
  if (!old) {
    q('.cl-note').textContent = 'After Create you\'re taken there: an empty cell with a floor grid to build on.';
    const l = el('label', 'check cl-build');
    const b = l.appendChild(el('input'));
    b.type = 'checkbox';
    b.checked = !document.body.classList.contains('touch');
    b.addEventListener('change', () => { f.build = b.checked; });
    f.build = b.checked;
    l.append(' Open the room builder there');
    q('.bar').prepend(l);
  }

  const out = () => Object.assign({ new: true }, Object.fromEntries(FIELDS.map((k) => [k, f[k]])), { name: f.name.trim() });
  bg.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !document.querySelector('.choose-dialog')) { e.stopPropagation(); close(); }
  });
  q('.cl-cancel').addEventListener('click', close);
  q('.cl-done').addEventListener('click', async () => {
    const c = out();
    if (old) {
      close();
      if (JSON.stringify(c) !== JSON.stringify(Object.assign({ new: true }, Object.fromEntries(FIELDS.map((k) => [k, old[k]]))))) {
        record((e) => { e.cells[c.name.toLowerCase()] = c; }, `Changed ${c.name}.`);
      }
      return;
    }
    const taken = Object.values(api.state.edits.cells || {}).map((x) => x.name);
    let got;
    try { got = await check(c.name, taken); } catch (err) { note('The editor didn\'t answer.'); return; }
    if (got.error) { note(got.error); return; }
    close();
    record((e) => { e.cells[c.name.toLowerCase()] = c; }, `Made ${c.name}.`);
    const build = f.build;
    Promise.resolve(api.go(c.name)).then(() => { if (build) api.build(); });
  });
  let sure = false;
  q('.cl-delete').addEventListener('click', () => {
    const inside = api.state.edits.added.filter((a) => a.cell === old.name);
    if (!sure) {
      sure = true;
      q('.cl-delete').textContent = 'Really delete';
      note(`Deletes ${old.name}${inside.length ? ` and the ${inside.length} object${inside.length === 1 ? '' : 's'} in it` : ''}. `
           + 'Doors that lead there keep pointing at it. Undo brings it back.');
      return;
    }
    close();
    record((e) => {
      const gone = new Set(inside.map((a) => 'added|' + a.uid));
      delete e.cells[old.name.toLowerCase()];
      e.added = e.added.filter((a) => a.cell !== old.name);
      e.deleted = e.deleted.filter((k) => !gone.has(k));
      for (const sec of ['moved', 'replaced', 'attached', 'doors', 'props']) {
        for (const k of Object.keys(e[sec] || {})) if (gone.has(k)) delete e[sec][k];
      }
      for (const [g, keys] of Object.entries(e.groups || {})) e.groups[g] = keys.filter((k) => !gone.has(k));
    }, `Deleted ${old.name}.`);
  });
}

// one undo step for a change to the edits
function record(change, text) {
  const { state } = api;
  const before = api.entriesOf(state.edits);
  state.edits.cells = state.edits.cells || {};
  change(state.edits);
  const diff = api.diffOf(before, api.entriesOf(state.edits));
  if (diff.length) state.undo.push({ diff });
  api.changed(diff.map((d) => d.id));
  api.status(text);
}
