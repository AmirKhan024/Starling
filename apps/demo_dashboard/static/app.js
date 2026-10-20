// Starling — shared page shell: header + navigation, icons, live state, toasts, button feedback.
(function () {
  const P = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  const ICONS = {
    camera: `<path d="M3 8h3l2-3h8l2 3h3v11H3z"/><circle cx="12" cy="13" r="4"/>`,
    person: `<circle cx="12" cy="7" r="4"/><path d="M4 21c1-5 4.5-7 8-7s7 2 8 7"/>`,
    pin: `<path d="M12 21s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="9" r="2.5"/>`,
    badge: `<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2.4"/><path d="M5.5 16.5c.7-1.8 2-2.6 3.5-2.6s2.8.8 3.5 2.6M15 10h3M15 13.5h3"/>`,
    note: `<path d="M4 6h16v12H4z"/><path d="m4 7 8 6 8-6"/><circle cx="18" cy="17" r="3.2" fill="currentColor" stroke="none" opacity=".25"/>`,
    network: `<circle cx="5" cy="6" r="2.5"/><circle cx="19" cy="6" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M7.5 6h9M7.5 18h9M5 8.5v7M19 8.5v7"/>`,
    search: `<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>`,
    brain: `<path d="M9 4a3 3 0 0 0-3 3v.3A3 3 0 0 0 4 10.2a3 3 0 0 0 1.2 2.4A3.2 3.2 0 0 0 9 17.6V20M15 4a3 3 0 0 1 3 3v.3a3 3 0 0 1 2 2.9 3 3 0 0 1-1.2 2.4 3.2 3.2 0 0 1-3.8 5V20M9 4c1.2 0 2.2.7 3 1.5C12.8 4.7 13.8 4 15 4M12 5.5V20"/>`,
    server: `<rect x="4" y="3" width="16" height="7" rx="1.5"/><rect x="4" y="14" width="16" height="7" rx="1.5"/><path d="M8 6.5h.01M8 17.5h.01"/>`,
    scissors: `<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.2 8.2 20 20M8.2 15.8 20 4"/>`,
    eye: `<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>`,
    eyeoff: `<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.1 3.9M6.6 6.6A17 17 0 0 0 2 12s3.6 7 10 7a9.6 9.6 0 0 0 5.4-1.6"/>`,
    shield: `<path d="M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>`,
    alert: `<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>`,
    play: `<path d="M7 4v16l13-8z"/>`,
    check: `<path d="m5 12 5 5 9-10"/>`,
    x: `<path d="M6 6l12 12M18 6 6 18"/>`,
    refresh: `<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>`,
    power: `<path d="M12 3v9M6.3 6.3a8 8 0 1 0 11.4 0"/>`,
    mask: `<path d="M3 7c3-1.5 6-1.5 9 0 3-1.5 6-1.5 9 0v4c0 4-4 7-9 7S3 15 3 11z"/><path d="M7.5 11h2M14.5 11h2"/>`,
    lock: `<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>`,
    unknown: `<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01"/>`,
    layers: `<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>`,
    monitor: `<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>`,
    split: `<path d="M12 3v18M4 8l-2 4 2 4M20 8l2 4-2 4"/>`,
    cover: `<path d="M3 8h3l2-3h8l2 3h3v11H3z"/><path d="M4 20 20 6"/>`,
    walk: `<circle cx="13" cy="4" r="2"/><path d="m9 21 2-6 3 3v3M7 12l3-4h4l2 4 3 1M11 8l-1 5"/>`,
    fire: `<path d="M12 21c-4 0-7-2.7-7-6.5C5 10 9 8 9 3c3 2 5 4.5 5 7.5 1-1 1.5-2 1.5-3.5 2 1.8 3.5 4.3 3.5 7.5 0 3.8-3 6.5-7 6.5z"/>`,
    ask: `<path d="M4 5h16v11H9l-5 4z"/><path d="M10 9.5a2 2 0 1 1 2.7 1.9c-.4.2-.7.6-.7 1V13M12 15.5h.01"/>`,
    gauge: `<path d="M4 18a8 8 0 1 1 16 0"/><path d="m12 18 4-6"/>`,
    cpu: `<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>`,
  };
  const icon = (name, cls = 'ico') => `<svg class="${cls}" viewBox="0 0 24 24" ${P} aria-hidden="true">${ICONS[name] || ''}</svg>`;

  const TABS = [
    ['live', '/', 'monitor', 'Live monitor'],
    ['inside', '/inside', 'network', 'Inside the system'],
    ['compare', '/compare', 'split', 'What if…'],
    ['how', '/how', 'layers', 'How it works'],
    ['tour', '/tour', 'play', 'Present'],
  ];
  const LOGO = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M3 13c3.5-.4 6-2.2 8-5 1.4 2.4 3.6 3.6 6.5 3.4L21 9l-1.6 4.4c-1.6 3.6-5 5.6-9.4 5.6H5l2-2.4C5.3 16 4 14.8 3 13z"/></svg>`;

  const embed = new URLSearchParams(location.search).has('embed');
  if (embed) document.documentElement.classList.add('embedded');

  function shell(active) {
    if (embed) document.body.classList.add('embed');
    const h = document.createElement('header');
    h.className = 'app-header';
    h.innerHTML = `<a class="app-brand" href="/">${'<span class="logo">' + LOGO + '</span>'}<div><b>Starling</b><span>Warehouse safety monitor</span></div></a>
      <nav class="app-tabs">${TABS.map(([k, href, ic, lbl]) => `<a href="${href}" class="${k === active ? 'on' : ''}">${icon(ic)}<span class="lbl">${lbl}</span></a>`).join('')}</nav>
      <div class="app-right"><span class="pill ok live" id="sys-pill"><span class="dot"></span><span id="sys-text">Connecting</span></span>
      <div class="app-clock"><span id="sys-clock">--:--:--</span><small id="sys-shift"></small></div></div>`;
    document.body.prepend(h);
    const b = document.createElement('div');
    b.className = 'banner'; b.id = 'sys-banner';
    h.after(b);
    const t = document.createElement('div'); t.className = 'toasts'; t.id = 'toasts'; document.body.appendChild(t);
  }

  function toast(title, text = '', kind = '', ms = 4500) {
    const box = document.getElementById('toasts'); if (!box) return;
    const el = document.createElement('div'); el.className = 'toast ' + kind;
    el.innerHTML = `${icon(kind === 'bad' ? 'alert' : 'check', 'ico')}<div><b>${title}</b>${text}</div>`;
    box.appendChild(el); setTimeout(() => el.remove(), ms);
    return el;
  }

  async function post(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    return r.json().catch(() => ({}));
  }
  // A button press: immediate "working" state, then a clear confirmation.
  async function act(btn, url, body, done) {
    if (btn) btn.classList.add('busy');
    try {
      const r = await post(url, body);
      if (r && r.ok === false) toast('That did not work', r.error || r.note || '', 'bad');
      else if (done) toast(done[0], done[1] || '', 'ok', 3500);
      return r;
    } catch (e) { toast('No answer from the dashboard', String(e), 'bad'); return null; }
    finally { if (btn) btn.classList.remove('busy'); }
  }

  // One shared poll of the live state for every component on the page.
  const subs = []; let last = null; let cfg = null;
  function onState(fn) { subs.push(fn); if (last) fn(last); }
  async function config() { if (!cfg) cfg = await (await fetch('/api/config')).json(); return cfg; }
  async function loop() {
    try {
      const s = await (await fetch('/api/state', { cache: 'no-store' })).json();
      if (s.ready) { last = s; header(s); subs.forEach(f => { try { f(s); } catch (e) { console.error(e); } }); }
    } catch { const p = document.getElementById('sys-pill'); if (p) { p.className = 'pill bad'; document.getElementById('sys-text').textContent = 'Dashboard offline'; } }
    setTimeout(loop, 1000);
  }
  function header(s) {
    const w = s.world || {}; const pill = document.getElementById('sys-pill'); if (!pill) return;
    document.getElementById('sys-clock').textContent = w.clock || '';
    document.getElementById('sys-shift').textContent = (w.company || {}).shift_name || '';
    const al = w.alerts || []; const bad = al.filter(a => a.level === 'bad').length;
    pill.className = 'pill live ' + (bad ? 'bad' : al.length ? 'warn' : 'ok');
    document.getElementById('sys-text').textContent = bad ? `${bad} alert${bad > 1 ? 's' : ''}` : al.length ? `${al.length} warning${al.length > 1 ? 's' : ''}` : 'All normal';
    const h = s.health || {}; const b = document.getElementById('sys-banner');
    b.classList.toggle('on', !!h.overloaded);
    if (h.overloaded) b.innerHTML = `${icon('cpu')}<span><b>This laptop is overloaded.</b> The cameras are falling behind (${h.slow_nodes.map(n => h.fps[n]).join(' / ')} of ${h.target_fps} frames a second), so people can be missed. Close other programs.</span>`;
  }
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const initials = n => String(n).split(' ').map(s => s[0]).join('').slice(0, 2).toUpperCase();
  const rate = b => !b ? '0' : b * 8 >= 1e6 ? `${(b * 8 / 1e6).toFixed(1)} Mbit/s` : `${Math.round(b * 8 / 1e3)} kbit/s`;

  // ── the floor plan, drawn the same way on every page ─────────────────
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs = {}, parent) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (parent) parent.appendChild(e); return e; };
  function drawFloor(g, C, opts = {}) {
    g.innerHTML = '';
    const W = C.world.building.width_m, D = C.world.building.depth_m;
    el('rect', { x: 0, y: 0, width: W, height: D, fill: 'var(--floor)', stroke: 'var(--wall)', 'stroke-width': 0.16, rx: 0.1 }, g);
    if (opts.zones !== false) for (const f of C.floorplan.features.filter(f => f.properties.role === 'camera_zone')) {
      const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
      for (const p of polys) el('path', { d: p.map(r => 'M' + r.map(c => c.join(',')).join('L') + 'Z').join(''), fill: `var(--c${f.properties.node_id % 4})`, opacity: 0.06 }, g);
    }
    for (const f of C.floorplan.features.filter(f => f.properties.role === 'obstacle')) {
      const c = f.geometry.coordinates[0]; const xs = c.map(p => p[0]), ys = c.map(p => p[1]);
      el('rect', { x: Math.min(...xs), y: Math.min(...ys), width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys), fill: f.properties.kind === 'rack' ? 'var(--rack)' : 'var(--prop)', rx: 0.08 }, g);
    }
    const ent = C.world.entrance;
    el('rect', { x: -0.35, y: ent.door_y - ent.door_width_m / 2, width: 0.5, height: ent.door_width_m, fill: 'var(--ok)', rx: 0.1 }, g);
    el('circle', { cx: ent.gate.x, cy: ent.gate.y, r: ent.gate.radius_m, fill: 'none', stroke: 'var(--ok)', 'stroke-width': 0.08, 'stroke-dasharray': '0.25 0.18' }, g);
    const gl = el('text', { x: ent.gate.x, y: ent.gate.y - ent.gate.radius_m - 0.25, 'font-size': 0.48, fill: 'var(--ok)', 'font-weight': 700, 'text-anchor': 'middle' }, g); gl.textContent = 'ENTRANCE GATE';
    for (const d of C.world.dock_doors) el('rect', { x: W - 0.15, y: d.y - d.width_m / 2, width: 0.5, height: d.width_m, fill: 'var(--c2)', rx: 0.1 }, g);
    if (opts.labels !== false) for (const a of C.world.areas || []) {
      if (a.name === 'Storage aisles') continue;
      const t = el('text', { x: (a.x0 + a.x1) / 2, y: a.y0 < D / 2 ? a.y0 + 1.1 : a.y1 - 0.55, 'font-size': 0.6, fill: 'var(--faint)', 'font-weight': 650, 'text-anchor': 'middle', 'letter-spacing': '0.04em' }, g);
      t.textContent = a.name.toUpperCase();
    }
    const rk = C.world.racks; const rx0 = Math.min(...rk.map(r => r.x0)), rx1 = Math.max(...rk.map(r => r.x1));
    for (const y of [(rk[0].y1 + rk[1].y0) / 2, (rk[1].y1 + rk[2].y0) / 2]) { const t = el('text', { x: (rx0 + rx1) / 2, y: y + 0.2, 'font-size': 0.48, fill: 'var(--faint)', 'text-anchor': 'middle', 'font-style': 'italic' }, g); t.textContent = 'aisle — no camera'; }
    for (const c of C.world.cameras) {
      const [x, y] = c.mount;
      el('circle', { cx: x, cy: y, r: 0.5, fill: `var(--c${c.node_id % 4})` }, g);
      const t = el('text', { x, y: y + 0.19, 'font-size': 0.5, 'font-weight': 800, 'text-anchor': 'middle', fill: '#fff' }, g); t.textContent = c.node_id;
    }
  }
  function regionPath(C, r) {
    const grid = C.grid;
    return r.runs.map(([j, i0, i1]) => { const x = grid.origin[0] + i0 * grid.cell, y = grid.origin[1] + j * grid.cell; return `M${x},${y}h${(i1 - i0 + 1) * grid.cell}v${grid.cell}h${-(i1 - i0 + 1) * grid.cell}Z`; }).join('');
  }
  function zonePath(C, n) {
    return C.floorplan.features.filter(f => f.properties.role === 'camera_zone' && f.properties.node_id === n)
      .flatMap(f => f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates)
      .map(p => p.map(r => 'M' + r.map(c => c.join(',')).join('L') + 'Z').join('')).join('');
  }
  const camName = (C, n) => { const c = (C.world.cameras || []).find(c => c.node_id === n); return c ? c.area : `Camera ${n}`; };

  window.Starling = { shell, icon, toast, post, act, onState, config, esc, initials, rate, el, drawFloor, regionPath, zonePath, camName, embed };
  if (!embed) loop(); else loop();
})();
