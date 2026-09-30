// OpenMW Cell Editor: the 3D view and editing of a project's cells.
// World axes are Morrowind's: x east, y north, z up; headings are clockwise from north.
import * as THREE from 'three';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { decodeTexture } from './textures.js';
import { keepAlive, showStopped } from './alive.js';
import { phoneButton } from './phone.js';
import { icon, fillIcons } from './icons.js';
import { setupNpcEditor } from './npc.js';

const $ = (id) => document.getElementById(id);
fillIcons();
function stored(key) {
  try { return localStorage.getItem(key); } catch (err) { return null; }
}
const MOVE_STEPS = [1, 2, 4, 8, 16, 32];
const ROT_STEPS = [1, 5, 15, 45, 90];
const DEG = Math.PI / 180;

const state = {
  data: null, cell: null, tiers: {}, edits: { moved: {}, deleted: [] },
  selected: null, selection: [], undo: [], moveStep: 8, rotStep: 15, dirty: false,
  yaw: 0, pitch: 0, speed: 400, sensitivity: 3, joy: { x: 0, y: 0 }, keys: new Set(), looking: false,
};

// --- Renderer, camera, lights ----------------------------------------------

const touchParam = new URLSearchParams(location.search).get('touch');
const TOUCH = touchParam != null ? touchParam === '1' : matchMedia('(pointer: coarse)').matches;
if (TOUCH) document.body.classList.add('touch');

let needsRender = true, previewNeedsRender = false;
function requestRender() { needsRender = true; previewNeedsRender = true; }

const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, TOUCH ? 1.5 : 2));
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101014);
const camera = new THREE.PerspectiveCamera(70, 1, 2, 30000);
camera.up.set(0, 0, 1);
scene.add(new THREE.AmbientLight(0xffffff, 1.4));
const headlight = new THREE.PointLight(0xfff2dd, 1.6, 0, 0);
camera.add(headlight);
scene.add(camera);
let world = new THREE.Group();
scene.add(world);
const selBoxes = new THREE.Group();
scene.add(selBoxes);

function updateSelBoxes() {
  requestRender();
  const sel = state.selection;
  const boxes = selBoxes.children.filter((b) => b.userData.obj);
  const same = boxes.length === sel.length && boxes.every((b, i) => b.userData.obj === sel[i]);
  if (!same) {
    for (const b of selBoxes.children) { b.geometry.dispose(); b.material.dispose(); }
    selBoxes.clear();
    selBoxes.userData.group = null;
    for (const o of sel) {
      const b = new THREE.Box3Helper(new THREE.Box3(), o === state.selected ? 0xffcc33 : 0xb0862a);
      b.userData.obj = o;
      selBoxes.add(b);
    }
  }
  for (const b of selBoxes.children) {
    if (b.userData.obj) b.box.setFromObject(b.userData.obj);
  }
  if (live.others.size) updateMarkers();
  if (selBoxes.userData.group) {
    selBoxes.remove(selBoxes.userData.group);
    selBoxes.userData.group.geometry.dispose();
    selBoxes.userData.group.material.dispose();
    selBoxes.userData.group = null;
  }
  if (state.selection.length > 1 && groupAction() === 'ungroup') {
    const box = new THREE.Box3();
    for (const o of state.selection) box.union(new THREE.Box3().setFromObject(o));
    box.expandByScalar(4);
    const b = new THREE.Box3Helper(box, 0x66ddff);
    selBoxes.add(b);
    selBoxes.userData.group = b;
  }
}

const gizmo = new TransformControls(camera, renderer.domElement);
const gizmoHelper = gizmo.getHelper ? gizmo.getHelper() : gizmo;
const proxy = new THREE.Object3D();
scene.add(proxy);
scene.add(gizmoHelper);
gizmo.setSpace('world');
if (TOUCH) gizmo.size = 1.6;
let gizmoStart = null;

let facingFor = '';
function syncGizmo() {
  const objs = state.placing || state.multiTouch ? [] : roots();
  if (!objs.length) { gizmo.detach(); facingFor = ''; return; }
  const r = (objs.includes(state.selected) ? state.selected : objs[0]).userData.ref;
  proxy.position.copy(pivotOf(objs));
  const sel = objs.map((o) => o.userData.ref.key).join('\n');
  if (sel !== facingFor) {
    facingFor = sel;
    gizmo._gizmo.facing = { x: camera.position.x < proxy.position.x ? -1 : 1, y: camera.position.y < proxy.position.y ? -1 : 1 };
  }
  proxy.rotation.set(0, 0, -r.rot[2]);        // three.js turns counter-clockwise, Morrowind clockwise
  proxy.scale.set(1, 1, 1);
  proxy.updateMatrixWorld();
  gizmo.attach(proxy);
}

function setGizmoMode(mode) {
  gizmo.setMode(mode);
  gizmo.showX = gizmo.showY = mode !== 'scale';
  $('mode-move').classList.toggle('on', mode === 'translate');
  $('mode-turn').classList.toggle('on', mode === 'rotate');
  $('mode-scale').classList.toggle('on', mode === 'scale');
  $('tb-move').classList.toggle('on', mode === 'translate');
  $('tb-turn').classList.toggle('on', mode === 'rotate');
  $('tb-scale').classList.toggle('on', mode === 'scale');
  updateSnap();
}

function updateSnap() {
  const on = $('snap').checked;
  gizmo.setTranslationSnap(on ? state.moveStep : null);
  gizmo.setRotationSnap(on ? state.rotStep * DEG : null);
}

gizmo.addEventListener('dragging-changed', (e) => {
  if (e.value) {
    gizmoStart = { q: proxy.quaternion.clone(), pivot: proxy.position.clone(),
                   items: new Map(roots().map((o) => {
                     const r = o.userData.ref;
                     return [o, { pos: [...r.pos], rot: [...r.rot], scale: r.scale }];
                   })) };
    beginContinuous();
  } else {
    gizmoStart = null;
    syncGizmo();
  }
});
gizmo.addEventListener('change', requestRender);
gizmo.addEventListener('objectChange', () => {
  if (!gizmoStart) return;
  const move = proxy.position.clone().sub(gizmoStart.pivot);
  const turn = new THREE.Matrix4().makeRotationFromQuaternion(proxy.quaternion.clone().multiply(gizmoStart.q.clone().invert()));
  const f = Math.max(proxy.scale.z, 1e-3);
  edit((r, obj) => {
    const s = gizmoStart.items.get(obj);
    if (!s) return;
    if (gizmo.mode === 'scale') {
      // Morrowind references scale uniformly.
      let v = s.scale * f;
      if ($('snap').checked) v = Math.round(v / 0.05) * 0.05;
      r.scale = clampScale(v);
    } else if (gizmo.mode === 'rotate') {
      const p = new THREE.Vector3(...s.pos).sub(gizmoStart.pivot).applyMatrix4(turn).add(gizmoStart.pivot);
      r.pos = p.toArray();
      r.rot = rotOf(turn.clone().multiply(rotMatrix(s.rot)));
    } else {
      r.pos = [s.pos[0] + move.x, s.pos[1] + move.y, s.pos[2] + move.z];
    }
  }, false);
});

function resize() {
  requestRender();
  const w = canvas.clientWidth || window.innerWidth, h = canvas.clientHeight || window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

function ndc(x, y) {
  const r = canvas.getBoundingClientRect();
  return [((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1];
}
window.addEventListener('resize', resize);
resize();

function viewDir() {
  return new THREE.Vector3(Math.sin(state.yaw) * Math.cos(state.pitch),
                           Math.cos(state.yaw) * Math.cos(state.pitch), Math.sin(state.pitch));
}

function aimCamera() {
  camera.lookAt(camera.position.clone().add(viewDir()));
  requestRender();
}

// --- Meshes and materials ---------------------------------------------------

const meshCache = new Map();
const texCache = new Map();
const matCache = new Map();

function texture(name) {
  if (!name) return null;
  const key = name.toLowerCase();
  if (!texCache.has(key)) {
    const t = new THREE.DataTexture();
    t.colorSpace = THREE.SRGBColorSpace;
    t.flipY = false;                       // NIF UVs are top-down
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.magFilter = THREE.LinearFilter;
    t.minFilter = THREE.LinearMipmapLinearFilter;
    t.generateMipmaps = true;
    t.anisotropy = 4;
    fetch('/api/tex?name=' + encodeURIComponent(name))
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(r.status))))
      .then(decodeTexture)
      .then((img) => {
        t.image = img;
        t.needsUpdate = true;
        requestRender();
      })
      .catch((e) => console.warn('texture', name, e.message));
    texCache.set(key, t);
  }
  return texCache.get(key);
}

function material(s) {
  const key = [s.texture, s.blend, s.alphaTest, s.doubleSided, s.color != null, s.diffuse, s.alpha].join('|');
  if (!matCache.has(key)) {
    const blend = s.blend || s.alpha < 0.99;
    matCache.set(key, new THREE.MeshLambertMaterial({
      map: texture(s.texture),
      color: new THREE.Color(...s.diffuse.map((v) => Math.min(1, v))),
      emissive: new THREE.Color(...s.emissive.map((v) => Math.min(1, v * 0.5))),
      vertexColors: s.color != null,
      side: s.doubleSided || blend ? THREE.DoubleSide : THREE.FrontSide,
      transparent: blend,
      opacity: s.alpha,
      alphaTest: s.alphaTest != null ? s.alphaTest : (blend ? 0.05 : 0),
      depthWrite: !blend,
    }));
  }
  return matCache.get(key);
}

async function meshParts(path) {
  if (!meshCache.has(path)) {
    meshCache.set(path, fetch('/api/mesh?path=' + encodeURIComponent(path)).then((r) => r.json()).then((shapes) =>
      shapes.map((s) => {
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.Float32BufferAttribute(s.pos, 3));
        if (s.uv) g.setAttribute('uv', new THREE.Float32BufferAttribute(s.uv, 2));
        if (s.color) g.setAttribute('color', new THREE.Float32BufferAttribute(s.color, 3));
        g.setIndex(s.index);
        if (s.normal) g.setAttribute('normal', new THREE.Float32BufferAttribute(s.normal, 3));
        else g.computeVertexNormals();
        g.computeBoundingSphere();
        return { geometry: g, material: material(s) };
      })).catch(() => []));
  }
  return meshCache.get(path);
}

const placeholders = {
  npc: [new THREE.CapsuleGeometry(22, 80, 4, 12).rotateX(Math.PI / 2).translate(0, 0, 62),
        new THREE.MeshLambertMaterial({ color: 0x5fa0e0 })],
  light: [new THREE.SphereGeometry(8, 12, 8), new THREE.MeshBasicMaterial({ color: 0xffd060 })],
  marker: [new THREE.BoxGeometry(16, 16, 16), new THREE.MeshBasicMaterial({ color: 0xd050d0, wireframe: true })],
};

// Reference rotations are clockwise and applied Z * Y * X.
function refMatrix(r) {
  const [rx, ry, rz] = r.rot;
  const s = r.scale;
  const c = Math.cos, n = Math.sin;
  const Rx = [[1, 0, 0], [0, c(rx), n(rx)], [0, -n(rx), c(rx)]];
  const Ry = [[c(ry), 0, -n(ry)], [0, 1, 0], [n(ry), 0, c(ry)]];
  const Rz = [[c(rz), n(rz), 0], [-n(rz), c(rz), 0], [0, 0, 1]];
  const mul = (A, B) => A.map((row, i) => B[0].map((_, j) => row.reduce((acc, _v, k) => acc + A[i][k] * B[k][j], 0)));
  const M = mul(mul(Rz, Ry), Rx);
  return new THREE.Matrix4().set(
    M[0][0] * s, M[0][1] * s, M[0][2] * s, r.pos[0],
    M[1][0] * s, M[1][1] * s, M[1][2] * s, r.pos[1],
    M[2][0] * s, M[2][1] * s, M[2][2] * s, r.pos[2],
    0, 0, 0, 1);
}

function rotMatrix(rot) {
  return refMatrix({ rot, scale: 1, pos: [0, 0, 0] });
}
function rotOf(m) {
  const e = m.elements;                         // three.js matrices are column-major: e[c * 4 + r]
  const at = (r, c) => e[c * 4 + r];
  const clean = (v) => (Math.abs(v) < 1e-6 ? 0 : v);
  const b = Math.asin(Math.max(-1, Math.min(1, at(2, 0))));
  const a = Math.atan2(-at(2, 1), at(2, 2));
  const g = Math.atan2(-at(1, 0), at(0, 0));
  return [clean(a), clean(b), wrapAngle(clean(g))];
}

function applyTransform(obj) {
  requestRender();
  obj.matrix.copy(refMatrix(obj.userData.ref));
  obj.matrixWorldNeedsUpdate = true;
  obj.updateMatrixWorld(true);
}

// --- Cells and tiers --------------------------------------------------------

function shownAtTiers(r) {
  if (!r.nook) return true;
  const t = state.tiers[r.nook] || 0;
  return r.only ? t === r.tier : t >= r.tier;
}

function refreshVisibility() {
  requestRender();
  const deleted = new Set(state.edits.deleted);
  for (const obj of world.children) {
    const r = obj.userData.ref;
    if (r) obj.visible = shownAtTiers(r) && !deleted.has(r.key);
  }
  if (state.selection.some((o) => !o.visible)) setSelection(state.selection);
}

async function fillObject(obj) {
  const r = obj.userData.ref;
  obj.clear();
  if (r.kind === 'mesh') {
    for (const p of await meshParts(r.mesh)) obj.add(new THREE.Mesh(p.geometry, p.material));
  }
  obj.userData.noMesh = r.kind === 'mesh' && obj.children.length === 0;
  if (obj.children.length === 0) {
    const [g, m] = placeholders[r.kind === 'mesh' ? 'marker' : r.kind];
    obj.add(new THREE.Mesh(g, m));
  }
  applyTransform(obj);
}

async function makeObject(r) {
  const obj = new THREE.Group();
  obj.matrixAutoUpdate = false;
  obj.userData.ref = r;
  await fillObject(obj);
  return obj;
}

let NOOK_NAMES = {};

function setupProject() {
  const p = state.data.project;
  if (p && p.name) document.title = `${p.name} · Cell Editor`;
  if (p) $('menu-name').textContent = p.plugin;
  NOOK_NAMES = (p && p.nooks) || {};
  const hasTiers = !!p && Object.keys(state.data.nooks || {}).length > 0;
  $('mod-section').style.display = hasTiers ? '' : 'none';
  if (!hasTiers) return;
  $('mod-summary').textContent = `${p.name} mod`;
  try { $('mod-section').open = stored('ce-mod-open') === '1'; } catch (err) { /* private mode */ }
  $('mod-section').addEventListener('toggle', () => {
    try { localStorage.setItem('ce-mod-open', $('mod-section').open ? '1' : '0'); } catch (err) { /* private mode */ }
  });
  $('pk-tier').addEventListener('change', updatePickerModSummary);
}

function updatePickerModSummary() {
  const p = state.data.project;
  const sel = $('pk-tier');
  $('pk-mod-summary').textContent = `${p ? p.name : 'Mod'} options: ${sel.options[sel.selectedIndex]?.text || 'Always there'}`;
}

const objByKey = new Map();
const cellCache = new Map();

async function fetchCell(name) {
  if (!cellCache.has(name)) {
    cellCache.set(name, fetch('/api/cell', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                             body: JSON.stringify({ name, edits: state.edits }) }).then((r) => r.json()));
  }
  return cellCache.get(name);
}

async function loadCell(name, keepCamera = false) {
  select(null);
  $('loading').style.display = '';
  state.loadingCell = true;
  const cell = await fetchCell(name);
  scene.remove(world);
  world = new THREE.Group();
  scene.add(world);
  state.cell = cell;
  localStorage.setItem('ce-last-cell', name);
  updateCellControls();
  objByKey.clear();
  const jobs = cell.refs.map(async (r) => { const o = await makeObject(r); objByKey.set(r.key, o); world.add(o); });
  if (cell.water != null) {
    const water = new THREE.Mesh(new THREE.PlaneGeometry(cell.grid ? 40000 : 6000, cell.grid ? 40000 : 6000),
      new THREE.MeshBasicMaterial({ color: 0x2a5a80, transparent: true, opacity: 0.45, depthWrite: false }));
    water.position.set(cell.grid ? cell.grid[0] * 8192 + 4096 : 0, cell.grid ? cell.grid[1] * 8192 + 4096 : 0, cell.water);
    water.userData.water = true;
    world.add(water);
  }
  if (cell.grid) {
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) jobs.push(loadTerrain(cell.grid[0] + dx, cell.grid[1] + dy, world));
    }
  }
  if (!keepCamera) {
    camera.position.set(...cell.start.pos);
    state.yaw = cell.start.yaw;
    state.pitch = cell.start.pitch ?? -0.3;
  }
  camera.far = cell.grid ? 60000 : 30000;
  camera.updateProjectionMatrix();
  aimCamera();
  await Promise.all(jobs);
  state.loadingCell = false;
  refreshVisibility();
  updateMarkers();
  $('loading').style.display = 'none';
  const e = state.edits;
  const lost = cell.refs.filter((r) => r.winsOver?.length && (e.moved[r.key] || e.replaced[r.key] || e.deleted.includes(r.key)));
  if (lost.length) {
    const files = [...new Set(lost.flatMap((r) => r.winsOver))].join(', ');
    status(`⚠ ${lost.length} of your edits in this cell change objects that ${files} also changes, and it loads `
           + `after ${state.data.project.plugin}: in game its version wins. Select them to see which.`, true);
  }
}

