// Container contents: what's inside, and a browser of items to put in
import { icon } from './icons.js';

let api = null;
let lists = null;
const TYPES = ['Weapon', 'Armor', 'Clothing', 'Misc', 'Book', 'Potion', 'Ingredient', 'Apparatus', 'Lockpick', 'Probe',
               'Repair', 'Light', 'Leveled list'];

export function setupContents(a) {
  api = a;
  return { open };
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

function itemLists() {
  lists = lists || fetch('/api/npc/lists').then((r) => r.json()).catch((err) => { lists = null; throw err; });
  return lists;
}

// an item's icon, loaded when it scrolls into view
let iconWatch = null;
function iconEl(name) {
  const img = el('img', 'ic');
  img.alt = '';
  if (!name) return img;
  iconWatch = iconWatch || new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      iconWatch.unobserve(e.target);
      api.icon(e.target.dataset.icon).then((url) => { if (url) e.target.src = url; });
    }
  }, { rootMargin: '200px' });
  img.dataset.icon = name;
  iconWatch.observe(img);
  return img;
}

async function fetchContainer(id) {
  const res = await fetch('/api/container', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                              body: JSON.stringify({ id, edits: api.state.edits.containers }) });
  if (!res.ok) throw new Error(`${id} isn't a container in the load order`);
  return res.json();
}

function dialog(html, cls) {
  const bg = el('div', 'dialog-bg');
  bg.innerHTML = `<div class="dialog ${cls}">${html}</div>`;
  document.body.appendChild(bg);
  return bg;
}

// "Only this one" or "every one of this kind": resolves to 'one', 'all' or null
export function askScope(info, noun = 'containers', what = 'The contents belong') {
  return new Promise((resolve) => {
    const bg = dialog(`<h3>Change which ${noun}?</h3>
      <p>${what} to the kind <b></b>, which other ${noun} in the game may use too.</p>
      <label class="check"><input type="radio" name="cs" value="one" checked> <span>Only this one: it becomes a copy of its own</span></label>
      <label class="check"><input type="radio" name="cs" value="all"> <span>Every one of this kind, everywhere in the game</span></label>
      <div class="bar"><button class="cs-cancel">Cancel</button><button class="primary cs-ok">Change</button></div>`, 'scope-dialog');
    bg.querySelector('b').textContent = `${info.name || info.id} (${info.id})`;
    const done = (v) => { bg.remove(); resolve(v); };
    bg.querySelector('.cs-cancel').addEventListener('click', () => done(null));
    bg.querySelector('.cs-ok').addEventListener('click', () => done(bg.querySelector('input:checked').value));
    bg.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); done(null); } });
    bg.querySelector('.cs-ok').focus();
  });
}

