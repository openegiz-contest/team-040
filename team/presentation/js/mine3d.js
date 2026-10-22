// The live mine behind the hero slides: the same env.glb (and actors) as the
// dispatcher's 3D stage, seen through its MainView orthographic camera.
// The art is baked for that view direction (SPEC §5), so the camera only pans
// and zooms: a slide names a view, and the camera glides to it — down the
// mine, horizon by horizon. Rendering runs only while something moves.
//
// Scene metres (SPEC §3): X = x - cx, Y = z * k, Z = cy - y.

import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {clone as cloneSkinned} from 'three/addons/utils/SkeletonUtils.js';

const ART = new URL('../../ui/public/models/mine-art/', import.meta.url).href;
const ACCENT = new THREE.Color('#2EF2C2');
const DANGER = '#FF4B3E';
const HALF_H = 234.5625;          // MainView ymag (16:9 frame)
const WORKER_SCALE = 1.6;         // 5 m figure drawn about 8 m, as on the stage (×4.4 a person)
const MACHINE_SCALE = 2.2 / 1.5;  // built 1.5× real, drawn 2.2× real, as on the stage

/** cubic-bezier(.2, .7, 0, 1), the poster easing of the UI (base.css --ease-poster). */
export function easePoster(t) {
  const x1 = 0.2, y1 = 0.7, x2 = 0, y2 = 1;
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  let u = t;
  for (let i = 0; i < 8; i += 1) {
    const x = ((ax * u + bx) * u + cx) * u - t;
    const d = (3 * ax * u + 2 * bx) * u + cx;
    if (Math.abs(x) < 1e-5 || Math.abs(d) < 1e-6) break;
    u -= x / d;
  }
  u = Math.min(1, Math.max(0, u));
  return ((ay * u + by) * u + cy) * u;
}

function loadGlb(url) {
  return new Promise((resolve, reject) => new GLTFLoader().load(url, resolve, undefined, reject));
}

