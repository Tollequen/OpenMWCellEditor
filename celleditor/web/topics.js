// An NPC's dialogue in the NPC editor: greetings and topic responses in the game's order
// INFOs form a linked list: no two edits may follow the same response
import { icon } from './icons.js';

const $ = (id) => document.getElementById(id);
let ctx = null;
let topics = [];
let names = null;
let loading = 0;
const opened = new Map();
const OPEN_UP_TO = 3;

const TYPE_NAMES = ['Topic', 'Voice', 'Greeting', 'Persuasion', 'Journal'];
const KINDS = [['function', 'Function'], ['journal', 'Journal'], ['item', 'Player has item'],
               ['global', 'Global variable'], ['local', 'Local variable'], ['notLocal', 'Local variable (not)'],
               ['dead', 'Dead count'], ['notId', 'Speaker isn\'t'], ['notFaction', 'Speaker\'s faction isn\'t'],
               ['notClass', 'Speaker\'s class isn\'t'], ['notRace', 'Speaker\'s race isn\'t'],
               ['notCell', 'Not in cell']];
const OPS = [['0', '='], ['1', '≠'], ['2', '>'], ['3', '≥'], ['4', '<'], ['5', '≤']];
// Condition functions by number (OpenMW components/esm3/dialoguecondition.hpp)
const PC_SKILLS = ['Block', 'Armorer', 'Medium Armor', 'Heavy Armor', 'Blunt Weapon', 'Long Blade', 'Axe', 'Spear',
                   'Athletics', 'Enchant', 'Destruction', 'Alteration', 'Illusion', 'Conjuration', 'Mysticism',
                   'Restoration', 'Alchemy', 'Unarmored', 'Security', 'Sneak', 'Acrobatics', 'Light Armor',
                   'Short Blade', 'Marksman', 'Mercantile', 'Speechcraft', 'Hand-to-hand'];
const FUNCTIONS = ['Faction reaction (lowest)', 'Faction reaction (highest)', 'Rank requirement', 'NPC reputation',
                   'NPC health %', 'Player reputation', 'Player level', 'Player health %', 'Player magicka',
                   'Player fatigue', 'Player Strength', ...PC_SKILLS.map((s) => 'Player ' + s), 'Player sex (0 male)',
                   'Player expelled', 'Player common disease', 'Player blight disease', 'Player clothing value',
                   'Player crime level', 'Same sex', 'Same race', 'Same faction', 'Faction rank difference', 'Detected',
                   'Alarmed', 'Choice', 'Player Intelligence', 'Player Willpower', 'Player Agility', 'Player Speed',
                   'Player Endurance', 'Player Personality', 'Player Luck', 'Player corprus', 'Weather',
                   'Player vampire', 'NPC level', 'Attacked', 'Talked to player', 'Player health', 'Creature target',
                   'Friend hit', 'NPC fight', 'NPC hello', 'NPC alarm', 'NPC flee', 'Should attack', 'Werewolf',
                   'Player werewolf kills'];
const MAX_TEXT = 512;
// The game checks Greeting 0 first, then 1 and so on
const GREETINGS = { 0: 'Greeting: looked at first (crimes, quests…)', 5: 'Greeting: most NPCs\' own',
                    9: 'Greeting: looked at last' };

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function sorted(o) {
  if (Array.isArray(o)) return o.map(sorted);
  if (o && typeof o === 'object') return Object.fromEntries(Object.keys(o).sort().map((k) => [k, sorted(o[k])]));
  return o;
}
const same = (a, b) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));

function edits() { return ctx.api.state.edits.dialogue; }

export async function showDialogue(box, c) {
  ctx = Object.assign({ box }, c);
  box.innerHTML = '<div class="npc-hint">Reading the dialogue…</div>';
  await reload();
}

export async function refreshDialogue() {
  if (ctx && ctx.box.isConnected) await reload();
}

async function reload() {
  const token = ++loading;
  const [res, list] = await Promise.all([
    fetch('/api/npc/dialogue', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                 body: JSON.stringify({ id: ctx.actor, edits: edits() }) }).then((r) => r.json()),
    names ? Promise.resolve(names) : fetch('/api/dialogue/topics').then((r) => r.json()),
  ]);
  if (token !== loading || !ctx.box.isConnected) return;
  names = list;
  topics = res.topics;
  const who = ctx.actor.toLowerCase();
  if (!opened.has(who)) opened.set(who, new Set(topics.length <= OPEN_UP_TO ? topics.map((t) => t.key) : []));
  fillTopicList();
  render();
}

