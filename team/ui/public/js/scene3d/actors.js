// What moves on the floors of the scene besides the markers: the loaders of the
// model (equipment twins, contract question 18) and small figures of people
// seen close up. Both move only by published positions (redesign spec §3,
// honest motion): a glide from the position drawn to the newly published one,
// ending exactly there and never beyond it, only while the link is ok, the
// data are fresh, the model runs and reduced motion is off; otherwise a jump.
//
// Loaders. With equipment twins of kind `lhd` in the attributes, each one is
// drawn at its published `at_working` + `offset_m` (the 3D polyline fraction,
// as people are), turned along its working: towards the published
// `toward_node` when it stands, along its travel while it glides. Its look is
// its published `state` (working, parked, stopped; anything else unknown) and
// its bucket carries rock when it is published `loaded`. Without equipment twins
// the scene keeps the static symbols of the zones' work (loaders.js, scene.js).
//
// People. A person's marker (a sprite of constant size) carries the three axes:
// hazard, knowledge, reachability. Once a person would be at least FIGURE_PX
// tall on the screen, a small low-poly miner (overalls with reflective bands,
// helmet, cap lamp) stands on the floor under the marker, facing the way the
// person last walked; the marker stays above the helmet. A position that is not
// fresh greys the figure and puts its lamp out. Two draw calls for all people.
//
// Walk cycle (mine-art SPEC §6). A figure model with an animation clip `walk`
// (a loop, root still, stride per cycle in the clip's `extras.strideM`, and
// optionally `idle`) is drawn per person as a skinned clone with its own mixer.
// The walk plays only for a person who is moving between two different drawn
// places (scene.js: the playback of walk.js), at the rate that makes one stride
// cover the ground the person covers (no sliding feet), and fades to the idle
// pose (held still) within FADE_MS when the person stops. Never under reduced
// motion. A model without the clip (miner.glb) is merged and glides as before.
//
// Pure three.js and the layout; no DOM, no words.

import * as THREE from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
import {clone as cloneSkinned} from 'three/addons/utils/SkeletonUtils.js';
import {alongStep, pointOnWorking, stepBetween, stepLength} from './layout.js';

/** A glide between two publications lasts as long as a person's (scene.js TWEEN_MS). */
export const MACHINE_MS = 900;
/**
 * A loader travels at most about 25 m between two publications of the model (fixtures/README.md, «Техника»); a longer
 * step is a jump of the model (a command moved it to a recorded state): it is shown at once, never glided.
 */
const MAX_STEP_M = 30;
/** A position this close to an end of its working is at that node: the same point as on any working that meets there. */
const AT_NODE_M = 0.5;
/** The figures are drawn this many times larger than a 1.8 m person, as the loaders are (layout.js LOADER_SCALE). */
export const FIGURE_SCALE = 2.5;
const FIGURE_M = 1.8;
/** A figure is drawn once it is at least this tall on the screen; at the overview the markers are enough. */
export const FIGURE_PX = 28;
/**
 * Art mode (one orthographic view, at most 4× the overview): people are part of the illustration, drawn once they
 * are this tall (the 8 m worker of the art is about 15 px tall at the overview of a 1920×1080 stage and about 9.6 px at
 * 1280×720, so the figures show from the first picture at both); the scene gives its threshold as source.figurePx.
 */
export const FIGURE_PX_ART = 9;
/**
 * People drawn close together (one place, or places closer than CLOSE of the figure's height) stand apart: side by
 * side across the channel and a step along it, diagonally, so that neither a working running across the view nor
 * one running towards it puts one figure over another. In shares of the figure's height (the rigged figure), or
 * scene metres for the small miner.
 */
const SPREAD = {close: 0.4, across: 0.42, along: 0.5, sideMax: 4.5};
const SIDE_STEP = 2.4;
const SIDE_MAX = 3.6;
/** A marker stands this high over the floor (scene.js), and over the helmet of its figure when one is drawn. */
const MARKER_LIFT = 6;
const FIGURE_TOP = FIGURE_M * FIGURE_SCALE;
/** The marker stands this far over the helmet of a figure. */
const OVER_HELMET = 3.5;
const DEG = Math.PI / 180;
/** The walk cycle fades in and out over this time (ms). */
export const FADE_MS = 200;

