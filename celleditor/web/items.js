// Item and object editor: a new record from scratch, or a placed item's record (or a copy of it for that one)
import * as THREE from 'three';
import { icon } from './icons.js';
import { setSuggestions, suggest } from './suggest.js';
import { askScope } from './contents.js';
import { choose, withChooser } from './choose.js';

let api = null;
let lists = null, listData = null;

export const KINDS = { WEAP: 'Weapon', ARMO: 'Armor', CLOT: 'Clothing', MISC: 'Misc', BOOK: 'Book', ALCH: 'Potion',
                       INGR: 'Ingredient', LIGH: 'Light', CONT: 'Container', STAT: 'Static', ACTI: 'Activator', DOOR: 'Door' };
// what the kinds have: an icon, value and weight (things that can be carried), a name, a script, an enchantment
const CARRIED = ['WEAP', 'ARMO', 'CLOT', 'MISC', 'BOOK', 'ALCH', 'INGR', 'LIGH'];
const ENCHANTED = ['WEAP', 'ARMO', 'CLOT', 'BOOK'];
const LIGHT_FLAGS = [[2, 'Can be carried (a torch or lantern)'], [16, 'Fire'], [8, 'Flickers'], [64, 'Flickers slowly'],
  [128, 'Pulses'], [256, 'Pulses slowly'], [4, 'Darkens instead of lighting'], [32, 'Off until carried']];
const WEAPON_TYPES = ['Short blade, one hand', 'Long blade, one hand', 'Long blade, two hands', 'Blunt, one hand',
  'Blunt, two hands (close)', 'Blunt, two hands (wide)', 'Spear, two hands', 'Axe, one hand', 'Axe, two hands',
  'Bow', 'Crossbow', 'Thrown', 'Arrow', 'Bolt'];
const ARMOR_TYPES = ['Helmet', 'Cuirass', 'Left pauldron', 'Right pauldron', 'Greaves', 'Boots', 'Left gauntlet',
  'Right gauntlet', 'Shield', 'Left bracer', 'Right bracer'];
const CLOTHING_TYPES = ['Pants', 'Shoes', 'Shirt', 'Belt', 'Robe', 'Right glove', 'Left glove', 'Skirt', 'Ring', 'Amulet'];
// worn slots of armour and clothing types, as actor.py has them
const ARMOR_SLOTS = ['helmet', 'cuirass', 'lpauldron', 'rpauldron', 'greaves', 'boots', 'lgauntlet', 'rgauntlet',
  'carriedleft', 'lgauntlet', 'rgauntlet'];
const CLOTHING_SLOTS = [['pants'], ['boots'], ['shirt'], ['belt'], ['robe'], ['rgauntlet'], ['lgauntlet'], ['skirt'],
  ['lring', 'rring'], ['amulet']];
const PARTS = ['Head', 'Hair', 'Neck', 'Chest', 'Groin', 'Skirt', 'Right hand', 'Left hand', 'Right wrist',
  'Left wrist', 'Shield', 'Right forearm', 'Left forearm', 'Right upper arm', 'Left upper arm', 'Right foot',
  'Left foot', 'Right ankle', 'Left ankle', 'Right knee', 'Left knee', 'Right upper leg', 'Left upper leg',
  'Right pauldron', 'Left pauldron', 'Weapon', 'Tail'];

// A body part record's kind (BYDT part), and the kind each worn slot (PARTS) takes
const BODY_KINDS = ['Head', 'Hair', 'Neck', 'Chest', 'Groin', 'Hand', 'Wrist', 'Forearm', 'Upper arm', 'Foot', 'Ankle',
  'Knee', 'Upper leg', 'Clavicle', 'Tail'];
const SLOT_BODY = [0, 1, 2, 3, 4, 4, 5, 5, 6, 6, -1, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, -1, 14];