async function open(r) {
  let info, names;
  try { [info, names] = await Promise.all([fetchContainer(r.src), itemLists()]); } catch (err) { api.status(err.message, true); return; }
  const all = [...api.newItems(), ...names.items];
  const byId = new Map(all.map((o) => [o.id.toLowerCase(), o]));
  const contents = info.contents.map((x) => [...x]);
  let respawn = info.respawn;
  // a record the project can't change can still be copied for this one container
  const editable = (info.canEdit || (info.canCopy && !info.own)) && r.editable;
  const copyOnly = editable && !info.canEdit;
  const bg = dialog(`<h3 class="ct-title"></h3><p class="dim ct-sub"></p>
    <div class="ct">
      <div class="ct-inside">
        <div class="ct-head"><b>Inside</b><label class="check"><input type="checkbox" class="ct-respawn"> Respawns</label></div>
        <div class="ct-list"></div>
        <div class="npc-hint">A negative count restocks: there are that many again after a while.</div>
      </div>
      <div class="ct-add">
        <div class="wr-filters"><input type="search" class="ct-search" placeholder="Search items to add"><select class="ct-type"></select>
          <span class="wr-views"><button class="icon ct-as-list" title="Show as a list">${icon('list')}</button><button class="icon ct-as-grid" title="Show as icons">${icon('grid')}</button></span></div>
        <div class="wr-list ct-items" tabindex="0"></div>
      </div>
    </div>
    <div class="npc-hint ct-note"></div>
    <div class="bar"><span class="npc-hint">Double-click or Enter puts one in</span><button class="ct-cancel">Cancel</button><button class="primary ct-done">Done</button></div>`,
  'contents-dialog');
  const q = (c) => bg.querySelector(c);
  q('.ct-title').textContent = `${info.name || info.id}: contents`;
  q('.ct-sub').textContent = [info.id, info.copy_of ? `a copy of ${info.copy_of}, for this chest only`
    : info.file ? `from ${info.file}` : '', !editable ? 'read-only in this project' : copyOnly ? 'changes make a copy for this one' : ''].filter(Boolean).join(' · ');
  q('.ct-note').textContent = 'A saved game that has already been in this cell may keep the old contents: try it in a new game.';
  q('.ct-respawn').checked = respawn;
  q('.ct-respawn').disabled = !editable;
  q('.ct-respawn').addEventListener('change', () => { respawn = q('.ct-respawn').checked; });
  q('.ct-type').add(new Option('All items', ''));
  for (const t of TYPES) q('.ct-type').add(new Option(t, t));

  const drawInside = () => {
    const box = q('.ct-list');
    box.innerHTML = '';
    if (!contents.length) box.appendChild(el('div', 'npc-hint', 'Empty.'));
    contents.forEach(([n, id], i) => {
      const o = byId.get(id.toLowerCase());
      const row = box.appendChild(el('div', 'ct-row'));
      row.appendChild(iconEl(o?.icon));
      const count = row.appendChild(el('input', 'count'));
      count.type = 'number';
      count.value = n;
      count.disabled = !editable;
      count.addEventListener('change', () => {
        const v = Math.round(Number(count.value)) || 0;
        if (v === 0) contents.splice(i, 1); else contents[i][0] = v;
        drawInside();
      });
      const name = row.appendChild(el('span', 'n', o ? o.name || o.id : id));
      name.title = o ? `${o.id} · ${o.type}` : `${id}: not in the load order`;
      if (!o) name.classList.add('bad');
      const rm = row.appendChild(el('button', 'ghost icon'));
      rm.innerHTML = icon('x');
      rm.title = 'Take out';
      rm.disabled = !editable;
      rm.addEventListener('click', () => { contents.splice(i, 1); drawInside(); });
    });
  };

  const view = { rows: [], sel: 0, grid: false };
  try { view.grid = localStorage.getItem('ce-contents-view') === 'grid'; } catch (err) { /* private mode */ }
  const list = q('.ct-items');
  const showView = () => {
    list.classList.toggle('grid', view.grid);
    q('.ct-as-list').classList.toggle('on', !view.grid);
    q('.ct-as-grid').classList.toggle('on', view.grid);
  };
  const setView = (grid) => {
    view.grid = grid;
    try { localStorage.setItem('ce-contents-view', grid ? 'grid' : 'list'); } catch (err) { /* private mode */ }
    showView();
  };
  q('.ct-as-list').addEventListener('click', () => setView(false));
  q('.ct-as-grid').addEventListener('click', () => setView(true));
  const choose = (k) => {
    view.sel = Math.max(0, Math.min(view.rows.length - 1, k));
    list.querySelectorAll('.wr-row').forEach((row, i) => row.classList.toggle('sel', i === view.sel));
    list.children[view.sel]?.scrollIntoView({ block: 'nearest' });
  };
  const put = () => {
    const o = view.rows[view.sel];
    if (!o || !editable) return;
    const have = contents.find(([, id]) => id.toLowerCase() === o.id.toLowerCase());
    if (have && have[0] > 0) have[0] += 1; else contents.push([1, o.id]);
    drawInside();
  };
  const render = () => {
    const words = q('.ct-search').value.toLowerCase().split(/\s+/).filter(Boolean);
    const type = q('.ct-type').value;
    view.rows = all.filter((o) => (!type || o.type === type)
      && words.every((w) => o.id.toLowerCase().includes(w) || (o.name || '').toLowerCase().includes(w)))
      .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id)).slice(0, 600);
    list.innerHTML = '';
    view.rows.forEach((o, i) => {
      const row = list.appendChild(el('div', 'wr-row'));
      row.appendChild(iconEl(o.icon));
      const t = row.appendChild(el('div', 't'));
      t.appendChild(el('div', 'n', o.name || o.id));
      t.appendChild(el('div', 'd', `${o.id} · ${o.type}`));
      row.title = `${o.name || o.id}\n${o.id} · ${o.type}`;
      row.addEventListener('click', () => choose(i));
      row.addEventListener('dblclick', () => { choose(i); put(); });
    });
    choose(0);
    showView();
  };
  q('.ct-search').addEventListener('input', render);
  q('.ct-type').addEventListener('change', render);
  q('.ct-add').style.display = editable ? '' : 'none';
  bg.querySelector('.dialog').addEventListener('keydown', (e) => {
    const cols = view.grid ? getComputedStyle(list).gridTemplateColumns.split(' ').length : 1;
    const sideways = e.key === 'ArrowLeft' || e.key === 'ArrowRight';
    const step = { ArrowDown: cols, ArrowUp: -cols, ArrowRight: 1, ArrowLeft: -1 }[e.key];
    const inList = e.target === list || e.target === q('.ct-search');
    if (step && inList && !(sideways && (!view.grid || e.target !== list))) { e.preventDefault(); choose(view.sel + step); }
    else if (e.key === 'Enter' && inList) { e.preventDefault(); put(); }
    else if (e.key === 'Escape') { e.stopPropagation(); bg.remove(); }
  });
  q('.ct-cancel').addEventListener('click', () => bg.remove());
  q('.ct-done').addEventListener('click', async () => {
    const same = JSON.stringify(contents) === JSON.stringify(info.contents) && respawn === info.respawn;
    if (same || !editable) { bg.remove(); return; }
    const scope = info.own ? 'all' : copyOnly ? 'one' : await askScope(info);
    if (!scope) return;
    bg.remove();
    await apply(r, info, { contents, respawn }, scope);
  });
  drawInside();
  render();
  if (!document.body.classList.contains('touch')) q('.ct-search').focus();
}

