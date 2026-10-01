import { icon } from './icons.js';
import { showDialogue, refreshDialogue } from './topics.js';
import { setSuggestions, suggest } from './suggest.js';

const $ = (id) => document.getElementById(id);
let api = null;
let list = null, lists = null, canEdit = true;
const bases = new Map();
const ui = { id: null, panes: null, tab: 'general' };
const TABS = [['general', 'General', 'General'], ['stats', 'Stats', 'Stats'], ['ai', 'AI and services', 'AI'],
              ['items', 'Inventory and spells', 'Items'], ['dialogue', 'Dialogue', 'Dialogue']];

const BLOOD = ['Default (red)', 'Skeleton (white dust)', 'Metal (sparks)'];
const BUYS = [['Weapons', 0x1], ['Armor', 0x2], ['Clothing', 0x4], ['Books', 0x8], ['Ingredients', 0x10],
              ['Lockpicks', 0x20], ['Probes', 0x40], ['Lights', 0x80], ['Apparatus', 0x100], ['Repair items', 0x200],
              ['Misc items', 0x400], ['Potions', 0x2000], ['Magic items', 0x1000]];
const OFFERS = [['Spells', 0x800], ['Training', 0x4000], ['Spellmaking', 0x8000], ['Enchanting', 0x10000],
                ['Repair', 0x20000]];
const STATS = ['attributes', 'skills', 'health', 'magicka', 'fatigue'];

export function setupNpcEditor(a) {
  api = a;
  $('npc-close').addEventListener('click', close);
  $('npc-cell').addEventListener('click', () => showList(true));
  $('npcl-close').addEventListener('click', () => showList(false));
  $('npcbox').addEventListener('click', (e) => { if (e.target === $('npcbox')) close(); });
  $('npc-cellbox').addEventListener('click', (e) => { if (e.target === $('npc-cellbox')) showList(false); });
  $('npcbox').addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !document.querySelector('.dialog-bg')) {
      e.preventDefault();
      const t = e.target;
      if (t.matches?.('input:not([type=checkbox]), textarea, select')) { t.blur(); $('npc-form').focus(); }
      else if (listOpen() && ui.id) showList(false); else close();
    }
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); document.activeElement?.blur(); api.save(); }
  });
  return { open, close, isOpen, refresh, newItems, create, nameOf: (id) => entryOf(id).name || id };
}

function isOpen() { return $('npcbox').classList.contains('open'); }

function listOpen() { return $('npc-cellbox').classList.contains('open'); }
function showList(on) {
  $('npc-cellbox').classList.toggle('open', on);
  if (on) {
    $('npcl-where').textContent = api.state.cell ? `· ${api.state.cell.name}` : '';
    $('npc-list').querySelector('.sel')?.scrollIntoView({ block: 'nearest' });
    $('npcl-box').focus();
  } else $('npc-form').focus?.();
}

async function open(id = null) {
  $('npcbox').classList.add('open');
  showList(!id);
  if (!(await loadLists())) return;
  $('npc-where').textContent = api.state.cell ? `· ${api.state.cell.name}` : '';
  renderList();
  const first = id || cellNpcs()[0]?.id;
  if (first) await show(first.toLowerCase());
  else if (!ui.id) $('npc-form').innerHTML = '<div class="npc-empty">This cell has no NPCs. Add one with Add NPC….</div>';
  if (!listOpen()) $('npc-form').focus?.();
}

async function loadLists() {
  if (!list) {
    $('npc-list').innerHTML = '<div class="npc-empty">Loading the NPCs…</div>';
    try {
      const [l, ls] = await Promise.all([fetch('/api/npcs').then((r) => r.json()),
                                         fetch('/api/npc/lists').then((r) => r.json())]);
      list = l.npcs;
      canEdit = l.canEdit;
      lists = ls;
      fillDatalists();
    } catch (err) {
      $('npc-list').innerHTML = '<div class="npc-empty bad">The NPCs couldn\'t be read.</div>';
      return false;
    }
  }
  return true;
}

function close() {
  document.activeElement?.blur();
  $('npc-cellbox').classList.remove('open');
  $('npcbox').classList.remove('open');
  api.closed();
}

// --- The list ------------------------------------------------------------------------

function edits() { return api.state.edits.npcs; }

function entryOf(id) {
  const key = id.toLowerCase(), e = edits()[key];
  if (e && e.new) return { id: e.id, name: e.name, race: e.race, class: e.class, file: api.state.data.project.plugin, isNew: true };
  const n = list.find((x) => x.id.toLowerCase() === key) || { id, name: '', race: '', class: '', file: '' };
  return e ? Object.assign({}, n, e, { id: n.id }) : n;
}

function cellNpcs() {
  const cell = api.state.cell;
  if (!cell) return [];
  const gone = new Set(api.state.edits.deleted);
  const seen = new Map();
  for (const r of cell.refs) {
    if (r.kind === 'npc' && !gone.has(r.key) && !seen.has(r.src.toLowerCase())) seen.set(r.src.toLowerCase(), entryOf(r.src));
  }
  return [...seen.values()].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
}

// NPDT padding is kept: the Construction Set leaves bytes in it
function placedIn(id) {
  const gone = new Set(api.state.edits.deleted);
  return [...new Set(api.state.edits.added.filter((a) => a.id.toLowerCase() === id.toLowerCase()
                                                       && !gone.has('added|' + a.uid)).map((a) => a.cell))];
}

function newItems() {
  return Object.values(api.state.edits.npcs || {}).filter((e) => e.new)
    .map((e) => ({ id: e.id, name: e.name, type: 'NPC', mesh: '', file: api.state.data.project.plugin }));
}