function fillTopicList() {
  let dl = $('npc-topics');
  if (!dl) {
    dl = el('datalist');
    dl.id = 'npc-topics';
    document.body.appendChild(dl);
  }
  if (dl.childElementCount) return;
  for (let i = 0; i < 10; i++) dl.appendChild(new Option(GREETINGS[i] || 'Greeting', `Greeting ${i}`));
  for (const t of names) if (t.type === 0) dl.appendChild(new Option('', t.name));
  for (const t of names) if (t.type === 3) dl.appendChild(new Option('Persuasion', t.name));
  const quests = el('datalist');
  quests.id = 'npc-quests';
  for (const t of names) if (t.type === 4) quests.appendChild(new Option('', t.name));
  document.body.appendChild(quests);
}

// --- Changes: one undo step each (several entries when a chain changes) ------------------

function change(entries, reloadAfter = true) {
  const e = edits(), steps = [];
  for (const [key, next] of entries) {
    const prev = e[key];
    if (same(next, prev)) continue;
    steps.push({ id: key, prev });
    if (next === undefined) delete e[key]; else e[key] = sorted(next);
  }
  if (!steps.length) return;
  ctx.api.state.undo.push({ dialogue: steps });
  ctx.api.changed();
  if (reloadAfter) reload();
}

function setFields(r, changes) {
  const prev = edits()[r.key];
  let next;
  if (prev && prev.new) next = Object.assign({}, prev, changes);
  else {
    next = Object.assign({}, prev || {});
    for (const [k, v] of Object.entries(changes)) {
      if (same(v, r.base[k])) delete next[k]; else next[k] = v;
    }
    if (!Object.keys(next).length) next = undefined;
  }
  Object.assign(r.fields, changes);
  change([[r.key, next]], false);
}

function following(topicKey, id) {
  const out = [];
  for (const [k, e] of Object.entries(edits())) {
    if (k.startsWith(topicKey + '|') && e.after === id && !e.deleted) out.push([k, e]);
  }
  return out;
}

function newId() {
  return `${Date.now()}${String(Math.floor(Math.random() * 1e6)).padStart(6, '0')}`;
}

function addResponse(topicKey, name, type) {
  const t = topics.find((x) => x.key === topicKey);
  const target = t && t.responses.length ? t.responses[t.responses.length - 1].id : '';
  const id = newId();
  const key = topicKey + '|' + id;
  const fresh = { new: true, topic: name, type, after: target, actor: ctx.actor, text: '', race: '', class: '',
                  faction: '', cell: '', pcFaction: '', sound: '', disposition: 0, rank: -1, sex: -1, pcRank: -1,
                  result: '', quest: null, conditions: [] };
  openSet().add(topicKey);
  change([...following(topicKey, target).map(([k, e]) => [k, Object.assign({}, e, { after: id })]), [key, fresh]]);
  ctx.focus = key;
}

function moveUp(t, n) {
  const b = t.responses[n], a = t.responses[n - 1];
  const to = a.prev;
  const steps = new Map();
  const put = (k, e) => steps.set(k, e);
  for (const [k, e] of following(t.key, b.id)) put(k, Object.assign({}, e, { after: b.prev }));
  for (const [k, e] of following(t.key, to)) if (k !== b.key) put(k, Object.assign({}, steps.get(k) || e, { after: b.id }));
  put(b.key, Object.assign({}, steps.get(b.key) || edits()[b.key] || {}, { after: to }));
  change([...steps]);
}

function remove(t, r) {
  const e = edits()[r.key];
  if (e && e.new) {
    change([...following(t.key, r.id).map(([k, x]) => [k, Object.assign({}, x, { after: e.after })]), [r.key, undefined]]);
  } else {
    change([[r.key, { deleted: true }]]);
  }
}

// --- The section -------------------------------------------------------------------------

