// Blueprints window: every blueprint, a look at the chosen one, and placing or deleting it
import { viewer } from './items.js';

let api = null;

export function setupBlueprints(a) {
  api = a;
  return { open };
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

async function open() {
  if (document.querySelector('.bp-dialog')) return;
  let list;
  try { list = await api.list(); } catch (err) { api.status('The blueprints didn\'t load.', true); return; }
  const bg = el('div', 'dialog-bg');
  bg.innerHTML = `<div class="dialog bp-dialog"><div class="rc-head"><h3>Blueprints</h3><span class="spacer"></span><button class="bp-close">Close</button></div>
    <p class="dim rc-sub">Ready-made rooms, and the groups of objects you saved. To save one, select several objects and choose Save as blueprint…</p>
    <div class="bp-main"><div class="wr-list bp-list" tabindex="0"></div>
      <div class="bp-side"><canvas class="bp-view"></canvas><div class="bp-name"></div><div class="dim bp-info"></div>
        <div class="bp-acts">
          <button class="primary bp-place" title="Click a floor, a table or any surface in the cell: it lands on what is under the pointer">Place in the cell</button>
          <button class="bp-build" title="Opens the room builder with it chosen: it lands on the grid, at the builder's height">Place in the room builder</button>
          <button class="danger bp-del" title="Delete this blueprint of yours">Delete</button>
        </div><div class="npc-hint">Drag the picture to turn it, scroll to zoom.</div></div></div></div>`;
  document.body.appendChild(bg);
  const q = (c) => bg.querySelector(c);
  const view = viewer(q('.bp-view'));
  let sel = -1;
  const close = () => { view.dispose(); bg.remove(); api.closed?.(); };
  const cur = () => list[sel] || null;
  const show = () => {
    const b = cur();
    q('.bp-list').querySelectorAll('.wr-row').forEach((r, i) => r.classList.toggle('sel', i === sel));
    q('.bp-list').children[sel]?.scrollIntoView({ block: 'nearest' });
    q('.bp-name').textContent = b ? b.name : 'No blueprints yet';
    q('.bp-info').textContent = b ? `${b.items.length} object${b.items.length === 1 ? '' : 's'} · ${b.ready ? 'ready-made' : 'yours'}` : '';
    q('.bp-place').disabled = q('.bp-build').disabled = !b;
    q('.bp-del').style.display = b && !b.ready ? '' : 'none';
    view.showGroup(b ? b.items.slice(0, 200).map((it) => ({ mesh: it.o.mesh, matrix: api.matrix(it) })) : []);
  };
  const draw = () => {
    const box = q('.bp-list');
    box.innerHTML = '';
    list.forEach((b, i) => {
      const row = box.appendChild(el('div', 'wr-row'));
      const t = row.appendChild(el('div', 't'));
      t.appendChild(el('div', 'n', b.name));
      t.appendChild(el('div', 'd', `${b.items.length} object${b.items.length === 1 ? '' : 's'} · ${b.ready ? 'ready-made' : 'yours'}`));
      row.addEventListener('click', () => { sel = i; show(); });
      row.addEventListener('dblclick', () => { sel = i; place(); });
    });
    sel = Math.max(0, Math.min(list.length - 1, sel));
    show();
  };
  const place = () => { const b = cur(); if (b) { close(); api.place(b); } };
  q('.bp-close').addEventListener('click', close);
  q('.bp-place').addEventListener('click', place);
  q('.bp-build').addEventListener('click', () => { const b = cur(); if (b) { close(); api.build(b); } });
  q('.bp-del').addEventListener('click', async () => {
    const b = cur();
    if (!b || b.ready || !await api.remove(b)) return;
    list = list.filter((x) => x !== b);
    draw();
  });
  bg.addEventListener('keydown', (e) => {
    const step = { ArrowDown: 1, ArrowUp: -1 }[e.key];
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
    else if (step && list.length) { e.preventDefault(); sel = Math.max(0, Math.min(list.length - 1, sel + step)); show(); }
    else if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') { e.preventDefault(); place(); }
  });
  sel = 0;
  draw();
  q('.bp-list').focus();
}

