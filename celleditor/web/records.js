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
const KINDS = { WEAP: 'Weapon', ARMO: 'Armour', CLOT: 'Clothing', MISC: 'Misc item', BOOK: 'Book', ALCH: 'Potion', INGR: 'Ingredient',
                LIGH: 'Light', STAT: 'Static', ACTI: 'Activator', DOOR: 'Door' };
const ENCHANT_TYPES = ['Cast once', 'Cast when strikes', 'Cast when used', 'Constant effect'];
const SPELL_TYPES = ['Spell', 'Ability', 'Blight', 'Disease', 'Curse', 'Power'];
const NO_USE = 'Unused';
const NO_USE_WHY = 'Not placed in a cell and not referenced by another record in this project. Scripts may still use it.';

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
    for (const [k, n] of Object.entries(e.npcs || {})) if (holds(n.items, id)) out.push(`Carried by ${nameOf(n, k)}`);
    for (const [k, c] of Object.entries(e.containers || {})) if (holds(c.contents, id)) out.push(`In ${nameOf(c, k)}`);
    const locks = Object.values(e.props || {}).filter((p) => low(p.key) === id).length;
    if (locks) out.push(`Key for ${plural(locks, 'lock', 'locks')}`);
  } else if (what === 'enchant') {
    for (const [k, it] of Object.entries(e.items || {})) if (low(it.enchant) === id) out.push(`Used by ${nameOf(it, k)}`);
  } else if (what === 'spell') {
    for (const [k, n] of Object.entries(e.npcs || {})) if (holds(n.spells, id)) out.push(`Known by ${nameOf(n, k)}`);
  }
  return out;
}

function useOf(id, what) {
  const at = placed(id), by = namedBy(id, what);
  const cells = [...new Set(at.map((p) => p.cell))];
  const parts = [];
  if (at.length) parts.push(`Placed ${at.length === 1 ? '' : at.length + '× '}in ${cells.slice(0, 2).join(', ')}${cells.length > 2 ? ` and ${cells.length - 2} more` : ''}`);
  parts.push(...by);
  return { at, text: parts.join(' · '), unused: !parts.length };
}