function renderList() {
  const box = $('npc-list');
  box.innerHTML = '';
  const here = cellNpcs();
  const inCell = new Set(here.map((n) => n.id.toLowerCase()));
  const shown = ui.id && !inCell.has(ui.id) && !(edits()[ui.id] || {}).new ? [entryOf(ui.id)] : [];
  const elsewhere = Object.values(edits()).filter((e) => e.new && !inCell.has(e.id.toLowerCase())).map((e) => entryOf(e.id));
  const head = (text) => box.appendChild(Object.assign(document.createElement('div'), { className: 'npc-group', textContent: text }));
  head(`In this cell (${here.length})`);
  $('npc-cell').textContent = `NPCs in this cell (${here.length})…`;
  if (!here.length) box.appendChild(Object.assign(document.createElement('div'), { className: 'npc-empty', textContent: 'No NPCs here.' }));
  here.concat(shown).forEach((n) => row(n));
  if (elsewhere.length) {
    head('Your new NPCs elsewhere');
    for (const n of elsewhere) {
      const cells = placedIn(n.id);
      row(n, cells.length ? `in ${cells.join(', ')}` : 'not placed yet');
    }
  }

  function row(n, where = null) {
    const key = n.id.toLowerCase();
    const row = document.createElement('div');
    row.className = 'npc-item' + (key === ui.id ? ' sel' : '');
    row.dataset.id = key;
    const e = edits()[key];
    const cur = e && !e.new ? Object.assign({}, n, e) : n;
    row.innerHTML = '<div class="n"></div><div class="d"></div>';
    row.querySelector('.n').textContent = cur.name || cur.id;
    row.querySelector('.d').textContent = [cur.name ? cur.id : '', [cur.race, cur.class].filter(Boolean).join(' '),
                                           where || n.file].filter(Boolean).join(' · ');
    if (e) {
      const mark = document.createElement('span');
      mark.className = 'mark';
      mark.textContent = n.isNew ? 'new' : 'changed';
      row.querySelector('.n').appendChild(mark);
    }
    row.addEventListener('click', async () => { await show(key); if (ui.id === key) showList(false); });
    box.appendChild(row);
  }
}

// --- One NPC: its fields as they are now ---------------------------------------------

async function show(id) {
  const e = edits()[id];
  if (!(e && e.new) && !bases.has(id)) {
    const res = await fetch('/api/npc?id=' + encodeURIComponent(id));
    if (!res.ok) {
      $('npc-form').innerHTML = '';
      const p = document.createElement('div');
      p.className = 'npc-empty bad';
      p.textContent = `${id} isn't in the load order${e ? ' any more: its changes can\'t be saved. Reset them to go on.' : '.'}`;
      $('npc-form').appendChild(p);
      if (e) {
        const b = document.createElement('button');
        b.textContent = 'Reset its changes';
        b.addEventListener('click', () => { setEntry(id, undefined); show(id); });
        $('npc-form').appendChild(b);
      }
      return;
    }
    bases.set(id, await res.json());
  }
  ui.id = id;
  if (![...$('npc-list').children].some((r) => r.dataset.id === id)) renderList();
  for (const row of $('npc-list').children) {
    row.classList?.toggle('sel', row.dataset.id === id);
    if (row.dataset.id === id) row.scrollIntoView({ block: 'nearest' });
  }
  build();
}

function base() { return bases.get(ui.id); }
function isNew() { return !!edits()[ui.id]?.new; }
function fields() {
  const e = edits()[ui.id];
  return e && e.new ? e : Object.assign({}, base().fields, e || {});
}
function editable() { return canEdit && (isNew() || base().editable); }

function sorted(o) {
  if (Array.isArray(o)) return o.map(sorted);
  if (o && typeof o === 'object') return Object.fromEntries(Object.keys(o).sort().map((k) => [k, sorted(o[k])]));
  return o;
}
const same = (a, b) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));

function setEntry(id, next) {
  const e = edits(), prev = e[id];
  if (same(next, prev)) return false;
  if (next === undefined) delete e[id]; else e[id] = sorted(next);
  api.state.undo.push({ npcs: [{ id, prev }] });
  api.changed();
  renderList();
  return true;
}

function setFields(changes) {
  const prev = edits()[ui.id];
  let next;
  if (prev && prev.new) next = Object.assign({}, prev, changes);
  else {
    const patch = Object.assign({}, prev || {});
    for (const [k, v] of Object.entries(changes)) {
      if (same(v, base().fields[k])) delete patch[k]; else patch[k] = v;
    }
    next = Object.keys(patch).length ? patch : undefined;
  }
  if (setEntry(ui.id, next)) fill();
}

function refresh(ids = null) {
  if (!isOpen() || !list) return;
  if (!ids || ids.some((i) => i.startsWith('dialogue|'))) refreshDialogue();
  renderList();
  if (!ui.id || (ids && !ids.includes('npcs|' + ui.id))) return;
  if (!edits()[ui.id] && !bases.has(ui.id)) {
    ui.id = null;
    $('npc-form').innerHTML = '<div class="npc-empty">Choose an NPC from the list.</div>';
    showList(true);
    return;
  }
  if (ui.built === ui.id + (isNew() ? '|new' : '')) fill(); else build();
}

// --- The game's rules: what an NPC with auto-calculated stats gets ---------------------

function roundEven(f) {
  const i = Math.floor(f), d = f - i;
  if (d < 0.5) return i;
  if (d > 0.5) return i + 1;
  return i % 2 === 0 ? i : i + 1;
}

const byId = (arr, id) => arr.find((x) => x.id.toLowerCase() === (id || '').toLowerCase());

