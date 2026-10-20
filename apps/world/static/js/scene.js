// apps/world/static/js/scene.js
// -----------------------------
// Builds the virtual warehouse (and its people: meta.employees plus
// meta.visitors) from the world server's /api/world
// description (itself generated from configs/world/warehouse.yaml) and
// keeps it in step with the simulation. Shared, unchanged, by:
//   * world.html — the presenter's 3D view (cutaway walls, labels, helpers)
//   * rig.html   — the headless CAMERA RIG that renders each node's frames
// so what the judge sees and what the cameras see is one and the same world.
//
// Floor coordinates (x east, y south, z up) map to three.js as (x, z, y).

import * as THREE from 'three';
import { buildCharacter, animateCharacter } from './character.js';

export const V = (x, y, z = 0) => new THREE.Vector3(x, z, y);

const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0.05, ...o });

function shadowed(mesh, cast = true, receive = true) {
  mesh.castShadow = cast; mesh.receiveShadow = receive; return mesh;
}

function boxMesh(w, h, d, material) {
  return shadowed(new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material));
}

// Seeded RNG so every page (viewer, rig) builds the identical scene.
function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

// ── textures ────────────────────────────────────────────────────────────

function floorTexture(meta) {
  const W = meta.building.width_m, D = meta.building.depth_m, PX = 64;
  const c = document.createElement('canvas');
  c.width = Math.round(W * PX); c.height = Math.round(D * PX);
  const g = c.getContext('2d');
  // polished concrete
  g.fillStyle = '#8b8c88'; g.fillRect(0, 0, c.width, c.height);
  const r = rng(11);
  for (let i = 0; i < 9000; i++) {
    const v = 118 + Math.floor(r() * 36);
    g.fillStyle = `rgba(${v},${v},${v - 4},0.10)`;
    g.fillRect(r() * c.width, r() * c.height, 2 + r() * 10, 2 + r() * 10);
  }
  // slab joints
  g.strokeStyle = 'rgba(80,80,76,0.35)'; g.lineWidth = 2;
  for (let x = 0; x <= W; x += 5) { g.beginPath(); g.moveTo(x * PX, 0); g.lineTo(x * PX, c.height); g.stroke(); }
  for (let y = 0; y <= D; y += 5) { g.beginPath(); g.moveTo(0, y * PX); g.lineTo(c.width, y * PX); g.stroke(); }
  const m = (x) => x * PX;
  // AGV lanes: yellow edge lines
  g.strokeStyle = '#e8b40c'; g.lineWidth = 7;
  for (const a of meta.agvs) {
    const [[x0, y0], [x1, y1]] = a.stops;
    for (const off of [-0.85, 0.85]) {
      g.beginPath(); g.moveTo(m(x0 - 1), m(y0 + off)); g.lineTo(m(x1 + 1), m(y1 + off)); g.stroke();
    }
  }
  // rack block outline
  g.strokeStyle = '#e8b40c'; g.lineWidth = 6; g.setLineDash([28, 18]);
  const rx0 = Math.min(...meta.racks.map(q => q.x0)) - 0.9, rx1 = Math.max(...meta.racks.map(q => q.x1)) + 0.9;
  const ry0 = Math.min(...meta.racks.map(q => q.y0)) - 0.4, ry1 = Math.max(...meta.racks.map(q => q.y1)) + 0.4;
  g.strokeRect(m(rx0), m(ry0), m(rx1 - rx0), m(ry1 - ry0));
  g.setLineDash([]);
  // dock hatching
  for (const d of meta.dock_doors) {
    const y0 = d.y - d.width_m / 2, x0 = W - 2.4;
    g.save(); g.beginPath(); g.rect(m(x0), m(y0), m(2.4), m(d.width_m)); g.clip();
    g.fillStyle = 'rgba(30,30,30,0.85)'; g.fillRect(m(x0), m(y0), m(2.4), m(d.width_m));
    g.strokeStyle = '#f2c200'; g.lineWidth = 16;
    for (let k = -10; k < 20; k++) { g.beginPath(); g.moveTo(m(x0) + k * 40, m(y0)); g.lineTo(m(x0) + k * 40 + 220, m(y0) + 220); g.stroke(); }
    g.restore();
  }
  // pedestrian walkway from the staff door (green with white edges)
  const e = meta.entrance;
  g.fillStyle = 'rgba(46,140,80,0.55)';
  g.fillRect(0, m(e.door_y - 0.9), m(e.gate.x + 1.8), m(1.8));
  g.strokeStyle = '#f4f4f4'; g.lineWidth = 5;
  g.strokeRect(0, m(e.door_y - 0.9), m(e.gate.x + 1.8), m(1.8));
  // gate box
  g.strokeStyle = '#1f8f4e'; g.lineWidth = 6;
  g.strokeRect(m(e.gate.x - 0.7), m(e.gate.y - 0.9), m(1.4), m(1.8));
  // packing area paint
  g.strokeStyle = 'rgba(40,90,200,0.55)'; g.lineWidth = 6; g.setLineDash([20, 14]);
  g.strokeRect(m(0.3), m(10.8), m(4.0), m(7.2));
  g.setLineDash([]);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

function wallTexture() {
  const c = document.createElement('canvas'); c.width = 256; c.height = 256;
  const g = c.getContext('2d');
  g.fillStyle = '#c9ccd0'; g.fillRect(0, 0, 256, 256);
  for (let x = 0; x < 256; x += 32) {
    const grd = g.createLinearGradient(x, 0, x + 32, 0);
    grd.addColorStop(0, 'rgba(255,255,255,0.25)'); grd.addColorStop(0.5, 'rgba(0,0,0,0.10)'); grd.addColorStop(1, 'rgba(255,255,255,0.25)');
    g.fillStyle = grd; g.fillRect(x, 0, 32, 256);
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function corrugated(color) {
  const c = document.createElement('canvas'); c.width = 128; c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = color; g.fillRect(0, 0, 128, 64);
  for (let x = 0; x < 128; x += 16) { g.fillStyle = 'rgba(0,0,0,0.18)'; g.fillRect(x, 0, 6, 64); g.fillStyle = 'rgba(255,255,255,0.10)'; g.fillRect(x + 8, 0, 3, 64); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function textSprite(lines, opts = {}) {
  const c = document.createElement('canvas'); c.width = 512; c.height = 160;
  const g = c.getContext('2d');
  g.fillStyle = opts.bg || 'rgba(15,20,28,0.82)';
  const r = 26; g.beginPath(); g.roundRect(8, 8, 496, 144, r); g.fill();
  if (opts.accent) { g.fillStyle = opts.accent; g.beginPath(); g.roundRect(8, 8, 22, 144, [r, 0, 0, r]); g.fill(); }
  g.fillStyle = '#ffffff'; g.font = '600 54px system-ui, Segoe UI, sans-serif'; g.textBaseline = 'middle';
  g.fillText(lines[0], 48, lines[1] ? 58 : 80);
  if (lines[1]) { g.fillStyle = 'rgba(255,255,255,0.75)'; g.font = '500 38px system-ui, Segoe UI, sans-serif'; g.fillText(lines[1], 48, 112); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false, transparent: true }));
  s.scale.set(2.6, 0.82, 1); s.renderOrder = 10;
  return s;
}

// ── props ───────────────────────────────────────────────────────────────

const MAT = {
  upright: std('#2459a8', { metalness: 0.4, roughness: 0.5 }),
  beam: std('#e4721b', { metalness: 0.3, roughness: 0.5 }),
  wood: std('#b38955', { roughness: 0.9 }),
  steel: std('#8b9097', { metalness: 0.6, roughness: 0.4 }),
  dark: std('#2c3036', { metalness: 0.3, roughness: 0.6 }),
  wrap: std('#dfe6ea', { roughness: 0.25, metalness: 0.0, transparent: true, opacity: 0.55 }),
};
const BOX_COLORS = ['#c39a66', '#b98d5a', '#cfa877', '#a87f4f', '#d6b385', '#9c7448'];

class BoxBatcher {
  constructor() { this.items = new Map(); }
  add(color, x, y, z, w, h, d) {
    if (!this.items.has(color)) this.items.set(color, []);
    this.items.get(color).push([x, y, z, w, h, d]);
  }
  build(parent) {
    const geo = new THREE.BoxGeometry(1, 1, 1);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion();
    for (const [color, list] of this.items) {
      const mesh = new THREE.InstancedMesh(geo, std(color), list.length);
      list.forEach(([x, y, z, w, h, d], i) => {
        m4.compose(V(x, y, z + h / 2), q, new THREE.Vector3(w, h, d));
        mesh.setMatrixAt(i, m4);
      });
      mesh.castShadow = true; mesh.receiveShadow = true;
      parent.add(mesh);
    }
  }
}

function palletLoad(batch, x0, y0, x1, y1, z, height, r) {
  // a wooden pallet with a stack of cartons
  batch.add('#b38955', (x0 + x1) / 2, (y0 + y1) / 2, z, x1 - x0, 0.14, y1 - y0);
  const nx = Math.max(1, Math.round((x1 - x0) / 0.42)), ny = Math.max(1, Math.round((y1 - y0) / 0.42));
  const bw = (x1 - x0) / nx, bd = (y1 - y0) / ny;
  const layers = Math.max(1, Math.round((height - 0.14) / 0.36));
  for (let l = 0; l < layers; l++) for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
    if (l === layers - 1 && r() < 0.25) continue;
    const col = BOX_COLORS[Math.floor(r() * BOX_COLORS.length)];
    batch.add(col, x0 + (i + 0.5) * bw, y0 + (j + 0.5) * bd, z + 0.14 + l * 0.36, bw * 0.96, 0.34, bd * 0.96);
  }
}

function buildRack(group, batch, rk, r) {
  const len = rk.x1 - rk.x0, dep = rk.y1 - rk.y0, H = rk.height_m;
  const bays = Math.round(len / 2.7);
  const bayW = len / bays;
  for (let b = 0; b <= bays; b++) {
    const x = rk.x0 + b * bayW;
    for (const y of [rk.y0 + 0.05, rk.y1 - 0.05]) {
      const u = boxMesh(0.09, H, 0.09, MAT.upright); u.position.copy(V(x, y, H / 2)); group.add(u);
    }
    // cross bracing
    const br = boxMesh(0.04, 0.04, dep, MAT.upright); br.position.copy(V(x, (rk.y0 + rk.y1) / 2, 0.4)); group.add(br);
    const br2 = br.clone(); br2.position.copy(V(x, (rk.y0 + rk.y1) / 2, H - 0.3)); group.add(br2);
  }
  const levelH = H / rk.levels;
  for (let l = 0; l < rk.levels; l++) {
    const z = 0.12 + l * levelH;
    for (const y of [rk.y0 + 0.05, rk.y1 - 0.05]) {
      const beam = boxMesh(len, 0.12, 0.07, MAT.beam); beam.position.copy(V((rk.x0 + rk.x1) / 2, y, z + (l ? 0 : 0))); group.add(beam);
    }
    for (let b = 0; b < bays; b++) {
      for (let p = 0; p < 2; p++) {
        if (r() < 0.12) continue; // the odd empty slot
        const px0 = rk.x0 + b * bayW + 0.12 + p * (bayW / 2), px1 = px0 + bayW / 2 - 0.24;
        palletLoad(batch, px0, rk.y0 + 0.08, px1, rk.y1 - 0.08, z + 0.07, levelH * (0.55 + r() * 0.3), r);
      }
    }
  }
  const top = boxMesh(len, 0.1, 0.07, MAT.beam); top.position.copy(V((rk.x0 + rk.x1) / 2, rk.y0 + 0.05, H - 0.05)); group.add(top);
  const top2 = top.clone(); top2.position.copy(V((rk.x0 + rk.x1) / 2, rk.y1 - 0.05, H - 0.05)); group.add(top2);
}

function buildProp(group, batch, p, r) {
  const cx = (p.x0 + p.x1) / 2, cy = (p.y0 + p.y1) / 2, w = p.x1 - p.x0, d = p.y1 - p.y0, H = p.height_m;
  if (p.kind === 'pallet') {
    palletLoad(batch, p.x0, p.y0, p.x1, p.y1, 0, H, r);
  } else if (p.kind === 'table') {
    const top = boxMesh(w, 0.05, d, std('#d9d6cf', { roughness: 0.6 })); top.position.copy(V(cx, cy, H)); group.add(top);
    for (const [ax, ay] of [[p.x0 + 0.06, p.y0 + 0.06], [p.x1 - 0.06, p.y0 + 0.06], [p.x0 + 0.06, p.y1 - 0.06], [p.x1 - 0.06, p.y1 - 0.06]]) {
      const leg = boxMesh(0.05, H, 0.05, MAT.steel); leg.position.copy(V(ax, ay, H / 2)); group.add(leg);
    }
    const shelf = boxMesh(w * 0.9, 0.03, d * 0.9, MAT.steel); shelf.position.copy(V(cx, cy, 0.25)); group.add(shelf);
    const mon = boxMesh(0.06, 0.32, 0.5, MAT.dark); mon.position.copy(V(p.x0 + 0.15, cy, H + 0.3)); group.add(mon);
    batch.add('#c39a66', cx + 0.1, cy - d * 0.25, H + 0.03, 0.4, 0.3, 0.35);
    batch.add('#cfa877', cx + 0.1, cy + d * 0.25, H + 0.03, 0.35, 0.22, 0.45);
    const tape = boxMesh(0.25, 0.12, 0.12, std('#2d6cdf')); tape.position.copy(V(cx, cy + 0.05, H + 0.08)); group.add(tape);
  } else if (p.kind === 'lockers') {
    const n = Math.round(w / 0.5);
    for (let i = 0; i < n; i++) {
      const L = boxMesh(w / n - 0.02, H, d, std(i % 2 ? '#7d8a99' : '#71808f', { metalness: 0.5, roughness: 0.45 }));
      L.position.copy(V(p.x0 + (i + 0.5) * (w / n), cy, H / 2)); group.add(L);
      const vent = boxMesh(0.2, 0.02, 0.01, MAT.dark); vent.position.copy(V(p.x0 + (i + 0.5) * (w / n), p.y1 + 0.005, H - 0.3)); group.add(vent);
    }
  } else if (p.kind === 'cage') {
    const bar = new THREE.MeshStandardMaterial({ color: '#9aa1a8', metalness: 0.7, roughness: 0.35 });
    const base = boxMesh(w, 0.12, d, MAT.dark); base.position.copy(V(cx, cy, 0.12)); group.add(base);
    for (let i = 0; i <= 6; i++) {
      for (const y of [p.y0, p.y1]) { const b = boxMesh(0.02, H - 0.15, 0.02, bar); b.position.copy(V(p.x0 + (w * i) / 6, y, 0.15 + (H - 0.15) / 2)); group.add(b); }
    }
    for (let k = 1; k <= 4; k++) for (const y of [p.y0, p.y1]) { const b = boxMesh(w, 0.02, 0.02, bar); b.position.copy(V(cx, y, 0.15 + (k * (H - 0.15)) / 4)); group.add(b); }
    batch.add('#b98d5a', cx, cy, 0.18, w * 0.8, 0.45, d * 0.8);
    batch.add('#cfa877', cx, cy, 0.63, w * 0.6, 0.4, d * 0.7);
  } else if (p.kind === 'wrapper') {
    const plate = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(Math.min(w, d) / 2, Math.min(w, d) / 2, 0.12, 32), std('#3a4048', { metalness: 0.5 })));
    plate.position.copy(V(cx, cy, 0.06)); group.add(plate);
    const mast = boxMesh(0.2, H, 0.2, std('#e6e8eb', { metalness: 0.3 })); mast.position.copy(V(p.x1 - 0.1, p.y0 + 0.1, H / 2)); group.add(mast);
    palletLoad(batch, cx - 0.5, cy - 0.5, cx + 0.5, cy + 0.5, 0.12, 1.5, r);
    const film = boxMesh(1.04, 1.4, 1.04, MAT.wrap); film.position.copy(V(cx, cy, 0.85)); film.castShadow = false; group.add(film);
  } else if (p.kind === 'desk') {
    const top = boxMesh(w, 0.05, d, std('#6e5a44')); top.position.copy(V(cx, cy, H)); group.add(top);
    for (const ax of [p.x0 + 0.05, p.x1 - 0.05]) { const leg = boxMesh(0.05, H, d - 0.1, MAT.dark); leg.position.copy(V(ax, cy, H / 2)); group.add(leg); }
    const mon = boxMesh(0.55, 0.36, 0.05, MAT.dark); mon.position.copy(V(cx, cy - 0.1, H + 0.28)); group.add(mon);
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 0.3), new THREE.MeshBasicMaterial({ color: '#5fa8ff' }));
    scr.position.copy(V(cx, cy - 0.07, H + 0.28)); group.add(scr);
  } else if (p.kind === 'conveyor') {
    const frame = boxMesh(w, 0.12, d, MAT.steel); frame.position.copy(V(cx, cy, H - 0.06)); group.add(frame);
    const belt = boxMesh(w, 0.03, d * 0.8, std('#1f2328', { roughness: 0.9 })); belt.position.copy(V(cx, cy, H + 0.015)); group.add(belt);
    for (let x = p.x0 + 0.3; x < p.x1; x += 1.2) { const leg = boxMesh(0.06, H, d * 0.9, MAT.steel); leg.position.copy(V(x, cy, H / 2)); group.add(leg); }
    for (let x = p.x0 + 0.5; x < p.x1 - 0.3; x += 1.1) batch.add(BOX_COLORS[Math.floor(r() * 6)], x, cy, H + 0.03, 0.4, 0.25, 0.35);
  } else {
    const b = boxMesh(w, H, d, MAT.steel); b.position.copy(V(cx, cy, H / 2)); group.add(b);
  }
}