// Terrain: a 65 x 65 height grid per cell, textured per 512-unit tile.
async function loadTerrain(gx, gy, into) {
  const t = await (await fetch(`/api/terrain?x=${gx}&y=${gy}`)).json();
  if (!t.heights || into !== world) return;
  const groups = new Map();
  for (let j = 0; j < 64; j++) {
    for (let i = 0; i < 64; i++) {
      const tex = t.tex[Math.floor(j / 4) * 16 + Math.floor(i / 4)];
      if (!groups.has(tex)) groups.set(tex, []);
      const a = j * 65 + i, b = a + 1, c = a + 65, d = c + 1;
      groups.get(tex).push(a, b, d, a, d, c);
    }
  }
  const pos = new Float32Array(65 * 65 * 3), uv = new Float32Array(65 * 65 * 2);
  const col = t.colors ? new Float32Array(t.colors) : null;
  for (let j = 0; j < 65; j++) {
    for (let i = 0; i < 65; i++) {
      const k = j * 65 + i, x = gx * 8192 + i * 128, y = gy * 8192 + j * 128;
      pos.set([x, y, t.heights[k]], k * 3);
      uv.set([i / 16, j / 16], k * 2);
    }
  }
  for (const [tex, index] of groups) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    if (col) g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    g.setIndex(index);
    g.computeVertexNormals();
    const m = new THREE.Mesh(g, material({ texture: t.textures[tex], blend: false, alphaTest: null,
      doubleSided: false, color: col ? 1 : null, diffuse: [1, 1, 1], emissive: [0, 0, 0], alpha: 1 }));
    m.userData.terrain = true;
    into.add(m);
  }
  requestRender();
}

function updateCellControls() {
  const cur = state.cell && state.cell.name;
  $('cell-name').textContent = cur || '…';
}

async function toggleFavorite(name) {
  state.favorites = state.favorites.includes(name) ? state.favorites.filter((n) => n !== name)
                                                    : [...state.favorites, name];
  updateCellControls();
  await fetch('/api/favorites', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ favorites: state.favorites }) });
}

function browseCells() {
  const fav = (o) => state.favorites.includes(o.id);
  openPicker({
    title: 'Cells', types: ['Favourites', 'Interior', 'Exterior'],
    placeholder: 'Search cells, e.g. balmora, guild, (-3, -2)…',
    items: state.data.cells.map((c) => ({ id: c.name, name: '', type: c.exterior ? 'Exterior' : 'Interior' })),
    first: fav, star: { on: fav, toggle: (o) => toggleFavorite(o.id) },
    onPick: (o) => loadCell(o.id),
  });
}

function buildTierControls() {
  const box = $('tiers');
  box.innerHTML = '';
  const names = NOOK_NAMES;
  for (const [nook, max] of Object.entries(state.data.nooks).sort()) {
    const label = document.createElement('label');
    label.textContent = names[nook] || nook;
    const sel = document.createElement('select');
    for (let t = 0; t <= Math.max(max, 1); t++) sel.add(new Option(t === 0 ? '0 (bare)' : String(t), t));
    sel.value = state.tiers[nook] = max;
    sel.addEventListener('change', () => { state.tiers[nook] = +sel.value; refreshVisibility(); sel.blur(); });
    label.appendChild(sel);
    box.appendChild(label);
  }
}

// --- Selection and editing -------------------------------------------------

function select(obj, add = false, single = false) {
  closeMenu();
  if (add && !obj) return;
  const objs = obj ? (single ? [obj] : groupMembers(obj)) : [];
  const rest = objs.filter((o) => o !== obj);
  if (add) {
    const all = objs.every((o) => state.selection.includes(o));
    const others = state.selection.filter((o) => !objs.includes(o));
    setSelection(all ? others : [...others, ...rest, obj]);
  } else {
    setSelection(obj ? [...rest, obj] : []);
  }
}

// --- Groups ---------------------------------------------------------------

function groupOf(key) {
  for (const [g, keys] of Object.entries(state.edits.groups)) if (keys.includes(key)) return g;
  return null;
}

function groupObjects(g) {
  return (state.edits.groups[g] || []).map((k) => objByKey.get(k)).filter((o) => o && o.visible);
}

function groupMembers(obj) {
  const g = groupOf(obj.userData.ref.key);
  return g ? groupObjects(g) : [obj];
}

function groupAction() {
  const sel = state.selection.filter((o) => o.visible && o.userData.ref.editable);
  if (!sel.length) return null;
  const gids = new Set(sel.map((o) => groupOf(o.userData.ref.key)));
  if (sel.length === 1) return gids.has(null) ? null : 'remove';
  if (gids.size === 1 && !gids.has(null)) {
    const [g] = gids;
    if (groupObjects(g).every((o) => sel.includes(o))) return 'ungroup';
  }
  return 'group';
}

function changeGroups(fn, message) {
  state.undo.push({ groups: JSON.parse(JSON.stringify(state.edits.groups)), selection: [...state.selection] });
  fn(state.edits.groups);
  for (const [g, keys] of Object.entries(state.edits.groups)) if (keys.length < 2) delete state.edits.groups[g];
  updateDirty();
  updateSelBoxes();
  updatePanel();
  status(message);
}

function mergedKeys() {
  const keys = new Set(state.selection.filter((o) => o.visible && o.userData.ref.editable).map((o) => o.userData.ref.key));
  for (const k of [...keys]) for (const m of state.edits.groups[groupOf(k)] || []) keys.add(m);
  return keys;
}

function groupSelected() {
  if (state.selection.filter((o) => o.visible && o.userData.ref.editable).length < 2) return;
  const keys = mergedKeys();
  changeGroups((groups) => {
    for (const k of keys) { const g = groupOf(k); if (g) delete groups[g]; }
    groups['g' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5)] = [...keys];
  }, `Grouped ${keys.size} objects: a ${TOUCH ? 'tap' : 'click'} on one selects them all${TOUCH ? '' : ' (Alt+click: just one)'}.`);
}

function ungroupSelected() {
  const gids = new Set(state.selection.map((o) => groupOf(o.userData.ref.key)).filter(Boolean));
  if (!gids.size) return;
  changeGroups((groups) => { for (const g of gids) delete groups[g]; }, 'Ungrouped.');
}

function removeFromGroup() {
  const obj = state.selected;
  const g = obj && groupOf(obj.userData.ref.key);
  if (!g) return;
  changeGroups((groups) => { groups[g] = groups[g].filter((k) => k !== obj.userData.ref.key); },
               `${obj.userData.ref.src} is no longer in the group.`);
}

function groupButton() {
  const a = groupAction();
  ({ group: groupSelected, ungroup: ungroupSelected, remove: removeFromGroup })[a]?.();
}

function setSelection(objs) {
  state.selection = objs.filter((o) => o && o.visible);
  state.selected = state.selection[state.selection.length - 1] || null;
  updateSelBoxes();
  syncGizmo();
  updatePanel();
}

function roots() {
  const sel = state.selection.filter((o) => o.userData.ref.editable && o.visible);
  const carried = new Set(sel.flatMap((o) => withAttached(o).slice(1)));
  return sel.filter((o) => !carried.has(o));
}

function pivotOf(objs) {
  const c = new THREE.Vector3();
  for (const o of objs) c.add(new THREE.Vector3(...o.userData.ref.pos));
  return c.divideScalar(objs.length || 1);
}

const wrapAngle = (a) => ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);

function rotateAround(p, c, d) {
  const dx = p[0] - c.x, dy = p[1] - c.y;
  return [c.x + dx * Math.cos(d) + dy * Math.sin(d), c.y - dx * Math.sin(d) + dy * Math.cos(d), p[2]];
}

function updateTouchBar() {
  if (!TOUCH) return;
  const obj = state.selected;
  const r = obj && obj.userData.ref;
  const n = state.selection.length;
  $('tb-name').textContent = state.multiTouch ? `Multi-select: ${n ? `${n} selected` : 'tap objects'}`
    : n > 1 ? `${n} objects` : r ? r.src : 'Tap an object';
  $('tb-nudge').style.display = roots().length && !state.multiTouch ? '' : 'none';
  $('tb-npc').style.display = n === 1 && r && r.kind === 'npc' ? '' : 'none';
  const door = n === 1 && r && doorOf(r);
  $('tb-door').style.display = door && door.cell ? '' : 'none';
  if (door && door.cell) $('tb-door').title = `Go through the door (to ${door.cell})`;
  const a = groupAction();
  $('tb-group').textContent = { ungroup: 'Ungroup', remove: 'Remove from group' }[a] || 'Group';
  $('tb-group').disabled = !a;
  const hidden = document.body.classList.contains('bar-hidden');
  document.documentElement.style.setProperty('--bar-h', (hidden ? 0 : $('touchbar').offsetHeight) + 'px');
  const top = $('tb-top');
  const topH = !hidden && getComputedStyle(top).position === 'fixed' ? top.offsetHeight : 0;
  document.documentElement.style.setProperty('--top-h', topH + 'px');
}

function updatePanel() {
  updateTouchBar();
  updateQuickActs();
  updateButtons();
  const obj = state.selected;
  $('npc-row').style.display = 'none';
  if (!obj) {
    $('sel-name').textContent = 'Nothing (click an object)';
    $('sel-info').textContent = '';
    $('door-row').style.display = 'none';
    $('sel-edit').style.display = 'none';
    return;
  }
  const r = obj.userData.ref;
  const n = state.selection.length;
  const wholeGroup = n > 1 && groupAction() === 'ungroup';
  $('sel-name').textContent = n > 1 ? `${wholeGroup ? 'Group of' : ''} ${n} objects`.trim()
    : r.src + (r.id !== r.src ? '  (' + r.id + ')' : '');
  if (n > 1) {
    const names = state.selection.map((o) => o.userData.ref.src);
    $('sel-info').textContent = `${names.slice(0, 4).join(', ')}${n > 4 ? ` and ${n - 4} more` : ''}. `
      + `They move and turn together; the fields show ${r.src} and change them all by the same amount.`
      + (wholeGroup && !TOUCH ? ' Alt+click or double-click selects just one of them.' : '');
    $('sel-edit').style.display = roots().length ? '' : 'none';
    fillFields(r);
    return;
  }
  const tier = r.nook ? `${NOOK_NAMES[r.nook] || r.nook} ${r.only ? 'only at' : 'from'} tier ${r.tier}`
    : Object.keys(NOOK_NAMES).length ? 'always there' : '';
  const p = state.data.project;
  const readOnly = p.standalone ? ` (read-only: the project is standalone, so ${p.plugin} uses only the game's files)`
    : p.inPlace ? ` (read-only: ${r.file} loads after ${p.plugin})`
    : ` (read-only: ${p.plugin} can only change objects of ${p.masters.join(', ')})`;
  const own = p.inPlace && (r.file || '').toLowerCase() === p.plugin.toLowerCase();
  const origin = r.origin === 'vanilla' ? (own ? `in ${p.plugin}` : `from ${r.file || 'a master'}`) + (r.editable ? '' : readOnly)
    : { added: 'added by you', mod: 'mod object' }[r.origin] || '';
  const parent = state.edits.attached[r.key];
  const mv = state.edits.moved[r.key];
  const near = (a, b, eps) => a.every((v, i) => Math.abs(v - b[i]) < eps);
  const moved = mv && !(near(mv.pos, r.orig.pos, 0.01) && near(mv.rot, r.orig.rot, 1e-4));
  const g = groupOf(r.key);
  const changes = [moved && 'moved', mv && mv.scale != null && `scale ${mv.scale.toFixed(2)}`, state.edits.replaced[r.key] && 'changed',
                   parent && `on ${objByKey.get(parent)?.userData.ref.src || 'an object'} (attached)`,
                   g && `in a group of ${state.edits.groups[g].length}`].filter(Boolean);
  const noMesh = obj.userData.noMesh && `its mesh (${r.mesh}) is missing or can't be read, so a box stands in`;
  const edited = mv || state.edits.replaced[r.key] || state.edits.deleted.includes(r.key);
  const others = (r.changedBy || []).filter((f) => !(r.winsOver || []).includes(f));
  const conflict = [others.length && `also changed by ${others.join(', ')}`,
                    r.winsOver?.length && (edited ? `⚠ ${r.winsOver.join(', ')} loads after ${p.plugin} and changes it too: its version wins in game`
                                                  : `changed by ${r.winsOver.join(', ')}, which loads after ${p.plugin}`)];
  $('sel-info').textContent = [origin, tier, ...changes, ...conflict, noMesh].filter(Boolean).join(' · ');
  updateDoor(r);
  $('sel-edit').style.display = r.editable ? '' : 'none';
  $('npc-row').style.display = r.kind === 'npc' ? '' : 'none';
  fillFields(r);
}

// --- Door destinations ----------------------------------------------------------

function doorOf(r) {
  const e = state.edits.doors[r.key];
  if (!e) return r.door;
  let cell = e.cell;
  if (!cell) {
    const g = [Math.floor(e.pos[0] / 8192), Math.floor(e.pos[1] / 8192)];
    cell = state.data.cells.find((c) => c.grid && c.grid[0] === g[0] && c.grid[1] === g[1])?.name;
  }
  return { cell, pos: e.pos, heading: e.rot[2] };
}

function updateQuickActs() {
  if (TOUCH) return;
  const r = state.selection.length === 1 && state.selected.userData.ref;
  const npc = !!(r && r.kind === 'npc');
  const door = r && r.isDoor ? doorOf(r) : null;
  const go = !!(door && door.cell), set = !!(r && r.isDoor && r.editable);
  $('qa-npc').style.display = npc ? '' : 'none';
  $('qa-go').style.display = go ? '' : 'none';
  $('qa-set').style.display = set ? '' : 'none';
  $('qa-name').textContent = npc ? r.src : door ? `Door to ${door.cell || 'the outside'}` : 'A door that leads nowhere';
  $('quick-acts').classList.toggle('open', npc || go || set);
}
$('qa-npc').addEventListener('click', () => $('edit-npc').click());
$('qa-go').addEventListener('click', () => $('door-go').click());
$('qa-set').addEventListener('click', () => $('door-set').click());

function updateDoor(r) {
  const show = state.selection.length === 1 && r.isDoor;
  $('door-row').style.display = show ? '' : 'none';
  if (!show) return;
  const d = doorOf(r);
  $('door-info').textContent = d ? `Door to ${d.cell || 'the outside'}${state.edits.doors[r.key] ? ' (changed)' : ''}`
    : 'A plain door: it leads nowhere.';
  $('door-go').disabled = !d || !d.cell;
  $('door-set').disabled = !r.editable;
}

async function goToDoorDest(r) {
  const d = doorOf(r);
  if (!d || !d.cell) return;
  await loadCell(d.cell, true);
  camera.position.set(d.pos[0], d.pos[1], d.pos[2] + 90);
  state.yaw = d.heading;
  state.pitch = -0.2;
  aimCamera();
}

function setDoorDest(r) {
  const fav = (o) => state.favorites.includes(o.id);
  openPicker({
    title: `Where does ${r.src} lead?`, types: ['Favourites', 'Interior', 'Exterior'],
    placeholder: 'Search cells, e.g. balmora, guild, (-3, -2)…',
    items: state.data.cells.map((c) => ({ id: c.name, name: '', type: c.exterior ? 'Exterior' : 'Interior' })),
    first: fav, star: { on: fav, toggle: (o) => toggleFavorite(o.id) },
    onPick: (o) => startDestPick(r, o.id),
  });
}

async function startDestPick(r, cellName) {
  state.destPick = { key: r.key, name: r.src, from: state.cell.name,
                     camera: { pos: camera.position.clone(), yaw: state.yaw, pitch: state.pitch } };
  const old = doorOf(r);
  await loadCell(cellName, !!(old && old.cell === cellName));
  if (old && old.cell === cellName) {
    camera.position.set(old.pos[0], old.pos[1], old.pos[2] + 90);
    state.yaw = old.heading;
    aimCamera();
  }
  $('dest-text').textContent = `${r.src} → ${cellName}: fly to where the player should arrive, `
    + 'facing the direction they should face, then click Set arrival point here.';
  $('dest-banner').classList.add('open');
}

async function finishDestPick(ok) {
  const p = state.destPick;
  if (!p) return;
  state.destPick = null;
  $('dest-banner').classList.remove('open');
  let dest = null;
  if (ok) {
    const floor = hits(camera.position.clone(), new THREE.Vector3(0, 0, -1), null)[0];
    const z = floor ? floor.point.z : camera.position.z - 90;
    dest = { cell: state.cell.grid ? '' : state.cell.name, pos: [camera.position.x, camera.position.y, z],
             rot: [0, 0, wrapAngle(state.yaw)] };
  }
  const there = state.cell.name;
  await loadCell(p.from, true);
  camera.position.copy(p.camera.pos);
  state.yaw = p.camera.yaw;
  state.pitch = p.camera.pitch;
  aimCamera();
  if (dest) {
    state.undo.push({ doors: [{ key: p.key, prev: state.edits.doors[p.key] }] });
    state.edits.doors[p.key] = dest;
    updateDirty();
    status(`Destination for ${p.name} set to ${there}.`);
  }
  const obj = objByKey.get(p.key);
  if (obj) select(obj);
}

$('door-go').addEventListener('click', () => state.selected && goToDoorDest(state.selected.userData.ref));
$('door-set').addEventListener('click', () => state.selected && setDoorDest(state.selected.userData.ref));
$('dest-here').addEventListener('click', () => finishDestPick(true));
$('dest-cancel').addEventListener('click', () => finishDestPick(false));