function autoStats(f) {
  const race = byId(lists.races, f.race), cls = byId(lists.classes, f.class);
  if (!race || !cls) return null;
  const level = f.level;
  const attrs = [];
  for (let a = 0; a < 8; a++) attrs.push(race.attrs[2 * a + (f.female ? 1 : 0)] + (cls.attrs.includes(a) ? 10 : 0));
  for (let a = 0; a < 8; a++) {
    let sum = 0;
    lists.skills.forEach(([attr], s) => {
      if (attr !== a) return;
      let add = 0.2;
      for (const pair of cls.skills) { if (pair[0] === s) add = 0.5; if (pair[1] === s) add = 1.0; }
      sum += add;
    });
    attrs[a] = Math.min(roundEven(attrs[a] + (level - 1) * sum), 100);
  }
  let mult = 3 + (cls.spec === 0 ? 2 : cls.spec === 2 ? 1 : 0) + (cls.attrs.includes(5) ? 1 : 0);
  const health = Math.floor(0.5 * (attrs[0] + attrs[5])) + mult * (level - 1);
  const skills = new Array(27).fill(0);
  for (const pair of cls.skills) {
    if (pair[0] >= 0 && pair[0] < 27) skills[pair[0]] += 10;
    if (pair[1] >= 0 && pair[1] < 27) skills[pair[1]] += 25;
  }
  lists.skills.forEach(([, spec], s) => {
    const bonus = race.bonus.find(([skill]) => skill === s);
    const major = cls.skills.some((pair) => pair.includes(s)) ? 1.0 : 0.1;
    const same = spec === cls.spec;
    skills[s] = Math.min(roundEven(skills[s] + 5 + (bonus ? bonus[1] : 0) + (same ? 5 : 0)
                                   + (level - 1) * (major + (same ? 0.5 : 0))), 100);
  });
  return { attributes: attrs, skills, health, magicka: Math.round(lists.magickaMult * attrs[1]),
           fatigue: attrs[0] + attrs[2] + attrs[3] + attrs[5] };
}

// --- The form ------------------------------------------------------------------------

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function section(title, tab, heading = true) {
  const s = el('section', 'npc-sec' + (heading ? '' : ' wide'));
  if (heading) s.appendChild(el('h4', null, title));
  ui.panes[tab].appendChild(s);
  return s;
}

function showTab(key) {
  ui.tab = key;
  for (const b of $('npc-form').querySelectorAll('.npc-tab')) {
    b.classList.toggle('sel', b.dataset.tab === key);
    b.setAttribute('aria-selected', b.dataset.tab === key);
  }
  for (const [k, pane] of Object.entries(ui.panes)) pane.classList.toggle('sel', k === key);
}

function labelled(parent, text, control, cls = '') {
  const l = el('label', 'npc-f ' + cls);
  l.appendChild(el('span', null, text));
  l.appendChild(control);
  parent.appendChild(l);
  return control;
}

function numberInput(min, max, onSet) {
  const i = el('input');
  i.type = 'number';
  i.min = min; i.max = max; i.step = 1;
  i.addEventListener('change', () => {
    const v = Math.round(Number(i.value));
    onSet(Number.isFinite(v) ? Math.min(max, Math.max(min, v)) : min);
  });
  i.addEventListener('keydown', (e) => { if (e.key === 'Enter') i.blur(); });
  return i;
}

function select(options, onSet) {
  const s = el('select');
  s.dataset.options = JSON.stringify(options);
  for (const [v, t] of options) s.add(new Option(t, v));
  s.addEventListener('change', () => onSet(s.value));
  return s;
}

function setSelect(s, v) {
  v = v ?? '';
  let opt = [...s.options].find((o) => o.value.toLowerCase() === String(v).toLowerCase());
  if (!opt) { opt = new Option(`${v} (not in the load order)`, v); s.add(opt); }
  s.value = opt.value;
}

function options(arr, none = null) {
  const out = none != null ? [['', none]] : [];
  return out.concat([...arr].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))
    .map((x) => [x.id, x.name && x.name !== x.id ? `${x.name} (${x.id})` : x.id]));
}

function bodyParts(f, part) {
  return lists.parts.filter((p) => p.part === part && p.race.toLowerCase() === (f.race || '').toLowerCase()
                            && p.female === !!f.female)
    .sort((a, b) => a.vampire - b.vampire || a.id.localeCompare(b.id));
}

function fillDatalists() {
  setSuggestions('npc-items', lists.items.map((o) => [o.id, o.name ? `${o.name} · ${o.type}` : o.type]));
  setSuggestions('npc-spells', lists.spells.map((o) => [o.id, `${o.name || o.id} · ${o.type}`]));
  setSuggestions('npc-scripts', lists.scripts.map((s) => [s, '']));
}