function buildAGV(colour) {
  const g = new THREE.Group();
  const body = std(colour, { metalness: 0.3, roughness: 0.45 });
  const chassis = boxMesh(1.0, 0.75, 1.5, body); chassis.position.set(0, 0.5, -0.25); g.add(chassis);
  const top = boxMesh(0.9, 0.12, 1.3, MAT.dark); top.position.set(0, 0.93, -0.3); g.add(top);
  const mastL = boxMesh(0.08, 2.0, 0.08, MAT.dark); mastL.position.set(-0.3, 1.0, 0.55); g.add(mastL);
  const mastR = mastL.clone(); mastR.position.x = 0.3; g.add(mastR);
  const cross = boxMesh(0.68, 0.08, 0.08, MAT.dark); cross.position.set(0, 1.95, 0.55); g.add(cross);
  for (const sx of [-0.25, 0.25]) { const f = boxMesh(0.1, 0.05, 1.1, MAT.steel); f.position.set(sx, 0.2, 1.15); g.add(f); }
  const load = new THREE.Group();
  const pal = boxMesh(0.9, 0.12, 1.0, MAT.wood); pal.position.set(0, 0.29, 1.15); load.add(pal);
  const cart = boxMesh(0.85, 0.7, 0.95, std('#c39a66')); cart.position.set(0, 0.7, 1.15); load.add(cart);
  g.add(load);
  for (const [x, z] of [[-0.45, -0.75], [0.45, -0.75], [-0.45, 0.25], [0.45, 0.25]]) {
    const wheel = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.12, 18), MAT.dark));
    wheel.rotation.z = Math.PI / 2; wheel.position.set(x, 0.16, z); g.add(wheel);
  }
  const lidar = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.12, 16), MAT.dark)); lidar.position.set(0, 1.05, 0.0); g.add(lidar);
  const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 8), new THREE.MeshStandardMaterial({ color: '#ff8c00', emissive: '#ff6a00', emissiveIntensity: 1.2 }));
  beacon.position.set(0.35, 1.08, -0.85); g.add(beacon);
  const stripe = new THREE.Mesh(new THREE.PlaneGeometry(0.98, 0.12), new THREE.MeshStandardMaterial({ color: '#111' }));
  stripe.position.set(0, 0.62, 0.505); g.add(stripe);
  g.userData = { beacon, load };
  return g;
}