function updateButtons() {
  const objs = state.selection.filter((o) => o.visible && o.userData.ref.editable);
  const attached = objs.length > 0 && objs.every((o) => state.edits.attached[o.userData.ref.key]);
  $('attach').disabled = !objs.length;
  $('attach').textContent = attached ? 'Detach' : 'Attach to object below';
  $('attach').title = attached ? 'Stop moving with object below (B)'
    : 'Attach to whatever this stands on (table, shelf, etc.), so moving that object carries this along (B)';
  const a = groupAction();
  $('group').disabled = !a;
  $('group').textContent = { group: 'Group together', ungroup: 'Ungroup',
                             remove: 'Remove from group' }[a] || 'Group together';
  $('group').title = { group: 'Cmd/Ctrl+G: a click on one then selects them all', ungroup: 'Cmd/Ctrl+Shift+G',
                       remove: 'Take just this object out of its group' }[a]
    || 'Cmd/Ctrl+click more objects, then group them: a click on one then selects them all';
  $('swap').disabled = !objs.length;
  $('duplicate').disabled = !objs.length;
  $('obj-history').disabled = state.selection.length !== 1;
  $('look').disabled = !state.selection.length;
}

function fillFields(r) {
  updateDoor(r);
  $('px').value = r.pos[0].toFixed(1);
  $('py').value = r.pos[1].toFixed(1);
  $('pz').value = r.pos[2].toFixed(1);
  $('rz').value = (((r.rot[2] / DEG) % 360) + 360) % 360 | 0;
  $('rx').value = (r.rot[0] / DEG).toFixed(1);
  $('ry').value = (r.rot[1] / DEG).toFixed(1);
  $('sc').value = r.scale.toFixed(2);
}

function canonical(e) {
  const deleted = new Set(e.deleted || []);
  const gone = new Set((e.added || []).map((a) => 'added|' + a.uid).filter((k) => deleted.has(k)));
  const r2 = (v) => Math.round(v * 100) / 100, r5 = (v) => Math.round(v * 1e5) / 1e5;
  const entries = (o, f) => Object.keys(o || {}).filter((k) => !gone.has(k)).sort().map((k) => [k, f(o[k])]);
  return JSON.stringify({
    moved: entries(e.moved, (m) => [m.pos.map(r2), m.rot.map(r5), m.scale == null ? null : Math.round(m.scale * 1000) / 1000]),
    deleted: [...deleted].filter((k) => !gone.has(k)).sort(),
    replaced: entries(e.replaced, (v) => v),
    added: (e.added || []).filter((a) => !gone.has('added|' + a.uid))
      .map((a) => [a.uid, a.cell, a.id, a.pos.map(r2), a.rot.map(r5), a.scale ?? null, a.tier ?? null]),
    attached: entries(e.attached, (v) => v).filter(([, v]) => !gone.has(v)),
    doors: entries(e.doors, (d) => [d.cell, d.pos.map(r2), d.rot.map(r5)]),
    groups: Object.values(e.groups || {}).map((ks) => ks.filter((k) => !gone.has(k)).sort())
      .filter((ks) => ks.length > 1).map((ks) => ks.join('\n')).sort(),
    npcs: entries(e.npcs, (v) => JSON.stringify(sortedKeys(v))),
    dialogue: entries(e.dialogue, (v) => JSON.stringify(sortedKeys(v))),
  });
}

function sortedKeys(o) {
  if (Array.isArray(o)) return o.map(sortedKeys);
  if (o && typeof o === 'object') return Object.fromEntries(Object.keys(o).sort().map((k) => [k, sortedKeys(o[k])]));
  return o;
}

function markSaved() {
  state.saved = canonical(state.edits);
  updateDirty();
}

function updateDirty() {
  state.dirty = canonical(state.edits) !== state.saved;
  $('save').classList.toggle('dirty', state.dirty);
  $('save').title = state.dirty ? 'Save (Ctrl/Cmd+S): there are unsaved changes' : 'Save (Ctrl/Cmd+S): nothing unsaved';
  $('tb-save').textContent = state.dirty ? 'Save *' : 'Save';
  syncSoon();
}

function withSections(e) {
  return Object.assign({ moved: {}, deleted: [], replaced: {}, added: [], attached: {}, doors: {}, groups: {}, npcs: {}, dialogue: {} }, e);
}

function offerDraft() {
  const d = state.data.live.draft;
  if (!d) return;
  $('draft-text').textContent = `Unsaved changes from ${new Date(d.at).toLocaleString()} were found: the editor `
    + 'stopped before they were saved.';
  $('draft-banner').classList.add('open');
  $('draft-restore').onclick = async () => {
    $('draft-banner').classList.remove('open');
    state.edits = withSections(d.edits);
    state.undo = [];
    updateDirty();
    cellCache.clear();
    await loadCell(state.cell.name, true);
    status('Unsaved changes restored.');
  };
  $('draft-drop').onclick = () => {
    $('draft-banner').classList.remove('open');
    fetch('/api/live/draft', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
  };
}

let statusTimer = null;
function status(msg, warn = false) {
  const t = $('toast');
  clearTimeout(statusTimer);
  if (!msg) { t.classList.remove('show'); return; }
  t.textContent = msg;
  t.classList.toggle('warn', warn);
  t.classList.add('show');
  statusTimer = setTimeout(() => t.classList.remove('show'), Math.min(30000, (warn ? 8000 : 3500) + msg.length * 30));
}
$('toast').addEventListener('click', () => status(''));

function attachedTo(key) {
  const out = [];
  for (const [child, parent] of Object.entries(state.edits.attached)) {
    if (parent === key && objByKey.has(child)) out.push(objByKey.get(child));
  }
  return out;
}

function withAttached(obj, seen = new Set()) {
  if (seen.has(obj)) return [];
  seen.add(obj);
  return [obj, ...attachedTo(obj.userData.ref.key).flatMap((c) => withAttached(c, seen))];
}

function snapshot(objs) {
  const one = (o) => { const r = o.userData.ref; return { obj: o, pos: [...r.pos], rot: [...r.rot], scale: r.scale, moved: state.edits.moved[r.key] }; };
  const all = [...new Set(objs.flatMap((o) => withAttached(o)))];
  return { obj: state.selected, selection: [...state.selection], items: all.map(one) };
}

function storeMoved(r) {
  state.edits.moved[r.key] = { pos: [...r.pos], rot: [...r.rot] };
  if (r.scale !== (r.orig.scale ?? 1)) state.edits.moved[r.key].scale = r.scale;
}

function carryAttached(obj, before, after, rot0) {
  const delta = after.clone().multiply(before.clone().invert());
  const turn = rotMatrix(obj.userData.ref.rot).multiply(rotMatrix(rot0).invert());
  for (const o of withAttached(obj).slice(1)) {
    const r = o.userData.ref;
    r.pos = new THREE.Vector3(...r.pos).applyMatrix4(delta).toArray();
    r.rot = rotOf(turn.clone().multiply(rotMatrix(r.rot)));
    storeMoved(r);
    applyTransform(o);
  }
}

function beginContinuous() {
  const objs = roots();
  if (objs.length) state.undo.push(snapshot(objs));
}

function edit(change, withUndo = true) {
  const objs = roots();
  if (!objs.length) return;
  if (withUndo) state.undo.push(snapshot(objs));
  for (const obj of objs) {
    const r = obj.userData.ref;
    const before = refMatrix(r), rot0 = [...r.rot];
    change(r, obj);
    if (attachedTo(r.key).length) carryAttached(obj, before, refMatrix(r), rot0);
    storeMoved(r);
    applyTransform(obj);
  }
  updateSelBoxes();
  updateDirty();
  updatePanel();
  if (!gizmoStart) syncGizmo();
}

function undo() {
  const u = state.undo.pop();
  if (!u) return;
  if (u.stale) { status('That change was changed again on another device, so undo leaves it as it is.'); return; }
  if (u.trimmed) status('Undone, except what another device changed since.');
  if (u.groups) {
    state.edits.groups = u.groups;
    setSelection(u.selection);
    updateDirty();
    return;
  }
  if (u.npcs || u.dialogue) {
    const sec = u.npcs ? 'npcs' : 'dialogue';
    for (const n of u[sec]) {
      if (n.prev === undefined) delete state.edits[sec][n.id]; else state.edits[sec][n.id] = n.prev;
    }
    npcEditor.refresh(u[sec].map((n) => sec + '|' + n.id));
    updateDirty();
    if (!npcEditor.isOpen()) status(u.npcs ? `Undone: a change to ${u.npcs.map((n) => n.id).join(', ')} (NPCs).`
                                           : 'Undone: a change to dialogue.');
    return;
  }
  if (u.doors) {
    for (const d of u.doors) {
      if (d.prev) state.edits.doors[d.key] = d.prev; else delete state.edits.doors[d.key];
    }
    updateDirty();
    updatePanel();
    return;
  }
  if (u.copies) {
    for (const c of u.copies) forgetAdded(c.obj, c.uid);
    setSelection(u.selection.filter((o) => objByKey.get(o.userData.ref.key) === o));
    updateDirty();
    return;
  }
  const r = u.obj.userData.ref;
  if (u.added) {
    forgetAdded(u.obj, u.added);
    select(null);
    updateDirty();
    return;
  }
  if (u.attaches) {
    for (const a of u.attaches) {
      const k = a.obj.userData.ref.key;
      if (a.prev) state.edits.attached[k] = a.prev; else delete state.edits.attached[k];
    }
    setSelection(u.selection);
    updateDirty();
    return;
  }
  if (u.swaps) {
    for (const p of u.swaps) {
      const rr = p.obj.userData.ref;
      Object.assign(rr, { src: p.src, mesh: p.mesh, kind: p.kind });
      if (rr.origin === 'added') state.edits.added.find((a) => 'added|' + a.uid === rr.key).id = p.src;
      else if (p.had) state.edits.replaced[rr.key] = p.value;
      else delete state.edits.replaced[rr.key];
    }
    Promise.all(u.swaps.map((p) => fillObject(p.obj))).then(() => setSelection(u.swaps.map((p) => p.obj)));
    updateDirty();
    return;
  }
  if (u.deleted) {
    const keys = new Set(u.deleted.map((o) => o.userData.ref.key));
    state.edits.deleted = state.edits.deleted.filter((k) => !keys.has(k));
    refreshVisibility();
    setSelection(u.deleted);
  } else {
    for (const s of u.items) {
      const rr = s.obj.userData.ref;
      rr.pos = s.pos; rr.rot = s.rot; rr.scale = s.scale;
      if (s.moved) state.edits.moved[rr.key] = s.moved; else delete state.edits.moved[rr.key];
      applyTransform(s.obj);
    }
    setSelection(u.selection);
  }
  updateDirty();
}

function forgetAdded(obj, uid) {
  const r = obj.userData.ref;
  world.remove(obj);
  state.cell.refs = state.cell.refs.filter((x) => x !== r);
  state.edits.added = state.edits.added.filter((a) => a.uid !== uid);
  delete state.edits.moved[r.key];
  delete state.edits.attached[r.key];
  delete state.edits.doors[r.key];
  for (const g of Object.keys(state.edits.groups)) {
    state.edits.groups[g] = state.edits.groups[g].filter((k) => k !== r.key);
    if (state.edits.groups[g].length < 2) delete state.edits.groups[g];
  }
  objByKey.delete(r.key);
}

async function duplicateSelected(rename = null) {
  const objs = roots();
  if (!objs.length) return;
  if (state.cell.canAdd === false) { addAt(null); return; }
  const all = [...new Set(objs.flatMap((o) => withAttached(o)))];
  const box = new THREE.Box3();
  for (const o of all) box.union(new THREE.Box3().setFromObject(o));
  const size = box.getSize(new THREE.Vector3());
  const rt = snapAxis(Math.cos(state.yaw), -Math.sin(state.yaw));
  const step = (rt[0] ? size.x : size.y) + 8;
  const keyOf = new Map();
  const copies = [];
  for (const o of all) {
    const src = o.userData.ref;
    const uid = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const pos = [src.pos[0] + rt[0] * step, src.pos[1] + rt[1] * step, src.pos[2]];
    const tier = src.nook ? `${src.nook}${src.tier}${src.only ? 'o' : ''}` : null;
    const as = rename && rename[src.src.toLowerCase()];
    const r = { key: 'added|' + uid, id: as || src.id, src: as || src.src, kind: src.kind, mesh: src.mesh, pos, rot: [...src.rot],
                scale: src.scale, editable: true, origin: 'added', structure: false, isDoor: src.isDoor, door: src.door,
                nook: src.nook || null, tier: src.tier ?? null, only: !!src.only };
    r.orig = { pos: [...r.pos], rot: [...r.rot] };
    state.edits.added.push({ uid, cell: state.cell.name, id: as || (tier ? src.src : src.id), pos: [...pos], rot: [...r.rot],
                             scale: src.scale === 1 ? 1 : src.scale, tier });
    const door = state.edits.doors[src.key]
      || (src.door && { cell: src.door.interior ? src.door.cell : '', pos: [...src.door.pos], rot: [0, 0, src.door.heading] });
    if (door) state.edits.doors[r.key] = JSON.parse(JSON.stringify(door));
    state.cell.refs.push(r);
    const copy = await makeObject(r);
    world.add(copy);
    objByKey.set(r.key, copy);
    keyOf.set(src.key, r.key);
    copies.push({ obj: copy, uid });
  }
  for (const o of all) {
    const parent = state.edits.attached[o.userData.ref.key];
    if (parent) state.edits.attached[keyOf.get(o.userData.ref.key)] = keyOf.get(parent) || parent;
  }
  const groups = new Set(all.map((o) => groupOf(o.userData.ref.key)).filter(Boolean));
  for (const g of groups) {
    const keys = state.edits.groups[g].map((k) => keyOf.get(k)).filter(Boolean);
    if (keys.length > 1) state.edits.groups['g' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5)] = keys;
  }
  state.undo.push({ obj: state.selected, copies, selection: [...state.selection] });
  refreshVisibility();
  setSelection(copies.map((c) => c.obj));
  updateDirty();
  status(rename ? `Created ${Object.values(rename).join(', ')}.`
    : all.length > 1 ? `Duplicated ${all.length} objects.` : `Duplicated ${all[0].userData.ref.src}.`);
}

function removeSelected() {
  const objs = state.selection.filter((o) => o.visible && o.userData.ref.editable);
  if (!objs.length) return;
  state.undo.push({ obj: state.selected, deleted: objs });
  for (const o of objs) state.edits.deleted.push(o.userData.ref.key);
  select(null);
  refreshVisibility();
  updateDirty();
  if (objs.length > 1) status(`Deleted ${objs.length} objects.`);
}

function snapAxis(dx, dy) {
  return Math.abs(dx) > Math.abs(dy) ? [Math.sign(dx), 0] : [0, Math.sign(dy)];
}

function nudge(forward, right, up) {
  const f = snapAxis(Math.sin(state.yaw), Math.cos(state.yaw));
  const rt = snapAxis(Math.cos(state.yaw), -Math.sin(state.yaw));
  const s = state.moveStep;
  edit((r) => {
    r.pos[0] += (f[0] * forward + rt[0] * right) * s;
    r.pos[1] += (f[1] * forward + rt[1] * right) * s;
    r.pos[2] += up * s;
  });
}

function turn(sign) {
  const objs = roots();
  if (!objs.length) return;
  const c = pivotOf(objs), d = sign * state.rotStep * DEG;
  edit((r) => { r.pos = rotateAround(r.pos, c, d); r.rot[2] = wrapAngle(r.rot[2] + d); });
}

const raycaster = new THREE.Raycaster();

function visibleChain(o) {
  for (; o; o = o.parent) if (!o.visible) return false;
  return true;
}

function refOf(o) {
  for (; o; o = o.parent) if (o.userData.ref) return o;
  return null;
}

function hits(origin, dir, exclude) {
  raycaster.set(origin, dir);
  return raycaster.intersectObjects(world.children, true)
    .filter((h) => visibleChain(h.object) && !h.object.userData.water && refOf(h.object) !== exclude);
}

function dropToFloor() {
  const objs = roots();
  if (!objs.length) return;
  const drops = new Map();
  for (const obj of objs) {
    const box = new THREE.Box3().setFromObject(obj);
    const c = box.getCenter(new THREE.Vector3());
    // Cast down from the object's top, so a floor it is sunk into still counts.
    const under = hits(new THREE.Vector3(c.x, c.y, box.max.z), new THREE.Vector3(0, 0, -1), obj)[0];
    if (under) drops.set(obj, { dz: under.point.z - box.min.z, onto: refOf(under.object)?.userData.ref.src });
  }
  if (!drops.size) { status('Nothing found below to drop onto.', true); return; }
  edit((r, obj) => { if (drops.has(obj)) r.pos[2] += drops.get(obj).dz; });
  const [d] = drops.values();
  status(objs.length === 1 ? `Dropped ${d.dz.toFixed(1)} onto ${d.onto || 'the surface below'}.`
                           : `Dropped ${drops.size} of ${objs.length} objects onto what's below them.`);
}

function lookAtSelected() {
  if (!state.selection.length) return;
  const box = new THREE.Box3();
  for (const o of state.selection) box.union(new THREE.Box3().setFromObject(o));
  const c = box.getCenter(new THREE.Vector3());
  const size = Math.max(60, box.getSize(new THREE.Vector3()).length());
  const d = viewDir();
  camera.position.copy(c).addScaledVector(d, -size * 1.4);
  aimCamera();
}

// --- Adding and changing objects ------------------------------------------