export function setupItems(a) {
  api = a;
  return { create, edit, newItems, newObjects };
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

function itemLists() {
  lists = lists || fetch('/api/npc/lists').then((r) => r.json()).then((l) => {
    setSuggestions('item-scripts', l.scripts.map((s) => [s, '']));
    setSuggestions('item-parts', l.wearParts.map((p) => [p.id, `${PARTS[p.part] || p.part}${p.female ? ', female' : ''}${p.armor ? ', armour' : ''}`]));
    listData = l;
    return l;
  }).catch((err) => { lists = null; throw err; });
  return lists;
}

// the new items of the edits, as the item lists have them (for the wardrobe, contents and the catalog)
function newItems() {
  return newObjects().filter((o) => o.carried);
}

// every new record that can be placed: the items, and statics, activators, doors and containers made from scratch
function newObjects() {
  const made = Object.values(api.state.edits.containers || {}).filter((c) => c.new && !c.copy_of).map((c) => ({
    id: c.id, name: c.name, type: 'Container', mesh: c.model, file: api.state.data.project.plugin }));
  return [...made, ...Object.values(api.state.edits.items || {}).filter((v) => v.new && v.kind in KINDS).map((v) => ({
    carried: CARRIED.includes(v.kind),
    id: v.id, name: v.name, type: KINDS[v.kind], icon: v.icon, mesh: v.model, file: api.state.data.project.plugin,
    ...(v.kind === 'ARMO' ? { slots: [ARMOR_SLOTS[v.atype]].filter(Boolean), rating: v.rating } : {}),
    ...(v.kind === 'CLOT' ? { slots: CLOTHING_SLOTS[v.ctype] || [], value: v.value } : {}),
    ...(v.kind === 'MISC' && v.mflags & 1 ? { key: true } : {}),
  }))];
}

let magicInfo = null;
function effectsInfo() {
  magicInfo = magicInfo || fetch('/api/magic/info', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    .then((r) => r.json()).catch((err) => { magicInfo = null; throw err; });
  return magicInfo;
}

const idFrom = (name) => name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 28) || 'new_item';

// --- A small model viewer ------------------------------------------------------------

function viewer(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1c1c24);
  const camera = new THREE.PerspectiveCamera(35, 1, 1, 100000);
  camera.up.set(0, 0, 1);
  scene.add(new THREE.AmbientLight(0xffffff, 1.4));
  const light = new THREE.DirectionalLight(0xfff2dd, 1.6);
  light.position.set(-0.4, -0.3, 1);
  camera.add(light);
  scene.add(camera);
  const group = new THREE.Group();
  scene.add(group);
  const v = { yaw: 0.6, pitch: 0.35, dist: 100, center: new THREE.Vector3(), dirty: true, token: 0, alive: true };
  const draw = () => {
    if (!v.alive) return;
    if (v.dirty && canvas.clientWidth && canvas.clientHeight) {
      v.dirty = false;
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * renderer.getPixelRatio())) renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.position.set(v.center.x + Math.sin(v.yaw) * Math.cos(v.pitch) * -v.dist,
                          v.center.y + Math.cos(v.yaw) * Math.cos(v.pitch) * -v.dist, v.center.z + Math.sin(v.pitch) * v.dist);
      camera.near = Math.max(0.5, v.dist / 200);
      camera.far = v.dist * 20;
      camera.updateProjectionMatrix();
      camera.lookAt(v.center);
      renderer.render(scene, camera);
    }
    requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => { canvas.setPointerCapture(e.pointerId); drag = { x: e.clientX, y: e.clientY }; });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    v.yaw -= (e.clientX - drag.x) * 0.01;
    v.pitch = Math.max(-1.4, Math.min(1.4, v.pitch + (e.clientY - drag.y) * 0.01));
    drag = { x: e.clientX, y: e.clientY };
    v.dirty = true;
  });
  canvas.addEventListener('pointerup', () => { drag = null; });
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); v.dist *= Math.exp(e.deltaY * 0.001); v.dirty = true; }, { passive: false });
  new ResizeObserver(() => { v.dirty = true; }).observe(canvas);
  return {
    async show(path) {
      const token = ++v.token;
      const parts = path ? await api.meshParts(path) : [];
      if (token !== v.token) return;
      group.clear();
      for (const p of parts) group.add(new THREE.Mesh(p.geometry, p.material));
      const box = new THREE.Box3().setFromObject(group);
      if (box.isEmpty()) { v.center.set(0, 0, 0); v.dist = 100; } else {
        const s = box.getBoundingSphere(new THREE.Sphere());
        v.center.copy(s.center);
        v.dist = Math.max(s.radius, 4) / Math.sin((camera.fov / 2) * Math.PI / 180) * 1.05;
      }
      v.dirty = true;
    },
    redraw() { v.dirty = true; },
    dispose() { v.alive = false; renderer.dispose(); },
  };
}

// --- File browser (models and icons) -------------------------------------------------