function buildCameraModel() {
  const g = new THREE.Group();
  const housing = boxMesh(0.42, 0.22, 0.22, std('#f0f0f0', { roughness: 0.4 }));
  g.add(housing);
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.06, 16), std('#111', { roughness: 0.2 }));
  lens.rotation.z = Math.PI / 2; lens.position.x = 0.23; g.add(lens);
  const led = new THREE.Mesh(new THREE.SphereGeometry(0.025, 8, 6), new THREE.MeshBasicMaterial({ color: '#ff2a2a' }));
  led.position.set(0.2, 0.08, 0.08); g.add(led);
  return g;
}

// ── the warehouse ───────────────────────────────────────────────────────

/**
 * @param {object} meta  /api/world
 * @param {object} opts  {cutaway: bool (viewer: low walls, no roof), labels: bool, helpers: bool}
 */
export function buildWarehouse(meta, opts = {}) {
  const scene = new THREE.Scene();
  const W = meta.building.width_m, D = meta.building.depth_m, WH = meta.building.wall_height_m;
  scene.background = new THREE.Color(opts.cutaway ? '#c9d6e3' : '#8fa3b8');
  scene.fog = opts.cutaway ? new THREE.Fog('#c9d6e3', 70, 160) : null;

  // light: overcast daylight + an even "high-bay lamps" key light with shadows
  scene.add(new THREE.HemisphereLight('#ffffff', '#5a5a55', 1.35));
  const key = new THREE.DirectionalLight('#fff6e8', 1.9);
  key.position.copy(V(W * 0.35, -D * 0.2, 40)); key.target.position.copy(V(W / 2, D / 2, 0));
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { left: -26, right: 26, top: 26, bottom: -26, near: 5, far: 90 });
  key.shadow.bias = -0.0004; key.shadow.normalBias = 0.02;
  scene.add(key, key.target);
  const fill = new THREE.DirectionalLight('#dfe8ff', 0.45); fill.position.copy(V(-10, D + 10, 20)); scene.add(fill);

  const world = new THREE.Group(); scene.add(world);
  const batch = new BoxBatcher();
  const r = rng(1234);

  // ground outside + floor inside
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(220, 220), std('#59605a', { roughness: 1 }));
  ground.rotation.x = -Math.PI / 2; ground.position.copy(V(W / 2, D / 2, -0.02)); ground.receiveShadow = true; world.add(ground);
  const asphalt = new THREE.Mesh(new THREE.PlaneGeometry(14, D + 16), std('#3c3f43', { roughness: 0.95 }));
  asphalt.rotation.x = -Math.PI / 2; asphalt.position.copy(V(W + 7, D / 2, -0.01)); asphalt.receiveShadow = true; world.add(asphalt);
  const path = new THREE.Mesh(new THREE.PlaneGeometry(10, 2.4), std('#9b9b94', { roughness: 0.95 }));
  path.rotation.x = -Math.PI / 2; path.position.copy(V(-5, meta.entrance.door_y, -0.005)); path.receiveShadow = true; world.add(path);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, D), new THREE.MeshStandardMaterial({ map: floorTexture(meta), roughness: 0.55, metalness: 0.05 }));
  floor.rotation.x = -Math.PI / 2; floor.position.copy(V(W / 2, D / 2, 0)); floor.receiveShadow = true; world.add(floor);

  // walls with openings (staff door west, dock doors east)
  const wallH = opts.cutaway ? 1.1 : WH;
  const wt = wallTexture();
  const wallMat = (len) => { const t = wt.clone(); t.needsUpdate = true; t.repeat.set(len / 2.5, wallH / 2.5); return std('#ffffff', { map: t, roughness: 0.7, metalness: 0.2 }); };
  const wall = (x0, y0, x1, y1, h = wallH, zb = 0) => {
    const len = Math.hypot(x1 - x0, y1 - y0); if (len < 0.01) return;
    const m = boxMesh(len, h, 0.2, wallMat(len));
    m.position.copy(V((x0 + x1) / 2, (y0 + y1) / 2, zb + h / 2)); m.rotation.y = -Math.atan2(y1 - y0, x1 - x0); world.add(m);
  };
  wall(0, 0, W, 0); wall(0, D, W, D);
  const dy = meta.entrance.door_y, dw = meta.entrance.door_width_m;
  wall(0, 0, 0, dy - dw / 2); wall(0, dy + dw / 2, 0, D);
  if (!opts.cutaway) wall(0, dy - dw / 2, 0, dy + dw / 2, WH - 2.6, 2.6);
  const doors = [...meta.dock_doors].sort((a, b) => a.y - b.y);
  let yy = 0;
  for (const d of doors) { wall(W, yy, W, d.y - d.width_m / 2); if (!opts.cutaway) wall(W, d.y - d.width_m / 2, W, d.y + d.width_m / 2, WH - 3.4, 3.4); yy = d.y + d.width_m / 2; }
  wall(W, yy, W, D);

  // staff door frame + canopy, gate turnstile
  const frameMat = std('#39424d', { metalness: 0.5 });
  for (const s of [-1, 1]) { const post = boxMesh(0.15, 2.6, 0.15, frameMat); post.position.copy(V(0, dy + s * (dw / 2), 1.3)); world.add(post); }
  const sign = boxMesh(0.06, 0.4, 1.8, std('#1f8f4e')); sign.position.copy(V(-0.12, dy, 2.95)); world.add(sign);
  // the gate: a slim badge-reader post BESIDE the person as the entrance
  // camera sees them (perpendicular to its line of sight), never behind or
  // in front — a post that overlaps a standing person's silhouette in the
  // image measurably hurts person detection at the gate.
  const g = meta.entrance.gate;
  const gcam = meta.cameras.find(c => c.node_id === g.node_id) || meta.cameras[0];
  let vx = g.x - gcam.mount[0], vy = g.y - gcam.mount[1];
  const vn = Math.hypot(vx, vy) || 1; vx /= vn; vy /= vn;
  const px = g.x + vy * 1.25, py = g.y - vx * 1.25;   // 1.25 m to the side
  const post = boxMesh(0.12, 1.05, 0.12, std('#c5ccd3', { metalness: 0.6, roughness: 0.3 }));
  post.position.copy(V(px, py, 0.525)); world.add(post);
  const reader = boxMesh(0.2, 0.16, 0.08, std('#1b1f24')); reader.position.copy(V(px, py, 1.12)); world.add(reader);
  const readerLed = new THREE.Mesh(new THREE.PlaneGeometry(0.12, 0.07), new THREE.MeshBasicMaterial({ color: '#2bd46a' }));
  readerLed.position.copy(V(px, py, 1.205)); readerLed.rotation.x = -Math.PI / 2; world.add(readerLed);

  // containers at the dock doors
  for (const d of doors) {
    const c = shadowed(new THREE.Mesh(new THREE.BoxGeometry(6.1, 2.6, 2.44), std('#ffffff', { map: (() => { const t = corrugated(d.container); t.repeat.set(6, 1); return t; })(), metalness: 0.35, roughness: 0.6 })));
    c.position.copy(V(W + 0.15 + 3.05, d.y, 1.35)); world.add(c);
    const chassis = boxMesh(6.0, 0.25, 2.2, MAT.dark); chassis.position.copy(V(W + 3.2, d.y, 0.18)); world.add(chassis);
    const leveler = boxMesh(1.2, 0.08, d.width_m - 0.4, MAT.steel); leveler.position.copy(V(W - 0.4, d.y, 0.04)); world.add(leveler);
  }

  // roof trusses and high-bay lamps (only for the cameras' full building)
  if (!opts.cutaway) {
    for (let x = 2.5; x < W; x += 5) {
      const t = boxMesh(0.25, 0.4, D, std('#7c848d', { metalness: 0.5 })); t.position.copy(V(x, D / 2, WH - 0.2)); world.add(t);
    }
    const roof = new THREE.Mesh(new THREE.PlaneGeometry(W, D), std('#9aa0a6', { side: THREE.DoubleSide }));
    roof.rotation.x = Math.PI / 2; roof.position.copy(V(W / 2, D / 2, WH)); world.add(roof);
  }
  const lampMat = new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: '#fffbe6', emissiveIntensity: 1.6 });
  // (no lamps in the roofless cutaway view: they would float in the air)
  if (!opts.cutaway) for (let x = 5; x < W; x += 5) for (let y = 4; y < D; y += 6) {
    const lamp = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.45, 0.25, 16), lampMat);
    lamp.position.copy(V(x, y, WH - 0.6)); world.add(lamp);
    const cable = boxMesh(0.02, 0.4, 0.02, MAT.dark); cable.position.copy(V(x, y, WH - 0.3)); world.add(cable);
  }

  for (const rk of meta.racks) buildRack(world, batch, rk, r);
  for (const p of meta.props) buildProp(world, batch, p, r);
  batch.build(world);

  // cameras: physical housings + the render cameras the rig uses
  const cams = {};
  const camModels = {};
  const tarps = {};
  for (const c of meta.cameras) {
    const aspect = meta.camera_frames.width_px / meta.camera_frames.height_px;
    const pc = new THREE.PerspectiveCamera(c.vfov_deg, aspect, 0.25, 120);
    pc.position.copy(V(...c.mount));
    pc.lookAt(V(...c.look_at));
    cams[c.node_id] = pc;

    const model = buildCameraModel();
    model.position.copy(V(...c.mount));
    const dir = V(...c.look_at).sub(V(...c.mount)).normalize();
    model.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), dir);
    // nudge the housing behind the lens so it never appears in its own frame
    model.position.addScaledVector(dir, -0.35);
    world.add(model);
    camModels[c.node_id] = model;
    const arm = boxMesh(0.06, 0.06, 0.6, MAT.dark); arm.position.copy(model.position).add(new THREE.Vector3(0, 0.2, 0)); world.add(arm);

    // the "tarp over the lens" fault: a dark cloth just in front of the lens
    const tarp = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 1.2, 8, 6), std('#1d2a1f', { roughness: 1, side: THREE.DoubleSide }));
    const pos = tarp.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) pos.setZ(i, Math.sin(pos.getX(i) * 4) * 0.05 + Math.cos(pos.getY(i) * 5) * 0.04);
    tarp.geometry.computeVertexNormals();
    tarp.position.copy(V(...c.mount)).addScaledVector(dir, 0.4);
    tarp.lookAt(V(...c.mount));
    tarp.visible = false;
    world.add(tarp);
    tarps[c.node_id] = tarp;
  }

  // people: the employees, plus any visitors (not employees: an unknown
  // person the operator can send in). Everyone starts hidden until present.
  const people = {};
  const visitorIds = new Set((meta.visitors || []).map(v => v.id));
  for (const e of [...meta.employees, ...(meta.visitors || [])]) {
    const visitor = visitorIds.has(e.id);
    const ch = buildCharacter(e.look);
    ch.visible = false;
    world.add(ch);
    let label = null;
    if (opts.labels) {
      label = visitor
        ? textSprite([e.name, e.role], { accent: '#e5322d', bg: 'rgba(70,12,12,0.86)' })
        : textSprite([e.name, e.role], { accent: e.look.vest || e.look.shirt });
      label.position.set(0, e.look.height_m + 0.75, 0);
      ch.add(label);
    }
    people[e.id] = { obj: ch, meta: e, label, visitor };
  }
  const agvs = {};
  for (const a of meta.agvs) {
    const m = buildAGV(a.colour);
    world.add(m);
    agvs[a.id] = m;
  }

  let helpers = null;
  if (opts.helpers) helpers = buildHelpers(meta, world, cams);

  let lastT = null;
  function apply(state, dtOverride) {
    const dt = dtOverride != null ? dtOverride : (lastT == null ? 0 : Math.max(0, Math.min(0.5, state.t - lastT)));
    lastT = state.t;
    for (const w of state.workers) {
      const p = people[w.id];
      if (!p) continue;
      p.obj.visible = !!w.present;
      if (!w.present) continue;
      p.obj.position.copy(V(w.x, w.y, 0));
      p.obj.rotation.y = w.heading;
      animateCharacter(p.obj, dt, w.speed, w.speed > 0.05 ? 'walk' : w.action, w.carry);
    }
    for (const a of state.agvs) {
      const m = agvs[a.id];
      if (!m) continue;
      m.position.copy(V(a.x, a.y, 0));
      m.rotation.y = a.heading;
      m.userData.beacon.material.emissiveIntensity = a.speed > 0 || a.safety_stop ? (Math.sin(state.t * 9) > 0 ? 2.2 : 0.2) : 0.4;
    }
    const blocked = new Set(state.blocked_cameras || []);
    for (const [n, tarp] of Object.entries(tarps)) tarp.visible = blocked.has(Number(n));
  }

  return { scene, world, cams, camModels, people, agvs, apply, helpers, tarps };
}