let catalogData = null;
async function getCatalog() {
  if (!catalogData) {
    status('Loading object list…');
    catalogData = await (await fetch('/api/catalog')).json();
    for (const o of catalogData) o.cat = category(o);
    const rank = (o) => OBJECT_CATEGORIES.indexOf(o.cat);
    const label = (o) => (o.cat === 'Furniture' ? o.id.toLowerCase().replace(/^.*?(?=furn_)/, '')
                                                 : (o.name || o.id).toLowerCase());
    [...catalogData].sort((a, b) => rank(a) - rank(b) || label(a).localeCompare(label(b)) ||
                                    a.id.localeCompare(b.id)).forEach((o, i) => { o.rank = i; });
    status('');
  }
  return catalogData;
}

const OFFICIAL_FILES = ['morrowind.esm', 'tribunal.esm', 'bloodmoon.esm'];
const OBJECT_CATEGORIES = ['Furniture', 'Containers', 'Lights', 'Clutter', 'Books', 'Signs and banners', 'Plants',
                           'Ingredients', 'Potions', 'Apparatus', 'Clothing', 'Armor', 'Weapons', 'Tools', 'Doors',
                           'Interior pieces', 'Exterior pieces', 'Rocks and terrain', 'Activators', 'Keys', 'NPCs',
                           'Other'];
const TYPE_CATEGORY = { Container: 'Containers', Light: 'Lights', Book: 'Books', Ingredient: 'Ingredients',
                        Potion: 'Potions', Apparatus: 'Apparatus', Clothing: 'Clothing', Armor: 'Armor',
                        Weapon: 'Weapons', Lockpick: 'Tools', Probe: 'Tools', Repair: 'Tools', Door: 'Doors',
                        Activator: 'Activators', NPC: 'NPCs' };

function category(o) {
  const id = o.id.toLowerCase();
  if ((o.type === 'Static' || o.type === 'Activator') && /(^|_)furn_/.test(id)) {
    return /banner|sign/.test(id) ? 'Signs and banners' : 'Furniture';
  }
  if (/(^|_)flora_/.test(id)) return 'Plants';
  if (o.type === 'Misc') return id.startsWith('key_') ? 'Keys' : 'Clutter';
  if (o.type === 'Static') {
    if (id.startsWith('in_')) return 'Interior pieces';
    if (id.startsWith('ex_')) return 'Exterior pieces';
    if (id.startsWith('terrain_')) return 'Rocks and terrain';
    return 'Other';
  }
  return TYPE_CATEGORY[o.type] || 'Other';
}
const picker = { onPick: null, items: [], source: [], sel: 0, tier: '' };

function tierChoices() {
  const sel = $('pk-tier');
  sel.innerHTML = '';
  sel.add(new Option('Always there', ''));
  for (const [nook, max] of Object.entries(state.data.nooks).sort()) {
    const name = NOOK_NAMES[nook] || nook;
    sel.add(new Option(`${name}: only before any upgrade`, nook + '0o'));
    for (let t = 1; t <= Math.max(max, 1); t++) {
      sel.add(new Option(`${name}: from tier ${t}`, nook + t));
      sel.add(new Option(`${name}: only at tier ${t}`, nook + t + 'o'));
    }
  }
  sel.value = picker.tier;
  if (sel.value !== picker.tier) sel.value = '';
}

async function openPicker({ title, items, types, placeholder, showTier = false, onPick, first = null, star = null,
                            attach = null, action = null, groups = [] }) {
  if (document.pointerLockElement) document.exitPointerLock();
  closeMenu();
  $('pk-title').textContent = title;
  $('pk-search').placeholder = placeholder || 'Search by name or id, e.g. chair, crate, torch…';
  const modTiers = showTier && $('mod-section').style.display !== 'none';
  $('pk-mod').style.display = modTiers ? '' : 'none';
  const type = $('pk-type');
  type.innerHTML = '';
  type.add(new Option('All', ''));
  for (const t of types) type.add(new Option(t, t));
  for (const g of groups) {
    const og = document.createElement('optgroup');
    og.label = g.label;
    for (const [value, label] of g.options) og.appendChild(new Option(label, value));
    type.appendChild(og);
  }
  if (modTiers) { tierChoices(); updatePickerModSummary(); } else $('pk-tier').innerHTML = '';
  picker.source = items;
  picker.onPick = onPick;
  picker.first = first;
  picker.star = star;
  $('pk-attach-row').style.display = attach ? '' : 'none';
  if (attach) $('pk-attach-label').textContent = `Attach to ${attach}`;
  $('pk-box').classList.toggle('with-preview', !!action);
  $('pk-type-label').textContent = action ? 'Category' : 'Type';
  if (action) $('pk-pv-use').textContent = action;
  preview.shown = null;
  $('picker').classList.add('open');
  filterPicker();
  if (!TOUCH) {
    $('pk-search').focus();
    $('pk-search').select();
  }
}

async function pickObject(title, showTier, onPick, attach = null, action = 'Add', group = 0) {
  const fav = (o) => state.objectFavorites.includes(o.id);
  const fresh = npcEditor.newItems().map((o) => Object.assign(o, { cat: 'NPCs', rank: -1 }));
  const items = [...fresh, ...await opening(getCatalog())];
  const files = [...new Set(items.map((o) => o.file).filter((f) => f && !OFFICIAL_FILES.includes(f.toLowerCase())))];
  const mods = files.map((f) => ['file:' + f, f.replace(/\.(esm|esp|omwaddon)$/i, '')]);
  openPicker({ title, items, types: ['Favourites', ...OBJECT_CATEGORIES], showTier, onPick,
               attach, action, first: fav, star: { on: fav, toggle: (o) => toggleObjectFavorite(o.id) },
               groups: mods.length ? [{ label: 'Mods', options: mods }] : [] });
  $('pk-group-row').style.display = group ? '' : 'none';
  $('pk-group').checked = true;
  $('pk-group-label').textContent = `Add to the group (${group} objects)`;
}

async function newNpc(put) {
  const n = await npcEditor.create();
  if (n === 'existing') { pickNpc(put); return; }
  showAddMarker(null);
  if (!n) { resumeFlySoon(); return; }
  await put({ id: n.id, name: n.name, type: 'NPC', mesh: '' });
  openNpcs(n.id);
}

async function pickNpc(onPick) {
  const fav = (o) => state.objectFavorites.includes(o.id);
  const fresh = npcEditor.newItems().map((o) => Object.assign(o, { cat: 'NPCs', rank: -1 }));
  const items = [...fresh, ...(await opening(getCatalog())).filter((o) => o.type === 'NPC')];
  const files = [...new Set(items.map((o) => o.file).filter((f) => f && !OFFICIAL_FILES.includes(f.toLowerCase())))];
  openPicker({ title: 'Place an existing NPC', items, types: ['Favourites'], onPick, first: fav,
               placeholder: 'Search by name or id, e.g. guard, Fargoth, trader…',
               star: { on: fav, toggle: (o) => toggleObjectFavorite(o.id) },
               groups: files.length ? [{ label: 'Mods', options: files.map((f) => ['file:' + f, f.replace(/\.(esm|esp|omwaddon)$/i, '')]) }] : [] });
  $('pk-group-row').style.display = 'none';
}

async function toggleObjectFavorite(id) {
  const f = state.objectFavorites;
  state.objectFavorites = f.includes(id) ? f.filter((x) => x !== id) : [...f, id];
  await fetch('/api/favorites', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ objects: state.objectFavorites }) });
}

function closePicker() {
  $('picker').classList.remove('open');
  picker.onPick = null;
  showAddMarker(null);
  resumeFlySoon();
}

function renderPicker() {
  const list = $('pk-list');
  list.innerHTML = '';
  const shown = picker.items.slice(0, 250);
  picker.paints = new Map();
  shown.forEach((o, i) => {
    const row = document.createElement('div');
    row.className = 'pk-item' + (i === picker.sel ? ' sel' : '');
    row.innerHTML = '<span class="n"></span><span class="t"></span>';
    row.querySelector('.n').textContent = o.name ? `${o.name}  ` : o.id;
    if (o.name) {
      const id = document.createElement('span');
      id.className = 'i';
      id.textContent = o.id;
      row.querySelector('.n').appendChild(id);
    }
    row.querySelector('.t').textContent = o.type;
    if (picker.star) {
      const st = document.createElement('span');
      const paint = () => { const on = picker.star.on(o); st.innerHTML = icon(on ? 'starFilled' : 'star'); st.className = 'star' + (on ? ' on' : ''); };
      paint();
      picker.paints.set(o, paint);
      st.title = 'Favourite';
      st.addEventListener('click', async (e) => { e.stopPropagation(); await picker.star.toggle(o); paint(); paintPreviewStar(); });
      row.appendChild(st);
    }
    row.addEventListener('click', () => (TOUCH && picker.sel !== i && previewing() ? highlight(i) : pick(o)));
    row.addEventListener('mouseenter', () => { if (!TOUCH) showPreview(o); });
    list.appendChild(row);
  });
  showPreview(picker.items[picker.sel]);
  $('pk-count').textContent = picker.items.length > shown.length
    ? `${picker.items.length} matches, showing the first ${shown.length}: type more to narrow it down`
    : `${picker.items.length} matches`;
  list.children[picker.sel]?.scrollIntoView({ block: 'nearest' });
}

function filterPicker() {
  const words = $('pk-search').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const type = $('pk-type').value;
  const score = (o) => {
    const text = (o.name + ' ' + o.id).toLowerCase();
    let sc = 0;
    for (const w of words) {
      const i = text.indexOf(w);
      if (i < 0) return -1;
      if (i > 0 && !/[\s_\-,(]/.test(text[i - 1])) sc += 1;
    }
    return sc;
  };
  const matchType = (o) => !type || (type === 'Favourites' ? picker.first && picker.first(o)
    : type.startsWith('file:') ? o.file === type.slice(5) : (o.cat || o.type) === type);
  const first = (o) => (picker.first && picker.first(o) ? 0 : 1);
  picker.items = picker.source.filter(matchType)
    .map((o) => [first(o), score(o), o]).filter(([, sc]) => sc >= 0)
    .sort((a, b) => a[0] - b[0] || a[1] - b[1] || (a[2].rank ?? 0) - (b[2].rank ?? 0)).map(([, , o]) => o);
  picker.sel = 0;
  renderPicker();
}

function pick(o) {
  const fn = picker.onPick;
  if ($('pk-tier').options.length) picker.tier = $('pk-tier').value;
  closePicker();
  if (fn) fn(o);
}

$('pk-search').addEventListener('input', filterPicker);
$('pk-type').addEventListener('change', filterPicker);
$('pk-cancel').addEventListener('click', closePicker);
$('picker').addEventListener('click', (e) => { if (e.target === $('picker')) closePicker(); });
$('pk-search').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closePicker(); return; }
  if (e.key === 'Enter' && picker.items[picker.sel]) { pick(picker.items[picker.sel]); return; }
  const d = { ArrowDown: 1, ArrowUp: -1 }[e.key];
  if (d) {
    e.preventDefault();
    highlight(Math.max(0, Math.min(Math.min(picker.items.length, 250) - 1, picker.sel + d)));
  }
});

function highlight(i) {
  const rows = $('pk-list').children;
  rows[picker.sel]?.classList.remove('sel');
  picker.sel = i;
  rows[i]?.classList.add('sel');
  rows[i]?.scrollIntoView({ block: 'nearest' });
  showPreview(picker.items[i]);
}

// --- Object preview in the picker -------------------------------------------

const preview = { renderer: null, scene: null, camera: null, group: null, shown: null, token: 0,
                  yaw: 0.6, pitch: 0.35, dist: 100, center: new THREE.Vector3(), pointers: new Map() };

function previewing() { return $('pk-box').classList.contains('with-preview'); }