/** A diagonal hatch in the hazard red, like --hatch-danger of the UI. */
function hatchTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(255, 75, 62, 0.34)';
  g.fillRect(0, 0, 64, 64);
  g.strokeStyle = DANGER;
  g.lineWidth = 9;
  for (let i = -64; i <= 128; i += 22) {
    g.beginPath(); g.moveTo(i, 64); g.lineTo(i + 64, 0); g.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** A flat ribbon along a polyline with the distance along it in `aDist`, dashes flowing toward the end. */
function routeRibbon(points, width) {
  const pos = [];
  const dist = [];
  const index = [];
  let run = 0;
  for (let i = 0; i < points.length; i += 1) {
    const p = points[i];
    const a = points[Math.max(0, i - 1)];
    const b = points[Math.min(points.length - 1, i + 1)];
    const dir = new THREE.Vector3().subVectors(b, a).setY(0);
    if (dir.lengthSq() < 1e-6) dir.set(1, 0, 0);
    dir.normalize();
    const side = new THREE.Vector3(-dir.z, 0, dir.x).multiplyScalar(width / 2);
    if (i > 0) run += p.distanceTo(points[i - 1]);
    pos.push(p.x + side.x, p.y, p.z + side.z, p.x - side.x, p.y, p.z - side.z);
    dist.push(run, run);
    if (i > 0) {
      const o = (i - 1) * 2;
      index.push(o, o + 1, o + 2, o + 1, o + 3, o + 2);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geometry.setAttribute('aDist', new THREE.Float32BufferAttribute(dist, 1));
  geometry.setIndex(index);
  const material = new THREE.ShaderMaterial({
    transparent: true, depthTest: false, depthWrite: false, side: THREE.DoubleSide,
    uniforms: {uTime: {value: 0}, uColor: {value: ACCENT.clone()}, uShow: {value: 1}, uTotal: {value: run}},
    vertexShader: `attribute float aDist; varying float vDist;
      void main() { vDist = aDist; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform float uTime; uniform vec3 uColor; uniform float uShow; uniform float uTotal; varying float vDist;
      void main() {
        if (vDist > uShow * uTotal) discard;
        float dash = step(0.42, fract((vDist - uTime * 26.0) / 22.0));
        gl_FragColor = vec4(uColor, mix(0.5, 0.95, dash));
      }`,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.renderOrder = 20;
  return mesh;
}

/**
 * The mine in a canvas.
 * @param {HTMLCanvasElement} canvas
 * @param {{reduced: boolean, onFrame?: Function}} options
 */
export async function createMine(canvas, {reduced = false} = {}) {
  const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: false, preserveDrawingBuffer: true});
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor('#0A0B0D', 1);
  const scene = new THREE.Scene();

  const env = await loadGlb(`${ART}env.glb`);
  const extras = env.scene.userData || {};
  const k = Number.isFinite(extras.k) ? extras.k : 1.35;
  const cx = Number.isFinite(extras.cx) ? extras.cx : 150;
  const cy = Number.isFinite(extras.cy) ? extras.cy : 50;
  const at = (x, y, z) => new THREE.Vector3(x - cx, z * k, cy - y);

  env.scene.updateMatrixWorld(true);
  let mainView = null;
  const anchors = new Map();
  env.scene.traverse((o) => {
    if (o.isCamera && !mainView) mainView = o;
    if (o.name.startsWith('ANCHOR_')) anchors.set(o.name.slice(7), o);
    if (o.isMesh) {
      const pick = /^PICK_/.test(o.name) || (o.parent && /^PICK_/.test(o.parent.name)) || (o.material && o.material.name === 'pick');
      if (pick) { o.visible = false; return; }
      for (const m of [].concat(o.material)) {
        if (m.map) { m.map.colorSpace = THREE.SRGBColorSpace; m.map.anisotropy = renderer.capabilities.getMaxAnisotropy(); m.map.needsUpdate = true; }
        m.toneMapped = false;
      }
    }
  });
  if (!mainView) throw new Error('env.glb: no MainView camera');
  scene.add(env.scene);

  const quaternion = new THREE.Quaternion();
  const mvPos = new THREE.Vector3();
  mainView.matrixWorld.decompose(mvPos, quaternion, new THREE.Vector3());
  const back = new THREE.Vector3(0, 0, 1).applyQuaternion(quaternion);
  const right = new THREE.Vector3(1, 0, 0).applyQuaternion(quaternion);
  const up = new THREE.Vector3(0, 1, 0).applyQuaternion(quaternion);
  const centre = mvPos.clone().addScaledVector(back, -mvPos.dot(back));

  const camera = new THREE.OrthographicCamera(-HALF_H * 16 / 9, HALF_H * 16 / 9, HALF_H, -HALF_H, 10, 8000);
  camera.quaternion.copy(quaternion);

  // ---- overlays: the hazard of zone A and the computed route to exit A --------------------------------------------
  const hazard = new THREE.Mesh(new THREE.PlaneGeometry(14, 80), new THREE.MeshBasicMaterial({
    map: hatchTexture(), transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -4, opacity: 0.95,
  }));
  hazard.material.map.repeat.set(14 / 10, 80 / 10);
  hazard.rotation.x = -Math.PI / 2;
  hazard.position.copy(at(150, -42, -120)).add(new THREE.Vector3(0, 0.35, 0));
  hazard.renderOrder = 5;
  hazard.visible = false;
  scene.add(hazard);

  const route = routeRibbon([
    at(150, -62, -120), at(150, 0, -120), at(0, 0, -120), at(-240, 0, -60), at(0, 0, 0),
  ].map((p) => p.add(new THREE.Vector3(0, 0.6, 0))), 4.2);
  route.visible = false;
  scene.add(route);

  // ---- actors: loaders at their anchors, crews in the two zone drifts -------------------------------------------
  const mixers = [];
  const groups = {zoneA: new THREE.Group(), zoneB: new THREE.Group(), machines: new THREE.Group()};
  Object.values(groups).forEach((g) => scene.add(g));
  const prepare = (root) => root.traverse((o) => {
    if (!o.isMesh) return;
    o.frustumCulled = false;
    for (const m of [].concat(o.material)) { if (m.map) m.map.colorSpace = THREE.SRGBColorSpace; m.toneMapped = false; }
  });
  try {
    const lhd = await loadGlb(`${ART}actors/lhd.glb`);
    prepare(lhd.scene);
    for (const zone of ['zone-a', 'zone-b']) {
      const anchor = anchors.get(`lhd_${zone}`);
      if (!anchor) continue;
      const copy = lhd.scene.clone(true);
      anchor.getWorldPosition(copy.position);
      anchor.getWorldQuaternion(copy.quaternion);
      copy.scale.setScalar(MACHINE_SCALE);
      groups.machines.add(copy);
    }
  } catch (error) { console.warn('lhd.glb not shown:', error.message); }
  try {
    const worker = await loadGlb(`${ART}actors/worker.glb`);
    prepare(worker.scene);
    const clips = worker.animations || [];
    const clip = (name) => clips.find((c) => c.name === name) || clips[0];
    const crew = [['work_drill', 20], ['work_inspect', 40], ['work_scale', 60]];
    for (const [key, level] of [['zoneA', -120], ['zoneB', -240]]) {
      crew.forEach(([action, offset], i) => {
        const figure = cloneSkinned(worker.scene);
        figure.position.copy(at(150 + (i - 1) * 2.5, -offset, level));
        figure.rotation.y = i % 2 ? Math.PI / 2 : -Math.PI / 2;
        figure.scale.setScalar(WORKER_SCALE);
        groups[key].add(figure);
        if (clips.length) {
          const mixer = new THREE.AnimationMixer(figure);
          const play = mixer.clipAction(clip(action));
          play.play();
          mixer.setTime(i * 0.7);
          mixers.push(mixer);
        }
      });
    }
  } catch (error) { console.warn('worker.glb not shown:', error.message); }

  // ---- views ------------------------------------------------------------------------------------------------------
  // A view: a scene point, where it sits on the screen (sx, sy in half-frames: +1 is the right/top edge) and a zoom.
  const VIEWS = {
    overview: {focus: centre.clone(), sx: 0, sy: 0, zoom: 1},
    surface: {focus: centre.clone().addScaledVector(up, 60), sx: 0.08, sy: -0.06, zoom: 1.12},
    zoneA: {focus: at(150, -40, -120), sx: 0.3, sy: -0.12, zoom: 2.5},
    level240: {focus: at(150, -40, -240), sx: 0.3, sy: -0.2, zoom: 1.85},
  };
  const MODES = {
    overview: {hazard: false, route: false, zoneA: true, zoneB: true},
    surface: {hazard: false, route: false, zoneA: true, zoneB: true},
    zoneA: {hazard: true, route: true, zoneA: true, zoneB: true},
    level240: {hazard: false, route: false, zoneA: false, zoneB: true},
  };
  const now = {focus: VIEWS.overview.focus.clone(), sx: 0, sy: 0, zoom: 1};
  let glide = null;
  let mode = 'overview';
  let running = false;
  let visible = false;
  let last = 0;
  const clock = {t: 0};

  function place() {
    camera.zoom = now.zoom;
    camera.updateProjectionMatrix();
    const halfW = (camera.right - camera.left) / 2;
    camera.position.copy(now.focus)
      .addScaledVector(right, -now.sx * halfW / now.zoom)
      .addScaledVector(up, -now.sy * HALF_H / now.zoom)
      .addScaledVector(back, 2600);
  }

  function applyMode(name) {
    const m = MODES[name] || MODES.overview;
    hazard.visible = m.hazard;
    route.visible = m.route;
    groups.zoneA.visible = m.zoneA;
    groups.zoneB.visible = m.zoneB;
  }

  function draw() {
    place();
    renderer.render(scene, camera);
  }

  function frame(time) {
    const dt = last ? Math.min(0.1, (time - last) / 1000) : 0;
    last = time;
    clock.t += dt;
    let moving = false;
    if (glide) {
      const t = Math.min(1, (time - glide.start) / glide.ms);
      const e = easePoster(t);
      now.focus.lerpVectors(glide.from.focus, glide.to.focus, e);
      now.sx = glide.from.sx + (glide.to.sx - glide.from.sx) * e;
      now.sy = glide.from.sy + (glide.to.sy - glide.from.sy) * e;
      now.zoom = Math.exp(Math.log(glide.from.zoom) + (Math.log(glide.to.zoom) - Math.log(glide.from.zoom)) * e);
      if (t >= 1) glide = null; else moving = true;
    }
    if (route.visible) {
      route.material.uniforms.uTime.value = clock.t;
      const show = route.material.uniforms.uShow;
      show.value = Math.min(1, show.value + dt / 1.4);
    }
    if (!reduced) for (const mixer of mixers) mixer.update(dt);
    draw();
    const alive = visible && !reduced;
    if (moving || alive) requestAnimationFrame(frame);
    else { running = false; last = 0; }
  }

  function kick() {
    if (running) return;
    running = true;
    requestAnimationFrame(frame);
  }

  function resize(width, height, ratio) {
    renderer.setPixelRatio(ratio);
    renderer.setSize(width, height, false);
    const aspect = width / height;
    camera.left = -HALF_H * aspect; camera.right = HALF_H * aspect;
    camera.updateProjectionMatrix();
    draw();
  }

  return {
    views: Object.keys(VIEWS),
    /** Glide (or jump) to a named view; `instant` for reduced motion and print. */
    go(name, {instant = false, ms = 1700} = {}) {
      const to = VIEWS[name] || VIEWS.overview;
      if (name !== mode) {
        mode = name;
        applyMode(name);
        route.material.uniforms.uShow.value = instant || reduced ? 1 : 0;
      }
      if (instant || reduced) {
        glide = null;
        now.focus.copy(to.focus); now.sx = to.sx; now.sy = to.sy; now.zoom = to.zoom;
        draw();
        if (visible && !reduced) kick();
        return;
      }
      glide = {from: {focus: now.focus.clone(), sx: now.sx, sy: now.sy, zoom: now.zoom}, to, ms, start: performance.now()};
      kick();
    },
    setVisible(flag) {
      visible = flag;
      if (flag) kick();
    },
    resize,
    /** A still of a view as a JPEG data URL (print). */
    still(name, width, height) {
      const keep = visible;
      visible = false;
      this.go(name, {instant: true});
      for (const mixer of mixers) mixer.setTime(1.2);
      resize(width, height, 1);
      route.material.uniforms.uTime.value = 0;
      route.material.uniforms.uShow.value = 1;
      draw();
      const url = renderer.domElement.toDataURL('image/jpeg', 0.86);
      visible = keep;
      return url;
    },
    info() {
      return {triangles: renderer.info.render.triangles, calls: renderer.info.render.calls, mode};
    },
  };
}