function render() {
  const box = ctx.box;
  box.innerHTML = '';
  const on = ctx.editable;
  if (!topics.length) box.appendChild(el('div', 'npc-hint', 'No responses of their own yet: they only say what everyone says.'));
  if (topics.length > 1) {
    const tools = el('div', 'dlg-tools');
    const n = topics.reduce((sum, t) => sum + t.responses.length, 0);
    tools.appendChild(el('span', 'dlg-type', `${topics.length} topics, ${n} responses`));
    for (const [text, open] of [['Expand all', true], ['Collapse all', false]]) {
      const b = tools.appendChild(el('button', 'ghost', text));
      b.addEventListener('click', () => {
        const set = openSet();
        for (const t of topics) if (open) set.add(t.key); else set.delete(t.key);
        for (const blk of box.querySelectorAll('.dlg-topic')) blk.setOpen(open);
      });
    }
    box.appendChild(tools);
  }
  for (const t of topics) box.appendChild(topicBlock(t, on));
  if (!on) return;

  const add = el('div', 'dlg-add');
  const topic = el('input');
  topic.type = 'text';
  topic.setAttribute('list', 'npc-topics');
  topic.placeholder = 'Greeting 5, a topic (e.g. latest rumors), or a new topic';
  const addTopic = el('button', null, 'Add response');
  const go = () => {
    const name = topic.value.trim();
    if (!name) { topic.focus(); return; }
    const known = names.find((x) => x.name.toLowerCase() === name.toLowerCase());
    const greeting = name.match(/^greeting ([0-9])$/i);
    addResponse(name.toLowerCase(), known ? known.name : greeting ? `Greeting ${greeting[1]}` : name,
                known ? known.type : greeting ? 2 : 0);
    topic.value = '';
  };
  addTopic.addEventListener('click', go);
  topic.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  add.append(topic, addTopic);
  box.appendChild(add);
  box.appendChild(el('div', 'npc-hint', 'Use Greeting 5 for unique NPC dialogue (Greetings 0–4 are reserved for crimes, quests, and disease). Variables such as %PCName, %PCRace, and %Name are replaced automatically in-game.'));
  if (ctx.focus) {
    box.querySelector(`[data-key="${CSS.escape(ctx.focus)}"] textarea`)?.focus();
    ctx.focus = null;
  }
}

function openSet() { return opened.get(ctx.actor.toLowerCase()); }

function topicBlock(t, on) {
  const b = el('div', 'dlg-topic');
  const h = el('button', 'dlg-topic-h');
  h.type = 'button';
  const chev = h.appendChild(el('span', 'dlg-chev'));
  h.appendChild(el('span', 'dlg-name', t.name));
  const changed = t.responses.some((r) => edits()[r.key]);
  h.appendChild(el('span', 'dlg-type', [TYPE_NAMES[t.type] || '', t.isNew ? 'new topic' : '',
                                        t.responses.length > 1 ? `${t.responses.length} responses` : '',
                                        changed && !t.isNew ? 'changed' : ''].filter(Boolean).join(' · ')));
  const first = t.responses.find((r) => !r.deleted);
  h.appendChild(el('span', 'dlg-peek', first ? first.fields.text : ''));
  b.appendChild(h);
  const body = b.appendChild(el('div', 'dlg-body'));
  t.responses.forEach((r, n) => body.appendChild(responseCard(t, r, n, on)));
  if (on) {
    const more = el('button', 'link', t.type === 2 ? '+ Another greeting here' : '+ Another response');
    more.addEventListener('click', () => addResponse(t.key, t.name, t.type));
    body.appendChild(more);
  }
  b.setOpen = (open) => {
    b.classList.toggle('open', open);
    h.setAttribute('aria-expanded', open);
    chev.innerHTML = icon(open ? 'chevDown' : 'chevRight');
  };
  b.setOpen(openSet().has(t.key));
  h.addEventListener('click', () => {
    const open = !b.classList.contains('open');
    if (open) openSet().add(t.key); else openSet().delete(t.key);
    b.setOpen(open);
  });
  return b;
}

function describe(r) {
  const f = r.fields, out = [];
  if (f.disposition) out.push(`disposition ≥ ${f.disposition}`);
  if (f.pcFaction) out.push(`player in ${f.pcFaction}${f.pcRank >= 0 ? ` (rank ${f.pcRank + 1}+)` : ''}`);
  if (f.cell) out.push(`in ${f.cell}`);
  if (f.conditions.length) out.push(`${f.conditions.length} condition${f.conditions.length > 1 ? 's' : ''}`);
  if (f.result) out.push('result script');
  return out.join(' · ') || 'always';
}