function setupPreview() {
  if (preview.renderer) return;
  const c = $('pk-canvas');
  preview.renderer = new THREE.WebGLRenderer({ canvas: c, antialias: true });
  preview.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  preview.scene = new THREE.Scene();
  preview.scene.background = new THREE.Color(0x1c1c24);
  preview.camera = new THREE.PerspectiveCamera(35, 1, 1, 100000);
  preview.camera.up.set(0, 0, 1);
  preview.scene.add(new THREE.AmbientLight(0xffffff, 1.4));
  const light = new THREE.DirectionalLight(0xfff2dd, 1.6);
  light.position.set(-0.4, -0.3, 1);
  preview.camera.add(light);
  preview.scene.add(preview.camera);
  preview.group = new THREE.Group();
  preview.scene.add(preview.group);
  const pinch = () => { const [a, b] = [...preview.pointers.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
  let pinchStart = null;
  c.addEventListener('pointerdown', (e) => {
    c.setPointerCapture(e.pointerId);
    preview.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (preview.pointers.size === 2) pinchStart = { d: pinch(), dist: preview.dist };
  });
  c.addEventListener('pointermove', (e) => {
    const p = preview.pointers.get(e.pointerId);
    if (!p) return;
    if (preview.pointers.size === 1) {
      preview.yaw -= (e.clientX - p.x) * 0.01;
      preview.pitch = Math.max(-1.4, Math.min(1.4, preview.pitch + (e.clientY - p.y) * 0.01));
    }
    p.x = e.clientX; p.y = e.clientY;
    if (preview.pointers.size === 2 && pinchStart) preview.dist = pinchStart.dist * pinchStart.d / Math.max(1, pinch());
    previewNeedsRender = true;
  });
  const up = (e) => { preview.pointers.delete(e.pointerId); pinchStart = null; };
  c.addEventListener('pointerup', up);
  c.addEventListener('pointercancel', up);
  c.addEventListener('wheel', (e) => {
    e.preventDefault();
    preview.dist *= Math.exp(e.deltaY * 0.001);
    previewNeedsRender = true;
  }, { passive: false });
}

async function showPreview(o) {
  if (!previewing() || !o || preview.shown === o) return;
  setupPreview();
  preview.shown = o;
  $('pk-pv-name').textContent = o.name || o.id;
  const from = o.file && o.file.toLowerCase() !== 'morrowind.esm' ? ` · ${o.file}` : '';
  $('pk-pv-id').textContent = (o.name ? `${o.id} · ${o.type}` : `${o.cat || o.type} · ${o.type}`) + from;
  paintPreviewStar();
  const token = ++preview.token;
  const parts = o.mesh ? await meshParts(o.mesh) : [];
  if (token !== preview.token) return;
  preview.group.clear();
  for (const p of parts) preview.group.add(new THREE.Mesh(p.geometry, p.material));
  const box = new THREE.Box3().setFromObject(preview.group);
  if (box.isEmpty()) {
    $('pk-pv-id').textContent += ' · no preview';
    preview.center.set(0, 0, 0);
    preview.dist = 100;
  } else {
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    preview.center.copy(sphere.center);
    preview.dist = Math.max(sphere.radius, 4) / Math.sin((preview.camera.fov / 2) * DEG) * 1.05;
  }
  previewNeedsRender = true;
}

function renderPreview() {
  const c = $('pk-canvas');
  const w = c.clientWidth, h = c.clientHeight;
  if (!w || !h) return;
  const r = preview.renderer;
  if (c.width !== Math.round(w * r.getPixelRatio()) || c.height !== Math.round(h * r.getPixelRatio())) {
    r.setSize(w, h, false);
    preview.camera.aspect = w / h;
    preview.camera.updateProjectionMatrix();
  }
  const { yaw, pitch, dist, center } = preview;
  preview.camera.position.set(center.x + Math.sin(yaw) * Math.cos(pitch) * -dist,
                              center.y + Math.cos(yaw) * Math.cos(pitch) * -dist,
                              center.z + Math.sin(pitch) * dist);
  preview.camera.near = Math.max(0.5, dist / 200);
  preview.camera.far = dist * 20;
  preview.camera.updateProjectionMatrix();
  preview.camera.lookAt(center);
  r.render(preview.scene, preview.camera);
}

$('pk-pv-use').addEventListener('click', () => { if (preview.shown) pick(preview.shown); });

function paintPreviewStar() {
  const b = $('pk-pv-fav'), o = preview.shown;
  b.style.display = picker.star && o ? '' : 'none';
  if (b.style.display) return;
  const on = picker.star.on(o);
  b.innerHTML = icon(on ? 'starFilled' : 'star');
  b.append('Favourite');
  b.title = on ? 'A favourite: shown first (click to take it out)' : 'Show it first in the list';
  b.classList.toggle('on', on);
}

$('pk-pv-fav').addEventListener('click', async () => {
  const o = preview.shown;
  if (!o || !picker.star) return;
  await picker.star.toggle(o);
  paintPreviewStar();
  picker.paints?.get(o)?.();
});

function surfaceAt(ndcX, ndcY) {
  camera.updateMatrixWorld();
  raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);
  return raycaster.intersectObjects(world.children, true).find((h) => visibleChain(h.object) && !h.object.userData.water);
}

function addAt(hit, kind = 'object') {
  const preset = state.placeObject;
  state.placeObject = null;
  if (state.cell.canAdd === false) {
    const p = state.data.project;
    status(p.standalone ? `Objects can't be added here: the cell comes from a mod, and the project is standalone.`
      : p.inPlace ? `Objects can't be added here: the cell comes from a file that loads after ${p.plugin}.`
      : `Objects can't be added here: ${p.plugin} can only use cells of ${p.masters.join(', ')}.`, true);
    return;
  }
  if (!hit) { status('Point at a surface to place the object.', true); return; }
  const point = hit.point.clone();
  const normal = hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : new THREE.Vector3(0, 0, 1);
  const base = refOf(hit.object);
  const baseRef = base && !base.userData.ref.structure ? base.userData.ref : null;
  const group = groupAction() === 'ungroup' ? groupOf(state.selected.userData.ref.key) : null;
  showAddMarker(hit);
  const put = async (o) => {
    const parts = o.mesh ? await meshParts(o.mesh) : [];
    const box = new THREE.Box3();
    for (const p of parts) { p.geometry.computeBoundingBox(); box.union(p.geometry.boundingBox); }
    const pos = point.clone();
    if (normal.z > 0.6 && Number.isFinite(box.min.z)) pos.z -= box.min.z;
    else pos.addScaledVector(normal, 2);
    const quarter = Math.PI / 2;
    const yaw = ((Math.round((state.yaw + Math.PI) / quarter) * quarter) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
    const uid = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const tier = ($('pk-tier').options.length && picker.tier) || null;
    const m = tier && tier.match(/^([a-z]+)(\d)(o?)$/);
    const npc = o.type === 'NPC';
    const r = { key: 'added|' + uid, id: o.id, src: o.id, kind: npc ? 'npc' : 'mesh', mesh: npc ? null : o.mesh, pos: pos.toArray(),
                rot: [0, 0, yaw], scale: 1, editable: true, origin: 'added', structure: false,
                nook: m ? m[1] : null, tier: m ? +m[2] : null, only: !!(m && m[3]) };
    r.orig = { pos: [...r.pos], rot: [...r.rot] };
    state.edits.added.push({ uid, cell: state.cell.name, id: o.id, pos: [...r.pos], rot: [...r.rot], scale: 1, tier });
    state.cell.refs.push(r);
    const obj = await makeObject(r);
    world.add(obj);
    objByKey.set(r.key, obj);
    const offered = (row) => !preset && $(row).style.display !== 'none';
    if (baseRef && offered('pk-attach-row') && $('pk-attach').checked) state.edits.attached[r.key] = baseRef.key;
    const grouped = group && offered('pk-group-row') && state.edits.groups[group] && $('pk-group').checked;
    if (grouped) state.edits.groups[group].push(r.key);
    state.undo.push({ obj, added: uid });
    refreshVisibility();
    select(obj.visible ? obj : null, false, true);
    updateDirty();
    status(`Added ${o.name || o.id}` + (state.edits.attached[r.key] ? `, attached to ${baseRef.src}` : '')
           + (grouped ? `, in the group (${state.edits.groups[group].length} objects).` : '.')
           + (obj.visible ? '' : ' It belongs to a tier that is hidden right now.'));
  };
  if (preset) { put(preset); return; }
  if (kind === 'npc') { newNpc(put); return; }
  pickObject('Add object', true, put, baseRef ? `"${baseRef.src}" (moves with it)` : null, 'Add',
             group ? state.edits.groups[group].length : 0);
}

// --- Placing ---------------------------------------------------------------

function startPlacing(kind = 'object') {
  if (state.placing) return;
  const body = document.body;
  state.placing = { hidden: body.classList.contains('panel-hidden'), open: body.classList.contains('panel-open'), kind };
  if (TOUCH && !sidePanel()) body.classList.remove('panel-open');
  $('place-text').textContent = kind === 'npc' ? 'Click where the NPC should stand (a floor, the ground).'
    : 'Click where to place the object (a floor, a table, a wall).';
  $('place-banner').classList.add('open');
  canvas.style.cursor = 'crosshair';
  gizmo.detach();
  resize();
}

function stopPlacing() {
  const p = state.placing;
  if (!p) return;
  state.placing = null;
  $('place-text').textContent = 'Click where to place the object (a floor, a table, a wall).';
  document.body.classList.toggle('panel-hidden', p.hidden);
  document.body.classList.toggle('panel-open', p.open);
  $('place-banner').classList.remove('open');
  canvas.style.cursor = '';
  showAddMarker(null);
  syncGizmo();
  resize();
}

function placeAt(ndcX, ndcY) {
  const hit = surfaceAt(ndcX, ndcY);
  const kind = state.placing?.kind;
  stopPlacing();
  addAt(hit, kind);
}

$('place-cancel').addEventListener('click', () => { state.placeObject = null; stopPlacing(); });

function swapSelected() {
  const objs = state.selection.filter((o) => o.visible && o.userData.ref.editable);
  if (!objs.length) return;
  const n = objs.length;
  pickObject(n > 1 ? `Swap ${n} models (keeps positions)` : 'Swap model (keeps position)', false, async (o) => {
    const swaps = objs.map((obj) => {
      const r = obj.userData.ref;
      return { obj, src: r.src, mesh: r.mesh, kind: r.kind, had: r.key in state.edits.replaced,
               value: state.edits.replaced[r.key] };
    });
    state.undo.push({ obj: state.selected, swaps });
    for (const obj of objs) {
      const r = obj.userData.ref;
      if (r.origin === 'added') state.edits.added.find((a) => 'added|' + a.uid === r.key).id = o.id;
      else state.edits.replaced[r.key] = o.id;
      Object.assign(r, { src: o.id, mesh: o.mesh, kind: 'mesh', structure: false });
    }
    await Promise.all(objs.map(fillObject));
    setSelection(objs);
    updateDirty();
    status(`Swapped ${n > 1 ? n + ' objects ' : ''}to ${o.name || o.id}.`);
  }, null, 'Swap');
}

$('add').addEventListener('click', () => startPlacing());
$('add-npc').addEventListener('click', () => startPlacing('npc'));
$('swap').addEventListener('click', swapSelected);

// --- Quick menu (right click / long-press) ----------------------------------

function closeMenu() {
  $('ctxmenu').classList.remove('open');
  if (!$('picker').classList.contains('open')) showAddMarker(null);
}

const addMarker = new THREE.Group();
{
  const mat = new THREE.MeshBasicMaterial({ color: 0xffcc33, depthTest: false, transparent: true, side: THREE.DoubleSide });
  addMarker.add(new THREE.Mesh(new THREE.RingGeometry(0.7, 1, 32), mat));
  addMarker.add(new THREE.Mesh(new THREE.CircleGeometry(0.18, 16), mat));
  addMarker.renderOrder = 10;
  addMarker.traverse((o) => { o.renderOrder = 10; });
  addMarker.visible = false;
  scene.add(addMarker);
}

function showAddMarker(hit) {
  addMarker.visible = !!hit;
  if (hit) {
    const n = hit.face ? hit.face.normal.clone().transformDirection(hit.object.matrixWorld) : new THREE.Vector3(0, 0, 1);
    addMarker.position.copy(hit.point).addScaledVector(n, 0.5);
    addMarker.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    addMarker.scale.setScalar(Math.max(8, camera.position.distanceTo(hit.point) * 0.045));
  }
  requestRender();
}

function openMenuAt(x, y) {
  const [ndcX, ndcY] = ndc(x, y);
  const hit = surfaceAt(ndcX, ndcY);
  const locked = $('lock').checked;
  const obj = hit && refOf(hit.object);
  const target = obj && !(locked && obj.userData.ref.structure) ? obj : null;
  if (target && !state.selection.includes(target)) select(target);
  const multi = target && state.selection.length > 1 ? state.selection.length : 0;
  const m = $('ctxmenu');
  m.innerHTML = '';
  const item = (label, fn) => {
    const d = document.createElement('div');
    d.className = fn ? 'mi' : 'mi off';
    d.textContent = label;
    d.title = label;
    if (fn) d.addEventListener('click', () => { closeMenu(); fn(); resumeFlySoon(); });
    m.appendChild(d);
  };
  if (target) {
    const h = document.createElement('div');
    h.className = 'mh';
    h.textContent = multi ? `${multi} objects` : target.userData.ref.src;
    m.appendChild(h);
    if (!multi && !target.userData.ref.editable) {
      item(state.data.project.standalone ? `Read-only: from ${target.userData.ref.file} (the project is standalone)`
        : `Read-only: from ${target.userData.ref.file}, not a master of ${state.data.project.plugin}`, null);
      if (target.userData.ref.kind === 'npc') item('NPC…', () => openNpcs(target.userData.ref.src));
      item('Focus selection', lookAtSelected);
    }
    if (multi || target.userData.ref.editable) {
      item(multi ? `Swap ${multi} models…` : 'Swap model…', swapSelected);
      item(multi ? `Duplicate ${multi} objects` : 'Duplicate', duplicateSelected);
      item(multi ? `Delete ${multi} objects` : 'Delete', removeSelected);
      item('Drop onto surface', dropToFloor);
      item('Reset', resetSelected);
      if (multi) {
        const ga = groupAction();
        if (ga === 'group') item('Group selection', groupSelected);
        if (ga === 'ungroup') {
          item('Ungroup', ungroupSelected);
          item(`Select just ${target.userData.ref.src}`, () => select(target, false, true));
        }
        item('Attach each to object below', toggleAttach);
      } else if (groupOf(target.userData.ref.key)) {
        item('Remove from group', removeFromGroup);
      }
      if (!multi) {
        if (target.userData.ref.kind === 'npc') item('Edit NPC…', () => openNpcs(target.userData.ref.src));
        item('Object history…', () => showObjectHistory(target.userData.ref));
        const parentKey = state.edits.attached[target.userData.ref.key];
        if (parentKey) item(`Detach from ${objByKey.get(parentKey)?.userData.ref.src || 'object below'}`, () => setAttached(target, null));
        else {
          const { under, why } = objectBelow(target);
          if (under) item(`Attach to ${under.userData.ref.src}`, () => attachBelow(target));
          else item(`Can't attach: ${why}`, null);
        }
      }
      item('Focus selection', lookAtSelected);
    }
  }
  if (hit && state.cell.canAdd !== false) {
    if (target) m.appendChild(Object.assign(document.createElement('div'), { className: 'sep' }));
    item('Add object here…', () => addAt(hit));
    item('Add NPC here…', () => addAt(hit, 'npc'));
  }
  showAddMarker(hit);
  m.classList.add('open');
  const w = m.offsetWidth, hgt = m.offsetHeight, off = TOUCH ? 24 : 16;
  m.style.left = Math.min(x + off, window.innerWidth - w - 6) + 'px';
  m.style.top = Math.min(y + off, window.innerHeight - hgt - 6) + 'px';
}

window.addEventListener('pointerdown', (e) => {
  if ($('ctxmenu').classList.contains('open') && !$('ctxmenu').contains(e.target)) closeMenu();
}, true);

function setAttached(obj, parentKey) {
  setAttachments([[obj, parentKey]]);
}

function setAttachments(changes) {
  if (!changes.length) return;
  state.undo.push({ obj: state.selected, selection: [...state.selection],
                    attaches: changes.map(([o]) => ({ obj: o, prev: state.edits.attached[o.userData.ref.key] })) });
  for (const [o, parentKey] of changes) {
    const k = o.userData.ref.key;
    if (parentKey) state.edits.attached[k] = parentKey; else delete state.edits.attached[k];
  }
  updateDirty();
  updatePanel();
}

function toggleAttach() {
  const objs = state.selection.filter((o) => o.visible && o.userData.ref.editable);
  if (!objs.length) return;
  const detach = objs.every((o) => state.edits.attached[o.userData.ref.key]);
  const changes = [], skipped = [];
  for (const o of objs) {
    const r = o.userData.ref;
    if (detach) { changes.push([o, null]); continue; }
    if (state.edits.attached[r.key]) continue;
    const { under, why } = objectBelow(o);
    if (under) changes.push([o, under.userData.ref.key]);
    else skipped.push(objs.length > 1 ? `${r.src}: ${why}` : why);
  }
  setAttachments(changes);
  const n = changes.length;
  if (detach) status(n > 1 ? `Detached ${n} objects.` : 'Detached: no longer moves with object below.');
  else if (n === 1 && objs.length === 1) {
    status(`Attached to ${objByKey.get(changes[0][1])?.userData.ref.src}: it now moves with it.`);
  } else {
    status([n ? `Attached ${n} object${n > 1 ? 's' : ''} to object below.` : '',
            skipped.length ? `Not attached: ${skipped.join('; ')}.` : ''].filter(Boolean).join(' '), !n);
  }
}

function objectBelow(obj) {
  const box = new THREE.Box3().setFromObject(obj);
  const c = box.getCenter(new THREE.Vector3());
  const under = hits(new THREE.Vector3(c.x, c.y, box.max.z), new THREE.Vector3(0, 0, -1), obj)
    .map((h) => refOf(h.object)).find((o) => o && o !== obj);
  if (!under || under.userData.ref.structure) return { why: 'not resting on another object' };
  if (withAttached(obj).includes(under)) return { why: `${under.userData.ref.src} is attached to it` };
  return { under };
}

function attachBelow(obj) {
  const { under, why } = objectBelow(obj);
  if (!under) { status(`Can't attach: ${why}.`, true); return; }
  setAttached(obj, under.userData.ref.key);
  status(`Attached to ${under.userData.ref.src}: it now moves with it.`);
}

function resetSelected() {
  const objs = roots();
  if (!objs.length) return;
  edit((r) => { r.pos = [...r.orig.pos]; r.rot = [...r.orig.rot]; r.scale = r.orig.scale ?? 1; });
  for (const o of objs) delete state.edits.moved[o.userData.ref.key];
  updateDirty();
  updatePanel();
}

// --- Panel, full screen ------------------------------------------------------

function togglePanel() {
  document.body.classList.toggle('panel-hidden');
  if (TOUCH) document.body.classList.remove('bar-hidden');
  updateTouchBar();
  resize();
}

function toggleFullscreen() {
  const el = document.documentElement;
  const isFull = document.fullscreenElement || document.webkitFullscreenElement;
  if (isFull) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
  else if (el.requestFullscreen) {
    el.requestFullscreen()
      .then(() => navigator.keyboard?.lock?.(['Escape']).catch(() => {}))
      .catch(() => fullscreenHelp());
  }
  else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
  else fullscreenHelp();
}

function fullscreenHelp() {
  status('This browser can\'t go full screen. On an iPhone: tap Share, then "Add to Home Screen", and open the '
         + 'editor from the new icon: it runs full screen there.', true);
  if (TOUCH) { document.body.classList.add('panel-open'); }
}

$('hide-panel').addEventListener('click', togglePanel);
$('show-panel').addEventListener('click', () => {
  document.body.classList.remove('panel-hidden', 'bar-hidden');
  updateTouchBar();
});
$('fullscreen').addEventListener('click', toggleFullscreen);
phoneButton($('phone')).then(() => { $('phone-row').style.display = $('phone').style.display; });
$('cell-btn').addEventListener('click', browseCells);
document.addEventListener('fullscreenchange', resize);

// --- History ------------------------------------------------------------------

function when(name) {
  const m = name.match(/^(\d{4})-(\d\d)-(\d\d)_(\d\d)-(\d\d)-(\d\d)(?:_\d{3})?(?:_(.+))?\.json$/);
  if (!m) return name;
  const label = { restored: ' (restored an earlier version)', reverted: ' (reverted an object)',
                  'before-history': ' (before the history started)' }[m[7]] || '';
  return `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}:${m[6]}${label}`;
}

function describe(st) {
  if (!st) return 'as generated (no edit)';
  if (st.added) {
    const p = (st.moved || st.added).pos.map((v) => v.toFixed(0)).join(', ');
    const sc = st.moved && st.moved.scale != null ? `, scale ${st.moved.scale}` : '';
    return `added ${st.replaced || st.added.id} at (${p})${sc}` + (st.deleted ? ', deleted' : '');
  }
  if (st.response) {
    const r = st.response;
    return r.new ? `new response: "${(r.text || '').slice(0, 60)}"` : r.deleted ? 'response deleted'
      : Object.keys(r).filter((k) => k !== 'after').length ? `response changed (${Object.keys(r).join(', ')})` : 'response moved';
  }
  if (st.npc) {
    const keys = Object.keys(st.npc).filter((k) => k !== 'new');
    return st.npc.new ? `new NPC ${st.npc.name || st.npc.id}`
      : `${keys.length} field${keys.length > 1 ? 's' : ''} changed (${keys.slice(0, 5).join(', ')}${keys.length > 5 ? '…' : ''})`;
  }
  const parts = [];
  if (st.replaced) parts.push(`changed to ${st.replaced}`);
  if (st.moved) parts.push(`at (${st.moved.pos.map((v) => v.toFixed(0)).join(', ')}), heading ${(((st.moved.rot[2] / DEG) % 360 + 360) % 360).toFixed(0)}°`);
  if (st.moved && st.moved.scale != null) parts.push(`scale ${st.moved.scale}`);
  if (st.attached) parts.push('attached');
  if (st.door) parts.push(`leads to ${st.door.cell || 'the exterior'}`);
  if (st.group) parts.push('grouped');
  if (st.deleted) parts.push('deleted');
  return parts.join(', ');
}

function historyBox(title, note) {
  $('hb-title').textContent = title;
  $('hb-note').textContent = note || '';
  $('hb-list').innerHTML = '';
  $('historybox').classList.add('open');
  return $('hb-list');
}

function historyRow(list, head, text, actions) {
  const row = document.createElement('div');
  row.className = 'hb-item';
  row.innerHTML = '<div class="when"></div><div class="what"></div><div class="acts"></div>';
  row.querySelector('.when').textContent = head;
  row.querySelector('.what').textContent = text;
  for (const [label, fn] of actions) {
    const b = document.createElement('button');
    b.textContent = label;
    b.addEventListener('click', fn);
    row.querySelector('.acts').appendChild(b);
  }
  list.appendChild(row);
}

async function showHistory() {
  closeMenu();
  const versions = await opening(fetch('/api/history').then((r) => r.json()));
  const list = historyBox('History', versions.length
    ? 'Every save is kept in layout_history/. Open a version to see what changed in it and revert objects.'
    : 'No saves yet: each save from now on is kept here.');
  for (const v of versions) {
    const what = `${v.changes} change${v.changes === 1 ? '' : 's'}` + (v.objects.length ? ': ' + v.objects.join(', ')
      + (v.changes > v.objects.length ? ', …' : '') : '');
    historyRow(list, when(v.name), what, [['Open', () => showVersion(v.name)],
                                          ['Restore this version', () => revertTo(v.name, null)]]);
  }
}

async function showVersion(name) {
  const v = await (await fetch('/api/history/version?name=' + encodeURIComponent(name))).json();
  const list = historyBox(when(name), 'What this save changed. "Revert" puts one object back to how it was before it.');
  historyRow(list, '', '', [['← All versions', showHistory]]);
  for (const c of v.changes) {
    historyRow(list, `${c.object}  ·  ${c.cell.replace(/^Balmora, /, '')}`,
      `before: ${describe(c.before)}\nafter: ${describe(c.after)}`,
      [['Revert to before', () => revertKey(c.key, c.before, name)], ['Object history', () => showObjectHistory({ key: c.key, src: c.object })]]);
  }
}

async function showObjectHistory(r) {
  closeMenu();
  const states = await opening(fetch('/api/history/object?key=' + encodeURIComponent(r.key)).then((x) => x.json()));
  const list = historyBox(`History of ${r.src}`, states.length
    ? 'Its saved states, newest first. "Revert to this" puts it back to that state.'
    : 'No saved changes to this object yet.');
  for (const st of [...states].reverse()) {
    historyRow(list, when(st.name), describe(st.state), [['Revert to this', () => revertTo(st.name, r.key)]]);
  }
}

async function revertTo(name, key) {
  if (state.dirty && !confirm('You have unsaved changes. Save them first, then revert?')) return;
  if (state.dirty) await save();
  const res = await (await fetch('/api/revert', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                   body: JSON.stringify({ name, key }) })).json();
  if (!res.ok) { status('Revert failed: ' + res.message, true); return; }
  state.edits = withSections(res.edits);
  live.shared = entriesOf(state.edits);
  state.undo = [];
  markSaved();
  cellCache.clear();
  $('historybox').classList.remove('open');
  await loadCell(state.cell.name, true);
  status(key ? 'Reverted the object and saved.' : `Restored the version from ${when(name)} and saved.`);
}

async function revertKey(key, before, versionName) {
  const versions = (await (await fetch('/api/history')).json()).map((v) => v.name).sort();
  const i = versions.indexOf(versionName);
  return revertTo(i > 0 ? versions[i - 1] : '', key);
}

$('history').addEventListener('click', showHistory);
$('obj-history').addEventListener('click', () => state.selected && showObjectHistory(state.selected.userData.ref));
$('hb-close').addEventListener('click', () => { $('historybox').classList.remove('open'); resumeFlySoon(); });
$('historybox').addEventListener('click', (e) => {
  if (e.target === $('historybox')) { $('historybox').classList.remove('open'); resumeFlySoon(); }
});

// --- Input -----------------------------------------------------------------

let down = null;
canvas.addEventListener('contextmenu', (e) => e.preventDefault());
// A right-drag look that ends over the panel must not open the browser menu either.
window.addEventListener('contextmenu', (e) => {
  if (state.rightDrag || performance.now() - (state.lookEnded || 0) < 400) e.preventDefault();
});

function setMouseLook(on) {
  if (TOUCH) return;
  state.flyPaused = false;
  if (on) {
    const refused = () => status('The browser blocked mouse capture from a keyboard shortcut. '
                                 + 'Click the "Fly mode" button directly.', true);
    try { canvas.requestPointerLock()?.catch?.(refused); } catch (err) { refused(); }
  } else if (document.pointerLockElement) {
    document.exitPointerLock();
  } else {
    setFly(false);
  }
}

function setFly(on) {
  if (!!state.fly === on) return;
  state.fly = on;
  if (on) state.panelWasHidden = document.body.classList.contains('panel-hidden');
  document.body.classList.toggle('panel-hidden', on || state.panelWasHidden);
  document.body.classList.toggle('mouse-look', on);
  $('look-keys').classList.toggle('open', on);
  resize();
}

function pauseFly() {
  state.flyPaused = true;
  document.exitPointerLock();
}
function resumeFly() {
  if (!state.flyPaused) return;
  if ($('ctxmenu').classList.contains('open') || $('picker').classList.contains('open') || state.opening
      || $('historybox').classList.contains('open') || state.placing || npcEditor.isOpen()
      || document.querySelector('.dialog-bg')) return;
  state.flyPaused = false;
  const stop = () => setFly(false);
  try { canvas.requestPointerLock()?.catch?.(stop); } catch (err) { stop(); }
}
const resumeFlySoon = () => setTimeout(resumeFly, 0);
async function opening(promise) {
  state.opening = (state.opening || 0) + 1;
  try { return await promise; } finally { state.opening -= 1; }
}

document.addEventListener('pointerlockchange', () => {
  const locked = document.pointerLockElement === canvas;
  if (!locked) state.looking = false;
  state.mouseLook = locked && !state.rightDrag;
  gizmo.enabled = !state.mouseLook;
  $('crosshair').style.display = state.mouseLook ? 'block' : 'none';
  if (state.mouseLook) setFly(true);
  else if (!state.flyPaused) setFly(false);
  resizeLater();
});

// The window size can settle a moment after a pointer lock or full-screen change.
function resizeLater() {
  for (const ms of [150, 600]) setTimeout(resize, ms);
}
document.addEventListener('fullscreenchange', resizeLater);
document.addEventListener('webkitfullscreenchange', resizeLater);

function pickAt(ndcX, ndcY, add = false, single = false) {
  camera.updateMatrixWorld();
  raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);
  const locked = $('lock').checked;
  const hits = raycaster.intersectObjects(world.children, true)
    .filter((x) => visibleChain(x.object) && !x.object.userData.water);
  const isStructure = (x) => refOf(x.object)?.userData.ref.structure;
  let h = hits[0];
  if (h && locked && isStructure(h)) {
    h = hits.find((x) => !isStructure(x) && x.distance - hits[0].distance < 40);
  }
  select(h ? refOf(h.object) : null, add, single);
}

