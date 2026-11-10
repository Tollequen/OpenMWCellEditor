// A picker for fields that take an id: a searchable list (icons and a type filter where the items have them)
import { icon } from './icons.js';

let iconOf = null;
const MAX = 600;

export function setupChoose(a) {
  iconOf = a.icon;
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

let iconWatch = null;
function iconEl(name) {
  const img = el('img', 'ic');
  img.alt = '';
  if (!name || !iconOf) return img;
  iconWatch = iconWatch || new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      iconWatch.unobserve(e.target);
      iconOf(e.target.dataset.icon).then((url) => { if (url) e.target.src = url; });
    }
  }, { rootMargin: '200px' });
  img.dataset.icon = name;
  iconWatch.observe(img);
  return img;
}

// items: [{id, name, type, icon, note, detail}] (detail: lines shown beside the list for the one picked); resolves to the id picked, '' for none, or null when cancelled
export function choose({ title, items, current = '', none = null, type = '' }) {
  return new Promise((resolve) => {
    const icons = items.some((o) => o.icon);
    const types = [...new Set(items.map((o) => o.type).filter(Boolean))].sort();
    const bg = el('div', 'dialog-bg');
    bg.innerHTML = `<div class="dialog choose-dialog"><h3></h3>
      <div class="wr-filters"><input type="search" class="ch-search"><select class="ch-type"></select>
        <span class="wr-views"><button class="icon ch-as-list" title="Show as a list">${icon('list')}</button><button class="icon ch-as-grid" title="Show as icons">${icon('grid')}</button></span></div>
      <div class="ch-main"><div class="wr-list ch-list" tabindex="0"></div><div class="ch-detail"></div></div><div class="npc-hint ch-more"></div>
      <div class="bar"><button class="ch-none"></button><span class="spacer"></span><button class="ch-cancel">Cancel</button><button class="primary ch-ok">Choose</button></div></div>`;
    document.body.appendChild(bg);
    const q = (c) => bg.querySelector(c);
    q('h3').textContent = title;
    q('.ch-search').placeholder = items.some((o) => o.detail) ? 'Search by name, id or effect' : 'Search by name or id';
    const search = q('.ch-search'), filter = q('.ch-type'), list = q('.ch-list');
    const details = items.some((o) => o.detail);
    q('.dialog').classList.toggle('with-detail', details);
    q('.ch-detail').style.display = details ? '' : 'none';
    const showDetail = (o) => {
      const box = q('.ch-detail');
      box.innerHTML = '';
      if (!details || !o) return;
      box.appendChild(el('div', 'ch-d-name', o.name || o.id));
      if (o.type) box.appendChild(el('div', 'ch-d-type', o.type));
      for (const line of o.detail || []) box.appendChild(el('div', 'ch-d-line', line));
    };
    filter.add(new Option('All', ''));
    for (const t of types) filter.add(new Option(t, t));
    filter.value = types.includes(type) ? type : '';
    filter.style.display = types.length > 1 ? '' : 'none';
    q('.wr-views').style.display = icons ? '' : 'none';
    q('.ch-none').textContent = none || '';
    q('.ch-none').style.display = none ? '' : 'none';
    const view = { rows: [], sel: -1, grid: false };
    try { view.grid = icons && localStorage.getItem('ce-choose-view') === 'grid'; } catch (err) { /* private mode */ }
    const showView = () => {
      list.classList.toggle('grid', view.grid);
      q('.ch-as-list').classList.toggle('on', !view.grid);
      q('.ch-as-grid').classList.toggle('on', view.grid);
    };
    const setView = (grid) => {
      view.grid = grid;
      try { localStorage.setItem('ce-choose-view', grid ? 'grid' : 'list'); } catch (err) { /* private mode */ }
      showView();
    };
    q('.ch-as-list').addEventListener('click', () => setView(false));
    q('.ch-as-grid').addEventListener('click', () => setView(true));
    const done = (v) => { bg.remove(); resolve(v); };
    const pick = (k) => {
      view.sel = Math.max(0, Math.min(view.rows.length - 1, k));
      list.querySelectorAll('.wr-row').forEach((row, i) => row.classList.toggle('sel', i === view.sel));
      list.children[view.sel]?.scrollIntoView({ block: 'nearest' });
      showDetail(view.rows[view.sel]);
    };
    const ok = () => { const o = view.rows[view.sel]; if (o) done(o.id); };
    const render = () => {
      const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      const want = filter.value;
      const found = items.filter((o) => (!want || o.type === want)
        && words.every((w) => o.id.toLowerCase().includes(w) || (o.name || '').toLowerCase().includes(w)
                                || (o.detail || []).some((d) => d.toLowerCase().includes(w))))
        .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
      view.rows = found.slice(0, MAX);
      q('.ch-more').textContent = found.length > MAX ? `${found.length - MAX} more: search to narrow it down.`
        : !found.length ? (items.length ? 'Nothing matches.' : 'There\'s nothing to choose from here.') : '';
      list.innerHTML = '';
      view.rows.forEach((o, i) => {
        const row = list.appendChild(el('div', 'wr-row'));
        if (icons) row.appendChild(iconEl(o.icon));
        const about = [o.name && o.name !== o.id ? o.id : '', o.type, o.note].filter(Boolean).join(' · ');
        const t = row.appendChild(el('div', 't'));
        t.appendChild(el('div', 'n', o.name || o.id));
        if (about) t.appendChild(el('div', 'd', about));
        row.title = [o.name || o.id, about].filter(Boolean).join('\n');
        row.addEventListener('click', () => pick(i));
        row.addEventListener('dblclick', () => { pick(i); ok(); });
      });
      const k = view.rows.findIndex((o) => o.id.toLowerCase() === (current || '').toLowerCase());
      pick(k >= 0 && !search.value ? k : 0);
      showView();
    };
    search.addEventListener('input', render);
    filter.addEventListener('change', render);
    q('.ch-none').addEventListener('click', () => done(''));
    q('.ch-cancel').addEventListener('click', () => done(null));
    q('.ch-ok').addEventListener('click', ok);
    bg.addEventListener('keydown', (e) => {
      const cols = view.grid ? getComputedStyle(list).gridTemplateColumns.split(' ').length : 1;
      const sideways = e.key === 'ArrowLeft' || e.key === 'ArrowRight';
      const step = { ArrowDown: cols, ArrowUp: -cols, ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (e.key === 'Escape') { e.stopPropagation(); done(null); }
      else if (step && !(sideways && (!view.grid || e.target === search))) { e.preventDefault(); pick(view.sel + step); }
      else if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') { e.preventDefault(); e.stopPropagation(); ok(); }
    });
    render();
    if (!document.body.classList.contains('touch')) search.focus();
  });
}

// A "choose from a list" button for a text field: pick() resolves to an id, '' to clear, or null
export function chooseButton(input, pick, onPick = null) {
  const b = el('button', 'icon pick-btn');
  b.type = 'button';
  b.innerHTML = icon('list');
  b.title = 'Choose from a list';
  b.addEventListener('click', async (e) => {
    e.preventDefault();
    if (input.disabled) return;
    const v = await pick(input.value.trim());
    if (v == null) return;
    input.value = v;
    if (onPick) { onPick(v); return; }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  return b;
}

// The field and its button side by side (taking the field's place if it's in the page already)
export function withChooser(input, pick, onPick = null) {
  const wrap = el('span', 'pick-wrap');
  if (input.parentNode) input.replaceWith(wrap);
  wrap.append(input, chooseButton(input, pick, onPick));
  return wrap;
}