function build() {
  const form = $('npc-form');
  form.innerHTML = '';
  ui.controls = {};
  const c = ui.controls;

  const head = el('div', 'npc-head');
  const titles = el('div', 'npc-titles');
  c.title = titles.appendChild(el('div', 'npc-title'));
  c.sub = titles.appendChild(el('div', 'npc-sub'));
  head.appendChild(titles);
  const acts = el('div', 'npc-acts');
  const copy = acts.appendChild(el('button', null, 'Copy as new NPC…'));
  copy.addEventListener('click', copyAsNew);
  copy.disabled = !canEdit;
  c.reset = acts.appendChild(el('button', null, isNew() ? 'Delete NPC…' : 'Reset changes'));
  c.reset.addEventListener('click', isNew() ? deleteNew : () => setEntry(ui.id, undefined) && build());
  head.appendChild(acts);
  form.appendChild(head);
  c.note = form.appendChild(el('div', 'npc-note'));
  c.warn = form.appendChild(el('div', 'npc-warn'));

  const tabs = el('div', 'npc-tabs');
  tabs.setAttribute('role', 'tablist');
  form.appendChild(tabs);
  ui.panes = {};
  for (const [key, label, short] of TABS) {
    const b = tabs.appendChild(el('button', 'npc-tab'));
    b.append(el('span', 'long', label), el('span', 'short', short));
    b.title = label;
    b.dataset.tab = key;
    b.setAttribute('role', 'tab');
    b.addEventListener('click', () => showTab(key));
    ui.panes[key] = form.appendChild(el('div', 'npc-grid npc-pane'));
  }

  const who = section('Identity', 'general');
  const looks = section('Appearance & Script', 'general');
  c.name = labelled(who, 'Name', el('input'));
  c.name.type = 'text';
  c.name.maxLength = 32;
  c.name.addEventListener('change', () => setFields({ name: c.name.value }));
  c.race = labelled(who, 'Race', select(options(lists.races), (v) => changeLook({ race: v })));
  c.sex = labelled(who, 'Sex', select([['m', 'Male'], ['f', 'Female']], (v) => changeLook({ female: v === 'f' })));
  c.cls = labelled(who, 'Class', select(options(lists.classes), (v) => setFields({ class: v })));
  c.faction = labelled(who, 'Faction', select(options(lists.factions, 'None'), (v) => {
    const fac = byId(lists.factions, v);
    setFields({ faction: v, rank: fac && fields().rank >= fac.ranks.length ? 0 : fields().rank });
  }));
  c.rank = labelled(who, 'Rank', el('select'));
  c.rank.addEventListener('change', () => setFields({ rank: Number(c.rank.value) }));
  c.head = labelled(looks, 'Head', el('select'));
  c.head.addEventListener('change', () => setFields({ head: c.head.value }));
  c.hair = labelled(looks, 'Hair', el('select'));
  c.hair.addEventListener('change', () => setFields({ hair: c.hair.value }));
  c.script = labelled(looks, 'Script', el('input'));
  c.script.type = 'text';
  suggest(c.script, 'npc-scripts');
  c.script.placeholder = 'None';
  c.script.addEventListener('change', () => setFields({ script: c.script.value.trim() }));
  c.model = labelled(looks, 'Animation', el('input'));
  c.model.type = 'text';
  c.model.placeholder = 'Usually empty (the race\'s body)';
  c.model.title = 'A special animation file (NIF), as some NPCs have; empty for most';
  c.model.addEventListener('change', () => setFields({ model: c.model.value.trim() }));
  const flags = el('div', 'npc-checks');
  for (const [k, text, tip] of [['essential', 'Essential', 'The player is warned when they die (the main quest can\'t go on)'],
                                ['respawn', 'Respawns', 'Comes back after death (their inventory restocks)']]) {
    const l = el('label', 'check');
    const box = el('input');
    box.type = 'checkbox';
    box.addEventListener('change', () => setFields({ [k]: box.checked }));
    l.title = tip;
    l.append(box, text);
    flags.appendChild(l);
    c[k] = box;
  }
  who.appendChild(flags);
  c.blood = labelled(looks, 'Blood', select(BLOOD.map((t, i) => [String(i), t]), (v) => setFields({ blood: Number(v) })));

  const num = (parent, text, min, max, onSet) => labelled(parent, text, numberInput(min, max, onSet), 'num');
  const gen = section('General', 'stats');
  const genCols = gen.appendChild(el('div', 'npc-cols'));
  c.level = num(genCols, 'Level', 1, 32767, (v) => setFields({ level: v }));
  c.disposition = num(genCols, 'Disposition', 0, 255, (v) => setFields({ disposition: v }));
  c.reputation = num(genCols, 'Reputation', 0, 255, (v) => setFields({ reputation: v }));
  c.gold = num(genCols, 'Gold', -2147483648, 2147483647, (v) => setFields({ gold: v }));
  const auto = el('label', 'check');
  c.autocalc = el('input');
  c.autocalc.type = 'checkbox';
  c.autocalc.addEventListener('change', () => setAutocalc(c.autocalc.checked));
  auto.append(c.autocalc, 'Auto-calculate attributes, skills and health');
  auto.title = 'The game works them out from race, class and level';
  gen.appendChild(auto);
  c.autoNote = gen.appendChild(el('div', 'npc-hint'));
  const dyn = section('Health, magicka and fatigue', 'stats');
  c.health = num(dyn, 'Health', 0, 65535, (v) => setFields({ health: v }));
  c.magicka = num(dyn, 'Magicka', 0, 65535, (v) => setFields({ magicka: v }));
  c.fatigue = num(dyn, 'Fatigue', 0, 65535, (v) => setFields({ fatigue: v }));
  const attrs = section('Attributes', 'stats').appendChild(el('div', 'npc-cols'));
  c.attributes = lists.attributeNames.map((name, i) => num(attrs, name, 0, 255, (v) => {
    const a = [...fields().attributes];
    a[i] = v;
    setFields({ attributes: a });
  }));
  const sk = section('Skills', 'stats');
  sk.classList.add('wide');
  const specs = sk.appendChild(el('div', 'npc-cols skills'));
  c.skills = [];
  ['Combat', 'Magic', 'Stealth'].forEach((spec, k) => {
    const col = specs.appendChild(el('div'));
    col.appendChild(el('div', 'npc-sub-h', spec));
    lists.skillNames.forEach((name, i) => {
      const sp = (lists.skills[i] || [])[1];
      if ((sp === 0 || sp === 1 ? sp : 2) !== k) return;
      c.skills[i] = num(col, name, 0, 255, (v) => {
        const a = [...fields().skills];
        a[i] = v;
        setFields({ skills: a });
      });
    });
  });

  const ai = section('AI', 'ai');
  const aiRow = el('div', 'npc-row');
  ai.appendChild(aiRow);
  for (const [k, text, max, tip] of [['hello', 'Hello', 65535, 'How far away they greet the player'],
                                     ['fight', 'Fight', 255, 'Attacks the player above 100 (with disposition and more)'],
                                     ['flee', 'Flee', 255, 'Runs away when losing'],
                                     ['alarm', 'Alarm', 255, 'Reports crimes they see (100: always)']]) {
    c[k] = labelled(aiRow, text, numberInput(0, max, (v) => setFields({ [k]: v })), 'small');
    c[k].parentElement.title = tip;
  }
  ai.appendChild(el('div', 'npc-sub-h', 'Wander'));
  c.wander = ai.appendChild(el('div'));
  c.extras = ai.appendChild(el('div', 'npc-hint'));
  const sv = section('Services', 'ai');
  sv.appendChild(el('div', 'npc-sub-h', 'Buys'));
  c.buys = sv.appendChild(el('div', 'npc-checks'));
  sv.appendChild(el('div', 'npc-sub-h', 'Offers'));
  c.offers = sv.appendChild(el('div', 'npc-checks'));
  c.servicesNote = sv.appendChild(el('div', 'npc-hint'));
  for (const [box, bits] of [[c.buys, BUYS], [c.offers, OFFERS]]) {
    for (const [text, bit] of bits) {
      const l = el('label', 'check');
      const cb = el('input');
      cb.type = 'checkbox';
      cb.dataset.bit = bit;
      cb.addEventListener('change', () => setFields({ services: cb.checked ? fields().services | bit : fields().services & ~bit }));
      l.append(cb, text);
      box.appendChild(l);
    }
  }

  const inv = section('Inventory', 'items');
  c.items = inv.appendChild(el('div', 'npc-rows'));
  inv.appendChild(addRow('npc-items', 'Item ID (e.g. iron_dagger)', true, (id, count) => {
    setFields({ items: [...fields().items, [count, id]] });
  }));
  inv.appendChild(el('div', 'npc-hint', 'A negative count restocks: a merchant has that many again after a while.'));
  const sp = section('Spells', 'items');
  c.spells = sp.appendChild(el('div', 'npc-rows'));
  sp.appendChild(addRow('npc-spells', 'Spell ID (e.g. fire_bite)', false, (id) => {
    setFields({ spells: [...fields().spells, id] });
  }));

  c.items.dataset.empty = 'No items in inventory.';
  c.spells.dataset.empty = 'No spells assigned.';

  const dia = section('Dialogue', 'dialogue', false);
  const diaBox = dia.appendChild(el('div'));
  showDialogue(diaBox, { api, actor: fields().id, editable: editable(), lists });
  showTab(ui.tab);
  ui.built = ui.id + (isNew() ? '|new' : '');
  const on = editable();
  for (const i of form.querySelectorAll('input, select')) i.disabled = !on;
  fill();
}