export function browse(folder, current) {
  return new Promise((resolve) => {
    const bg = el('div', 'dialog-bg');
    bg.innerHTML = `<div class="dialog files-dialog"><h3>${folder === 'icons' ? 'Choose an icon' : 'Choose a model'}</h3>
      <input type="search" class="fb-search" placeholder="Words in the file's path, e.g. ${folder === 'icons' ? 'dagger' : 'w iron'}">
      <div class="fb-list wr-list${folder === 'icons' ? ' grid' : ''}" tabindex="0"></div><div class="npc-hint fb-more"></div>
      <div class="bar"><button class="fb-cancel">Cancel</button><button class="primary fb-ok">Choose</button></div></div>`;
    document.body.appendChild(bg);
    const q = (c) => bg.querySelector(c);
    let pick = current || '';
    let timer = null;
    const done = (v) => { bg.remove(); resolve(v); };
    const load = async () => {
      const res = await fetch('/api/files', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                              body: JSON.stringify({ folder, query: q('.fb-search').value }) });
      const out = await res.json();
      const list = q('.fb-list');
      list.innerHTML = '';
      for (const f of out.files || []) {
        const row = list.appendChild(el('div', 'wr-row' + (f.toLowerCase() === pick.toLowerCase() ? ' sel' : '')));
        if (folder === 'icons') {
          const img = row.appendChild(el('img', 'ic'));
          api.icon(f).then((u) => { if (u) img.src = u; });
        }
        row.appendChild(el('div', 'n', f));
        row.title = f;
        row.addEventListener('click', () => {
          pick = f;
          list.querySelectorAll('.wr-row').forEach((r) => r.classList.toggle('sel', r === row));
        });
        row.addEventListener('dblclick', () => done(f));
      }
      q('.fb-more').textContent = out.more ? `${out.more} more: add words to narrow it down.` : '';
    };
    q('.fb-search').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 150); });
    q('.fb-cancel').addEventListener('click', () => done(null));
    q('.fb-ok').addEventListener('click', () => done(pick || null));
    bg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); done(null); } else if (e.key === 'Enter') { e.preventDefault(); done(pick || null); }
    });
    q('.fb-search').value = current ? current.split('\\').pop().replace(/\.(nif|tga|dds)$/i, '').replace(/_/g, ' ') : '';
    load();
    q('.fb-search').focus();
    q('.fb-search').select();
  });
}

// --- The editor ----------------------------------------------------------------------

async function itemInfo(id) {
  const res = await fetch('/api/item', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                         body: JSON.stringify({ id, edits: api.state.edits.items }) });
  if (!res.ok) throw new Error(`${id} isn't an item this editor can change`);
  return res.json();
}

// place: what Create does with the new item (default: the click that puts it in the cell)
async function create(place = null, kind = 'MISC') {
  try { await Promise.all([itemLists(), effectsInfo()]); } catch (err) { api.status('The lists didn\'t load.', true); return; }
  open({ new: true, kind, id: '', name: '', model: '', icon: '', script: '', enchant: '', weight: 1, value: 1,
         enchant_pts: 0, ...JSON.parse(JSON.stringify(DEFAULTS[kind])), own: true, canEdit: true }, null, place);
}

async function edit(r) {
  let info;
  try { [info] = await Promise.all([itemInfo(r.src), itemLists(), effectsInfo()]); } catch (err) { api.status(err.message, true); return; }
  open(info, r);
}

const DEFAULTS = {
  WEAP: { wtype: 0, health: 100, speed: 1, reach: 1, chop_min: 1, chop_max: 5, slash_min: 1, slash_max: 5,
          thrust_min: 1, thrust_max: 5, wflags: 0 },
  ARMO: { atype: 1, health: 100, rating: 5, parts: [] },
  CLOT: { ctype: 2, parts: [] },
  MISC: { mflags: 0 },
  BOOK: { scroll: 0, skill: -1, text: '' },
  ALCH: { auto: true, effects: [] },
  INGR: { effects: [] },
  LIGH: { time: -1, radius: 128, color: [255, 200, 120], lflags: 1, sound: '' },
  CONT: { capacity: 100 },
  STAT: {},
  ACTI: {},
  DOOR: { open_sound: '', close_sound: '' },
};

