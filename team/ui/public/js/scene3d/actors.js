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
// Pure three.js and the layout; no DOM, no words.

import * as THREE from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
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
/** People of one group (one stretch of a working) stand side by side across the channel, this far apart (scene m). */
const SIDE_STEP = 2.4;
const SIDE_MAX = 3.6;
/** A marker stands this high over the floor (scene.js), and over the helmet of its figure when one is drawn. */
const MARKER_LIFT = 6;
const FIGURE_TOP = FIGURE_M * FIGURE_SCALE;
const MARKER_OVER_FIGURE = FIGURE_TOP + 3.5;
const DEG = Math.PI / 180;

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
 * @param {Object} options
 * @param {boolean} options.low                    the light quality: Lambert materials
 * @param {Object} options.source                  read when drawing: {layout, k, view, groups, camera, height,
 *                                                 position(name, now), tween(name), tweenMs}
 */
export function createActors({low, source}) {
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
  const shapes = figureGeometry();
  const lit = low ? THREE.MeshLambertMaterial : THREE.MeshStandardMaterial;
  const bodyMaterial = new lit(low ? {color: '#ffffff', vertexColors: true}
    : {color: '#ffffff', vertexColors: true, roughness: 0.85, metalness: 0});
  // The cap lamp is not lit by the scene: its colour is its light.
  const lensMaterial = new THREE.MeshBasicMaterial({color: '#ffffff'});
  let capacity = 0;
  let bodies = null;
  let lenses = null;
  const facings = new Map();      // person -> {working, facing}: the way the person last walked
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

  /** The way a person faces: along the step being glided, else the way last walked on this working, else +1. */
  function facingOf(name, position, now) {
    const tween = source.tween(name);
    if (tween && tween.start !== null) {
      const t = Math.min((now - tween.start) / source.tweenMs, 1);
      const piece = pieceAt(tween.pieces, tween.length * t);
      const sign = Math.sign(piece.end - piece.start);
      if (sign !== 0) {
        facings.set(name, {working: piece.working, facing: sign});
        return sign;
      }
    }
    const last = facings.get(name);
    return last && last.working === position.working ? last.facing : 1;
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
      return figured.has(group.key) ? MARKER_OVER_FIGURE : MARKER_LIFT;
    },
    /** Where the pin of a marker starts over the floor: on the helmet of a figure, else on the floor. */
    pinFrom(group) {
      return figured.has(group.key) ? FIGURE_TOP : 0.3;
    },

    /**
     * Per frame: the figures of the people that are close enough, at their drawn positions. True when the set of
     * groups drawn as figures changed: their markers must be placed again.
     */
    drawFigures(now = performance.now()) {
      const {layout, k, view, groups, camera, height} = source;
      const before = [...figured].join();
      figured = new Set();
      if (!layout || !view || !groups) {
        if (bodies) bodies.visible = lenses.visible = false;
        figureInfo = {shown: 0, people: 0, px: 0};
        return before !== '';
      }
      const people = groups.reduce((sum, entry) => sum + entry.members.length, 0);
      ensure(people);
      const perPixel = 2 * Math.tan((camera.fov * DEG) / 2) / Math.max(height, 1);
      let n = 0;
      let largest = 0;
      const placed = {};
      for (const entry of groups) {
        entry.members.forEach((name, index) => {
          const person = view.workers[name];
          const position = person && person.at ? source.position(name, now) : null;
          if (!position) return;
          const at = pointOnWorking(layout, position.working, position.offsetM, k);
          if (!at) return;
          const distance = camera.position.distanceTo(where.set(at.point[0], at.point[1], at.point[2]));
          const px = (FIGURE_M * FIGURE_SCALE) / Math.max(distance * perPixel, 1e-6);
          largest = Math.max(largest, px);
          if (px < FIGURE_PX) return;
          const facing = facingOf(name, position, now);
          const side = [-at.dir[2], at.dir[0]];
          const sideLength = Math.hypot(side[0], side[1]) || 1;
          const across = Math.max(-SIDE_MAX, Math.min(SIDE_MAX, (index - (entry.members.length - 1) / 2) * SIDE_STEP));
          where.set(at.point[0] + (side[0] / sideLength) * across, at.point[1] + 0.05, at.point[2] + (side[1] / sideLength) * across);
          rotation.setFromAxisAngle(up, Math.atan2(-at.dir[2] * facing, at.dir[0] * facing));
          matrix.compose(where, rotation, scaleVector);
          bodies.setMatrixAt(n, matrix);
          lenses.setMatrixAt(n, matrix);
          const look = !person.posQuality || person.posQuality === 'fresh' ? FRESH : DIMMED;
          bodies.setColorAt(n, colour.set(look.body));
          lenses.setColorAt(n, colour.set(look.lens));
          figured.add(entry.key);
          placed[name] = [position.working, Math.round(position.offsetM * 100) / 100, facing];
          n += 1;
        });
      }
      for (const mesh of [bodies, lenses]) {
        mesh.count = n;
        mesh.visible = n > 0;
        mesh.instanceMatrix.needsUpdate = true;
        if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      }
      figureInfo = {shown: n, people, px: Math.round(largest * 10) / 10, groups: [...figured].sort(), at: placed};
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
        figures: {...figureInfo, threshold: FIGURE_PX, scale: FIGURE_SCALE,
          triangles: shapes.body.attributes.position.count / 3 + shapes.lens.index.count / 3},
      };
    },

    dispose() {
      for (const mesh of [bodies, lenses]) if (mesh) mesh.dispose();
      shapes.body.dispose();
      shapes.lens.dispose();
      bodyMaterial.dispose();
      lensMaterial.dispose();
    },
  };
}
