// New enchantments and spells: a form with the effects, worded as the game words them
import { icon } from './icons.js';
import { choose, withChooser } from './choose.js';

let api = null;
let info = null;
const lineCache = new Map();          // id (lower case): effect lines of a new one

export function setupMagic(a) {
  api = a;
  return { create, edit, newEnchants, newSpells, refresh };
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};
const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                         body: JSON.stringify(body) }).then((r) => {
  if (!r.ok) throw new Error(r.status);
  return r.json();
});

let lists = null;
function loadLists() {
  lists = lists || fetch('/api/npc/lists').then((r) => r.json()).catch((err) => { lists = null; throw err; });
  return lists;
}

function loadInfo() {
  info = info || post('/api/magic/info', {}).catch((err) => { info = null; throw err; });
  return info;
}

const mine = (kind) => Object.values(api.state.edits.magic || {}).filter((m) => m.new && m.kind === kind);

// the new ones as the pickers list them (lines: the effects, once refresh has them)
function newEnchants() {
  return mine('ENCH').map((m) => ({ id: m.id, type: ENCHANT_TYPES[m.type] || '?', effects: lineCache.get(m.id.toLowerCase()) || [],
                                     ...(m.auto || m.type === 0 || m.type === 3 ? {} : { charge: m.charge }), mine: true }));
}
function newSpells() {
  return mine('SPEL').map((m) => ({ id: m.id, name: m.name, type: SPELL_TYPES[m.type] || '?', mine: true,
                                    note: (lineCache.get(m.id.toLowerCase()) || []).join(', ') }));
}
const ENCHANT_TYPES = ['Cast once', 'Cast when strikes', 'Cast when used', 'Constant effect'];
const SPELL_TYPES = ['Spell', 'Ability', 'Blight', 'Disease', 'Curse', 'Power'];

// the effect lines of every new one
async function refresh() {
  await Promise.all([...mine('ENCH'), ...mine('SPEL')].map(async (m) => {
    try { lineCache.set(m.id.toLowerCase(), await post('/api/magic/lines', { kind: m.kind, type: m.type, effects: m.effects })); }
    catch (err) { /* shown without effects */ }
  }));
}

const constant = (f) => (f.kind === 'ENCH' && f.type === 3) || (f.kind === 'SPEL' && f.type === 1);

// kind: 'ENCH' or 'SPEL'; type: the enchantment's type to start with; resolves to the new id, or null
function create(args) { return open(args, null); }

// Change one: the project's own, or the game's (for everything that uses it); resolves to its id, or null
async function edit(id) {
  let old = api.state.edits.magic?.[id.toLowerCase()];
  if (!old) {
    try { old = await post('/api/magic/get', { id }); } catch (err) { api.status(`${id} couldn't be read.`, true); return null; }
  }
  return open({ kind: old.kind, type: old.type, name: old.name || '' }, old);
}

