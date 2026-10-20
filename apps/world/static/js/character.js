// apps/world/static/js/character.js
// ---------------------------------
// A procedurally built, jointed 3D person with a walk / idle / pick
// animation. No external model files: every worker is assembled from
// capsules and spheres so the demo runs offline and every visual trait
// (height, build, skin, hair, clothing colours) comes from the employee's
// entry in configs/world/warehouse.yaml.
//
// Coordinates: three.js is Y-up. The warehouse floor plan's (x, y) maps to
// three's (x, z). A character faces +Z in its own frame.

import * as THREE from 'three';

const _matCache = new Map();
function mat(color, opts = {}) {
  const key = color + JSON.stringify(opts);
  if (!_matCache.has(key)) {
    _matCache.set(key, new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.0, ...opts }));
  }
  return _matCache.get(key);
}

function capsule(radius, length, material) {
  const m = new THREE.Mesh(new THREE.CapsuleGeometry(radius, length, 6, 14), material);
  m.castShadow = true;
  return m;
}

function sphere(radius, material, wSeg = 18, hSeg = 14) {
  const m = new THREE.Mesh(new THREE.SphereGeometry(radius, wSeg, hSeg), material);
  m.castShadow = true;
  return m;
}

// A limb hangs DOWN from its joint: the pivot sits at the joint, the mesh
// is offset so its top cap is at the pivot.
function limb(radius, length, material) {
  const pivot = new THREE.Group();
  const m = capsule(radius, length, material);
  m.position.y = -(length / 2 + radius * 0.6);
  pivot.add(m);
  return pivot;
}

/**
 * Build one worker.
 * @param {object} look  {height_m, build: "male"|"female", skin, hair, hair_style,
 *                        shirt, vest (or null), trousers, shoes, hat (or null)}
 */