function open(info, r, place = null) {
  const f = JSON.parse(JSON.stringify(info));
  const isNew = !!info.new && !r;
  const editable = isNew || ((info.canEdit || (info.canCopy && !info.own)) && r?.editable);
  const copyOnly = editable && !isNew && !info.canEdit;
  const bg = el('div', 'dialog-bg');
  bg.innerHTML = `<div class="dialog item-dialog"><h3 class="it-title"></h3><p class="dim it-sub"></p>
    <div class="it">
      <div class="it-form"></div>
      <div class="it-side"><canvas class="it-canvas"></canvas>
        <div class="it-iconrow"><img class="ic it-icon" alt=""><span class="npc-hint">Drag to turn, scroll to zoom</span></div></div>
    </div>
    <div class="npc-hint it-note"></div>
    <div class="bar"><button class="it-cancel">Cancel</button><button class="primary it-done">${isNew ? 'Create' : 'Done'}</button></div></div>`;
  document.body.appendChild(bg);
  const q = (c) => bg.querySelector(c);
  const view = viewer(q('.it-canvas'));
  const form = q('.it-form');
  const close = () => { view.dispose(); bg.remove(); };
  q('.it-title').textContent = isNew ? 'New item' : `${info.name || info.id}`;
  q('.it-sub').textContent = isNew ? 'A new item in your plugin.' : [info.id, KINDS[info.kind], info.file ? `from ${info.file}` : 'new',
    !editable ? 'read-only in this project' : copyOnly ? 'changes make a copy for this one' : ''].filter(Boolean).join(' · ');

  const showIcon = () => {
    const img = q('.it-icon');
    img.removeAttribute('src');
    if (f.icon) api.icon(f.icon).then((u) => { if (u) img.src = u; });
  };
  const row = (label, control) => {
    const l = form.appendChild(el('label', 'opt'));
    l.appendChild(el('span', null, label));
    l.appendChild(control);
    control.disabled = !editable;
    return control;
  };
  const text = (k, label, opts = {}) => {
    const i = el('input');
    i.type = 'text';
    i.value = f[k] ?? '';
    if (opts.placeholder) i.placeholder = opts.placeholder;
    if (opts.max) i.maxLength = opts.max;
    i.addEventListener('input', () => { f[k] = i.value.trim(); opts.after?.(); });
    if (opts.list) suggest(i, opts.list);
    if (!opts.pick) return row(label, i);
    i.disabled = !editable;
    const l = form.appendChild(el('label', 'opt'));
    l.appendChild(el('span', null, label));
    l.appendChild(withChooser(i, opts.pick));
    return i;
  };
  const num = (k, label, opts = {}) => {
    const i = el('input');
    i.type = 'number';
    if (opts.step) i.step = opts.step;
    if (opts.min != null) i.min = opts.min;
    if (opts.max != null) i.max = opts.max;
    i.value = f[k] ?? 0;
    i.addEventListener('input', () => { f[k] = Number(i.value) || 0; });
    return row(label, i);
  };
  const choice = (k, label, options) => {
    const s = el('select');
    options.forEach((t, i) => s.add(new Option(t, String(i))));
    s.value = String(f[k] ?? 0);
    s.addEventListener('change', () => { f[k] = Number(s.value); });
    return row(label, s);
  };
  const flag = (k, bit, label) => {
    const l = form.appendChild(el('label', 'check'));
    const c = l.appendChild(el('input'));
    c.type = 'checkbox';
    c.checked = !!((f[k] || 0) & bit);
    c.disabled = !editable;
    c.addEventListener('change', () => { f[k] = c.checked ? (f[k] || 0) | bit : (f[k] || 0) & ~bit; });
    l.append(' ' + label);
  };
  const file = (k, label, folder, after) => {
    const box = el('div', 'it-file');
    const i = box.appendChild(el('input'));
    i.type = 'text';
    i.value = f[k] || '';
    i.placeholder = folder === 'icons' ? 'e.g. m\\tx_key_01.tga' : 'e.g. m\\key_01.nif';
    i.addEventListener('change', () => { f[k] = i.value.trim(); after(); });
    const b = box.appendChild(el('button', null, 'Choose…'));
    b.addEventListener('click', async (e) => {
      e.preventDefault();
      const got = await browse(folder, f[k]);
      if (got) { f[k] = got; i.value = got; after(); }
    });
    const l = form.appendChild(el('label', 'opt'));
    l.appendChild(el('span', null, label));
    l.appendChild(box);
    i.disabled = b.disabled = !editable;
  };

  const pickTemplate = (cur) => choose({
    title: 'Choose an item to start from', current: cur, none: 'No template',
    items: [...newItems(), ...listData.items].filter((o) => Object.values(KINDS).includes(o.type)) });
  // the new item takes the template's values (all but its id), or the blank ones again
  const useTemplate = async (id) => {
    let from = info;
    if (id) {
      try { from = await itemInfo(id); } catch (err) { q('.it-note').textContent = err.message; return; }
    }
    for (const k of Object.keys(f)) delete f[k];
    Object.assign(f, JSON.parse(JSON.stringify(id ? clean(from) : from)), { new: true, id: id ? idFrom(from.name || from.id) : '' });
    if (id) f.template = from.id;
    build();
    view.show(f.model);
    showIcon();
  };
  const build = () => {
    form.innerHTML = '';
    if (isNew) {
      const t = el('input');
      t.type = 'text';
      t.readOnly = true;
      t.value = f.template || '';
      t.placeholder = 'None: from scratch';
      t.title = 'Start from an existing item\'s values';
      const l = form.appendChild(el('label', 'opt'));
      l.appendChild(el('span', null, 'Use template'));
      l.appendChild(withChooser(t, pickTemplate, useTemplate));
      const s = choice('kindIndex', 'Kind', Object.values(KINDS));
      s.value = String(Object.keys(KINDS).indexOf(f.kind));
      s.addEventListener('change', () => {
        f.kind = Object.keys(KINDS)[Number(s.value)];
        for (const [k, v] of Object.entries(DEFAULTS[f.kind])) if (!(k in f)) f[k] = JSON.parse(JSON.stringify(v));
        build();
      });
    }
    const carried = CARRIED.includes(f.kind);
    if (f.kind !== 'STAT') {
      text('name', f.kind === 'ACTI' || f.kind === 'DOOR' ? 'Name (shown when pointed at)' : 'Name',
           { max: 31, after: () => { if (isNew && !f.idTouched) { f.id = idFrom(f.name); idBox.value = f.id; } } });
    }
    const idBox = isNew ? text('id', 'ID', { max: 31, after: () => { f.idTouched = true; } }) : null;
    file('model', 'Model', 'meshes', () => view.show(f.model));
    if (carried) {
      file('icon', 'Icon', 'icons', showIcon);
      num('value', 'Value', { min: 0 });
      num('weight', 'Weight', { step: 0.1, min: 0 });
    }
    if (f.kind !== 'STAT' && f.kind !== 'CONT') {
      text('script', 'Script', { placeholder: 'None', list: 'item-scripts', pick: (cur) => choose({
        title: 'Choose a script', items: listData.scripts.map((s) => ({ id: s })), current: cur, none: 'No script' }) });
    }
    if (f.kind === 'LIGH') {
      num('radius', 'Radius', { min: 0 });
      const c = el('input');
      c.type = 'color';
      c.value = '#' + (f.color || [255, 255, 255]).map((v) => Math.max(0, Math.min(255, v | 0)).toString(16).padStart(2, '0')).join('');
      c.addEventListener('input', () => { f.color = [1, 3, 5].map((i) => parseInt(c.value.slice(i, i + 2), 16)); });
      row('Colour', c);
      num('time', 'Burns for (seconds; -1: always)', { min: -1 });
      text('sound', 'Sound', { placeholder: 'None, e.g. Fire' });
      for (const [bit, label] of LIGHT_FLAGS) flag('lflags', bit, label);
    } else if (f.kind === 'DOOR') {
      text('open_sound', 'Opening sound', { placeholder: 'None, e.g. Door Stone Open' });
      text('close_sound', 'Closing sound', { placeholder: 'None, e.g. Door Stone Close' });
    } else if (f.kind === 'CONT') {
      num('capacity', 'Holds (weight)', { min: 0 });
      form.appendChild(el('div', 'npc-hint', 'Put things in it with Contents…, once it stands in a cell.'));
    } else if (f.kind === 'ALCH' || f.kind === 'INGR') {
      if (f.kind === 'ALCH') {
        const l = form.appendChild(el('label', 'check'));
        const c = l.appendChild(el('input'));
        c.type = 'checkbox';
        c.checked = !!f.auto;
        c.disabled = !editable;
        c.addEventListener('change', () => { f.auto = c.checked; });
        l.append(' The game works out its value');
      }
      effectRows(form, f, editable);
    }
    if (ENCHANTED.includes(f.kind)) {
      const about = el('div', 'npc-hint it-effects');
      const allEnchants = () => [...api.magic().newEnchants(), ...listData.enchants];
      const showEffects = () => {
        const e = f.enchant && allEnchants().find((x) => x.id.toLowerCase() === f.enchant.toLowerCase());
        about.textContent = e ? enchantLines(e).join('\n') : f.enchant ? 'No enchantment has this id.' : '';
      };
      const box = text('enchant', 'Enchantment', { placeholder: 'None', after: showEffects, pick: (cur) => choose({
        title: 'Choose an enchantment', current: cur, none: 'No enchantment',
        items: allEnchants().map((e) => ({ id: e.id, type: e.type, note: (e.effects || []).join(', '), detail: enchantLines(e).slice(1) })) }) });
      if (editable) {
        const make = el('button', null, 'New…');
        make.title = 'Make a new enchantment for it';
        make.addEventListener('click', async (e) => {
          e.preventDefault();
          const id = await api.magic().create({ kind: 'ENCH', type: f.kind === 'WEAP' ? 1 : f.kind === 'BOOK' ? 0 : 3 });
          if (!id) return;
          f.enchant = id;
          box.value = id;
          setTimeout(showEffects, 300);
        });
        box.closest('.pick-wrap').appendChild(make);
        const change = el('button', null, 'Edit…');
        change.title = 'Change this enchantment\'s effects';
        change.addEventListener('click', async (e) => {
          e.preventDefault();
          if (!f.enchant) { about.textContent = 'Choose an enchantment first.'; return; }
          if (await api.magic().edit(f.enchant)) setTimeout(showEffects, 300);
        });
        box.closest('.pick-wrap').appendChild(change);
      }
      form.appendChild(about);
      showEffects();
    }
    if (f.kind === 'WEAP') {
      choice('wtype', 'Type', WEAPON_TYPES);
      num('health', 'Health', { min: 0 });
      num('speed', 'Speed', { step: 0.05, min: 0 });
      num('reach', 'Reach', { step: 0.05, min: 0 });
      for (const [k, l] of [['chop', 'Chop'], ['slash', 'Slash'], ['thrust', 'Thrust']]) {
        num(k + '_min', `${l} damage, least`, { min: 0, max: 255 });
        num(k + '_max', `${l} damage, most`, { min: 0, max: 255 });
      }
      flag('wflags', 2, 'Silver');
      flag('wflags', 1, 'Hits creatures only magic hurts');
    } else if (f.kind === 'ARMO') {
      choice('atype', 'Slot', ARMOR_TYPES);
      num('rating', 'Armour rating', { min: 0 });
      num('health', 'Health', { min: 0 });
    } else if (f.kind === 'CLOT') {
      choice('ctype', 'Slot', CLOTHING_TYPES);
    } else if (f.kind === 'MISC') {
      flag('mflags', 1, 'A key (it can open locks)');
    } else if (f.kind === 'BOOK') {
      flag('scroll', 1, 'A scroll (one page)');
      const skills = ['None', ...listData.skillNames];
      const s = choice('skillIndex', 'Teaches', skills);
      s.value = String((f.skill ?? -1) + 1);
      s.addEventListener('change', () => { f.skill = Number(s.value) - 1; });
      const t = el('textarea', 'it-text');
      t.value = f.text || '';
      t.rows = 6;
      t.placeholder = 'The text; Morrowind books use HTML-like tags such as <BR> and <DIV ALIGN="CENTER">';
      t.disabled = !editable;
      t.addEventListener('input', () => { f.text = t.value; });
      form.appendChild(t);
    }
    if (f.kind === 'ARMO' || f.kind === 'CLOT') {
      form.appendChild(el('div', 'npc-hint', 'Body parts: the meshes a character shows wearing it (male, and female if it differs).'));
      const box = form.appendChild(el('div', 'it-parts'));
      const draw = () => {
        box.innerHTML = '';
        (f.parts || []).forEach((p, i) => {
          const line = box.appendChild(el('div', 'it-part'));
          const s = line.appendChild(el('select'));
          PARTS.forEach((t, k) => s.add(new Option(t, String(k))));
          s.value = String(p[0]);
          s.addEventListener('change', () => { p[0] = Number(s.value); });
          for (const [k, ph] of [[1, 'male part'], [2, 'female (optional)']]) {
            const inp = el('input');
            inp.type = 'text';
            inp.placeholder = ph;
            inp.value = p[k];
            suggest(inp, 'item-parts');
            inp.addEventListener('input', () => { p[k] = inp.value.trim(); });
            inp.disabled = !editable;
            line.appendChild(withChooser(inp, (cur) => choose({
              title: `Choose the ${k === 2 ? 'female' : 'male'} body part`, current: cur, none: 'None',
              type: BODY_KINDS[SLOT_BODY[p[0]]] || '',
              items: listData.wearParts.filter((b) => b.armor === (f.kind === 'ARMO'))
                .map((b) => ({ id: b.id, type: BODY_KINDS[b.part] || 'Other', note: b.female ? 'female' : '' })) })));
          }
          const rm = line.appendChild(el('button', 'ghost icon'));
          rm.innerHTML = icon('x');
          rm.addEventListener('click', (e) => { e.preventDefault(); f.parts.splice(i, 1); draw(); });
          s.disabled = rm.disabled = !editable;
        });
        const add = box.appendChild(el('button', null, 'Add body part'));
        add.disabled = !editable;
        add.addEventListener('click', (e) => { e.preventDefault(); f.parts = f.parts || []; f.parts.push([3, '', '']); draw(); });
      };
      draw();
    }
  };
  build();
  view.show(f.model);
  showIcon();
  q('.it-note').textContent = isNew && place ? 'Create adds it as the object you were adding.' : isNew ? 'After Create, click where to put it (or press Escape to only keep it for inventories and chests).' : '';

  bg.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !document.querySelector('.files-dialog')) { e.stopPropagation(); close(); } });
  q('.it-cancel').addEventListener('click', close);
  q('.it-done').addEventListener('click', async () => {
    if (!editable) { close(); return; }
    const out = clean(f);
    if (f.kind === 'ALCH' && !out.effects.length) { q('.it-note').textContent = 'A potion needs at least one effect.'; return; }
    if (isNew) {
      if (!out.model) { q('.it-note').textContent = 'Choose a model first.'; return; }
      const res = await fetch('/api/item/new-id', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                    body: JSON.stringify({ base: out.id || idFrom(out.name), taken: Object.keys(api.state.edits.items) }) });
      out.id = (await res.json()).id;
      close();
      record(null, { ...out, new: true });
      (place || api.place)({ id: out.id, name: out.name || '', type: KINDS[out.kind], mesh: out.model });
      return;
    }
    const before = JSON.stringify(clean(info));
    if (JSON.stringify(out) === before) { close(); return; }
    const scope = info.own ? 'all' : copyOnly ? 'one' : await askScope(info, 'items', 'Its name, model and stats belong');
    if (!scope) return;
    close();
    if (scope === 'one') {
      const res = await fetch('/api/item/new-id', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                    body: JSON.stringify({ base: info.id, taken: Object.keys(api.state.edits.items) }) });
      const id = (await res.json()).id;
      record(r, { ...out, id, new: true, copy_of: info.id });
    } else {
      const key = info.id.toLowerCase();
      const prev = api.state.edits.items[key] || {};
      const changed = Object.fromEntries(Object.entries(out).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(clean(info)[k])));
      record(null, prev.new ? { ...prev, ...out, id: prev.id } : { ...prev, ...changed }, key);
    }
  });
}

