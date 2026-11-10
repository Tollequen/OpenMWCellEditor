// Records: what the project made or changed (items, NPCs, magic, containers, cells, dialogue), and where it's used

let api = null;

export function setupRecords(a) {
  api = a;
  return { open };
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};
const low = (s) => String(s || '').toLowerCase();
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const KINDS = { WEAP: 'Weapon', ARMO: 'Armour', CLOT: 'Clothing', MISC: 'Misc item', BOOK: 'Book' };
const ENCHANT_TYPES = ['Cast once', 'Cast when strikes', 'Cast when used', 'Constant effect'];
const SPELL_TYPES = ['Spell', 'Ability', 'Blight', 'Disease', 'Curse', 'Power'];
const NO_USE = 'Not placed or used by anything made here';
const NO_USE_WHY = 'Nothing in this project places it, carries it or names it. A script or another mod could still use it.';

// where the edits place an object id: [{key, cell}]
function placed(id) {
  const e = api.state.edits, gone = new Set(e.deleted || []), out = [];
  const cellOf = (k) => (k.startsWith('added|') ? (e.added.find((a) => 'added|' + a.uid === k) || {}).cell : k.split('|')[0]);
  for (const a of e.added || []) {
    if (low(a.id) === id && !gone.has('added|' + a.uid)) out.push({ key: 'added|' + a.uid, cell: a.cell });
  }
  for (const [k, v] of Object.entries(e.replaced || {})) {
    if (low(v) === id && !gone.has(k)) out.push({ key: k, cell: cellOf(k) });
  }
  return out.filter((p) => p.cell);
}

const nameOf = (v, k) => v.name || v.id || k;
const holds = (list, id) => (list || []).some((x) => low(Array.isArray(x) ? x[1] : x) === id);

// the other records of the edits that name an id
function namedBy(id, what) {
  const e = api.state.edits, out = [];
  if (what === 'item') {
    for (const [k, n] of Object.entries(e.npcs || {})) if (holds(n.items, id)) out.push(`carried by ${nameOf(n, k)}`);
    for (const [k, c] of Object.entries(e.containers || {})) if (holds(c.contents, id)) out.push(`inside ${nameOf(c, k)}`);
    const locks = Object.values(e.props || {}).filter((p) => low(p.key) === id).length;
    if (locks) out.push(`the key of ${plural(locks, 'lock', 'locks')}`);
  } else if (what === 'enchant') {
    for (const [k, it] of Object.entries(e.items || {})) if (low(it.enchant) === id) out.push(`on ${nameOf(it, k)}`);
  } else if (what === 'spell') {
    for (const [k, n] of Object.entries(e.npcs || {})) if (holds(n.spells, id)) out.push(`known by ${nameOf(n, k)}`);
  }
  return out;
}

function useOf(id, what) {
  const at = placed(id), by = namedBy(id, what);
  const cells = [...new Set(at.map((p) => p.cell))];
  const parts = [];
  if (at.length) parts.push(`Placed ${at.length === 1 ? 'once' : at.length + ' times'} in ${cells.slice(0, 2).join(', ')}${cells.length > 2 ? ` and ${cells.length - 2} more` : ''}`);
  parts.push(...by);
  return { at, text: parts.join(' · '), unused: !parts.length };
}

function tabs() {
  const e = api.state.edits;
  const rows = (sec, make) => Object.entries(e[sec] || {}).map(([k, v]) => make(k, v)).filter(Boolean)
    .sort((a, b) => a.name.localeCompare(b.name));
  const objectRow = (k, v, what, kind) => {
    const fresh = !!v.new, u = useOf(low(v.id || k), what);
    return { name: nameOf(v, k), id: v.id || k, tag: v.copy_of ? `Copy of ${v.copy_of}` : fresh ? 'New' : 'Changed', kind,
             use: fresh || u.at.length ? u.text : 'One of the game\'s, changed here', unused: fresh && u.unused, at: u.at };
  };
  const magic = (kind, what, types) => rows('magic', (k, v) => {
    if (v.kind !== kind) return null;
    const u = useOf(low(v.id), what);
    return { name: v.name || v.id, id: v.id, tag: 'New', kind: types[v.type] || '', use: u.text, unused: u.unused, at: [],
             note: (api.magicLines(v.id) || []).join(', ') };
  });
  return [
    { id: 'items', title: 'Items', empty: 'No items made or changed yet.', add: ['New item…', api.newItem],
      rows: rows('items', (k, v) => Object.assign(objectRow(k, v, 'item', KINDS[v.kind] || 'Item'),
                                                  v.new ? { edit: () => api.editItem(v.id) } : {})) },
    { id: 'npcs', title: 'NPCs', empty: 'No NPCs made or changed yet.', add: ['New NPC…', api.newNpc, true],
      rows: rows('npcs', (k, v) => Object.assign(objectRow(k, v, 'npc', [v.race, v.class].filter(Boolean).join(' ')),
                                                 { name: v.name || api.npcName(k), edit: () => api.editNpc(v.id || k), leave: true })) },
    { id: 'enchants', title: 'Enchantments', empty: 'No enchantments made yet.',
      add: ['New enchantment…', () => api.newMagic('ENCH')], rows: magic('ENCH', 'enchant', ENCHANT_TYPES) },
    { id: 'spells', title: 'Spells', empty: 'No spells made yet.',
      add: ['New spell…', () => api.newMagic('SPEL')], rows: magic('SPEL', 'spell', SPELL_TYPES) },
    { id: 'containers', title: 'Containers', empty: 'No container\'s contents changed yet. Select a chest or sack and choose Contents.',
      rows: rows('containers', (k, v) => Object.assign(objectRow(k, v, 'container', plural((v.contents || []).length, 'kind of item', 'kinds of items') + ' inside'))) },
    { id: 'cells', title: 'Cells', empty: 'No cells made yet.', add: ['New cell…', api.newCell, true],
      rows: rows('cells', (k, v) => {
        if (!v.new) return null;
        const objects = (e.added || []).filter((a) => a.cell === v.name && !(e.deleted || []).includes('added|' + a.uid)).length;
        const doors = Object.values(e.doors || {}).filter((d) => d.cell === v.name).length;
        return { name: v.name, id: '', tag: 'New', kind: 'Interior',
                 use: `${plural(objects, 'object', 'objects')} · ${doors ? plural(doors, 'door leads', 'doors lead') + ' here' : 'no door leads here yet'}`,
                 unused: !doors, why: 'The player can\'t get in until a door\'s destination is set to this cell (or a script moves them).',
                 at: [], edit: () => api.editCell(v.name), go: () => api.goCell(v.name) };
      }) },
    { id: 'dialogue', title: 'Dialogue', empty: 'No responses written or changed yet. They\'re on an NPC\'s Dialogue tab.',
      rows: rows('dialogue', (k, v) => ({
        name: v.topic || k.split('|')[0], id: '', tag: v.deleted ? 'Deleted' : v.new ? 'New' : 'Changed', kind: v.actor ? `said by ${api.npcName(v.actor)}` : '',
        use: v.text ? `“${v.text.length > 110 ? v.text.slice(0, 110) + '…' : v.text}”` : '', unused: false, at: [],
        ...(v.actor ? { edit: () => api.editNpc(v.actor), leave: true } : {}) })) },
  ];
}