export function buildCharacter(look) {
  const H = look.height_m || 1.75;
  const female = look.build === 'female';
  const root = new THREE.Group();
  root.name = 'character';

  const skin = mat(look.skin || '#c68642');
  const shirt = mat(look.shirt || '#3b5b92');
  const trousers = mat(look.trousers || '#2b2b2b');
  const shoes = mat(look.shoes || '#1a1a1a', { roughness: 0.6 });
  const hairMat = mat(look.hair || '#1b1b1b', { roughness: 0.9 });

  const legLen = 0.53 * H;
  const thighL = 0.235 * H, shinL = 0.235 * H;
  const torsoL = 0.30 * H;
  const shoulderHalf = (female ? 0.105 : 0.125) * H;
  const hipHalf = (female ? 0.058 : 0.052) * H;
  const upperArmL = 0.165 * H, foreArmL = 0.145 * H;

  // hips: the animated pelvis joint
  const hips = new THREE.Group();
  hips.position.y = legLen;
  root.add(hips);

  const pelvis = capsule(0.09 * H * (female ? 1.08 : 1.0), 0.06 * H, trousers);
  pelvis.rotation.z = Math.PI / 2;
  pelvis.scale.set(1, 1, 0.75);
  pelvis.position.y = 0.01 * H;
  hips.add(pelvis);

  // spine / torso
  const spine = new THREE.Group();
  spine.position.y = 0.03 * H;
  hips.add(spine);

  const chestR = (female ? 0.085 : 0.095) * H;
  const torso = capsule(chestR, torsoL - 2 * chestR * 0.8, shirt);
  torso.position.y = torsoL / 2;
  torso.scale.set(female ? 1.12 : 1.22, 1, 0.66);
  spine.add(torso);

  if (look.vest) {
    const vestMat = mat(look.vest, { roughness: 0.55, emissive: look.vest, emissiveIntensity: 0.12 });
    const vest = capsule(chestR * 1.06, torsoL * 0.62 - chestR, vestMat);
    vest.position.y = torsoL * 0.47;
    vest.scale.set(female ? 1.14 : 1.24, 1, 0.70);
    spine.add(vest);
    // two retro-reflective bands
    const bandMat = mat('#e8e8e8', { roughness: 0.3, emissive: '#bbbbbb', emissiveIntensity: 0.25 });
    for (const y of [0.30, 0.50]) {
      const band = new THREE.Mesh(new THREE.CylinderGeometry(chestR * 1.08, chestR * 1.08, 0.022 * H, 20, 1, true), bandMat);
      band.position.y = torsoL * y;
      band.scale.set(female ? 1.15 : 1.25, 1, 0.71);
      spine.add(band);
    }
  }

  // neck + head
  const neck = new THREE.Group();
  neck.position.y = torsoL;
  spine.add(neck);
  const neckMesh = capsule(0.028 * H, 0.03 * H, skin);
  neckMesh.position.y = 0.025 * H;
  neck.add(neckMesh);

  const head = new THREE.Group();
  head.position.y = 0.06 * H;
  neck.add(head);
  const headR = 0.062 * H;
  const skull = sphere(headR, skin);
  skull.scale.set(0.9, 1.08, 1.0);
  skull.position.y = headR;
  head.add(skull);
  // eyes and nose give the face a direction
  const eyeMat = mat('#111111', { roughness: 0.3 });
  for (const s of [-1, 1]) {
    const eye = sphere(headR * 0.12, eyeMat, 8, 6);
    eye.position.set(s * headR * 0.36, headR * 1.12, headR * 0.86);
    head.add(eye);
  }
  const nose = sphere(headR * 0.16, skin, 8, 6);
  nose.position.set(0, headR * 0.92, headR * 0.98);
  head.add(nose);

  // hair
  const hairCap = sphere(headR * 1.05, hairMat, 18, 10);
  hairCap.geometry = new THREE.SphereGeometry(headR * 1.05, 18, 10, 0, Math.PI * 2, 0, Math.PI * 0.55);
  hairCap.scale.set(0.92, 1.1, 1.04);
  hairCap.position.set(0, headR * 1.02, -headR * 0.06);
  hairCap.rotation.x = -0.25;
  head.add(hairCap);
  if (look.hair_style === 'ponytail') {
    const tail = capsule(headR * 0.28, headR * 1.3, hairMat);
    tail.position.set(0, headR * 0.55, -headR * 1.05);
    tail.rotation.x = 0.35;
    head.add(tail);
    const tie = sphere(headR * 0.3, hairMat, 10, 8);
    tie.position.set(0, headR * 1.3, -headR * 0.95);
    head.add(tie);
  } else if (look.hair_style === 'beard') {
    const beard = sphere(headR * 0.62, hairMat, 14, 10);
    beard.scale.set(1.15, 0.8, 0.7);
    beard.position.set(0, headR * 0.45, headR * 0.5);
    head.add(beard);
  }

  if (look.hat) {
    const hatMat = mat(look.hat, { roughness: 0.35 });
    const shell = new THREE.Mesh(new THREE.SphereGeometry(headR * 1.18, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), hatMat);
    shell.castShadow = true;
    shell.position.y = headR * 1.32;
    shell.scale.set(0.95, 0.85, 1.05);
    head.add(shell);
    const brim = new THREE.Mesh(new THREE.CylinderGeometry(headR * 1.32, headR * 1.32, headR * 0.08, 20), hatMat);
    brim.position.set(0, headR * 1.32, headR * 0.12);
    brim.scale.set(0.95, 1, 1.1);
    head.add(brim);
  }

  // arms
  const arms = [];
  for (const s of [-1, 1]) {
    const shoulder = new THREE.Group();
    shoulder.position.set(s * shoulderHalf, torsoL * 0.88, 0);
    spine.add(shoulder);
    const upper = limb(0.042 * H * (female ? 0.9 : 1), upperArmL, shirt);
    upper.rotation.z = s * 0.08;
    shoulder.add(upper);
    const elbow = new THREE.Group();
    elbow.position.y = -upperArmL - 0.02 * H;
    upper.add(elbow);
    const fore = limb(0.035 * H * (female ? 0.9 : 1), foreArmL, look.sleeves === 'short' ? skin : shirt);
    elbow.add(fore);
    const hand = sphere(0.03 * H, skin, 10, 8);
    hand.position.y = -foreArmL - 0.045 * H;
    fore.add(hand);
    arms.push({ shoulder, upper, elbow, fore, side: s });
  }

  // legs
  const legs = [];
  for (const s of [-1, 1]) {
    const hip = new THREE.Group();
    hip.position.set(s * hipHalf, 0, 0);
    hips.add(hip);
    const thigh = limb(0.058 * H * (female ? 1.04 : 1), thighL - 0.05 * H, trousers);
    hip.add(thigh);
    const knee = new THREE.Group();
    knee.position.y = -thighL;
    thigh.add(knee);
    const shin = limb(0.046 * H, shinL - 0.06 * H, trousers);
    knee.add(shin);
    const foot = new THREE.Mesh(new THREE.BoxGeometry(0.06 * H, 0.04 * H, 0.15 * H), shoes);
    foot.castShadow = true;
    foot.position.set(0, -shinL + 0.005 * H, 0.03 * H);
    shin.add(foot);
    legs.push({ hip, thigh, knee, shin, side: s });
  }

  // something to carry (a tote) — shown while the worker is carrying stock
  const tote = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.26, 0.32), mat('#2f6fb3', { roughness: 0.5 }));
  tote.castShadow = true;
  tote.position.set(0, legLen + torsoL * 0.35, 0.30);
  tote.visible = false;
  root.add(tote);

  root.userData.rig = { hips, spine, neck, head, arms, legs, tote, legLen, H, phase: Math.random() * 6.28, t: 0 };
  return root;
}