let lastTouch = -1e9;
const fromTouch = () => performance.now() - lastTouch < 1000;   // browsers send emulated mouse events after a tap

canvas.addEventListener('mousedown', (e) => {
  if (fromTouch()) return;
  if (document.body.classList.contains('panel-open') && !sidePanel()) {
    $('close-sheet').click();
    down = null;
    return;
  }
  if (state.flyPaused) {
    closeMenu();
    down = null;
    resumeFly();
    return;
  }
  down = { x: e.clientX, y: e.clientY, button: e.button, onGizmo: gizmo.axis !== null && !state.mouseLook };
  if (state.mouseLook) {
    if (e.button === 0 && state.placing) { placeAt(0, 0); return; }
    if (e.button === 0) pickAt(0, 0, e.metaKey || e.ctrlKey, e.altKey);
    if (e.button === 2) {
      pauseFly();
      const r = canvas.getBoundingClientRect();
      openMenuAt(r.left + r.width / 2, r.top + r.height / 2);
    }
    return;
  }
  if (e.button === 2) {
    state.rightDrag = true;
    state.lookMoved = 0;
    state.looking = true;       // no pointer lock: the browser would show a notice each time
  }
});
window.addEventListener('mouseup', (e) => {
  if (fromTouch()) { down = null; return; }
  if (e.button === 2 && state.rightDrag) {
    state.rightDrag = false;
    state.looking = false;
    state.lookEnded = performance.now();
    if (state.lookMoved < 6 && down && e.target === canvas) {
      if (state.placing) stopPlacing(); else openMenuAt(down.x, down.y);
    }
  }
  if (e.button === 0 && down && !down.onGizmo && !state.mouseLook && e.target === canvas
      && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) {
    const [nx, ny] = ndc(e.clientX, e.clientY);
    if (state.placing) placeAt(nx, ny);
    else pickAt(nx, ny, e.metaKey || e.ctrlKey || !!state.multiTouch, e.altKey);
  }
  down = null;
});
canvas.addEventListener('dblclick', (e) => {
  if (fromTouch() || state.mouseLook) return;
  pickAt(...ndc(e.clientX, e.clientY), e.metaKey || e.ctrlKey, true);
});
window.addEventListener('mousemove', (e) => {
  if (state.placing && !state.looking && e.target === canvas) {
    showAddMarker(surfaceAt(...(state.mouseLook ? [0, 0] : ndc(e.clientX, e.clientY))));
  }
  if (!state.looking && !state.mouseLook) return;
  state.lookMoved = (state.lookMoved || 0) + Math.abs(e.movementX) + Math.abs(e.movementY);
  const k = 0.0025 * (state.mouseLook ? state.sensitivity : 1);
  state.yaw += e.movementX * k;
  state.pitch = Math.max(-1.55, Math.min(1.55, state.pitch - e.movementY * k));
  aimCamera();
});
canvas.addEventListener('wheel', (e) => e.preventDefault(), { passive: false });

window.addEventListener('keydown', (e) => {
  if ((e.target.tagName === 'INPUT' && e.target.type !== 'checkbox') || e.target.tagName === 'SELECT') return;
  if ($('picker').classList.contains('open') || $('historybox').classList.contains('open')) return;
  if (document.querySelector('.dialog-bg')) return;
  if (npcEditor.isOpen()) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
    return;
  }
  if (e.key === '?') { showGuide(); return; }
  const k = e.key.toLowerCase();
  const mod = e.ctrlKey || e.metaKey;
  if (mod && k === 'z') { e.preventDefault(); undo(); return; }
  if (mod && k === 's') { e.preventDefault(); save(); return; }
  if (mod && k === 'g') { e.preventDefault(); if (e.shiftKey) ungroupSelected(); else groupButton(); return; }
  if (mod && k === 'd') { e.preventDefault(); duplicateSelected(); return; }
  if (mod) return;
  state.keys.add(e.code);
  const step = { ArrowUp: [1, 0, 0], ArrowDown: [-1, 0, 0], ArrowRight: [0, 1, 0], ArrowLeft: [0, -1, 0],
                 PageUp: [0, 0, 1], PageDown: [0, 0, -1] }[e.key];
  if (step) {
    e.preventDefault();
    if (e.shiftKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) nudge(0, 0, step[0]);
    else nudge(...step);
    return;
  }
  if (e.key === 'Tab') { e.preventDefault(); setMouseLook(!state.mouseLook); return; }
  if (k === 't') { setGizmoMode('translate'); return; }
  if (k === 'p') { togglePanel(); return; }
  if (k === 'r') { setGizmoMode('rotate'); return; }
  if (k === 'y') { setGizmoMode('scale'); return; }
  if (k === 'l') { $('lock').checked = !$('lock').checked; lockChanged(); return; }
  if (k === 'z') turn(-1);
  else if (k === 'x') turn(1);
  else if (k === 'g') dropToFloor();
  else if (k === 'b') toggleAttach();
  else if (e.key === '-' || e.key === '+' || e.key === '=') {
    const f = e.key === '-' ? 1 / 1.05 : 1.05;
    edit((r) => { r.scale = clampScale(r.scale * f); });
  }
  else if (k === 'f') lookAtSelected();
  else if (k === 'escape') {
    if (state.placing) stopPlacing();
    else if ($('ctxmenu').classList.contains('open')) { closeMenu(); resumeFly(); }
    else select(null);
  }
  else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); removeSelected(); }
  else if (/^[1-6]$/.test(e.key)) { state.moveStep = MOVE_STEPS[+e.key - 1]; $('move-step').value = state.moveStep; updateSnap(); }
});
window.addEventListener('keyup', (e) => state.keys.delete(e.code));
window.addEventListener('blur', () => state.keys.clear());

function fly(dt) {
  const k = state.keys;
  const joy = state.joy;
  if (!k.size && !joy.x && !joy.y) return;
  const fast = k.has('ShiftLeft') || k.has('ShiftRight') ? 4 : 1;
  const v = state.speed * fast * dt;
  const d = viewDir();
  const right = new THREE.Vector3(Math.cos(state.yaw), -Math.sin(state.yaw), 0);
  const move = new THREE.Vector3();
  if (k.has('KeyW')) move.add(d);
  if (k.has('KeyS')) move.sub(d);
  if (k.has('KeyD')) move.add(right);
  if (k.has('KeyA')) move.sub(right);
  if (k.has('KeyE')) move.z += 1;
  if (k.has('KeyQ')) move.z -= 1;
  move.addScaledVector(d, joy.y).addScaledVector(right, joy.x);
  if (move.lengthSq() > 0) {
    requestRender();
    if (move.lengthSq() > 1) move.normalize();
    camera.position.addScaledVector(move, v);
    aimCamera();
  }
}

// --- Touch -----------------------------------------------------------------

const sidePanel = () => TOUCH && matchMedia('(orientation: landscape)').matches;

// Pointer capture keeps a held finger's events coming to its control.
function capture(el, id) {
  try { el.setPointerCapture(id); } catch (err) {}
}

if (TOUCH) {
  const touches = new Map();
  canvas.addEventListener('pointerdown', (e) => {
    if (e.pointerType !== 'touch') return;
    lastTouch = performance.now();
    if (document.body.classList.contains('panel-open') && !sidePanel()) { sheet(false); return; }
    if (gizmo.dragging) return;
    const t = { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, t: performance.now(), moved: false };
    t.press = setTimeout(() => { t.pressed = true; openMenuAt(t.sx, t.sy); }, 550);
    touches.set(e.pointerId, t);
  });
  canvas.addEventListener('pointermove', (e) => {
    const t = touches.get(e.pointerId);
    if (!t) return;
    lastTouch = performance.now();
    const dx = e.clientX - t.x, dy = e.clientY - t.y;
    t.x = e.clientX; t.y = e.clientY;
    if (Math.hypot(e.clientX - t.sx, e.clientY - t.sy) > 8) { t.moved = true; clearTimeout(t.press); }
    if (!t.moved || gizmo.dragging) return;
    const k = 0.005 * state.sensitivity / 3;
    state.yaw += dx * k;
    state.pitch = Math.max(-1.55, Math.min(1.55, state.pitch - dy * k));
    aimCamera();
  });
  const endTouch = (e) => {
    const t = touches.get(e.pointerId);
    if (!t) return;
    touches.delete(e.pointerId);
    clearTimeout(t.press);
    lastTouch = performance.now();
    if (e.type === 'pointerup' && !t.moved && !t.pressed && !gizmo.dragging && performance.now() - t.t < 600) {
      const [nx, ny] = ndc(e.clientX, e.clientY);
      if (state.placing) placeAt(nx, ny); else pickAt(nx, ny, state.multiTouch);
    }
  };
  canvas.addEventListener('pointerup', endTouch);
  canvas.addEventListener('pointercancel', endTouch);

  const pad = $('joystick'), stick = $('stick');
  const R = 50;
  let origin = null;
  const joyMove = (e) => {
    if (!origin) origin = { x: e.clientX, y: e.clientY };
    let x = e.clientX - origin.x, y = e.clientY - origin.y;
    const l = Math.hypot(x, y);
    if (l > R) { x *= R / l; y *= R / l; }
    stick.style.transform = `translate(${x}px, ${y}px)`;
    state.joy = { x: x / R, y: -y / R };
  };
  const joyEnd = () => { state.joy = { x: 0, y: 0 }; stick.style.transform = ''; delete pad.dataset.active; origin = null; };
  pad.addEventListener('pointerdown', (e) => { e.preventDefault(); capture(pad, e.pointerId); pad.dataset.active = e.pointerId; origin = null; joyMove(e); });
  pad.addEventListener('pointermove', (e) => { if (pad.dataset.active == e.pointerId) joyMove(e); });
  for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) pad.addEventListener(ev, joyEnd);

  const hold = (btn, code) => {
    btn.addEventListener('pointerdown', (e) => { e.preventDefault(); capture(btn, e.pointerId); state.keys.add(code); });
    for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) btn.addEventListener(ev, () => state.keys.delete(code));
  };
  hold($('fly-up'), 'KeyE');
  hold($('fly-down'), 'KeyQ');

  const actions = {
    'turn-': () => turn(-1), 'turn+': () => turn(1), left: () => nudge(0, -1, 0), right: () => nudge(0, 1, 0),
    fwd: () => nudge(1, 0, 0), back: () => nudge(-1, 0, 0), up: () => nudge(0, 0, 1), down: () => nudge(0, 0, -1),
  };
  $('tb-drop').addEventListener('click', dropToFloor);
  $('tb-door').addEventListener('click', () => state.selected && goToDoorDest(state.selected.userData.ref));
  for (const btn of document.querySelectorAll('#tb-nudge button[data-act]')) {
    const fn = actions[btn.dataset.act];
    let timer = null, rep = null;
    const stop = () => { clearTimeout(timer); clearInterval(rep); timer = rep = null; };
    btn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      capture(btn, e.pointerId);
      fn();
      timer = setTimeout(() => { rep = setInterval(fn, 90); }, 350);
    });
    for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) btn.addEventListener(ev, stop);
  }

  function sheet(open) {
    document.body.classList.toggle('panel-open', open);
    $('tb-panel').classList.toggle('on', open);
    updateTouchBar();
  }
  const SHEET_MIN = 160;
  const sheetMax = () => window.innerHeight - 40;
  const setSheet = (h) => document.documentElement.style.setProperty('--sheet-h', Math.round(h) + 'px');
  const savedSheet = +stored('ce-sheet-h');
  if (savedSheet) setSheet(Math.min(savedSheet, sheetMax()));
  let drag = null;
  $('sheet-grip').addEventListener('pointerdown', (e) => {
    e.preventDefault();
    capture($('sheet-grip'), e.pointerId);
    drag = { y: e.clientY, h: $('panel').offsetHeight };
  });
  $('sheet-grip').addEventListener('pointermove', (e) => {
    if (!drag) return;
    setSheet(Math.max(80, Math.min(sheetMax(), drag.h + drag.y - e.clientY)));
  });
  const endDrag = () => {
    if (!drag) return;
    drag = null;
    const h = $('panel').offsetHeight;
    if (h < SHEET_MIN) { sheet(false); setSheet(Math.max(SHEET_MIN * 2, window.innerHeight * 0.55)); }
    try { localStorage.setItem('ce-sheet-h', Math.max(h, SHEET_MIN * 2)); } catch (err) { /* private mode */ }
  };
  for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) $('sheet-grip').addEventListener(ev, endDrag);
  $('tb-panel').addEventListener('click', () => sheet(!document.body.classList.contains('panel-open')));
  $('close-sheet').addEventListener('click', () => sheet(false));
  $('show-panel').innerHTML = icon('chevUp');
  $('show-panel').title = 'Show the bar';
  $('tb-save').addEventListener('click', save);
  $('tb-full').addEventListener('click', toggleFullscreen);
  $('tb-hide').addEventListener('click', () => { document.body.classList.add('bar-hidden'); document.body.classList.remove('panel-open'); updateTouchBar(); });
  const addMenu = (open) => {
    const m = $('tb-add-menu'), b = $('tb-add');
    m.classList.toggle('open', open);
    b.classList.toggle('on', open);
    b.setAttribute('aria-expanded', String(open));
    if (!open) return;
    const r = b.getBoundingClientRect();
    m.style.left = Math.max(6, Math.min(r.left, window.innerWidth - m.offsetWidth - 6)) + 'px';
    m.style.bottom = (window.innerHeight - r.top + 6) + 'px';
  };
  $('tb-add').addEventListener('click', () => addMenu(!$('tb-add-menu').classList.contains('open')));
  for (const b of $('tb-add-menu').querySelectorAll('button')) {
    b.addEventListener('click', () => { addMenu(false); startPlacing(b.dataset.add); });
  }
  window.addEventListener('pointerdown', (e) => {
    if ($('tb-add-menu').classList.contains('open') && !e.target.closest('#tb-add-menu, #tb-add')) addMenu(false);
  }, true);
  $('tb-undo').addEventListener('click', undo);
  const multiMode = (on) => {
    state.multiTouch = on;
    document.body.classList.toggle('multi-mode', on);
    syncGizmo();
    updateTouchBar();
  };
  $('tb-multi').addEventListener('click', () => multiMode(true));
  $('tb-done').addEventListener('click', () => multiMode(false));
  $('tb-group').addEventListener('click', () => { groupButton(); updateTouchBar(); });
  $('tb-move').addEventListener('click', () => setGizmoMode('translate'));
  $('tb-turn').addEventListener('click', () => setGizmoMode('rotate'));
  $('tb-scale').addEventListener('click', () => setGizmoMode('scale'));
  window.addEventListener('resize', updateTouchBar);
  updateTouchBar();
}