const LOOKS = new Set(['working', 'parked', 'stopped']);

/** The loaders among the twins of the attributes (kind `equipment`, `equipment_kind: lhd`), local names, sorted. */
export function machinesOf(model) {
  return (model && model.byKind.equipment ? model.byKind.equipment : [])
    .filter((thing) => thing.attrs.equipment_kind === 'lhd').map((thing) => thing.name).sort();
}

/** The piece of a stretch reached after `metres`. */
function pieceAt(pieces, metres) {
  let left = Math.max(metres, 0);
  for (const piece of pieces) {
    const span = Math.abs(piece.end - piece.start);
    if (left <= span) return piece;
    left -= span;
  }
  return pieces[pieces.length - 1];
}

/** Which way along a working a node lies: +1 towards growing offsets (its `to`), −1 towards its `from`, null. */
function sideOf(line, node) {
  if (!line || typeof node !== 'string') return null;
  if (node === line.to) return 1;
  if (node === line.from) return -1;
  return null;
}

/**
 * A position at a node, written on the working of the target when that working meets there: (w-19, 0) and
 * (w-12, length) are one point at their shared node, and the glide then runs along the target's working only.
 */
function onWorkingOf(layout, position, target) {
  const line = layout.workings.get(position.working);
  const other = layout.workings.get(target.working);
  if (!line || !other || line === other) return position;
  const node = position.offsetM <= AT_NODE_M ? line.from : (position.offsetM >= line.lengthM - AT_NODE_M ? line.to : null);
  if (node === null) return position;
  if (node === other.from) return {...position, working: other.name, offsetM: 0};
  if (node === other.to) return {...position, working: other.name, offsetM: other.lengthM};
  return position;
}

// ---- the figure of a person ------------------------------------------------------------------

/** A box with a colour, in the figure's frame (x forward, y up, metres). */
function box(size, at, colour) {
  const geometry = new THREE.BoxGeometry(...size).toNonIndexed();
  geometry.translate(...at);
  return painted(geometry, colour);
}

function painted(geometry, colour) {
  const flat = geometry.index ? geometry.toNonIndexed() : geometry;
  flat.deleteAttribute('uv');
  const c = new THREE.Color(colour);
  const colours = new Float32Array(flat.attributes.position.count * 3);
  for (let i = 0; i < colours.length; i += 3) {
    colours[i] = c.r;
    colours[i + 1] = c.g;
    colours[i + 2] = c.b;
  }
  flat.setAttribute('color', new THREE.BufferAttribute(colours, 3));
  return flat;
}

/** The low-poly miner: about 180 triangles, the lens of the cap lamp apart (it is drawn unlit). */
function figureGeometry() {
  const overalls = '#3B444E';
  const band = '#DAD5CB';
  const helmet = '#E6E1D7';
  const dark = '#1F2124';
  const parts = [];
  for (const side of [-1, 1]) {
    parts.push(box([0.22, 0.8, 0.18], [0, 0.5, side * 0.11], overalls));
    parts.push(box([0.3, 0.12, 0.2], [0.04, 0.06, side * 0.11], dark));
    parts.push(box([0.23, 0.05, 0.19], [0, 0.36, side * 0.11], band));
    parts.push(box([0.15, 0.56, 0.13], [0.02, 1.13, side * 0.31], overalls));
    parts.push(box([0.16, 0.05, 0.14], [0.02, 1.05, side * 0.31], band));
  }
  parts.push(box([0.3, 0.6, 0.48], [0, 1.15, 0], overalls));
  parts.push(box([0.31, 0.07, 0.49], [0, 1.02, 0], band));
  parts.push(box([0.06, 0.5, 0.06], [0.155, 1.18, 0.12], band));
  parts.push(box([0.06, 0.5, 0.06], [0.155, 1.18, -0.12], band));
  parts.push(box([0.09, 0.13, 0.17], [-0.19, 0.98, 0], dark));
  const head = new THREE.SphereGeometry(0.12, 6, 4);
  head.translate(0, 1.55, 0);
  parts.push(painted(head, '#9C8270'));
  const shell = new THREE.SphereGeometry(0.165, 8, 3, 0, Math.PI * 2, 0, Math.PI / 2);
  shell.translate(0, 1.6, 0);
  parts.push(painted(shell, helmet));
  const brim = new THREE.CylinderGeometry(0.205, 0.205, 0.025, 8);
  brim.translate(0.02, 1.6, 0);
  parts.push(painted(brim, helmet));
  const body = mergeGeometries(parts, false);
  parts.forEach((part) => part.dispose());
  body.computeVertexNormals();
  const lens = new THREE.BoxGeometry(0.06, 0.07, 0.09);
  lens.translate(0.175, 1.68, 0);
  lens.deleteAttribute('uv');
  return {body, lens};
}