// one undo step: the changed record, or a copy for this container and the swap to it
async function apply(r, info, change, scope) {
  const { state } = api;
  const before = api.entriesOf(state.edits);
  const key = info.id.toLowerCase();
  let id = info.id;
  if (scope === 'one') {
    const res = await fetch('/api/container/new-id', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                       body: JSON.stringify({ base: info.id, taken: Object.keys(state.edits.containers) }) });
    id = (await res.json()).id;
    state.edits.containers[id.toLowerCase()] = { new: true, copy_of: info.id, id, ...change };
    if (r.origin === 'added') state.edits.added.find((a) => 'added|' + a.uid === r.key).id = id;
    else state.edits.replaced[r.key] = id;
    r.src = id;
  } else {
    state.edits.containers[key] = { ...(state.edits.containers[key] || {}), ...change };
  }
  const diff = api.diffOf(before, api.entriesOf(state.edits));
  if (diff.length) state.undo.push({ diff });
  api.changed();
  const n = change.contents.length;
  api.status(`${info.name || info.id}: ${n ? `${n} kind${n > 1 ? 's' : ''} of item inside` : 'empty'}`
    + (scope === 'one' ? ` (this one is now ${id}, a copy of ${info.id}).` : info.own ? '.' : ' (every one of this kind).'));
}