// A potion's or an ingredient's effects: the effect, what it's about, and for a potion how strong and how long
function effectRows(form, f, editable) {
  const potion = f.kind === 'ALCH', most = potion ? 8 : 4;
  form.appendChild(el('div', 'mg-head', potion ? 'Effects' : 'Effects (found by alchemy skill, in this order)'));
  const box = form.appendChild(el('div', 'it-fx'));
  magicInfo.then((info) => {
    const draw = () => {
      box.innerHTML = '';
      f.effects.forEach((e, i) => {
        const d = info.effects[e.effect] || info.effects[0];
        const line = box.appendChild(el('div', 'mg-effect'));
        const top = line.appendChild(el('div', 'mg-row'));
        const s = top.appendChild(el('select', 'mg-name'));
        [...info.effects].sort((a, b) => a.name.localeCompare(b.name)).forEach((x) => s.add(new Option(x.name, String(x.index))));
        s.value = String(d.index);
        s.addEventListener('change', () => { e.effect = Number(s.value); e.skill = e.attribute = -1; draw(); });
        for (const [k, names] of [['skill', info.skills], ['attribute', info.attributes]]) {
          if (!d[k]) continue;
          const t = top.appendChild(el('select'));
          names.forEach((n, j) => t.add(new Option(n, String(j))));
          if (!(e[k] >= 0)) e[k] = 0;
          t.value = String(e[k]);
          t.disabled = !editable;
          t.addEventListener('change', () => { e[k] = Number(t.value); });
        }
        const rm = top.appendChild(el('button', 'ghost icon'));
        rm.innerHTML = icon('x');
        rm.addEventListener('click', (ev) => { ev.preventDefault(); f.effects.splice(i, 1); draw(); });
        s.disabled = rm.disabled = !editable;
        if (!potion) return;
        const nums = line.appendChild(el('div', 'mg-row mg-nums'));
        for (const [k, label, on] of [['min', 'From', d.magnitude], ['max', 'to', d.magnitude], ['duration', 'for (seconds)', d.duration]]) {
          if (!on) continue;
          const l = nums.appendChild(el('label'));
          l.append(label + ' ');
          const n = l.appendChild(el('input'));
          n.type = 'number';
          n.min = 0;
          n.value = e[k] ?? 0;
          n.disabled = !editable;
          n.addEventListener('input', () => { e[k] = Number(n.value) || 0; if (k === 'min' && e.max < e.min) e.max = e.min; });
        }
      });
      const add = box.appendChild(el('button', null, 'Add effect'));
      add.disabled = !editable || f.effects.length >= most;
      add.addEventListener('click', (ev) => {
        ev.preventDefault();
        f.effects.push(potion ? { effect: 75, skill: -1, attribute: -1, range: 0, area: 0, duration: 5, min: 5, max: 5 }
          : { effect: 75, skill: -1, attribute: -1 });
        draw();
      });
    };
    f.effects = f.effects || [];
    draw();
  });
}