function responseCard(t, r, n, on) {
  const card = el('div', 'dlg-card' + (r.deleted ? ' deleted' : ''));
  card.dataset.key = r.key;
  const top = el('div', 'dlg-row');
  const e = edits()[r.key];
  const state = r.deleted ? 'deleted' : r.isNew ? 'new' : e ? 'changed' : r.file;
  top.appendChild(el('span', 'dlg-n', `${n + 1}.`));
  const sum = top.appendChild(el('span', 'dlg-sum', `${describe(r)}${state ? ' · ' + state : ''}`));
  const btn = (name, title, fn, disabled = false) => {
    const x = el('button', 'ghost icon');
    x.innerHTML = icon(name);
    x.title = title;
    x.disabled = disabled || !on;
    x.addEventListener('click', fn);
    top.appendChild(x);
    return x;
  };
  if (r.deleted) {
    const back = el('button', 'ghost', 'Restore');
    back.disabled = !on;
    back.addEventListener('click', () => change([[r.key, undefined]]));
    top.appendChild(back);
    card.appendChild(top);
    card.appendChild(el('div', 'dlg-text-ro', r.fields.text));
    return card;
  }
  btn('chevUp', 'Earlier: said before the one above when both fit', () => moveUp(t, n), n === 0);
  btn('chevDown', 'Later', () => moveUp(t, n + 1), n === t.responses.length - 1);
  if (e && !r.isNew) {
    const reset = el('button', 'ghost', 'Reset');
    reset.title = 'Back to how the load order has it';
    reset.disabled = !on;
    reset.addEventListener('click', () => change([[r.key, undefined]]));
    top.appendChild(reset);
  }
  btn('trash', r.isNew ? 'Delete this response' : 'Delete this response (the plugin removes it)', () => remove(t, r));
  card.appendChild(top);

  const text = el('textarea', 'dlg-text');
  text.value = r.fields.text;
  text.rows = Math.min(8, Math.max(2, Math.ceil(r.fields.text.length / 70)));
  text.placeholder = t.type === 2 ? 'Greeting dialogue…' : 'Response dialogue…';
  text.disabled = !on;
  const count = el('div', 'dlg-count');
  const counted = () => {
    count.textContent = text.value.length > MAX_TEXT * 0.8 ? `${text.value.length} / ${MAX_TEXT}` : '';
    count.classList.toggle('bad', text.value.length > MAX_TEXT);
  };
  counted();
  text.addEventListener('input', counted);
  text.addEventListener('change', () => { setFields(r, { text: text.value }); sum.textContent = `${describe(r)} · ${r.isNew ? 'new' : 'changed'}`; });
  card.append(text, count);

  const more = el('details', 'dlg-more');
  more.appendChild(el('summary', null, 'Conditions and result script'));
  const body = el('div', 'dlg-more-b');
  more.appendChild(body);
  card.appendChild(more);
  const refreshSum = () => { sum.textContent = `${describe(r)} · ${r.isNew ? 'new' : 'changed'}`; };
  const field = (label, control) => {
    const l = el('label', 'npc-f');
    l.append(el('span', null, label), control);
    body.appendChild(l);
    control.disabled = !on;
    return control;
  };
  const disp = field('Disposition ≥', el('input'));
  disp.type = 'number'; disp.min = 0; disp.max = 100; disp.value = r.fields.disposition;
  disp.title = 'Said only when the NPC likes the player at least this much';
  disp.addEventListener('change', () => { setFields(r, { disposition: Math.max(0, Math.min(255, Math.round(+disp.value) || 0)) }); refreshSum(); });
  const fac = field('Player in', el('select'));
  fac.add(new Option('Any faction', ''));
  for (const x of ctx.lists.factions) fac.add(new Option(x.name || x.id, x.id));
  if (r.fields.pcFaction && ![...fac.options].some((o) => o.value.toLowerCase() === r.fields.pcFaction.toLowerCase())) {
    fac.add(new Option(r.fields.pcFaction, r.fields.pcFaction));
  }
  fac.value = [...fac.options].find((o) => o.value.toLowerCase() === (r.fields.pcFaction || '').toLowerCase())?.value ?? '';
  const rank = field('Player rank ≥', el('select'));
  const ranks = () => {
    rank.innerHTML = '';
    rank.add(new Option('Any', '-1'));
    const f = ctx.lists.factions.find((x) => x.id.toLowerCase() === (r.fields.pcFaction || '').toLowerCase());
    (f ? f.ranks : []).forEach((name, i) => rank.add(new Option(`${i + 1}. ${name}`, String(i))));
    rank.value = String(r.fields.pcRank);
    rank.disabled = !on || !f;
  };
  ranks();
  fac.addEventListener('change', () => { setFields(r, { pcFaction: fac.value, pcRank: -1 }); ranks(); refreshSum(); });
  rank.addEventListener('change', () => { setFields(r, { pcRank: +rank.value }); refreshSum(); });
  const cell = field('Only in cell', el('input'));
  cell.type = 'text'; cell.value = r.fields.cell; cell.placeholder = 'Any cell';
  cell.addEventListener('change', () => { setFields(r, { cell: cell.value.trim() }); refreshSum(); });
  const other = [r.fields.race && `race ${r.fields.race}`, r.fields.class && `class ${r.fields.class}`,
                 r.fields.faction && (r.fields.faction === 'FFFF' ? 'no faction' : `faction ${r.fields.faction}`),
                 r.fields.rank >= 0 && `rank ${r.fields.rank + 1}+`, r.fields.sex >= 0 && (r.fields.sex ? 'female' : 'male')]
    .filter(Boolean);
  if (other.length) body.appendChild(el('div', 'npc-hint', `Also only when the speaker has ${other.join(', ')} (kept as it is).`));

  body.appendChild(el('div', 'npc-sub-h', 'Conditions (all must hold)'));
  const rows = el('div', 'dlg-conds');
  body.appendChild(rows);
  const conds = () => r.fields.conditions.map((c) => Object.assign({}, c));
  const setConds = (list) => { setFields(r, { conditions: list.map((c, i) => Object.assign(c, { index: i })) }); refreshSum(); };
  const drawConds = () => {
    rows.innerHTML = '';
    r.fields.conditions.forEach((c, i) => rows.appendChild(conditionRow(c, on, (nc) => {
      const list = conds();
      if (nc) list[i] = nc; else list.splice(i, 1);
      setConds(list);
      drawConds();
    })));
    addCond.disabled = !on || r.fields.conditions.length >= 6;
  };
  const addCond = el('button', null, 'Add condition');
  addCond.addEventListener('click', () => {
    setConds([...conds(), { kind: 'journal', name: '', op: '3', value: 10, float: false }]);
    drawConds();
    rows.lastChild?.querySelector('input')?.focus();
  });
  body.appendChild(addCond);
  drawConds();

  body.appendChild(el('div', 'npc-sub-h', 'Result script (runs when this is said)'));
  const script = el('textarea', 'dlg-script');
  script.value = r.fields.result;
  script.rows = Math.max(2, Math.min(10, r.fields.result.split('\n').length));
  script.placeholder = 'e.g.\nJournal "MyQuest" 10\nAddTopic "my topic"';
  script.spellcheck = false;
  script.disabled = !on;
  script.addEventListener('change', () => { setFields(r, { result: script.value.replace(/\r?\n/g, '\r\n') }); refreshSum(); });
  body.appendChild(script);
  return card;
}