/**
 * Advance one character's animation.
 * @param {THREE.Group} root
 * @param {number} dt      wall seconds since last frame
 * @param {number} speed   ground speed, m/s
 * @param {string} action  "walk" | "idle" | "pick" | "scan"
 * @param {boolean} carrying
 */
export function animateCharacter(root, dt, speed, action, carrying) {
  const r = root.userData.rig;
  r.t += dt;
  const H = r.H;
  const stride = 0.75 * H; // metres per full gait cycle (two steps)
  const moving = speed > 0.05;
  if (moving) r.phase += (speed / stride) * Math.PI * 2 * dt;
  const p = r.phase;
  const amp = moving ? Math.min(1, speed / 1.2) : 0;

  // legs: thigh swings, knee bends on the forward swing
  for (const L of r.legs) {
    const ph = p + (L.side > 0 ? Math.PI : 0);
    L.hip.rotation.x = -Math.sin(ph) * 0.48 * amp;
    L.knee.rotation.x = Math.max(0, Math.cos(ph)) * 0.95 * amp;
  }
  // body bob + slight forward lean while walking
  const bob = moving ? Math.abs(Math.cos(p)) * 0.025 * H * amp : Math.sin(r.t * 1.6) * 0.003 * H;
  r.hips.position.y = r.legLen - (moving ? 0.012 * H : 0) + bob;
  r.spine.rotation.x = moving ? 0.06 * amp : 0.0;
  r.spine.rotation.y = moving ? Math.sin(p) * 0.08 * amp : 0;
  r.hips.rotation.y = moving ? -Math.sin(p) * 0.06 * amp : 0;

  // arms
  for (const A of r.arms) {
    const ph = p + (A.side > 0 ? 0 : Math.PI);
    let sx, el;
    if (action === 'pick') {
      // reaching up to a shelf, alternating hands
      const reach = 0.5 + 0.5 * Math.sin(r.t * 2.2 + (A.side > 0 ? 0 : 1.6));
      sx = -1.2 - 1.0 * reach; el = -0.4 + 0.3 * reach;
    } else if (action === 'scan') {
      sx = A.side > 0 ? -1.0 : -0.25; el = A.side > 0 ? -1.1 : -0.2;
    } else if (carrying) {
      sx = -0.55; el = -1.2;
    } else if (moving) {
      sx = Math.sin(ph) * 0.5 * amp; el = -0.25 - Math.max(0, Math.sin(ph)) * 0.35 * amp;
    } else {
      sx = Math.sin(r.t * 1.6 + A.side) * 0.03; el = -0.12;
    }
    A.shoulder.rotation.x = sx;
    A.elbow.rotation.x = el;
  }
  r.head.rotation.y = action === 'idle' ? Math.sin(r.t * 0.5) * 0.35 : 0;
  r.tote.visible = !!carrying;
}