// an enchantment as an item's tooltip tells it: how it's cast, its effects, its charge
const enchantLines = (e) => [e.type, ...(e.effects || []), ...(e.charge != null ? [`Charge: ${e.charge}`] : [])];

// the item's fields as they're stored (the editor's helpers left out)
function clean(f) {
  const other = { ALCH: ['name', 'icon', 'script', 'weight', 'value', 'auto', 'effects'],
                  INGR: ['name', 'icon', 'script', 'weight', 'value', 'effects'],
                  LIGH: ['name', 'icon', 'script', 'sound', 'weight', 'value', 'time', 'radius', 'color', 'lflags'],
                  CONT: ['name', 'capacity'], STAT: [], ACTI: ['name', 'script'],
                  DOOR: ['name', 'script', 'open_sound', 'close_sound'] }[f.kind];
  const keep = other ? ['kind', 'id', 'model'] : ['kind', 'id', 'name', 'model', 'icon', 'script', 'enchant', 'weight', 'value', 'enchant_pts'];
  const more = other || { WEAP: Object.keys(DEFAULTS.WEAP), ARMO: ['atype', 'health', 'rating', 'parts'], CLOT: ['ctype', 'parts'],
                          MISC: ['mflags'], BOOK: ['scroll', 'skill', 'text'] }[f.kind] || [];
  const out = {};
  for (const k of [...keep, ...more]) if (f[k] !== undefined) out[k] = k === 'parts' ? f[k].filter((p) => p[1] || p[2]) : f[k];
  return out;
}

// one undo step: the item's record, and for a copy the swap of the placed one to it
function record(r, entry, key = entry.id.toLowerCase()) {
  const { state } = api;
  const before = api.entriesOf(state.edits);
  if (entry.kind === 'CONT') {
    state.edits.containers[key] = { new: true, id: entry.id, name: entry.name || '', model: entry.model,
                                    capacity: entry.capacity ?? 100, contents: [], respawn: false };
  } else state.edits.items[key] = entry;
  if (r) {
    if (r.origin === 'added') state.edits.added.find((a) => 'added|' + a.uid === r.key).id = entry.id;
    else state.edits.replaced[r.key] = entry.id;
  }
  const diff = api.diffOf(before, api.entriesOf(state.edits));
  if (diff.length) state.undo.push({ diff });
  api.changed(r ? r.key : null);
  api.status(r ? `${entry.name || entry.id}: this one is now ${entry.id}, a copy of ${entry.copy_of}.`
    : entry.new && !entry.copy_of ? `Made ${entry.name || entry.id}.` : `Changed ${entry.name || entry.id}.`);
}