function conditionRow(c, on, onSet) {
  const row = el('div', 'dlg-cond');
  const kind = el('select');
  for (const [v, t] of KINDS) kind.add(new Option(t, v));
  if (!KINDS.some(([v]) => v === c.kind)) kind.add(new Option(c.kind, c.kind));
  kind.value = c.kind;
  const func = el('select');
  FUNCTIONS.forEach((f, i) => func.add(new Option(f, String(i))));
  func.value = String(c.func ?? 6);
  const name = el('input');
  name.type = 'text';
  name.value = c.name || '';
  const op = el('select');
  for (const [v, t] of OPS) op.add(new Option(t, v));
  op.value = c.op;
  const value = el('input');
  value.type = 'text';
  value.inputMode = 'decimal';
  value.value = c.value;
  value.className = 'val';
  const rm = el('button', 'ghost icon');
  rm.innerHTML = icon('x');
  rm.title = 'Remove the condition';
  const shape = () => {
    const k = kind.value;
    func.style.display = k === 'function' ? '' : 'none';
    name.style.display = k === 'function' ? 'none' : '';
    name.setAttribute('list', k === 'journal' ? 'npc-quests' : k === 'item' ? 'npc-items' : '');
    name.placeholder = { journal: 'quest id', item: 'item id', dead: 'NPC or creature id', global: 'variable',
                         local: 'variable', notLocal: 'variable', notId: 'id', notFaction: 'faction id',
                         notClass: 'class id', notRace: 'race id', notCell: 'cell name' }[k] || '';
  };
  shape();
  // An edited condition is written anew; its old SCVR rule string is dropped
  const set = () => {
    const v = value.value.trim();
    const float = /[.eE]/.test(v);
    const nc = { kind: kind.value, op: op.value, name: kind.value === 'function' ? '' : name.value.trim(),
                 value: float ? parseFloat(v) || 0 : parseInt(v, 10) || 0, float };
    if (kind.value === 'function') nc.func = +func.value;
    onSet(nc);
  };
  kind.addEventListener('change', () => { shape(); set(); });
  for (const x of [func, name, op, value]) x.addEventListener('change', set);
  rm.addEventListener('click', () => onSet(null));
  kind.className = 'k'; func.className = 'f'; name.className = 'nm'; op.className = 'o'; rm.classList.add('rm');
  row.append(kind, func, name, op, value, rm);
  for (const x of row.querySelectorAll('select, input, button')) x.disabled = !on;
  return row;
}