function addRow(listId, placeholder, withCount, onAdd) {
  const row = el('div', 'npc-add');
  let count = null;
  if (withCount) {
    count = el('input');
    count.type = 'number';
    count.value = 1;
    count.className = 'count';
    row.appendChild(count);
  }
  const id = el('input');
  id.type = 'text';
  suggest(id, listId);
  id.placeholder = placeholder;
  row.appendChild(id);
  const b = el('button', null, 'Add');
  const add = () => {
    const v = id.value.trim();
    if (!v) { id.focus(); return; }
    onAdd(v, withCount ? Math.round(Number(count.value)) || 1 : null);
    id.value = '';
    if (count) count.value = 1;
    id.focus();
  };
  b.addEventListener('click', add);
  id.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
  row.appendChild(b);
  return row;
}

function fill() {
  const c = ui.controls, f = fields(), b = isNew() ? null : base();
  const put = (i, v) => { if (document.activeElement !== i) i.value = v; };
  const e = edits()[ui.id];
  c.title.textContent = f.name || f.id;
  c.sub.textContent = [f.id, isNew() ? `new in ${api.state.data.project.plugin}` : `from ${b.file}`,
                       e && !isNew() ? `${Object.keys(e).length} field${Object.keys(e).length > 1 ? 's' : ''} changed` : '']
    .filter(Boolean).join(' · ');
  c.reset.disabled = !canEdit || (!isNew() && !e);
  const p = api.state.data.project;
  c.note.textContent = !canEdit ? `Read-only: ${p.plugin} is built by the project's own script, which would undo changes to NPCs.`
    : !isNew() && !b.editable ? `Read-only: ${b.file} ${p.inPlace ? `loads after ${p.plugin}` : `isn't one the project may use`}.`
    : '';
  c.note.style.display = c.note.textContent ? '' : 'none';
  put(c.name, f.name);
  setSelect(c.race, f.race);
  c.sex.value = f.female ? 'f' : 'm';
  setSelect(c.cls, f.class);
  setSelect(c.faction, f.faction);
  const fac = byId(lists.factions, f.faction);
  c.rank.innerHTML = '';
  (fac ? fac.ranks : []).forEach((r, i) => c.rank.add(new Option(`${i + 1}. ${r}`, String(i))));
  if (!fac) c.rank.add(new Option('—', String(f.rank)));
  if (fac && f.rank >= fac.ranks.length) c.rank.add(new Option(`${f.rank + 1} (not a rank of it)`, String(f.rank)));
  c.rank.value = String(f.rank);
  c.rank.disabled = !fac || !editable();
  for (const [k, part] of [['head', 0], ['hair', 1]]) {
    c[k].innerHTML = '';
    for (const x of bodyParts(f, part)) c[k].add(new Option(x.id + (x.vampire ? ' (vampire)' : ''), x.id));
    setSelect(c[k], f[k]);
  }
  put(c.script, f.script);
  put(c.model, f.model);
  c.essential.checked = f.essential;
  c.respawn.checked = f.respawn;
  if (![...c.blood.options].some((o) => o.value === String(f.blood))) c.blood.add(new Option(`Type ${f.blood}`, String(f.blood)));
  c.blood.value = String(f.blood);
  for (const k of ['level', 'disposition', 'reputation', 'gold', 'hello', 'fight', 'flee', 'alarm']) put(c[k], f[k]);

  c.autocalc.checked = f.autocalc;
  const auto = f.autocalc ? autoStats(f) : null;
  const s = auto || f;
  c.autoNote.textContent = f.autocalc ? (auto ? 'Worked out by the game from race, class, sex and level; abilities that fortify magicka '
    + 'add to it (untick to set them yourself).'
                                               : 'Worked out by the game (the race or class isn\'t in the load order).') : '';
  for (const k of ['health', 'magicka', 'fatigue']) { put(c[k], s[k]); c[k].disabled = f.autocalc || !editable(); }
  s.attributes.forEach((v, i) => { put(c.attributes[i], v); c.attributes[i].disabled = f.autocalc || !editable(); });
  s.skills.forEach((v, i) => { put(c.skills[i], v); c.skills[i].disabled = f.autocalc || !editable(); });

  fillWander(f);
  const kept = [];
  if (!isNew() && b.travel) kept.push(`${b.travel} travel destination${b.travel > 1 ? 's' : ''}`);
  if (!isNew() && b.packages.length) kept.push(`AI packages: ${b.packages.join(', ')}`);
  c.extras.textContent = kept.length ? `Also ${kept.join('; ')} (kept as they are).` : '';

  const cls = byId(lists.classes, f.class);
  const services = f.autocalc ? (cls ? cls.services : 0) : f.services;
  for (const cb of [...c.buys.querySelectorAll('input'), ...c.offers.querySelectorAll('input')]) {
    cb.checked = !!(services & Number(cb.dataset.bit));
    cb.disabled = f.autocalc || !editable();
  }
  c.servicesNote.textContent = f.autocalc ? `With auto-calculated stats, the NPC offers what the class ${cls ? cls.name : f.class} offers.` : '';

  fillItems(f);
  fillSpells(f);
  warnings(f);
}