async function open({ kind, type = 0, name = '' }, old) {
  let fx, all;
  try { [fx, all] = await Promise.all([loadInfo(), loadLists()]); } catch (err) { api.status('The magic effects didn\'t load.', true); return null; }
  const what = kind === 'ENCH' ? 'enchantment' : 'spell';
  const f = { kind, id: '', name, type, cost: 0, charge: 100, auto: true, always: false, effects: [] };
  if (old) {
    Object.assign(f, { id: old.id, cost: old.cost, charge: old.charge ?? 100, auto: !!old.auto, always: !!old.always,
                       effects: old.effects.map((e) => ({ ...e })) });
  }
  return new Promise((resolve) => {
    const bg = el('div', 'dialog-bg');
    bg.innerHTML = `<div class="dialog magic-dialog"><h3>${old ? (old.name || old.id) : `New ${what}`}</h3><p class="dim">${old
      ? old.new ? `${old.id} · a new ${what} of this project.` : `${old.id} · one of the game's: the change applies to everything that uses it.`
      : 'In your plugin. Start from an existing one or add effects.'}</p>
      <div class="mg-form"></div><div class="mg-effects"></div>
      <div class="mg-preview"></div><div class="npc-hint mg-note"></div>
      <div class="bar"><span class="spacer"></span><button class="mg-cancel">Cancel</button><button class="primary mg-done">${old ? 'Done' : 'Create'}</button></div></div>`;
    document.body.appendChild(bg);
    const q = (c) => bg.querySelector(c);
    const done = (v) => { bg.remove(); resolve(v); };
    const note = (t) => { q('.mg-note').textContent = t || ''; };
    const row = (label, control, box = q('.mg-form')) => {
      const l = box.appendChild(el('label', 'opt'));
      l.appendChild(el('span', null, label));
      l.appendChild(control);
      return control;
    };
    const num = (value, onInput, opts = {}) => {
      const i = el('input');
      i.type = 'number';
      Object.assign(i, { min: opts.min ?? 0, step: 1, value });
      if (opts.max != null) i.max = opts.max;
      i.addEventListener('input', () => onInput(Math.max(0, Math.round(Number(i.value) || 0))));
      return i;
    };
    let timer = null;
    const preview = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const box = q('.mg-preview');
        if (!f.effects.length) { box.textContent = 'No effects yet.'; return; }
        try {
          const lines = await post('/api/magic/lines', { kind, type: f.type, effects: f.effects });
          box.innerHTML = '';
          box.appendChild(el('div', 'mg-p-type', (kind === 'ENCH' ? ENCHANT_TYPES : SPELL_TYPES)[f.type]));
          for (const t of lines) box.appendChild(el('div', 'mg-p-line', t));
        } catch (err) { /* keep the last one */ }
      }, 120);
    };

    const buildForm = () => {
      const box = q('.mg-form');
      box.innerHTML = '';
      const t = el('input');
      t.type = 'text';
      t.readOnly = true;
      t.value = f.template || '';
      t.placeholder = 'None';
      const tl = (old ? el('div') : box).appendChild(el('label', 'opt'));
      tl.appendChild(el('span', null, 'Use template'));
      tl.appendChild(withChooser(t, (cur) => choose({
        title: `Choose ${kind === 'ENCH' ? 'an enchantment' : 'a spell'} to start from`, current: cur, none: 'No template',
        items: kind === 'ENCH'
          ? [...newEnchants(), ...all.enchants].map((e) => ({ id: e.id, type: e.type, note: (e.effects || []).join(', ') }))
          : [...newSpells(), ...all.spells].map((s) => ({ id: s.id, name: s.name, type: s.type })) }), useTemplate));
      if (kind === 'SPEL') {
        const n = row('Name', el('input'));
        n.type = 'text';
        n.maxLength = 31;
        n.value = f.name;
        n.placeholder = 'As the game shows it, e.g. Spark';
        n.addEventListener('input', () => { f.name = n.value; if (!old && !f.idTouched) { f.id = idFrom(f.name); idBox.value = f.id; } });
      }
      const idBox = row('ID', el('input'), old ? el('div') : undefined);
      idBox.type = 'text';
      idBox.maxLength = 31;
      idBox.value = f.id;
      idBox.placeholder = kind === 'ENCH' ? 'e.g. my_frost_en' : 'e.g. my_spark';
      idBox.addEventListener('input', () => { f.id = idBox.value.trim(); f.idTouched = true; });
      const s = row(kind === 'ENCH' ? 'Cast' : 'Type', el('select'));
      (kind === 'ENCH' ? ENCHANT_TYPES : SPELL_TYPES).forEach((x, i) => s.add(new Option(x, String(i))));
      s.value = String(f.type);
      s.addEventListener('change', () => { f.type = Number(s.value); buildForm(); buildEffects(); preview(); });
      const al = box.appendChild(el('label', 'check'));
      const auto = al.appendChild(el('input'));
      auto.type = 'checkbox';
      auto.checked = f.auto;
      al.append(kind === 'ENCH' ? ' The game works out the cost and charge' : ' The game works out the cost');
      auto.addEventListener('change', () => { f.auto = auto.checked; buildForm(); });
      if (!f.auto) {
        row(kind === 'ENCH' ? 'Cost to cast' : 'Magicka cost', num(f.cost, (v) => { f.cost = v; }));
        if (kind === 'ENCH' && f.type !== 3) row('Charge', num(f.charge, (v) => { f.charge = v; }));
      }
      if (kind === 'SPEL') {
        const ll = box.appendChild(el('label', 'check'));
        const always = ll.appendChild(el('input'));
        always.type = 'checkbox';
        always.checked = f.always;
        ll.append(' Casting always succeeds');
        always.addEventListener('change', () => { f.always = always.checked; });
      }
    };

    const byIndex = new Map(fx.effects.map((e) => [e.index, e]));
    const names = [...fx.effects].sort((a, b) => a.name.localeCompare(b.name));
    const buildEffects = () => {
      const box = q('.mg-effects');
      box.innerHTML = '';
      box.appendChild(el('div', 'mg-head', `Effects (${f.effects.length} of 8)`));
      const always = constant(f);
      f.effects.forEach((e, k) => {
        const d = byIndex.get(e.effect);
        const line = box.appendChild(el('div', 'mg-effect'));
        const top = line.appendChild(el('div', 'mg-row'));
        const pick = top.appendChild(el('select', 'mg-name'));
        for (const x of names) pick.add(new Option(x.name, String(x.index)));
        pick.value = String(e.effect);
        pick.addEventListener('change', () => { setEffect(e, Number(pick.value)); buildEffects(); preview(); });
        if (d.skill || d.attribute) {
          const t = top.appendChild(el('select'));
          (d.skill ? fx.skills : fx.attributes).forEach((x, i) => t.add(new Option(x, String(i))));
          t.value = String(d.skill ? Math.max(0, e.skill) : Math.max(0, e.attribute));
          t.addEventListener('change', () => { if (d.skill) e.skill = Number(t.value); else e.attribute = Number(t.value); preview(); });
        }
        if (!always) {
          const r = top.appendChild(el('select'));
          for (const k2 of d.ranges) r.add(new Option(['On self', 'On touch', 'On target'][k2], String(k2)));
          r.value = String(e.range);
          r.addEventListener('change', () => { e.range = Number(r.value); preview(); });
        }
        const rm = top.appendChild(el('button', 'ghost icon'));
        rm.innerHTML = icon('x');
        rm.title = 'Take this effect away';
        rm.addEventListener('click', () => { f.effects.splice(k, 1); buildEffects(); preview(); });
        const nums = line.appendChild(el('div', 'mg-row mg-nums'));
        const field = (label, key, show) => {
          if (!show) return;
          const l = nums.appendChild(el('label'));
          l.append(label + ' ');
          l.appendChild(num(e[key], (v) => { e[key] = v; preview(); }));
        };
        field('Magnitude', 'min', d.magnitude);
        field('to', 'max', d.magnitude);
        field('Seconds', 'duration', d.duration && !always);
        field('Area (ft)', 'area', !always && e.range !== 0);
      });
      if (f.effects.length < 8) {
        const add = box.appendChild(el('button', null, 'Add an effect…'));
        add.addEventListener('click', async () => {
          const got = await choose({ title: 'Choose an effect', items: names.map((x) => ({ id: String(x.index), name: x.name })) });
          if (!got) return;
          const e = { effect: 0, skill: -1, attribute: -1, range: 0, area: 0, duration: 10, min: 5, max: 10 };
          setEffect(e, Number(got));
          f.effects.push(e);
          buildEffects();
          preview();
        });
      }
    };
    const setEffect = (e, index) => {
      const d = byIndex.get(index);
      e.effect = index;
      e.skill = d.skill ? Math.max(0, e.skill) : -1;
      e.attribute = d.attribute ? Math.max(0, e.attribute) : -1;
      if (!d.ranges.includes(e.range)) e.range = d.ranges[0] ?? 0;
      if (kind === 'ENCH' && f.type === 1 && d.ranges.includes(1)) e.range = 1;     // a weapon's strike is a touch
    };
    const useTemplate = async (id) => {
      if (!id) { f.template = ''; buildForm(); return; }
      let got = api.state.edits.magic?.[id.toLowerCase()];
      if (!got) {
        try { got = await post('/api/magic/get', { id }); } catch (err) { note(`${id} couldn't be read.`); return; }
      }
      Object.assign(f, { type: got.type, cost: got.cost, charge: got.charge ?? f.charge, auto: got.auto, always: !!got.always,
                         effects: got.effects.map((e) => ({ ...e })), template: got.id });
      if (kind === 'SPEL' && !f.name) f.name = got.name || '';
      buildForm();
      buildEffects();
      preview();
    };

    buildForm();
    buildEffects();
    preview();
    bg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !document.querySelector('.choose-dialog')) { e.stopPropagation(); done(null); }
    });
    q('.mg-cancel').addEventListener('click', () => done(null));
    q('.mg-done').addEventListener('click', async () => {
      if (!f.effects.length) { note('Add an effect first.'); return; }
      if (f.effects.some((e) => e.min > e.max)) { note('A least magnitude is more than its most.'); return; }
      if (kind === 'SPEL' && !f.name.trim()) { note('Give the spell a name.'); return; }
      let id = old?.id;
      if (!old) try {
        id = (await post('/api/magic/new-id', { base: f.id || idFrom(f.name) || (kind === 'ENCH' ? 'new_en' : 'new_spell'),
                                                taken: Object.values(api.state.edits.magic || {}).map((m) => m.id) })).id;
      } catch (err) { note('The editor didn\'t answer.'); return; }
      const m = { ...(old && !old.new ? {} : { new: true }), kind, id, type: f.type, cost: f.cost, charge: f.charge, auto: f.auto,
                  effects: f.effects.map((e) => ({ ...e })), ...(kind === 'SPEL' ? { name: f.name.trim(), always: f.always } : {}) };
      done(id);
      const before = api.entriesOf(api.state.edits);
      api.state.edits.magic = api.state.edits.magic || {};
      api.state.edits.magic[id.toLowerCase()] = m;
      const diff = api.diffOf(before, api.entriesOf(api.state.edits));
      if (diff.length) api.state.undo.push({ diff });
      api.changed();
      try { lineCache.set(id.toLowerCase(), await post('/api/magic/lines', { kind, type: m.type, effects: m.effects })); } catch (err) { /* later */ }
      api.status(old ? `Changed the ${what} ${id}.` : `Made the ${what} ${id}.`);
    });
  });
}

const idFrom = (name) => (name || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 28);