// --- Panel -----------------------------------------------------------------

for (const s of MOVE_STEPS) $('move-step').add(new Option(`${s} units`, s));
for (const s of ROT_STEPS) $('rot-step').add(new Option(`${s}°`, s));
$('move-step').value = state.moveStep;
$('rot-step').value = state.rotStep;
function setSpeed(v) {
  state.speed = Math.max(10, Math.min(10000, Math.round(v)));
  $('fly-speed').value = state.speed;
  try { localStorage.setItem('ce-fly-speed', state.speed); } catch (err) { /* private mode */ }
}
try { setSpeed(+stored('ce-fly-speed') || state.speed); } catch (err) { setSpeed(state.speed); }
$('fly-speed').addEventListener('change', (e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) setSpeed(v); e.target.blur(); });
$('fly-speed').addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === 'Escape') e.target.blur(); });
$('move-step').addEventListener('change', (e) => { state.moveStep = +e.target.value; updateSnap(); e.target.blur(); });
$('rot-step').addEventListener('change', (e) => { state.rotStep = +e.target.value; updateSnap(); e.target.blur(); });
$('snap').addEventListener('change', (e) => { updateSnap(); e.target.blur(); });
$('mode-move').addEventListener('click', () => setGizmoMode('translate'));
$('mode-turn').addEventListener('click', () => setGizmoMode('rotate'));
$('mode-scale').addEventListener('click', () => setGizmoMode('scale'));
$('mouselook').addEventListener('click', () => setMouseLook(true));
$('lock-btn').addEventListener('click', () => { $('lock').checked = !$('lock').checked; lockChanged(); });
function paintLock() {
  const on = $('lock').checked;
  $('lock-btn').classList.toggle('on', on);
  $('lock-btn').setAttribute('aria-pressed', String(on));
  $('lock-btn').title = on ? 'On: walls and floors are locked, so clicks select objects in front of them. Click (or L) to unlock.'
    : 'Off: walls and floors can be selected and moved. Click (or L) to lock.';
}
paintLock();
function lockChanged() {
  paintLock();
  const on = $('lock').checked;
  status(on ? 'Walls and floors are locked: clicks select objects in front.'
            : 'Walls and floors can be selected and moved now (L locks them again).');
  if (on && state.selection.some((o) => o.userData.ref.structure)) select(null);
}

function scrubbable(input, perPixel, apply, isEdit = true) {
  input.classList.add('scrub');
  input.addEventListener('mousedown', (e) => {
    if (document.activeElement === input || e.button !== 0) return;
    e.preventDefault();
    const startX = e.clientX;
    let dragging = false;
    const move = (ev) => {
      if (!dragging) {
        if (Math.abs(ev.clientX - startX) < 3) return;
        dragging = true;
        if (isEdit) beginContinuous();
      }
      const mult = ev.shiftKey ? 10 : ev.altKey ? 0.1 : 1;
      apply(ev.movementX * perPixel * mult);
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      if (!dragging) { input.focus(); input.select(); }
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  });
}

scrubbable($('fly-speed'), 5, (d) => setSpeed(state.speed + d), false);
function setSensitivity(v) {
  state.sensitivity = Math.max(0.1, Math.min(20, Math.round(v * 10) / 10));
  $('sensitivity').value = state.sensitivity;
  try { localStorage.setItem('ce-mouse-sensitivity', state.sensitivity); } catch (err) { /* private mode */ }
}
try { setSensitivity(+stored('ce-mouse-sensitivity') || state.sensitivity); } catch (err) { setSensitivity(state.sensitivity); }
$('sensitivity').addEventListener('change', (e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) setSensitivity(v); e.target.blur(); });
$('sensitivity').addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === 'Escape') e.target.blur(); });
scrubbable($('sensitivity'), 0.05, (d) => setSensitivity(state.sensitivity + d), false);

for (const [id, i, isRot] of [['px', 0], ['py', 1], ['pz', 2], ['rx', 0, true], ['ry', 1, true], ['rz', 2, true]]) {
  $(id).addEventListener('change', (e) => {
    const v = parseFloat(e.target.value);
    const p = state.selected?.userData.ref;
    if (Number.isNaN(v) || !p) return;
    const d = isRot ? v * DEG - p.rot[i] : v - p.pos[i];
    edit((r) => {
      if (!isRot) r.pos[i] += d;
      else r.rot[i] = r === p ? v * DEG : i === 2 ? wrapAngle(r.rot[i] + d) : r.rot[i] + d;
    });
    e.target.blur();
  });
  $(id).addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === 'Escape') e.target.blur(); });
  scrubbable($(id), isRot ? 0.5 : 1, (d) => edit((r) => {
    if (isRot) r.rot[i] += d * DEG; else r.pos[i] += d;
  }, false));
}
// OpenMW limits reference scale to 0.5 - 2.
const clampScale = (v) => Math.min(2, Math.max(0.5, Math.round(v * 1000) / 1000));
function setScale(v, withUndo = true) { edit((r) => { r.scale = clampScale(v); }, withUndo); }
$('sc').addEventListener('change', (e) => {
  const v = parseFloat(e.target.value);
  if (!Number.isNaN(v)) setScale(v);
  e.target.blur();
});
$('sc').addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === 'Escape') e.target.blur(); });
scrubbable($('sc'), 0.005, (d) => edit((r) => { r.scale = clampScale(r.scale + d); }, false));
$('drop').addEventListener('click', dropToFloor);
$('attach').addEventListener('click', toggleAttach);
$('look').addEventListener('click', lookAtSelected);
function toggleMenu(open = !$('menu').classList.contains('open')) {
  $('menu').classList.toggle('open', open);
  $('menu-btn').setAttribute('aria-expanded', String(open));
}
$('menu-btn').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu(); });
document.addEventListener('pointerdown', (e) => { if (!e.target.closest('#menu, #menu-btn')) toggleMenu(false); });
async function toLauncher(screen, path) {
  try {
    const r = await fetch('/api/launcher/show', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ screen, path }) });
    return !!(await r.json()).shown;
  } catch (err) { return false; }
}
$('to-start').addEventListener('click', async () => {
  toggleMenu(false);
  if (await toLauncher('projects')) return;
  if (state.dirty && !confirm('You have unsaved changes. Leave them and go to the start page?')) return;
  leaving();
  location.href = '/home.html';
});
$('to-settings').addEventListener('click', async () => {
  toggleMenu(false);
  if (await toLauncher('project', state.data.project.path)) return;
  leaving();
  try { sessionStorage.setItem('ce-page', state.data.project.path); } catch (err) { /* private mode */ }
  location.href = '/home.html#project';
});
$('quit').addEventListener('click', async () => {
  toggleMenu(false);
  const others = [...live.others.values()].map((o) => o.label);
  if (others.length && !confirm(`${others.join(' and ')} ${others.length > 1 ? 'are' : 'is'} also editing. `
                                + 'Quit the editor anyway?')) return;
  leaving();
  state.stopped = true;
  await fetch('/api/quit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
  document.body.innerHTML = '<p style="font: 16px system-ui; color: #ddd; padding: 30px">The editor has stopped. '
    + 'You can close this tab.</p>';
});
function leaving() {
  state.stopped = true;
}
$('group').addEventListener('click', groupButton);
$('delete').addEventListener('click', removeSelected);
$('duplicate').addEventListener('click', duplicateSelected);
$('undo').addEventListener('click', undo);
$('save').addEventListener('click', save);

// --- NPCs ------------------------------------------------------------------

const npcEditor = setupNpcEditor({
  state, status, save, changed: updateDirty, closed: resumeFlySoon,
  async placeCopy(n, fromId) {
    const o = { id: n.id, name: n.name, type: 'NPC', mesh: '' };
    const src = fromId && ([state.selected, ...objByKey.values()].find((x) => x && x.visible
      && x.userData.ref.kind === 'npc' && x.userData.ref.src.toLowerCase() === fromId.toLowerCase()));
    if (!src || !src.userData.ref.editable) {
      state.placeObject = o;
      startPlacing();
      $('place-text').textContent = `Click where to place ${n.name || n.id}.`;
      return;
    }
    setSelection([src]);
    await duplicateSelected({ [fromId.toLowerCase()]: n.id });
    status(`Created ${n.name || n.id} (copied from ${npcEditor.nameOf(fromId)}).`);
  },
});
function openNpcs(id = null) {
  if (document.pointerLockElement) pauseFly();
  closeMenu();
  npcEditor.open(id);
}
$('edit-npc').addEventListener('click', () => { const r = state.selected?.userData.ref; if (r) openNpcs(r.src); });
$('tb-npc').addEventListener('click', () => { const r = state.selected?.userData.ref; if (r) openNpcs(r.src); });
$('reset').addEventListener('click', resetSelected);

async function save() {
  if (!state.dirty) { status('Nothing to save: no changes since the last save.'); return; }
  status('Saving…');
  try {
    await flushAll();
    const res = await fetch('/api/save', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                           body: JSON.stringify({ live: true }) });
    const out = await res.json();
    if (!out.ok) throw new Error(out.message);
    state.saved = canonical(out.edits);
    updateDirty();
    sendPicture(true);
    status(`Saved: ${out.moved} moved, ${out.added} added, ${out.replaced} swapped, ${out.deleted} deleted`
           + `${out.doors ? `, ${out.doors} door${out.doors > 1 ? 's' : ''} redirected` : ''}`
           + `${out.npcs ? `, ${out.npcs} NPC${out.npcs > 1 ? 's' : ''} changed or new` : ''}`
           + `${out.responses ? `, ${out.responses} response${out.responses > 1 ? 's' : ''} changed or new` : ''}.\n`
           + `${out.message}\nRestart OpenMW to see it in game.`, !!out.newMasters?.length);
  } catch (err) {
    status('Save failed: ' + err.message, true);
  }
}

// --- Panel placement, quick guide, thumbnail -------------------------------

function setDock(v) {
  document.body.classList.toggle('docked', v !== 'float');
  $('dock').value = v === 'float' ? 'float' : 'dock';
  try { localStorage.setItem('ce-dock', $('dock').value); } catch (err) { /* private mode */ }
  resize();
}
setDock(stored('ce-dock') || 'dock');
$('dock').addEventListener('change', () => { setDock($('dock').value); $('dock').blur(); });

function showGuide() {
  if (document.querySelector('.dialog-bg')) return;
  const mac = /Mac|iPhone|iPad/.test(navigator.platform);
  const cmd = mac ? 'Cmd' : 'Ctrl';
  const keys = (...ks) => ks.map((k) => (k.startsWith('<') ? k : `<kbd>${k}</kbd>`)).join('');
  const rows = TOUCH ? [
    ['Thumbstick', 'Fly (bottom left); the up and down buttons on the right'],
    ['Drag', 'Look around'],
    ['Tap', 'Select an object; the bottom bar moves and rotates it'],
    ['Long-press', 'Quick menu: add object, actions, etc.'],
    ['Lock walls', 'In the panel: lock or unlock walls and floors. Locked: taps select objects in front of them'],
    ['Save', 'In the bottom bar'],
  ] : [
    [keys('W', 'A', 'S', 'D'), `Fly; ${keys('Q')} down, ${keys('E')} up; Shift faster`],
    ['Right mouse', `Hold to look around; Fly mode (${keys('Tab')} or top right): look around with the mouse`],
    ['Click', 'Select an object, then drag the arrows to move it'],
    ['Right click', 'Quick menu: add object, actions, etc. (or Add object… in the panel)'],
    [keys('F'), 'Focus selection'],
    [keys('L'), 'Lock or unlock walls and floors (Lock walls in the panel). Locked: clicks select objects in front of them'],
    [keys(cmd) + '+' + keys('Z'), 'Undo'],
    [keys(cmd) + '+' + keys('S'), 'Save'],
  ];
  const bg = document.createElement('div');
  bg.className = 'dialog-bg';
  const d = document.createElement('div');
  d.className = 'dialog guide';
  d.innerHTML = '<h3>Getting around</h3><ul></ul><div class="foot"></div><div class="bar"><button class="primary">Got it</button></div>';
  for (const [k, what] of rows) {
    const li = document.createElement('li');
    li.innerHTML = `<span class="k">${k}</span><span>${what}</span>`;
    d.querySelector('ul').appendChild(li);
  }
  d.querySelector('.foot').textContent = TOUCH ? 'All controls: Controls, in the panel.'
    : 'All controls: Controls, at the bottom of the panel (or press ?).';
  bg.appendChild(d);
  document.body.appendChild(bg);
  const close = () => {
    bg.remove();
    document.removeEventListener('keydown', onKey, true);
    try { localStorage.setItem('ce-guide-seen', '1'); } catch (err) { /* private mode */ }
  };
  const onKey = (e) => { if (e.key === 'Escape' || e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); close(); } };
  document.addEventListener('keydown', onKey, true);
  bg.addEventListener('click', (e) => { if (e.target === bg) close(); });
  d.querySelector('button').addEventListener('click', close);
  d.querySelector('button').focus();
}
$('guide-btn').addEventListener('click', showGuide);
if (/Mac|iPhone|iPad/.test(navigator.platform)) document.querySelectorAll('kbd.mod').forEach((k) => { k.textContent = 'Cmd'; });

function sendPicture(saved) {
  if (!state.cell || $('loading').style.display !== 'none') return;
  const hide = [gizmoHelper, selBoxes, markers].filter((o) => o.visible);
  for (const o of hide) o.visible = false;
  renderer.render(scene, camera);
  const pic = document.createElement('canvas');
  pic.width = 320;
  pic.height = 200;
  const src = renderer.domElement, aspect = pic.width / pic.height;
  let sw = src.width, sh = src.width / aspect;
  if (sh > src.height) { sh = src.height; sw = sh * aspect; }
  pic.getContext('2d').drawImage(src, (src.width - sw) / 2, (src.height - sh) / 2, sw, sh, 0, 0, pic.width, pic.height);
  for (const o of hide) o.visible = true;
  requestRender();
  fetch('/api/thumb', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ data: pic.toDataURL('image/jpeg', 0.8), cell: state.cell.name, saved }) })
    .catch(() => {});
}

// --- Live editing ----------------------------------------------------------