/**
 * The miner of miner.glb (assets/README.md: 1.8 m, feet at the origin, facing +X): every mesh painted with its
 * material's colour into one body, the cap lamp (`miner_lamp`) apart as the lens. Throws when it cannot be read.
 */
async function readFigure(url) {
  const {GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js');
  return new GLTFLoader().loadAsync(url);
}

function mergedFigure(gltf) {
  gltf.scene.updateMatrixWorld(true);
  const body = [];
  const lens = [];
  gltf.scene.traverse((object) => {
    if (!object.isMesh) return;
    const source = Array.isArray(object.material) ? object.material[0] : object.material;
    let geometry = object.geometry.clone();
    geometry.applyMatrix4(object.matrixWorld);
    if (geometry.index) geometry = geometry.toNonIndexed();
    for (const name of Object.keys(geometry.attributes)) if (name !== 'position' && name !== 'normal') geometry.deleteAttribute(name);
    if (!geometry.attributes.normal) geometry.computeVertexNormals();
    const lamp = /lamp/.test(object.name) || /lamp/.test(source && source.name ? source.name : '');
    if (lamp) {
      lens.push(geometry);
      return;
    }
    // The colour of the material (linear, as the loader gives it) into the vertices.
    const c = source && source.color ? source.color : new THREE.Color(1, 1, 1);
    const colours = new Float32Array(geometry.attributes.position.count * 3);
    for (let i = 0; i < colours.length; i += 3) {
      colours[i] = c.r;
      colours[i + 1] = c.g;
      colours[i + 2] = c.b;
    }
    geometry.setAttribute('color', new THREE.BufferAttribute(colours, 3));
    body.push(geometry);
  });
  gltf.scene.traverse((object) => {
    if (object.geometry) object.geometry.dispose();
    if (object.material) [].concat(object.material).forEach((material) => material.dispose());
  });
  if (body.length === 0 || lens.length === 0) throw new Error('miner.glb: no body or no lamp');
  const merged = {body: mergeGeometries(body, false), lens: mergeGeometries(lens, false)};
  [...body, ...lens].forEach((geometry) => geometry.dispose());
  return merged;
}

const triangleCount = (geometry) => (geometry.index ? geometry.index.count : geometry.attributes.position.count) / 3;

/**
 * @param {Object} options
 * @param {boolean} options.low                    the light quality: Lambert materials
 * @param {Object} options.source                  read when drawing: {layout, k, view, groups, camera, height,
 *                                                 position(name) -> {working, offsetM, facing, moving}, viewDistance(point)}
 * @param {() => boolean} [options.reducedMotion]   no walk cycle when true
 */
export function createActors({low, source, reducedMotion = () => false}) {
  const group = new THREE.Group();
  group.name = 'actors';
  let names = [];                 // the loaders of the attributes; empty: the static symbols of the zones

  // ---- loaders of the model ----------------------------------------------------------------
  const drawn = new Map();        // name -> {working, offsetM, facing} at its last published position
  const glides = new Map();       // name -> {pieces, length, start}

  function machineAt(name, now) {
    const glide = glides.get(name);
    const still = drawn.get(name) || null;
    if (!glide) return still;
    const t = glide.start === null ? 0 : Math.min((now - glide.start) / MACHINE_MS, 1);
    const metres = glide.length * t;
    const at = alongStep(glide.pieces, metres);
    const piece = pieceAt(glide.pieces, metres);
    return {...at, facing: Math.sign(piece.end - piece.start) || (still ? still.facing : 1)};
  }

  // ---- figures of people ----------------------------------------------------------------------
  let shapes = figureGeometry();
  let figureSource = 'primitives';
  const lit = low ? THREE.MeshLambertMaterial : THREE.MeshStandardMaterial;
  const bodyMaterial = new lit(low ? {color: '#ffffff', vertexColors: true}
    : {color: '#ffffff', vertexColors: true, roughness: 0.85, metalness: 0});
  // The cap lamp is not lit by the scene: its colour is its light.
  const lensMaterial = new THREE.MeshBasicMaterial({color: '#ffffff'});
  let capacity = 0;
  let bodies = null;
  let lenses = null;
  const matrix = new THREE.Matrix4();
  const rotation = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const where = new THREE.Vector3();
  const scaleVector = new THREE.Vector3(FIGURE_SCALE, FIGURE_SCALE, FIGURE_SCALE);
  const colour = new THREE.Color();
  const FRESH = {body: '#ffffff', lens: '#FFE3A8'};
  const DIMMED = {body: '#8C9096', lens: '#2A2C2F'};
  let figureInfo = {shown: 0, people: 0, px: 0};
  let figured = new Set();        // keys of the groups whose people are drawn as figures (their markers stand higher)

  function ensure(count) {
    if (count <= capacity && bodies) return;
    capacity = Math.max(count, 8, capacity * 2);
    for (const mesh of [bodies, lenses]) {
      if (!mesh) continue;
      group.remove(mesh);
      mesh.dispose();
    }
    bodies = new THREE.InstancedMesh(shapes.body, bodyMaterial, capacity);
    lenses = new THREE.InstancedMesh(shapes.lens, lensMaterial, capacity);
    for (const mesh of [bodies, lenses]) {
      mesh.frustumCulled = false;
      mesh.matrixAutoUpdate = false;
      mesh.count = 0;
      mesh.visible = false;
      group.add(mesh);
    }
  }

  // ---- the walk cycle of a figure model with a `walk` clip (rig) -------------------------------------------------
  /** {template, walk, idle, strideM, scale, top} of the rigged figure, or null (the merged figure, instanced). */
  let rig = null;
  /** person -> {root, mixer, walk, idle, materials, weight, last, speed} */
  const riggedPeople = new Map();
  let fading = false;
  let lastDraw = null;

  /** A clone of the rigged figure for one person, with its own mixer: the walk at weight 0, the idle pose held. */
  function riggedPerson(name) {
    if (riggedPeople.has(name)) return riggedPeople.get(name);
    const root = cloneSkinned(rig.template);
    const materials = [];
    root.traverse((object) => {
      if (!object.isMesh) return;
      object.frustumCulled = false;
      object.material = [].concat(object.material).map((material) => {
        const own = material.clone();
        // Its own colour, kept: a position that is not fresh multiplies it by the grey of DIMMED.
        own.userData.baseColor = own.color ? own.color.clone() : null;
        materials.push(own);
        return own;
      });
      if (object.material.length === 1) object.material = object.material[0];
    });
    root.matrixAutoUpdate = true;
    const mixer = new THREE.AnimationMixer(root);
    const walk = mixer.clipAction(rig.walk);
    walk.setEffectiveWeight(0);
    walk.play();
    const idle = rig.idle ? mixer.clipAction(rig.idle) : null;
    if (idle) {
      idle.setEffectiveWeight(1);
      idle.timeScale = 0;
      idle.play();
    }
    mixer.update(0);
    const entry = {root, mixer, walk, idle, materials, weight: 0, last: null, speed: 0, rate: 0};
    riggedPeople.set(name, entry);
    group.add(root);
    return entry;
  }

  function dropRigged(name) {
    const entry = riggedPeople.get(name);
    if (!entry) return;
    entry.mixer.stopAllAction();
    entry.mixer.uncacheRoot(entry.root);
    group.remove(entry.root);
    entry.materials.forEach((material) => material.dispose());
    riggedPeople.delete(name);
  }

  /**
   * One frame of a rigged person at `point` (scene metres): the walk while the person moves between two different
   * drawn places, at the rate that makes the stride cover the ground speed; a fade to the idle pose when it stops.
   */
  function animateRigged(entry, moving, dtMs) {
    const p = entry.root.position;
    if (entry.last && dtMs > 0 && dtMs < 250) {
      const metresPerS = (p.distanceTo(entry.last) * 1000) / dtMs;
      // Smoothed over about 120 ms: the frames of a software renderer are uneven.
      const a = 1 - Math.exp(-dtMs / 120);
      entry.speed += (metresPerS - entry.speed) * a;
    } else {
      entry.speed = 0;
    }
    entry.last = entry.last ? entry.last.copy(p) : p.clone();
    const walking = moving && !reducedMotion();
    const goal = walking ? 1 : 0;
    if (reducedMotion()) entry.weight = goal;
    else if (entry.weight !== goal) {
      const stepW = dtMs / FADE_MS;
      entry.weight = goal > entry.weight ? Math.min(entry.weight + stepW, 1) : Math.max(entry.weight - stepW, 0);
    }
    // One stride (strideM of the model, times its scale) per cycle of the clip: the feet keep to the ground. At most
    // rig.maxCycles cycles a second (a faster honest rate looks frantic; above it the feet slide a little).
    const stride = rig.strideM * rig.scale;
    entry.rate = walking && stride > 0 ? Math.min((entry.speed * rig.walk.duration) / stride, rig.maxCycles * rig.walk.duration) : 0;
    entry.walk.timeScale = entry.weight > 0 ? entry.rate : 0;
    entry.walk.setEffectiveWeight(entry.weight);
    if (entry.idle) entry.idle.setEffectiveWeight(1 - entry.weight);
    if (entry.weight > 0 || walking) entry.mixer.update(Math.max(dtMs, 0) / 1000);
    else entry.mixer.update(0);
    return entry.weight > 0 && entry.weight < 1;
  }

  /**
   * Where the people of a group are drawn: each at its drawn place (source.position), and people closer together
   * than SPREAD.close of a figure's height stand apart (SPREAD): name -> {position, at, across}. The published
   * places are never changed; only the figures of one place are set side by side.
   */
  function spreadOf(entry, layout, k) {
    const out = new Map();
    const tall = rig ? rig.top : FIGURE_M * FIGURE_SCALE;
    const close = rig ? tall * SPREAD.close : SIDE_STEP;
    const items = [];
    for (const name of entry.members) {
      const person = source.view.workers[name];
      const position = person && person.at ? source.position(name) : null;
      const at = position ? pointOnWorking(layout, position.working, position.offsetM, k) : null;
      if (at) items.push({name, position, at});
    }
    // Clusters of figures that would stand on one another, in the order of their places along the working.
    items.sort((p, q) => (p.position.working === q.position.working ? p.position.offsetM - q.position.offsetM : (p.name < q.name ? -1 : 1)));
    const clusters = [];
    for (const item of items) {
      const last = clusters[clusters.length - 1];
      const near = last && last.some((other) => Math.hypot(other.at.point[0] - item.at.point[0], other.at.point[2] - item.at.point[2]) < close
        && Math.abs(other.at.point[1] - item.at.point[1]) < tall);
      if (near) last.push(item);
      else clusters.push([item]);
    }
    for (const cluster of clusters) {
      cluster.forEach((item, index) => {
        const t = index - (cluster.length - 1) / 2;
        if (t === 0) {
          out.set(item.name, {position: item.position, at: item.at, across: 0});
          return;
        }
        const sideMax = rig ? SPREAD.sideMax : SIDE_MAX;
        const across = Math.max(-sideMax, Math.min(sideMax, t * (rig ? tall * SPREAD.across : SIDE_STEP)));
        const line = layout.workings.get(item.position.working);
        // A step along the working, kept on it (the ends of the working bound it); on a ramp the floor rises with it.
        const along = rig ? t * tall * SPREAD.along * (line && line.total > 0 ? line.lengthM / line.total : 1) : 0;
        const offsetM = line ? Math.min(Math.max(item.position.offsetM + along, 0), line.lengthM) : item.position.offsetM;
        const at = along ? pointOnWorking(layout, item.position.working, offsetM, k) || item.at : item.at;
        out.set(item.name, {position: item.position, at, across});
      });
    }
    return out;
  }

  return {
    group,

    /** The loaders of new attributes; true when they are drawn from equipment twins. */
    setModel(model) {
      names = machinesOf(model);
      drawn.clear();
      glides.clear();
      return names.length > 0;
    },
    /**
     * The figure of a model instead of the primitives (kept when it cannot be read); true when it was taken.
     * A model with an animation clip `walk` becomes the rigged figure (walk cycle, see the header): `scale` is how
     * many times it is drawn larger (a 1.8 m miner: FIGURE_SCALE; the 5 m worker of the art: 1); the stride of the
     * cycle is the clip's extras.strideM (else the scene's extras.strideM, else 0.8 of the figure's height). Any
     * other model is merged into one body (its `lamp` meshes the lens) and drawn instanced, as miner.glb.
     */
    async loadFigure(url, {scale = FIGURE_SCALE, maxCycles = Infinity} = {}) {
      try {
        const gltf = await readFigure(url);
        const walkClip = (gltf.animations || []).find((clip) => clip.name === 'walk');
        if (walkClip) {
          this.useRig(gltf, {scale, maxCycles, source: url.split('/').pop()});
          return true;
        }
        const next = mergedFigure(gltf);
        for (const mesh of [bodies, lenses]) {
          if (!mesh) continue;
          group.remove(mesh);
          mesh.dispose();
        }
        bodies = null;
        lenses = null;
        capacity = 0;
        shapes.body.dispose();
        shapes.lens.dispose();
        shapes = next;
        figureSource = url.split('/').pop();
        return true;
      } catch (error) {
        return false;
      }
    },
    /**
     * The rigged figure from a loaded glTF ({scene, animations}) with a clip `walk` (and maybe `idle`). Phase II gives
     * models/mine-art/actors/worker.glb through loadFigure; this is the same hook for a model built in memory.
     */
    useRig(gltf, {scale = FIGURE_SCALE, maxCycles = Infinity, source = 'rig'} = {}) {
      const walkClip = (gltf.animations || []).find((clip) => clip.name === 'walk');
      if (!walkClip) throw new Error('useRig: no clip "walk"');
      for (const name of [...riggedPeople.keys()]) dropRigged(name);
      const template = gltf.scene;
      template.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(template);
      const tall = Math.max(box.max.y - box.min.y, 1e-3);
      const declared = [walkClip.userData && walkClip.userData.strideM, template.userData && template.userData.strideM]
        .find((value) => Number.isFinite(value) && value > 0);
      rig = {template, walk: walkClip, idle: (gltf.animations || []).find((clip) => clip.name === 'idle') || null,
        strideM: declared || tall * 0.8, strideDeclared: Boolean(declared), scale, top: tall * scale, maxCycles, merged: figureSource};
      figureSource = source;
      if (bodies) bodies.visible = lenses.visible = false;
    },
    /** Back to the merged figure (instanced, no walk cycle): the rigged one is dropped. */
    clearRig() {
      if (!rig) return;
      for (const name of [...riggedPeople.keys()]) dropRigged(name);
      figureSource = rig.merged;
      rig = null;
    },
    /** The rigged figure is in use (a model with a clip `walk`). */
    get rigged() {
      return Boolean(rig);
    },
    /** True when the loaders are the machines of the model (equipment twins), not the symbols of the zones. */
    get equipment() {
      return names.length > 0;
    },

    /**
     * New published positions of the loaders: a glide from the position drawn now to the published one when
     * `allow` (honest motion) and the two are neighbours on the workings, else a jump. True when a loader moved.
     */
    update(view, layout, allow, now = performance.now()) {
      if (names.length === 0 || !layout) return false;
      const seen = new Set();
      let changed = false;
      for (const name of names) {
        const machine = view.equipment[name];
        if (!machine || !machine.at || !view.hasSnapshot) continue;
        seen.add(name);
        const line = layout.workings.get(machine.at);
        const current = machineAt(name, now);
        const before = drawn.get(name);
        glides.delete(name);
        let facing = sideOf(line, machine.toward);
        const moved = current && (current.working !== machine.at || Math.abs(current.offsetM - machine.offsetM) > 0.05);
        if (moved && allow) {
          const target = {working: machine.at, offsetM: machine.offsetM};
          const pieces = stepBetween(layout, onWorkingOf(layout, current, target), target);
          const length = pieces ? stepLength(pieces) : Infinity;
          if (pieces && length <= MAX_STEP_M && length > 0.05) {
            glides.set(name, {pieces, length, start: null});
            const last = pieces[pieces.length - 1];
            if (facing === null) facing = Math.sign(last.end - last.start) || null;
          }
        }
        if (facing === null) facing = current && current.working === machine.at ? current.facing : 1;
        const next = {working: machine.at, offsetM: machine.offsetM, facing};
        if (!before || before.working !== next.working || before.offsetM !== next.offsetM || before.facing !== next.facing) changed = true;
        drawn.set(name, next);
      }
      for (const name of [...drawn.keys()]) {
        if (seen.has(name)) continue;
        drawn.delete(name);
        glides.delete(name);
        changed = true;
      }
      return changed || glides.size > 0;
    },

    /** Every glide ends at once at the published position (old data, a failed read, a pause). True if one ran. */
    snap() {
      if (glides.size === 0) return false;
      glides.clear();
      return true;
    },

    /** Advance the glides: `moved` when the loaders must be placed again, `active` while one still runs. */
    step(now) {
      if (glides.size === 0) return {moved: false, active: false};
      for (const [name, glide] of glides) {
        if (glide.start === null) glide.start = now;
        if (now - glide.start >= MACHINE_MS) glides.delete(name);
      }
      return {moved: true, active: glides.size > 0};
    },

    /** Where each loader is drawn now, as the places of the scene: name -> {working, offsetM, facing, span}. */
    places(now = performance.now()) {
      const out = new Map();
      for (const name of drawn.keys()) {
        const at = machineAt(name, now);
        if (!at) continue;
        out.set(name, {working: at.working, offsetM: at.offsetM, facing: at.facing, span: [at.offsetM - 6, at.offsetM + 6]});
      }
      return out;
    },

    /** The look of each loader from its published state, and the machines with a load and the selected one. */
    looks(view) {
      const out = new Map();
      for (const name of names) {
        const machine = view.equipment[name];
        out.set(name, view.hasSnapshot && machine && LOOKS.has(machine.state) ? machine.state : 'unknown');
      }
      return out;
    },
    loadedOf(view) {
      return names.filter((name) => view.hasSnapshot && view.equipment[name] && view.equipment[name].loaded === true);
    },
    selectedOf(view) {
      return names.find((name) => view.equipment[name] && view.equipment[name].thingId === view.selected) || null;
    },

    /** How high the marker of a group stands over the floor: over the helmets when its people are drawn. */
    liftOf(group) {
      return figured.has(group.key) ? (rig ? rig.top : FIGURE_TOP) + OVER_HELMET : MARKER_LIFT;
    },
    /** True when the people of a group are drawn as figures (the last frame). */
    figured(group) {
      return figured.has(group.key);
    },
    /** Where the pin of a marker starts over the floor: on the helmet of a figure, else on the floor. */
    pinFrom(group) {
      return figured.has(group.key) ? (rig ? rig.top : FIGURE_TOP) : 0.3;
    },
    /** How tall the largest figure was drawn in the last frame (screen pixels; one scale for all in art mode). */
    get figurePx() {
      return figureInfo.px || 0;
    },
    /** True while a walk cycle fades in or out (frames are needed although nobody moves). */
    get animating() {
      return fading;
    },

    /**
     * Per frame: the figures of the people that are close enough, at their drawn positions. True when the set of
     * groups drawn as figures changed: their markers must be placed again.
     */
    drawFigures(now = performance.now()) {
      const {layout, k, view, groups, camera, height} = source;
      const before = [...figured].join();
      figured = new Set();
      const dtMs = lastDraw === null ? 0 : Math.min(Math.max(now - lastDraw, 0), 250);
      lastDraw = now;
      fading = false;
      if (!layout || !view || !groups) {
        if (bodies) bodies.visible = lenses.visible = false;
        for (const name of [...riggedPeople.keys()]) dropRigged(name);
        figureInfo = {shown: 0, people: 0, px: 0};
        return before !== '';
      }
      const people = groups.reduce((sum, entry) => sum + entry.members.length, 0);
      if (!rig) ensure(people);
      const perPixel = 2 * Math.tan((camera.fov * DEG) / 2) / Math.max(height, 1);
      const tall = rig ? rig.top : FIGURE_M * FIGURE_SCALE;
      let n = 0;
      let largest = 0;
      const placed = {};
      const walks = {};
      const feet = {};
      const shown = new Set();
      for (const entry of groups) {
        const spread = spreadOf(entry, layout, k);
        entry.members.forEach((name) => {
          const person = view.workers[name];
          const placedAt = spread.get(name);
          if (!person || !placedAt) return;
          const {position, at, across} = placedAt;
          const distance = source.viewDistance(at.point);
          const px = tall / Math.max(distance * perPixel, 1e-6);
          largest = Math.max(largest, px);
          if (px < (source.figurePx || FIGURE_PX)) return;
          // Facing follows the travel along the path (walk.js); standing, the way last walked on this working.
          const facing = position.facing || 1;
          const side = [-at.dir[2], at.dir[0]];
          const sideLength = Math.hypot(side[0], side[1]) || 1;
          where.set(at.point[0] + (side[0] / sideLength) * across, at.point[1] + 0.05, at.point[2] + (side[1] / sideLength) * across);
          rotation.setFromAxisAngle(up, Math.atan2(-at.dir[2] * facing, at.dir[0] * facing));
          const look = !person.posQuality || person.posQuality === 'fresh' ? FRESH : DIMMED;
          if (rig) {
            const one = riggedPerson(name);
            one.root.position.copy(where);
            one.root.quaternion.copy(rotation);
            one.root.scale.setScalar(rig.scale);
            one.root.visible = true;
            for (const material of one.materials) {
              if (material.userData.baseColor) material.color.copy(material.userData.baseColor).multiply(colour.set(look.body));
            }
            if (animateRigged(one, Boolean(position.moving), dtMs)) fading = true;
            walks[name] = [Math.round(one.weight * 1000) / 1000, Math.round(one.walk.timeScale * 1000) / 1000, Math.round(one.speed * 100) / 100];
            shown.add(name);
          } else {
            matrix.compose(where, rotation, scaleVector);
            bodies.setMatrixAt(n, matrix);
            lenses.setMatrixAt(n, matrix);
            bodies.setColorAt(n, colour.set(look.body));
            lenses.setColorAt(n, colour.set(look.lens));
          }
          figured.add(entry.key);
          placed[name] = [position.working, Math.round(position.offsetM * 100) / 100, facing];
          feet[name] = [where.x, where.y, where.z].map((v) => Math.round(v * 1000) / 1000);
          n += 1;
        });
      }
      if (rig) {
        for (const [name, one] of riggedPeople) {
          if (shown.has(name)) continue;
          if (!view.workers[name] || !view.workers[name].at) dropRigged(name);
          else {
            one.root.visible = false;
            one.last = null;
          }
        }
      } else {
        for (const mesh of [bodies, lenses]) {
          mesh.count = n;
          mesh.visible = n > 0;
          mesh.instanceMatrix.needsUpdate = true;
          if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
        }
      }
      figureInfo = {shown: n, people, px: Math.round(largest * 10) / 10, groups: [...figured].sort(), at: placed,
        // The walk cycle per person drawn: [weight of the walk, playback rate of the clip, ground speed scene m/s].
        walks: rig ? walks : null, feet};
      return [...figured].join() !== before;
    },

    /** For tests: the loaders drawn now and the figures of the last frame. */
    info(now = performance.now()) {
      return {
        equipment: names.length > 0,
        machines: names.filter((name) => drawn.has(name)).map((name) => {
          const at = machineAt(name, now);
          return {name, working: at.working, offsetM: Math.round(at.offsetM * 100) / 100, facing: at.facing, gliding: glides.has(name)};
        }),
        glides: glides.size,
        figures: {...figureInfo, threshold: source.figurePx || FIGURE_PX, scale: rig ? rig.scale : FIGURE_SCALE,
          triangles: rig ? null : triangleCount(shapes.body) + triangleCount(shapes.lens), source: figureSource,
          rig: rig ? {strideM: rig.strideM, strideDeclared: rig.strideDeclared, walkS: rig.walk.duration, idle: Boolean(rig.idle), top: rig.top,
            maxCycles: rig.maxCycles} : null},
      };
    },

    dispose() {
      for (const name of [...riggedPeople.keys()]) dropRigged(name);
      for (const mesh of [bodies, lenses]) if (mesh) mesh.dispose();
      shapes.body.dispose();
      shapes.lens.dispose();
      bodyMaterial.dispose();
      lensMaterial.dispose();
    },
  };
}