function fillWander(f) {
  const box = ui.controls.wander;
  const w = f.wander;
  const on = editable();
  const put = (i, v) => { if (document.activeElement !== i) i.value = v; };
  if (box.dataset.mode === (w ? 'on' : 'off')) {
    if (w) {
      const [dist, dur, tod, ...idle] = box.querySelectorAll('input');
      put(dist, w.distance); put(dur, w.duration); put(tod, w.time);
      idle.forEach((i, k) => put(i, w.idle[k]));
    }
    return;
  }
  box.dataset.mode = w ? 'on' : 'off';
  box.innerHTML = '';
  if (!w) {
    const row = el('div', 'npc-row');
    row.appendChild(el('span', 'npc-hint', 'No wander package: stands where placed.'));
    const add = el('button', null, 'Add wander');
    add.disabled = !on;
    add.addEventListener('click', () => setFields({ wander: { distance: 128, duration: 5, time: 0,
                                                               idle: [60, 20, 20, 20, 0, 0, 0, 0], repeat: true } }));
    row.appendChild(add);
    box.appendChild(row);
    return;
  }
  const set = (k, v) => setFields({ wander: Object.assign({}, fields().wander, { [k]: v }) });
  const row = el('div', 'npc-row');
  box.appendChild(row);
  const dist = labelled(row, 'Distance', numberInput(0, 32767, (v) => set('distance', v)), 'small');
  dist.parentElement.title = 'How far they wander (0: they stay where placed)';
  const dur = labelled(row, 'Duration', numberInput(0, 32767, (v) => set('duration', v)), 'small');
  dur.parentElement.title = 'Hours';
  const tod = labelled(row, 'Time of day', numberInput(0, 255, (v) => set('time', v)), 'small');
  const rm = el('button', 'ghost', 'Remove');
  rm.title = 'No wander package: they stand still';
  rm.disabled = !on;
  rm.addEventListener('click', () => setFields({ wander: null }));
  row.appendChild(rm);
  const idles = el('div', 'npc-stats idle');
  box.appendChild(idles);
  const idle = w.idle.map((v, i) => labelled(idles, `Idle ${i + 2}`, numberInput(0, 255, (n) => {
    const a = [...fields().wander.idle];
    a[i] = n;
    set('idle', a);
  })));
  idles.title = 'How often each idle animation plays (chance, 0-100)';
  dist.value = w.distance; dur.value = w.duration; tod.value = w.time;
  idle.forEach((i, k) => { i.value = w.idle[k]; });
  for (const i of box.querySelectorAll('input')) i.disabled = !on;
}

function rows(box, arr, make, update) {
  while (box.children.length > arr.length) box.lastChild.remove();
  while (box.children.length < arr.length) box.appendChild(make(box.children.length));
  arr.forEach((v, i) => update(box.children[i], v, i));
}

function removeButton(onClick) {
  const b = el('button', 'ghost icon');
  b.innerHTML = icon('x');
  b.title = 'Remove';
  b.addEventListener('click', onClick);
  return b;
}

function fillItems(f) {
  const on = editable();
  rows(ui.controls.items, f.items, (i) => {
    const row = el('div', 'npc-line');
    const count = el('input', 'count');
    count.type = 'number';
    count.addEventListener('change', () => {
      const items = fields().items.map((x) => [...x]);
      items[i][0] = Math.round(Number(count.value)) || 0;
      setFields({ items: items.filter((x) => x[0] !== 0) });
    });
    const id = el('input', 'id');
    id.type = 'text';
    suggest(id, 'npc-items');
    id.addEventListener('change', () => {
      const items = fields().items.map((x) => [...x]);
      items[i][1] = id.value.trim();
      setFields({ items: items.filter((x) => x[1]) });
    });
    row.append(count, id, el('span', 'what'), removeButton(() => {
      setFields({ items: fields().items.filter((_, k) => k !== i) });
    }));
    return row;
  }, (row, [count, id]) => {
    const [c, i, what, rm] = row.children;
    if (document.activeElement !== c) c.value = count;
    if (document.activeElement !== i) i.value = id;
    const o = byId(lists.items, id);
    what.textContent = o ? [o.name, o.type].filter(Boolean).join(' · ') : 'not in the load order';
    what.classList.toggle('bad', !o);
    c.disabled = i.disabled = rm.disabled = !on;
  });
}