const pageId = Math.random().toString(36).slice(2) + Date.now().toString(36);
const live = { shared: new Map(), sent: new Map(), timer: null, sending: null, again: false, ready: false,
               others: new Map(), lastWhere: '', whereAt: 0, refreshing: false, refreshAgain: false };
const SECTIONS = ['moved', 'replaced', 'attached', 'doors', 'groups', 'npcs', 'dialogue'];
const UA = navigator.userAgent;
const DEVICE = /iPhone/.test(UA) ? 'iPhone' : /iPad/.test(UA) || (/Macintosh/.test(UA) && navigator.maxTouchPoints > 1) ? 'iPad'
  : /Android/.test(UA) ? (/Mobile/.test(UA) ? 'Android phone' : 'Android tablet') : 'Computer';

function entriesOf(e) {
  const m = new Map();
  for (const sec of SECTIONS) for (const [k, v] of Object.entries(e[sec] || {})) m.set(sec + '|' + k, JSON.stringify(v));
  for (const k of e.deleted || []) m.set('deleted|' + k, 'true');
  for (const a of e.added || []) m.set('added|' + a.uid, JSON.stringify(a));
  return m;
}

function splitId(id) {
  const i = id.indexOf('|');
  return [id.slice(0, i), id.slice(i + 1)];
}

function entryOf(e, id) {
  const [sec, k] = splitId(id);
  if (sec === 'deleted') return e.deleted.includes(k) ? 'true' : undefined;
  if (sec === 'added') { const a = e.added.find((x) => x.uid === k); return a ? JSON.stringify(a) : undefined; }
  const v = (e[sec] || {})[k];
  return v === undefined ? undefined : JSON.stringify(v);
}

function setEntry(e, id, v) {
  const [sec, k] = splitId(id);
  if (sec === 'deleted') {
    e.deleted = e.deleted.filter((x) => x !== k);
    if (v != null) e.deleted.push(k);
  } else if (sec === 'added') {
    const j = e.added.findIndex((a) => a.uid === k);
    if (v == null) { if (j >= 0) e.added.splice(j, 1); } else if (j >= 0) e.added[j] = v; else e.added.push(v);
  } else if (SECTIONS.includes(sec)) {
    if (v == null) delete e[sec][k]; else e[sec][k] = v;
  }
}

function localOps() {
  const now = entriesOf(state.edits), ops = [];
  for (const id of new Set([...now.keys(), ...live.shared.keys()])) {
    const v = now.get(id);
    if (v !== live.shared.get(id) && (v ?? '') !== live.sent.get(id)) ops.push({ id, v: v === undefined ? null : JSON.parse(v) });
  }
  return ops;
}

function syncSoon() {
  if (!live.ready || live.timer) return;
  live.timer = setTimeout(() => { live.timer = null; flush(); }, 100);
}

function flush() {
  if (live.sending) { live.again = true; return live.sending; }
  const ops = localOps();
  if (!ops.length) return Promise.resolve();
  for (const op of ops) live.sent.set(op.id, op.v == null ? '' : JSON.stringify(op.v));
  live.sending = fetch('/api/live/ops', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page: pageId, path: state.data.project.path, ops }) })
    .then((r) => r.json())
    .then((out) => { if (!out.ok) location.reload(); })
    .catch(() => {
      for (const op of ops) live.sent.delete(op.id);
      setTimeout(syncSoon, 2000);
    })
    .finally(() => {
      live.sending = null;
      if (live.again) { live.again = false; flush(); }
    });
  return live.sending;
}

async function flushAll() {
  clearTimeout(live.timer);
  live.timer = null;
  for (let i = 0; i < 3 && (live.sending || localOps().length); i++) {
    await flush();
    if (live.sending) await live.sending;
  }
}

function take(ops, from) {
  const changed = [];
  for (const op of ops) {
    const json = op.v == null ? undefined : JSON.stringify(op.v);
    const before = live.shared.get(op.id);
    if (json === undefined) live.shared.delete(op.id); else live.shared.set(op.id, json);
    if (from === pageId) {
      if (live.sent.get(op.id) === (json ?? '')) live.sent.delete(op.id);
      continue;
    }
    if (json === before || entryOf(state.edits, op.id) !== before) continue;
    setEntry(state.edits, op.id, json === undefined ? null : JSON.parse(json));
    changed.push(op.id);
  }
  if (changed.length) showChanges(changed);
  syncSoon();
}

function opsTo(edits) {
  const m = entriesOf(withSections(edits)), ops = [];
  for (const id of new Set([...m.keys(), ...live.shared.keys()])) {
    if (m.get(id) !== live.shared.get(id)) ops.push({ id, v: m.has(id) ? JSON.parse(m.get(id)) : null });
  }
  return ops;
}

function onLive(ev) {
  if (ev.type === 'hello') {
    live.sent.clear();
    take(opsTo(ev.edits), null);
    live.others = new Map(ev.others.map((o) => [o.page, o]));
    live.lastWhere = '';
    updateMarkers();
  } else if (ev.type === 'ops') {
    take(ev.ops, ev.from);
    if (ev.from !== pageId) $('draft-banner').classList.remove('open');
  } else if (ev.type === 'saved') {
    take(opsTo(ev.edits), null);
    state.saved = canonical(withSections(ev.edits));
    updateDirty();
  } else if (ev.type === 'project') {
    try { sessionStorage.setItem('ce-note', ev.path === state.data.project.path ? 'same' : 'other'); } catch (err) { /* private mode */ }
    location.reload();
  } else if (ev.type === 'presence') {
    live.others.set(ev.page, ev);
    updateMarkers();
  } else if (ev.type === 'gone') {
    live.others.delete(ev.page);
    updateMarkers();
  }
}

function connectLive() {
  live.ready = true;
  const es = new EventSource('/api/live?page=' + encodeURIComponent(pageId));
  es.onmessage = (m) => {
    try { onLive(JSON.parse(m.data)); } catch (err) { console.warn('live', err); }
  };
  window.addEventListener('pagehide', () => {
    navigator.sendBeacon('/api/live/bye', JSON.stringify({ page: pageId }));
  });
  syncSoon();
}

function showChanges(ids) {
  for (const name of [...cellCache.keys()]) if (name !== state.cell?.name) cellCache.delete(name);
  trimUndo(ids);
  let refresh = false;
  for (const id of ids) {
    const [sec, k] = splitId(id);
    if (sec === 'moved') {
      const obj = objByKey.get(k);
      if (!obj) { if (state.cell?.grid) refresh = true; continue; }
      if (gizmoStart?.items.has(obj)) continue;
      const r = obj.userData.ref, m = state.edits.moved[k];
      r.pos = [...(m ? m.pos : r.orig.pos)];
      r.rot = [...(m ? m.rot : r.orig.rot)];
      r.scale = m?.scale ?? r.orig.scale ?? 1;
      applyTransform(obj);
    } else if (sec === 'added' || sec === 'replaced') {
      refresh = true;
    }
  }
  if (ids.some((id) => id.startsWith('npcs|') || id.startsWith('dialogue|'))) npcEditor.refresh(ids);
  refreshVisibility();
  updateSelBoxes();
  updatePanel();
  if (!gizmoStart) syncGizmo();
  updateDirty();
  if (refresh) refreshCell();
}

async function refreshCell() {
  if (live.refreshing) { live.refreshAgain = true; return; }
  live.refreshing = true;
  try {
    const name = state.cell?.name;
    if (!name) return;
    if (state.loadingCell) { setTimeout(refreshCell, 500); return; }
    const cell = await (await fetch('/api/cell', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                   body: JSON.stringify({ name, edits: state.edits }) })).json();
    if (state.cell?.name !== name || state.loadingCell) return;
    const fresh = new Map(cell.refs.map((r) => [r.key, r]));
    for (const [k, obj] of [...objByKey]) {
      if (fresh.has(k)) continue;
      world.remove(obj);
      obj.visible = false;
      objByKey.delete(k);
    }
    const jobs = [];
    for (const r of cell.refs) {
      const obj = objByKey.get(r.key);
      if (!obj) {
        jobs.push(makeObject(r).then((o) => { objByKey.set(r.key, o); world.add(o); }));
        continue;
      }
      const old = obj.userData.ref;
      if (gizmoStart?.items.has(obj)) Object.assign(r, { pos: old.pos, rot: old.rot, scale: old.scale });
      const newMesh = old.mesh !== r.mesh || old.kind !== r.kind;
      Object.assign(old, r);
      jobs.push(newMesh ? fillObject(obj) : Promise.resolve(applyTransform(obj)));
    }
    await Promise.all(jobs);
    state.cell.refs = [...objByKey.values()].map((o) => o.userData.ref);
    refreshVisibility();
    setSelection(state.selection.filter((o) => objByKey.get(o.userData.ref.key) === o));
    updateMarkers();
  } finally {
    live.refreshing = false;
    if (live.refreshAgain) { live.refreshAgain = false; refreshCell(); }
  }
}

function trimUndo(ids) {
  const hit = new Set(ids), groups = ids.some((id) => id.startsWith('groups|'));
  const key = (o) => o.userData.ref.key;
  const idOf = {
    doors: (d) => 'doors|' + d.key,
    npcs: (n) => 'npcs|' + n.id,
    dialogue: (n) => 'dialogue|' + n.id,
    attaches: (a) => 'attached|' + key(a.obj),
    swaps: (p) => (key(p.obj).startsWith('added|') ? key(p.obj) : 'replaced|' + key(p.obj)),
    deleted: (o) => 'deleted|' + key(o),
    items: (it) => 'moved|' + key(it.obj),
  };
  for (const u of state.undo) {
    if (u.stale) continue;
    if (u.groups) { if (groups) u.stale = true; continue; }
    if (u.added) { if (hit.has('added|' + u.added)) u.stale = true; continue; }
    if (u.copies) { if (u.copies.some((c) => hit.has('added|' + c.uid))) u.stale = true; continue; }
    const field = Object.keys(idOf).find((f) => Array.isArray(u[f]));
    if (!field) continue;
    const kept = u[field].filter((x) => !hit.has(idOf[field](x)));
    if (kept.length === u[field].length) continue;
    u[field] = kept;
    u.trimmed = true;
    if (!kept.length) u.stale = true;
  }
}

function sendWhere(now) {
  if (!live.ready || !state.cell || now - live.whereAt < 250) return;
  const info = { label: DEVICE, cell: state.cell.name, pos: camera.position.toArray().map(Math.round),
                 yaw: Math.round(state.yaw * 1000) / 1000, pitch: Math.round(state.pitch * 1000) / 1000,
                 sel: state.selection.map((o) => o.userData.ref.key) };
  const json = JSON.stringify(info);
  if (json === live.lastWhere) return;
  live.lastWhere = json;
  live.whereAt = now;
  fetch('/api/live/where', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                             body: JSON.stringify(Object.assign({ page: pageId }, info)) }).catch(() => {});
}

const markers = new THREE.Group();
scene.add(markers);
const MARKER_COLORS = [0x4fc3f7, 0xf06292, 0x81c784, 0xba68c8, 0xffb74d];
const coneGeometry = new THREE.ConeGeometry(16, 36, 4, 1, true).rotateZ(Math.PI).translate(0, 18, 0);
const headGeometry = new THREE.SphereGeometry(7, 12, 8);
const labels = new Map();

function colorOf(page) {
  let h = 0;
  for (const c of page) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return MARKER_COLORS[h % MARKER_COLORS.length];
}

function labelTexture(text, color) {
  const k = text + '|' + color;
  if (!labels.has(k)) {
    const c = document.createElement('canvas');
    c.width = 256; c.height = 64;
    const g = c.getContext('2d');
    g.fillStyle = '#' + color.toString(16).padStart(6, '0');
    g.beginPath();
    if (g.roundRect) g.roundRect(4, 8, 248, 48, 12); else g.rect(4, 8, 248, 48);    // roundRect is missing in older Safari
    g.fill();
    g.fillStyle = '#101014';
    g.font = '600 28px system-ui, sans-serif';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(text, 128, 33);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    labels.set(k, t);
  }
  return labels.get(k);
}

function updateMarkers() {
  requestRender();
  for (const m of markers.children) {
    m.traverse((o) => {
      if (o.userData.own) { o.geometry.dispose(); o.material.dispose(); }
      else if (o.isMesh || o.isSprite) o.material.dispose();
    });
  }
  markers.clear();
  for (const [page, o] of live.others) {
    if (!state.cell || o.cell !== state.cell.name || !o.pos) continue;
    const color = colorOf(page);
    const g = new THREE.Group();
    g.position.set(...o.pos);
    g.rotation.order = 'ZXY';
    g.rotation.set(o.pitch || 0, 0, -(o.yaw || 0));
    const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55, side: THREE.DoubleSide, depthWrite: false });
    g.add(new THREE.Mesh(coneGeometry, mat));
    g.add(new THREE.Mesh(headGeometry, new THREE.MeshBasicMaterial({ color })));
    const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: labelTexture(o.label || 'Device', color),
                                                               depthTest: false, sizeAttenuation: false }));
    label.scale.set(0.16, 0.04, 1);
    label.position.set(0, 0, 22);
    label.renderOrder = 20;
    const holder = new THREE.Group();
    holder.position.copy(g.position);
    holder.add(label);
    markers.add(g, holder);
    for (const k of o.sel || []) {
      const obj = objByKey.get(k);
      if (!obj || !obj.visible) continue;
      const b = new THREE.Box3Helper(new THREE.Box3().setFromObject(obj).expandByScalar(2), color);
      b.userData.own = true;
      markers.add(b);
    }
  }
  updateOthers();
}

function updateOthers() {
  const box = $('others');
  box.innerHTML = '';
  for (const [page, o] of live.others) {
    const b = document.createElement('button');
    b.className = 'other';
    b.title = `Go to where the ${o.label || 'device'} is`;
    const dot = document.createElement('span');
    dot.className = 'dot';
    dot.style.background = '#' + colorOf(page).toString(16).padStart(6, '0');
    const text = document.createElement('span');
    text.className = 'txt';
    text.textContent = `${o.label || 'Device'} · ${o.cell || '…'}`;
    b.append(dot, text);
    b.addEventListener('click', () => goToOther(page));
    box.appendChild(b);
  }
  box.style.display = live.others.size ? '' : 'none';
}

async function goToOther(page) {
  const o = live.others.get(page);
  if (!o || !o.cell) return;
  if (o.cell !== state.cell?.name) await loadCell(o.cell, true);
  state.yaw = o.yaw || 0;
  state.pitch = o.pitch || 0;
  camera.position.set(...o.pos).addScaledVector(viewDir(), -120);
  camera.position.z += 20;
  aimCamera();
  updateMarkers();
}

// --- Start -----------------------------------------------------------------

let last = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  fly(dt);
  sendWhere(now);
  if (needsRender || gizmo.dragging) {
    needsRender = false;
    renderer.render(scene, camera);
  }
  if (previewNeedsRender) {
    previewNeedsRender = false;
    if (preview.renderer && $('picker').classList.contains('open') && previewing()) renderPreview();
  }
  requestAnimationFrame(frame);
}

window.editor = { state, camera, gizmo, proxy, THREE, aimCamera, select, loadCell, render: () => renderer.render(scene, camera) };

keepAlive(() => {
  if (state.stopped) return;
  state.stopped = true;
  showStopped(state.dirty ? 'Your unsaved changes are kept: the editor offers them back when you open this '
                            + 'project again.' : '');
});

function openFailed(detail) {
  $('loading').style.display = 'none';
  const last = String(detail || '').trim().split('\n').pop();
  const bg = document.createElement('div');
  bg.className = 'dialog-bg';
  bg.innerHTML = '<div class="dialog"><h3>The project couldn\'t be opened</h3><p></p>'
    + '<p class="dim">The details are in editor.log, in the editor\'s settings folder.</p>'
    + '<div class="bar"><button class="primary">Back to projects</button></div></div>';
  bg.querySelector('p').textContent = last || 'The editor had a problem reading it.';
  bg.querySelector('button').addEventListener('click', async () => {
    if (!(await toLauncher('projects'))) location.href = '/home.html';
  });
  document.body.appendChild(bg);
}

(async () => {
  let res;
  try {
    res = await fetch('/api/scene');
    state.data = await res.json();
  } catch (err) { openFailed(err.message); return; }
  if (!res.ok || state.data.error) { openFailed(state.data.error); return; }
  state.saved = canonical(withSections(state.data.edits));
  state.edits = withSections(state.data.live.edits);
  live.shared = entriesOf(state.edits);
  state.favorites = state.data.favorites;
  state.objectFavorites = state.data.objectFavorites || [];
  updateDirty();
  setupProject();
  buildTierControls();
  const last = stored('ce-last-cell');
  await loadCell(last && state.data.cells.some((c) => c.name === last) ? last : state.data.startCell);
  offerDraft();
  connectLive();
  if (!state.data.hasThumb) setTimeout(() => sendPicture(false), 3000);
  let note = null;
  try { note = sessionStorage.getItem('ce-note'); sessionStorage.removeItem('ce-note'); } catch (err) { /* private mode */ }
  if (note) status(note === 'same' ? "The project's settings were changed on the computer."
                                   : `${state.data.project.name} was opened on the computer.`);
  if (stored('ce-guide-seen') !== '1') showGuide();
  if (state.data.notice) status(state.data.notice, true);
  if (state.data.orphans.length) {
    status(`${state.data.orphans.length} saved edit(s) no longer match an object (the build changed):\n`
           + state.data.orphans.join('\n'), true);
  }
  requestAnimationFrame(frame);
})();