let last = 'items';

function open(tab = null) {
  if (document.querySelector('.records-dialog')) return;
  const bg = el('div', 'dialog-bg');
  bg.innerHTML = `<div class="dialog records-dialog"><div class="rc-head"><h3>Records</h3><span class="spacer"></span><button class="rc-close">Close</button></div>
    <p class="dim rc-sub">What this project made or changed, apart from the objects standing in its cells. Unsaved ones are here too.</p>
    <div class="npc-tabs rc-tabs" role="tablist"></div><div class="rc-list"></div>
    <div class="bar"><span class="npc-hint rc-note"></span><span class="spacer"></span><button class="primary rc-add"></button></div></div>`;
  document.body.appendChild(bg);
  const q = (c) => bg.querySelector(c);
  let cur = tab || last;
  const top = () => [...document.querySelectorAll('.dialog-bg')].pop() === bg;
  const watch = new MutationObserver(() => { if (bg.isConnected && top()) draw(); });
  const close = () => {
    watch.disconnect();
    document.removeEventListener('keydown', onKey, true);
    bg.remove();
  };
  const onKey = (e) => { if (e.key === 'Escape' && top()) { e.preventDefault(); e.stopPropagation(); close(); } };
  const leaving = (act) => () => { close(); act(); };

  function draw() {
    const all = tabs();
    const t = all.find((x) => x.id === cur) || all[0];
    last = cur = t.id;
    const bar = q('.rc-tabs');
    bar.innerHTML = '';
    for (const x of all) {
      const b = bar.appendChild(el('button', 'npc-tab' + (x === t ? ' sel' : ''), `${x.title} (${x.rows.length})`));
      b.setAttribute('role', 'tab');
      b.addEventListener('click', () => { cur = x.id; draw(); });
    }
    const list = q('.rc-list');
    list.innerHTML = '';
    if (!t.rows.length) list.appendChild(el('div', 'npc-hint rc-empty', t.empty));
    for (const r of t.rows) {
      const row = list.appendChild(el('div', 'rc-row'));
      const text = row.appendChild(el('div', 'rc-text'));
      const head = text.appendChild(el('div', 'rc-name'));
      head.appendChild(el('b', null, r.name));
      if (r.id && r.id !== r.name) head.appendChild(el('span', 'dim', r.id));
      head.appendChild(el('span', 'rc-tag' + (r.tag === 'New' ? ' new' : ''), r.tag));
      if (r.kind) head.appendChild(el('span', 'dim', r.kind));
      if (r.note) text.appendChild(el('div', 'rc-use', r.note));
      const use = text.appendChild(el('div', 'rc-use' + (r.unused ? ' unused' : ''), r.unused && !r.use ? NO_USE : r.use));
      if (r.unused) use.title = r.why || NO_USE_WHY;
      const acts = row.appendChild(el('div', 'rc-acts'));
      if (r.at.length) {
        const go = acts.appendChild(el('button', null, 'Show'));
        go.title = `Go to it in ${r.at[0].cell}`;
        go.addEventListener('click', leaving(() => api.goTo(r.at[0].key, r.at[0].cell)));
      }
      if (r.go) acts.appendChild(el('button', null, 'Go there')).addEventListener('click', leaving(r.go));
      if (r.edit) acts.appendChild(el('button', null, 'Edit…')).addEventListener('click', r.leave ? leaving(r.edit) : r.edit);
    }
    const unused = t.rows.filter((r) => r.unused).length;
    q('.rc-note').textContent = unused ? `${unused} not used yet (in yellow). A script could still use them.` : '';
    const add = q('.rc-add');
    add.style.display = t.add ? '' : 'none';
    if (t.add) {
      add.textContent = t.add[0];
      add.onclick = t.add[2] ? leaving(t.add[1]) : async () => { await t.add[1](); if (bg.isConnected) draw(); };
    }
  }

  q('.rc-close').addEventListener('click', close);
  bg.addEventListener('click', (e) => { if (e.target === bg) close(); });
  document.addEventListener('keydown', onKey, true);
  watch.observe(document.body, { childList: true });
  api.refreshMagic().then(() => { if (bg.isConnected) draw(); }).catch(() => {});
  draw();
}