function fillSpells(f) {
  const on = editable();
  rows(ui.controls.spells, f.spells, (i) => {
    const row = el('div', 'npc-line');
    const id = el('input', 'id');
    id.type = 'text';
    suggest(id, 'npc-spells');
    id.addEventListener('change', () => {
      const spells = [...fields().spells];
      spells[i] = id.value.trim();
      setFields({ spells: spells.filter(Boolean) });
    });
    row.append(id, el('span', 'what'), removeButton(() => {
      setFields({ spells: fields().spells.filter((_, k) => k !== i) });
    }));
    return row;
  }, (row, id) => {
    const [i, what, rm] = row.children;
    if (document.activeElement !== i) i.value = id;
    const o = byId(lists.spells, id);
    what.textContent = o ? `${o.name || o.id} · ${o.type}` : 'not in the load order';
    what.classList.toggle('bad', !o);
    i.disabled = rm.disabled = !on;
  });
}

function warnings(f) {
  const w = [];
  if (!byId(lists.races, f.race)) w.push(`The race ${f.race || '(none)'} isn't in the load order: the plugin can't be saved like this.`);
  if (!byId(lists.classes, f.class)) w.push(`The class ${f.class || '(none)'} isn't in the load order: the plugin can't be saved like this.`);
  if (f.script && !lists.scripts.some((s) => s.toLowerCase() === f.script.toLowerCase())) w.push(`The script ${f.script} isn't in the load order.`);
  const c = ui.controls.warn;
  c.textContent = w.join('\n');
  c.style.display = w.length ? '' : 'none';
}

function changeLook(changes) {
  const f = Object.assign({}, fields(), changes);
  for (const [k, part] of [['head', 0], ['hair', 1]]) {
    const ok = bodyParts(f, part);
    if (!ok.some((x) => x.id.toLowerCase() === (f[k] || '').toLowerCase())) {
      changes[k] = (ok.find((x) => !x.vampire) || ok[0] || { id: f[k] }).id;
    }
  }
  setFields(changes);
}

function setAutocalc(on) {
  const f = fields();
  if (on) {
    const back = { autocalc: true };
    if (!isNew()) for (const k of STATS) back[k] = base().fields[k];
    setFields(back);
    return;
  }
  const auto = autoStats(f) || {};
  setFields(Object.assign({ autocalc: false }, ...STATS.filter((k) => auto[k] != null).map((k) => ({ [k]: auto[k] }))));
}

// --- New NPCs --------------------------------------------------------------------------

function dialog(html) {
  const bg = el('div', 'dialog-bg');
  bg.innerHTML = `<div class="dialog">${html}</div>`;
  document.body.appendChild(bg);
  bg.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); bg.remove(); } });
  return bg;
}

async function idProblem(id) {
  if (!id) return 'The id can\'t be empty.';
  if (id.length > 31) return 'An id can have 31 letters at most.';
  if (!/^[\x20-\x7e]+$/.test(id)) return 'Use plain letters, numbers, spaces and _ in the id.';
  if (edits()[id.toLowerCase()]) return 'There\'s already a new NPC with that id.';
  const taken = (await (await fetch('/api/npc/id?id=' + encodeURIComponent(id))).json()).taken;
  return taken ? `${taken[1]} already has ${taken[0]} with that id (ids are shared by every kind of object).` : '';
}

function copyDialog(f) {
  const bg = dialog('<h3>New NPC</h3>'
    + '<p class="dim"></p>'
    + '<label class="npc-f"><span>Id</span><input type="text" id="nc-id" maxlength="31" autocomplete="off"></label>'
    + '<label class="npc-f"><span>Name</span><input type="text" id="nc-name" maxlength="32"></label>'
    + '<p id="nc-err" class="bad" style="display:none;white-space:pre-wrap"></p>'
    + '<div class="bar"><button id="nc-cancel">Cancel</button><button id="nc-ok" class="primary">Create</button></div>');
  bg.querySelector('p.dim').textContent = `A copy of ${f.name || f.id} with everything they have: stats, looks, `
    + 'inventory, spells and wander (not travel destinations, other AI packages or dialogue).';
  const idIn = bg.querySelector('#nc-id'), nameIn = bg.querySelector('#nc-name'), err = bg.querySelector('#nc-err');
  idIn.value = `${f.id}_2`.slice(0, 31);
  nameIn.value = f.name;
  idIn.focus();
  idIn.select();
  return new Promise((resolve) => {
    const cancel = () => { bg.remove(); resolve(null); };
    bg.querySelector('#nc-cancel').addEventListener('click', cancel);
    bg.addEventListener('keydown', (e) => { if (e.key === 'Escape') resolve(null); });
    const ok = async () => {
      const id = idIn.value.trim();
      const problem = await idProblem(id);
      if (problem) { err.textContent = problem; err.style.display = ''; return; }
      const fresh = Object.assign({}, f, { id, name: nameIn.value, new: true });
      bg.remove();
      setEntry(id.toLowerCase(), fresh);
      resolve(fresh);
    };
    bg.querySelector('#nc-ok').addEventListener('click', ok);
    for (const i of [idIn, nameIn]) i.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); });
  });
}

async function copyAsNew() {
  const f = fields();
  const beside = cellNpcs().some((n) => n.id.toLowerCase() === f.id.toLowerCase());
  const n = await copyDialog(f);
  if (!n) return;
  if (beside) {
    await api.placeCopy(n, f.id);
    renderList();
    await show(n.id.toLowerCase());
  } else {
    close();
    api.placeCopy(n, null);
  }
}

// --- The creator: Add NPC makes a new NPC from scratch ---------------------------------

const CLOTHES = ['common_shirt_01', 'common_pants_01', 'common_shoes_01'];