function tabs() {
  const e = api.state.edits;
  const rows = (sec, make) => Object.entries(e[sec] || {}).map(([k, v]) => make(k, v)).filter(Boolean)
    .sort((a, b) => a.name.localeCompare(b.name));
  // Delete takes a new record out of the edits (only one nothing uses); Revert drops the changes to a game record
  const remover = (sec, k, name, fresh, used, also = null) => ({
    label: fresh ? 'Delete' : 'Revert',
    blocked: fresh && used ? `In use (${used}). Remove those uses first.` : '',
    title: fresh ? 'Remove it from the project' : 'Drop this project\'s changes to it',
    run: () => {
      api.change((edits) => { delete edits[sec][k]; also?.(edits); });
      api.status(`${fresh ? 'Deleted' : 'Reverted'} ${name}. Undo brings ${fresh ? 'it' : 'the changes'} back.`);
    },
  });
  const objectRow = (k, v, what, kind, sec, also) => {
    const fresh = !!v.new, u = useOf(low(v.id || k), what);
    return { del: remover(sec, k, nameOf(v, k), fresh, u.text, also), name: nameOf(v, k), id: v.id || k, tag: v.copy_of ? `Copy of ${v.copy_of}` : fresh ? 'New' : 'Modified', kind,
             use: u.text, unused: fresh && u.unused, at: u.at };
  };
  const magic = (kind, what, types) => rows('magic', (k, v) => {
    if (v.kind !== kind) return null;
    const u = useOf(low(v.id), what);
    return { name: v.name || v.id, id: v.id, tag: 'New', kind: types[v.type] || '', use: u.text, unused: u.unused, at: [],
             del: remover('magic', k, v.name || v.id, true, u.text),
             note: (api.magicLines(v.id) || []).join(', ') };
  });
  return [
    { id: 'items', title: 'Items and objects', empty: 'No items or objects yet.', add: ['New item or object…', api.newItem],
      rows: rows('items', (k, v) => Object.assign(objectRow(k, v, 'item', KINDS[v.kind] || 'Item', 'items'),
                                                  v.new ? { edit: () => api.editItem(v.id) } : {})) },
    { id: 'npcs', title: 'NPCs', empty: 'No NPCs yet.', add: ['New NPC…', api.newNpc, true],
      rows: rows('npcs', (k, v) => Object.assign(objectRow(k, v, 'npc', [v.race, v.class].filter(Boolean).join(' '), 'npcs', (edits) => {
        for (const [d, r] of Object.entries(edits.dialogue || {})) if (r.new && low(r.actor) === k) delete edits.dialogue[d];
      }),
                                                 { name: v.name || api.npcName(k), edit: () => api.editNpc(v.id || k), leave: true })) },
    { id: 'enchants', title: 'Enchantments', empty: 'No enchantments yet.',
      add: ['New enchantment…', () => api.newMagic('ENCH')], rows: magic('ENCH', 'enchant', ENCHANT_TYPES) },
    { id: 'spells', title: 'Spells', empty: 'No spells yet.',
      add: ['New spell…', () => api.newMagic('SPEL')], rows: magic('SPEL', 'spell', SPELL_TYPES) },
    { id: 'containers', title: 'Containers', empty: 'No modified containers. To change one, select it in a cell and choose Contents.',
      rows: rows('containers', (k, v) => Object.assign(objectRow(k, v, 'container', plural((v.contents || []).length, 'item type', 'item types'), 'containers'))) },
    { id: 'cells', title: 'Cells', empty: 'No new cells yet.', add: ['New cell…', api.newCell, true],
      rows: rows('cells', (k, v) => {
        if (!v.new) return null;
        const objects = (e.added || []).filter((a) => a.cell === v.name && !(e.deleted || []).includes('added|' + a.uid)).length;
        const doors = Object.values(e.doors || {}).filter((d) => d.cell === v.name).length;
        return { name: v.name, id: '', tag: 'New', kind: 'Interior',
                 use: `${plural(objects, 'object', 'objects')} · ${doors ? plural(doors, 'door leads', 'doors lead') + ' here' : 'no doors lead here'}`,
                 unused: !doors, why: 'No door has this cell as its destination, so the player can\'t reach it without a script.',
                 at: [], edit: () => api.editCell(v.name), go: () => api.goCell(v.name) };
      }) },
    { id: 'dialogue', title: 'Dialogue', empty: 'No dialogue yet. Add responses on an NPC\'s Dialogue tab.',
      rows: rows('dialogue', (k, v) => ({
        name: v.topic || k.split('|')[0], id: '', tag: v.deleted ? 'Deleted' : v.new ? 'New' : 'Modified', kind: v.actor ? `Speaker: ${api.npcName(v.actor)}` : '',
        use: v.text ? `“${v.text.length > 110 ? v.text.slice(0, 110) + '…' : v.text}”` : '', unused: false, at: [],
        ...(v.actor ? { edit: () => api.editNpc(v.actor), leave: true } : {}) })) },
  ];
}

let last = 'items';

function open(tab = null) {
  if (document.querySelector('.records-dialog')) return;
  const bg = el('div', 'dialog-bg');
  bg.innerHTML = `<div class="dialog records-dialog"><div class="rc-head"><h3>Records</h3><span class="spacer"></span><button class="rc-close">Close</button></div>
    <p class="dim rc-sub">Records this project adds or modifies, including unsaved changes.</p>
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
      if (r.del) {
        const b = acts.appendChild(el('button', r.del.label === 'Delete' ? 'rc-del' : null, r.del.label));
        b.disabled = !!r.del.blocked;
        b.title = r.del.blocked || r.del.title;
        b.addEventListener('click', () => { r.del.run(); draw(); });
      }
    }
    const unused = t.rows.filter((r) => r.unused).length;
    q('.rc-note').textContent = !unused ? '' : t.id === 'cells' ? `${unused} with no door leading to ${unused === 1 ? 'it' : 'them'}.`
      : `${unused} unused. Scripts may still use ${unused === 1 ? 'it' : 'them'}.`;
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