// Viewer-only overlays: camera frustums and the computed camera zones.
function buildHelpers(meta, world, cams) {
  const group = new THREE.Group(); world.add(group);
  const zoneColors = ['#4285f4', '#34a853', '#fbbc05', '#ea4335'];
  const zones = new THREE.Group(); group.add(zones);
  for (const f of meta.zones) {
    const role = f.properties.role;
    const col = role === 'blind' ? '#7a1fa2' : zoneColors[f.properties.node_id % 4];
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const poly of polys) {
      const shape = new THREE.Shape(poly[0].map(([x, y]) => new THREE.Vector2(x, -y)));
      for (const hole of poly.slice(1)) shape.holes.push(new THREE.Path(hole.map(([x, y]) => new THREE.Vector2(x, -y))));
      const m = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: role === 'blind' ? 0.30 : 0.16, depthWrite: false }));
      m.rotation.x = -Math.PI / 2; m.position.y = 0.02; m.renderOrder = 2;
      zones.add(m);
    }
  }
  const frusta = new THREE.Group(); group.add(frusta);
  for (const [n, pc] of Object.entries(cams)) {
    const h = new THREE.CameraHelper(pc.clone());
    h.camera.far = 9; h.camera.updateProjectionMatrix(); h.update();
    h.setColors(new THREE.Color(zoneColors[n % 4]), new THREE.Color(zoneColors[n % 4]), new THREE.Color('#ffffff'), new THREE.Color(zoneColors[n % 4]), new THREE.Color(zoneColors[n % 4]));
    frusta.add(h);
  }
  return { group, zones, frusta };
}