function blank({ id, name, race, female, cls, level, clothes }) {
  const f = { new: true, id, name, model: '', race, class: cls, faction: '', rank: 0, head: '', hair: '', script: '',
              level, autocalc: true, attributes: new Array(8).fill(0), skills: new Array(27).fill(0),
              health: 0, magicka: 0, fatigue: 0, disposition: 50, reputation: 0, gold: 0, female,
              essential: false, respawn: false, blood: 0, items: [], spells: [],
              hello: 30, fight: 30, flee: 30, alarm: 0, services: 0,
              wander: { distance: 0, duration: 5, time: 0, idle: [60, 20, 20, 20, 0, 0, 0, 0], repeat: true } };
  for (const [k, part] of [['head', 0], ['hair', 1]]) {
    const ok = bodyParts(f, part);
    f[k] = (ok.find((x) => !x.vampire) || ok[0] || { id: '' }).id;
  }
  const auto = autoStats(f);
  if (auto) for (const k of STATS) f[k] = auto[k];
  const beast = (byId(lists.races, race)?.flags & 2) !== 0;
  if (clothes) f.items = CLOTHES.filter((c) => byId(lists.items, c) && !(beast && c.includes('shoes'))).map((c) => [1, c]);
  return f;
}

const idFrom = (name) => name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 28) || 'new_npc';

async function create() {
  if (!(await loadLists())) return null;
  if (!canEdit) return 'existing';
  const pick = (arr, id) => (byId(arr, id) || [...arr].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))[0] || { id: '' }).id;
  const bg = dialog('<h3>New NPC</h3>'
    + '<p class="dim">Places a new NPC at the clicked location. You can customize appearance, '
    + 'stats, inventory, AI, and dialogue in the NPC editor.</p>'
    + '<label class="npc-f"><span>Name</span><input type="text" id="nn-name" maxlength="32" placeholder="e.g. Jiub"></label>'
    + '<label class="npc-f"><span>ID</span><input type="text" id="nn-id" maxlength="31" autocomplete="off"></label>'
    + '<label class="npc-f"><span>Race</span><select id="nn-race"></select></label>'
    + '<label class="npc-f"><span>Sex</span><select id="nn-sex"><option value="m">Male</option><option value="f">Female</option></select></label>'
    + '<label class="npc-f"><span>Class</span><select id="nn-class"></select></label>'
    + '<label class="npc-f"><span>Level</span><input type="number" id="nn-level" min="1" max="100" value="1"></label>'
    + '<label class="check" id="nn-clothes-row"><input type="checkbox" id="nn-clothes" checked> Common clothes (shirt, pants, shoes)</label>'
    + '<p id="nn-err" class="bad" style="display:none;white-space:pre-wrap"></p>'
    + '<div class="bar"><button id="nn-existing" class="ghost" title="Place an existing NPC from your load order">'
    + 'Place an existing NPC…</button><span class="spacer"></span>'
    + '<button id="nn-cancel">Cancel</button><button id="nn-ok" class="primary">Create</button></div>');
  const q = (id) => bg.querySelector('#' + id);
  const nameIn = q('nn-name'), idIn = q('nn-id'), race = q('nn-race'), cls = q('nn-class'), err = q('nn-err');
  for (const [v, t] of options(lists.races)) race.add(new Option(t, v));
  for (const [v, t] of options(lists.classes)) cls.add(new Option(t, v));
  race.value = pick(lists.races, 'Dark Elf');
  cls.value = pick(lists.classes, 'Commoner');
  q('nn-clothes-row').style.display = CLOTHES.some((c) => byId(lists.items, c)) ? '' : 'none';
  let ownId = false;
  idIn.placeholder = 'Generated from name';
  nameIn.addEventListener('input', () => { if (!ownId) idIn.value = nameIn.value.trim() ? idFrom(nameIn.value) : ''; });
  idIn.addEventListener('input', () => { ownId = !!idIn.value.trim(); });
  nameIn.focus();
  return new Promise((resolve) => {
    const done = (v) => { bg.remove(); resolve(v); };
    q('nn-cancel').addEventListener('click', () => done(null));
    q('nn-existing').addEventListener('click', () => done('existing'));
    bg.addEventListener('keydown', (e) => { if (e.key === 'Escape') resolve(null); });
    const ok = async () => {
      const say = (t) => { err.textContent = t; err.style.display = ''; };
      const name = nameIn.value.trim();
      if (!name) { nameIn.focus(); return say('Please enter a name.'); }
      let id = idIn.value.trim();
      if (!ownId) {
        const root = idFrom(name);
        id = root;
        for (let k = 2; await idProblem(id) && k < 100; k++) id = `${root}_${k}`;
      }
      const problem = await idProblem(id);
      if (problem) { idIn.focus(); return say(problem); }
      const level = Math.min(100, Math.max(1, Math.round(Number(q('nn-level').value)) || 1));
      const f = blank({ id, name, race: race.value, female: q('nn-sex').value === 'f', cls: cls.value, level,
                        clothes: q('nn-clothes').checked });
      setEntry(id.toLowerCase(), f);
      done(f);
    };
    q('nn-ok').addEventListener('click', ok);
    for (const i of [nameIn, idIn, q('nn-level')]) i.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); });
  });
}

function deleteNew() {
  const f = fields();
  const cells = placedIn(f.id);
  if (cells.length) {
    const bg = dialog('<h3>The NPC is placed</h3><p></p><div class="bar"><button class="primary">OK</button></div>');
    bg.querySelector('p').textContent = `${f.id} stands in ${cells.join(', ')}. `
      + 'Delete them there first, so no cell is left with an NPC that isn\'t there.';
    bg.querySelector('button').addEventListener('click', () => bg.remove());
    bg.querySelector('button').focus();
    return;
  }
  const bg = dialog('<h3>Delete NPC</h3><p></p><div class="bar"><button id="nd-cancel">Cancel</button>'
    + '<button id="nd-ok" class="primary">Delete</button></div>');
  bg.querySelector('p').textContent = `Delete ${f.name || f.id} (${f.id})? Undo brings it back.`;
  bg.querySelector('#nd-cancel').addEventListener('click', () => bg.remove());
  bg.querySelector('#nd-ok').addEventListener('click', () => {
    bg.remove();
    setEntry(ui.id, undefined);
    ui.id = null;
    $('npc-form').innerHTML = '<div class="npc-empty">Choose an NPC from the list.</div>';
    renderList();
    showList(true);
  });
  bg.querySelector('#nd-ok').focus();
}
