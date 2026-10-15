// The surroundings of the stone model: the rock massif the horizon slabs are cut
// from, the light, the depth, the background and the lamps of the workings.
// Decoration only — nothing here is a state, a position or a figure of the model,
// and the gizmo says so («массив — оформление»).
//
// The massif is a cutaway: of the rock volume around the stacked slabs only the
// faces away from the camera are drawn — the two far vertical walls and the floor
// — so the rock is always behind the mine and never in front of a person, a route,
// a barricade or a label. Which two walls are far is picked again before every
// frame from the camera position (no frame of its own: it rides on the frames the
// camera already asks for). The walls and the floor are sawn rock with strata and
// thin copper ore veins (textures.js), lit by baked shading (vertex colours: lighter
// towards the cut top, darker at the foot and in the corners) and a pale cut edge.
//
// The light is a warm work light as the key, a cool hemisphere sky over a dark
// ground and a cool rim from behind the model (following the camera). Depth comes
// from the baked shading of the massif, not from a fog (a fog costs on every pixel
// of a software renderer); the high quality adds the scene's own background, a
// cool graphite with a soft vignette.
//
// Details of the workings, per slab (in its local frame): a pale chipped lip along
// every cut edge of the top face, under the frames of the states. The foot of the
// channel walls and the underside of a slab are darkened in their own textures
// (baked ambient occlusion), the pale floors carry faint wheel ruts (textures.js).
// Lamps: small fixtures every LAMP_EVERY metres along the horizontal workings, on
// the side away from the sensors and clear of the ends, junctions and the middle
// (where a barricade stands), each a dark post with a lit head: two draw calls
// for all of them, whatever the size of the mine. No light source of its own in either quality (the high
// quality keeps the scene's three exit lamps), no shadows, no post-processing:
// the light quality must stay fast on a software renderer.

import * as THREE from 'three';
import * as geo from '../geometry.js';
import {inside} from './carve.js';
import {DIMS, levelY, sceneBounds} from './layout.js';
import {ENV} from './palette.js';
import {merge, ribbon} from './shapes.js';
import {backdrop, MASSIF_TILE} from './textures.js';

/** Sizes of the massif in scene metres: room around the model, thickness of the walls, depth of the floor. */
const MASSIF = {margin: 22, wall: 6, floorDepth: 16, above: 3, dip: 0.07};
/** Baked shading of the massif (vertex colours multiply the rock texture). */
const SHADE = {foot: 0.36, top: 0.86, corner: 0.7, cutTop: 1.75, cutEnd: 1.2, floor: 0.7, edge: 1.45, plinthTop: 1, plinthFoot: 0.55};
/** Lamps along the horizontal workings: spacing, and how far from ends, junctions, the middle and sensors they keep. */
const LAMP_EVERY = 34;
const LAMP_CLEAR = {end: 9, node: 9, middle: 9, sensor: 6};

/**
 * @param {THREE.Scene} scene
 * @param {Object} options
 * @param {boolean} options.low          the light quality
 * @param {Object} options.textures      textures.js
 */
export function createEnvironment(scene, {low, textures}) {
  // ---- light, background ------------------------------------------------------------------
  const hemi = new THREE.HemisphereLight(ENV.sky, ENV.ground, low ? 1.4 : 1.15);
  const key = new THREE.DirectionalLight(ENV.key, low ? 2.15 : 2.0);
  key.position.set(420, 900, 520);
  // The rim: a cool light from behind the model, wherever the camera is (update()).
  const fill = new THREE.DirectionalLight(ENV.rim, 0.5);
  fill.position.set(-700, 300, -300);
  scene.add(hemi, key, fill);
  const baseHemi = hemi.intensity;
  // A fog costs a little on every pixel of every lit material, measurably on a software renderer: no fog. The depth
  // is in the baked shading of the massif (darker towards its foot and corners) and the vignette of the high quality;
  // the light quality clears to the tone of the background.
  scene.fog = null;
  const vignette = low ? null : backdrop();
  scene.background = low ? new THREE.Color(ENV.back) : vignette;

  // ---- materials of the surroundings ------------------------------------------------------
  const rock = new THREE.MeshBasicMaterial({map: textures.massif, vertexColors: true});
  const detail = new THREE.MeshBasicMaterial({map: textures.detail, transparent: true, depthWrite: false,
    polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1});

  const group = new THREE.Group();
  group.name = 'environment';
  scene.add(group);
  const walls = {minX: null, maxX: null, minZ: null, maxZ: null};
  let floor = null;
  let box = null;
  let layout = null;
  let lampSpots = [];               // {level, x, z, side: [x, z]} local plan points of the lamps
  let lampMeshes = [];
  const camera = new THREE.Vector3();

  // ---- the massif -------------------------------------------------------------------------

  function clearMassif() {
    for (const name of Object.keys(walls)) {
      if (walls[name]) {
        group.remove(walls[name]);
        walls[name].geometry.dispose();
        walls[name] = null;
      }
    }
    if (floor) {
      group.remove(floor);
      floor.geometry.dispose();
      floor = null;
    }
  }

  /** The rock box around the model for a vertical factor: plan rectangle, floor and top. */
  function boxFor(k) {
    const bounds = sceneBounds(layout, k);
    const lowest = layout.levels[layout.levels.length - 1];
    const upper = layout.levels[0];
    const m = MASSIF.margin;
    const b = {minX: bounds.minX - m, maxX: bounds.maxX + m, minZ: bounds.minZ - m, maxZ: bounds.maxZ + m,
      floorY: levelY(layout, lowest, k) + DIMS.depth - DIMS.thickness - 0.85,
      topY: levelY(layout, upper, k) + DIMS.depth + MASSIF.above};
    // The lowest slab stands on the floor: the floor under it is never seen and is not drawn.
    const foot = lowest.box;
    b.hole = {minX: foot.minX + 0.5, maxX: foot.maxX - 0.5, minZ: foot.minZ + 0.5, maxZ: foot.maxZ - 0.5};
    b.cx = (b.minX + b.maxX) / 2;
    b.cz = (b.minZ + b.maxZ) / 2;
    b.bottomY = b.floorY - MASSIF.floorDepth;
    return b;
  }

  /** Builds triangles with uv and a grey shade per vertex. */
  function mesher() {
    const position = [];
    const uv = [];
    const color = [];
    const api = {
      vertex(p, t, shade) {
        position.push(p[0], p[1], p[2]);
        uv.push(t[0], t[1]);
        color.push(shade, shade, shade);
      },
      /** a-b-c-d counter-clockwise seen from the front. */
      quad(a, b, c, d, uvOf, shadeOf) {
        for (const p of [a, b, c, a, c, d]) api.vertex(p, uvOf(p), shadeOf(p));
      },
      build() {
        if (position.length === 0) return null;
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(position, 3));
        geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
        geometry.setAttribute('color', new THREE.Float32BufferAttribute(color, 3));
        return geometry;
      },
    };
    return api;
  }

  /**
   * One far wall: a slab of rock `MASSIF.wall` thick standing on the outer edge of the box, its inner face towards
   * the model (subdivided for the baked shading), its sawn top and ends, and a strip of floor along its foot that
   * darkens towards the wall. `axis` x: the wall stands at x = at, its face looking along `inward`; z likewise.
   */
  function wallGeometry(b, axis, at, inward) {
    const t = MASSIF.wall;
    const [tu, tv] = MASSIF_TILE;
    const along = axis === 'x' ? [b.minZ - t, b.maxZ + t] : [b.minX, b.maxX];
    // A point of the wall from (along, y, depth from the inner face outwards; negative is in front of it).
    const P = (s, y, depth = 0) => (axis === 'x' ? [at - inward * depth, y, s] : [s, y, at - inward * depth]);
    const sOf = (p) => (axis === 'x' ? p[2] : p[0]);
    const normal = axis === 'x' ? [inward, 0, 0] : [0, 0, inward];
    const uvFace = (p) => [sOf(p) / tu, (p[1] + sOf(p) * MASSIF.dip) / tv];
    const uvTop = (p) => [p[0] / tu, p[2] / tu];
    const height = b.topY - b.floorY;
    const corners = axis === 'x' ? [b.minZ, b.maxZ] : [b.minX, b.maxX];
    const faceShade = (p) => {
      const h = Math.min(Math.max((p[1] - b.floorY) / height, 0), 1);
      const lift = SHADE.foot + (SHADE.top - SHADE.foot) * h ** 0.6;
      const s = sOf(p);
      const corner = Math.min(Math.abs(s - corners[0]), Math.abs(s - corners[1]));
      return lift * (1 - (1 - SHADE.corner) * Math.exp(-Math.max(corner, 0) / 45));
    };
    const m = mesher();
    // Few large triangles: the shading is a slow gradient, and a software renderer pays for every triangle it sets up.
    const nx = 5;
    const ny = 3;
    const ys = Array.from({length: ny + 1}, (_, j) => b.bottomY + ((b.topY - b.bottomY) * j) / ny);
    // The floor line belongs to the grid, so the foot darkens exactly where the wall meets the floor.
    ys.push(b.floorY);
    ys.sort((p, q) => p - q);
    const cuts = Array.from({length: nx + 1}, (_, i) => along[0] + ((along[1] - along[0]) * i) / nx);
    for (let i = 0; i < nx; i += 1) {
      for (let j = 0; j < ys.length - 1; j += 1) {
        facing(m, [P(cuts[i], ys[j]), P(cuts[i + 1], ys[j]), P(cuts[i + 1], ys[j + 1]), P(cuts[i], ys[j + 1])], normal, uvFace, faceShade);
      }
    }
    // The sawn top: the pale cut edge of the massif.
    facing(m, [P(along[0], b.topY, t), P(along[1], b.topY, t), P(along[1], b.topY, 0), P(along[0], b.topY, 0)], [0, 1, 0], uvTop,
      () => SHADE.cutTop);
    // The ends, sawn too.
    const uvEnd = (p) => [(axis === 'x' ? p[0] : p[2]) / tu, p[1] / tv];
    for (const [s, sign] of [[along[0], -1], [along[1], 1]]) {
      const n = axis === 'x' ? [0, 0, sign] : [sign, 0, 0];
      facing(m, [P(s, b.bottomY, 0), P(s, b.bottomY, t), P(s, b.topY, t), P(s, b.topY, 0)], n, uvEnd, () => SHADE.cutEnd);
    }
    return m.build();
  }

  /** A quad wound so that its front faces along `n` (the rock is drawn one-sided). */
  function facing(m, [a, b, c, d], n, uvOf, shadeOf) {
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const cross = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    if (cross[0] * n[0] + cross[1] * n[1] + cross[2] * n[2] >= 0) m.quad(a, b, c, d, uvOf, shadeOf);
    else m.quad(a, d, c, b, uvOf, shadeOf);
  }

  /** The floor of the massif: its top under the whole box, a pale cut edge round it, and the sawn sides below. */
  function floorGeometry(b) {
    const t = MASSIF.wall;
    const [x0, x1, z0, z1] = [b.minX - t, b.maxX + t, b.minZ - t, b.maxZ + t];
    const [tu, tv] = MASSIF_TILE;
    const y = b.floorY;
    const up = [0, 1, 0];
    const m = mesher();
    const uvTop = (p) => [p[0] / tu, p[2] / tu];
    const edge = 2.2;
    // The top round the foot of the lowest slab (a software renderer pays for every pixel it rasterises, seen or not).
    const [a0, a1, c0, c1] = [x0 + edge, x1 - edge, z0 + edge, z1 - edge];
    const hole = b.hole;
    const top = (p0, p1, q0, q1) => {
      if (p1 > p0 && q1 > q0) facing(m, [[p0, y, q0], [p1, y, q0], [p1, y, q1], [p0, y, q1]], up, uvTop, () => SHADE.floor);
    };
    top(a0, a1, c0, hole.minZ);
    top(a0, a1, hole.maxZ, c1);
    top(a0, hole.minX, hole.minZ, hole.maxZ);
    top(hole.maxX, a1, hole.minZ, hole.maxZ);
    // The cut edge: a pale band round the top.
    const ring = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
    const inner = [[x0 + edge, z0 + edge], [x1 - edge, z0 + edge], [x1 - edge, z1 - edge], [x0 + edge, z1 - edge]];
    for (let i = 0; i < 4; i += 1) {
      const j = (i + 1) % 4;
      facing(m, [[ring[i][0], y, ring[i][1]], [ring[j][0], y, ring[j][1]], [inner[j][0], y, inner[j][1]], [inner[i][0], y, inner[i][1]]], up,
        uvTop, () => SHADE.edge);
    }
    // Sawn sides, facing out: strata of the massif; darker towards the bottom.
    const sides = [[[x0, z1], [x1, z1], [0, 0, 1]], [[x1, z1], [x1, z0], [1, 0, 0]], [[x1, z0], [x0, z0], [0, 0, -1]], [[x0, z0], [x0, z1], [-1, 0, 0]]];
    for (const [a, c, n] of sides) {
      const uvOf = (p) => [(p[0] + p[2]) / tu, (p[1] + (p[0] + p[2]) * MASSIF.dip) / tv];
      const shadeOf = (p) => (p[1] > b.bottomY + 0.1 ? SHADE.plinthTop : SHADE.plinthFoot);
      facing(m, [[a[0], b.bottomY, a[1]], [c[0], b.bottomY, c[1]], [c[0], y, c[1]], [a[0], y, a[1]]], n, uvOf, shadeOf);
    }
    return m.build();
  }

  function buildMassif(k) {
    clearMassif();
    if (!layout) return;
    box = boxFor(k);
    const meshOf = (geometry) => {
      const mesh = new THREE.Mesh(geometry, rock);
      mesh.matrixAutoUpdate = false;
      // Drawn after the model (opaque, larger order): the rock behind the slabs is rejected by depth, not shaded.
      mesh.renderOrder = 10;
      group.add(mesh);
      return mesh;
    };
    walls.minX = meshOf(wallGeometry(box, 'x', box.minX, 1));
    walls.maxX = meshOf(wallGeometry(box, 'x', box.maxX, -1));
    walls.minZ = meshOf(wallGeometry(box, 'z', box.minZ, 1));
    walls.maxZ = meshOf(wallGeometry(box, 'z', box.maxZ, -1));
    floor = meshOf(floorGeometry(box));
    pick();
  }

  /**
   * Show the far walls for the camera where it is: per axis the wall on the side of the box opposite the camera,
   * so the camera and every object inside the box are on its inner side and it never covers them; the floor while
   * the camera is above it.
   */
  function pick() {
    if (!box || !walls.minX) return;
    walls.minX.visible = camera.x >= box.cx;
    walls.maxX.visible = !walls.minX.visible;
    walls.minZ.visible = camera.z >= box.cz;
    walls.maxZ.visible = !walls.minZ.visible;
    floor.visible = camera.y > box.floorY + 0.5;
  }

  // ---- details of the workings (per slab, local frame) --------------------------------------

  /** The v of a lip ribbon turned so that v = 1 lies on the cut (`cutAt` is the ribbon side, 0 or 1, at the cut). */
  function lipUv(geometry, cutAt) {
    if (!geometry) return null;
    const uv = geometry.attributes.uv;
    for (let i = 0; i < uv.count; i += 1) uv.setY(i, cutAt === 1 ? uv.getY(i) : 1 - uv.getY(i));
    uv.needsUpdate = true;
    return geometry;
  }

  /**
   * The details of one slab: the lips of its cuts, one merged geometry in the frame of the slab (a thin transparent
   * band). `carved` is the outline of its stone (shapes.carveSlab).
   */
  function levelDetail(currentLayout, level, carved) {
    void level;
    if (!currentLayout || !carved) return [];
    const d = DIMS.depth;
    const stone = (p) => carved.shapes.some((shape) => inside(p, shape.outer) && !shape.holes.some((hole) => inside(p, hole)));
    const parts = [];
    for (const loop of carved.loops) {
      if (loop.length < 3) continue;
      // Which side of the loop is stone: probe beside its longest segment.
      let best = 0;
      let bestLength = 0;
      for (let i = 0; i < loop.length; i += 1) {
        const a = loop[i];
        const b = loop[(i + 1) % loop.length];
        const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (length > bestLength) {
          bestLength = length;
          best = i;
        }
      }
      const a = loop[best];
      const b = loop[(best + 1) % loop.length];
      const left = [-(b[1] - a[1]) / bestLength, (b[0] - a[0]) / bestLength];
      const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      const s = stone([mid[0] + left[0] * 0.5, mid[1] + left[1] * 0.5]) ? 1 : -1;
      // The lip: a pale chipped band on the stone along every cut, the outer edges of the slab included.
      const lipWidth = 1.7;
      parts.push(lipUv(ribbon(loop, lipWidth, d + 0.02, {closed: true, offset: (s * lipWidth) / 2, period: 24}), s > 0 ? 0 : 1));
    }
    const geometry = merge(parts);
    if (!geometry) return [];
    const mesh = new THREE.Mesh(geometry, detail);
    mesh.name = 'detail';
    mesh.renderOrder = 1;
    mesh.matrixAutoUpdate = false;
    return [mesh];
  }

  // ---- lamps ---------------------------------------------------------------------------

  /** Places of the lamps of a topology, local plan points per level; attributes only (sensors from the model). */
  function lampPlaces(model) {
    const spots = [];
    const sensors = new Map();
    for (const sensor of model && model.byKind ? model.byKind.sensor || [] : []) {
      const attrs = sensor.attrs || {};
      if (typeof attrs.working !== 'string' || !Number.isFinite(attrs.offset_m)) continue;
      if (!sensors.has(attrs.working)) sensors.set(attrs.working, []);
      sensors.get(attrs.working).push(attrs.offset_m);
    }
    for (const level of layout.levels) {
      const nodes = [...layout.nodes.entries()].filter(([name]) => layout.nodeLevel.get(name) === level.name)
        .map(([, point]) => layout.toPlan(point));
      for (const name of level.workings) {
        const line = layout.workings.get(name);
        const cum = geo.cumulative(line.plan.map((p) => [p[0], 0, p[1]]));
        const total = cum[cum.length - 1];
        const avoid = (sensors.get(name) || []).map((offset) => geo.offsetLength(offset, line.lengthM, total));
        const count = Math.floor((total - 2 * LAMP_CLEAR.end) / LAMP_EVERY);
        if (count < 1) continue;
        const start = (total - (count - 1) * LAMP_EVERY) / 2;
        for (let i = 0; i < count; i += 1) {
          const at = start + i * LAMP_EVERY;
          if (Math.abs(at - total / 2) < LAMP_CLEAR.middle) continue;
          if (avoid.some((offset) => Math.abs(offset - at) < LAMP_CLEAR.sensor)) continue;
          const {point, dir} = geo.pointAt(line.plan.map((p) => [p[0], 0, p[1]]), cum, at);
          if (nodes.some((node) => Math.hypot(node[0] - point[0], node[1] - point[2]) < LAMP_CLEAR.node)) continue;
          // The sensors stand on the left of the working's direction: the lamps on the right, against the wall.
          const right = [dir[2], -dir[0]];
          const rl = Math.hypot(right[0], right[1]) || 1;
          spots.push({level, x: point[0], z: point[2], side: [right[0] / rl, right[1] / rl]});
        }
      }
    }
    return spots;
  }

  /**
   * A fixture is a dark post at the foot of the wall with a lit head above it. Each part of all the lamps is one
   * plain merged mesh of a flat colour (the program of the flat marks of the scene: no shader of its own), rebuilt
   * when the slabs spread (a few hundred boxes).
   */
  const LAMP_PARTS = [{size: [0.55, 3.2, 0.55], y: 1.6, colour: ENV.lampPost}, {size: [1.5, 0.75, 1.5], y: 3.4, colour: ENV.lampLens}];
  const lampMaterials = LAMP_PARTS.map((part) => new THREE.MeshBasicMaterial({color: part.colour}));
  const lampTemplates = LAMP_PARTS.map((part) => new THREE.BoxGeometry(...part.size).toNonIndexed().attributes.position.array);

  function clearLamps() {
    for (const mesh of lampMeshes) {
      group.remove(mesh);
      mesh.geometry.dispose();
    }
    lampMeshes = [];
  }

  function buildLamps(model) {
    clearLamps();
    lampSpots = layout ? lampPlaces(model) : [];
  }

  function placeLamps(k) {
    clearLamps();
    if (lampSpots.length === 0) return;
    const offset = DIMS.half - 0.9;
    LAMP_PARTS.forEach((part, j) => {
      const template = lampTemplates[j];
      const position = new Float32Array(template.length * lampSpots.length);
      lampSpots.forEach((spot, index) => {
        const x = spot.x + spot.side[0] * offset;
        const y = levelY(layout, spot.level, k) + part.y;
        const z = spot.z + spot.side[1] * offset;
        const base = index * template.length;
        for (let v = 0; v < template.length; v += 3) {
          position[base + v] = template[v] + x;
          position[base + v + 1] = template[v + 1] + y;
          position[base + v + 2] = template[v + 2] + z;
        }
      });
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(position, 3));
      const mesh = new THREE.Mesh(geometry, lampMaterials[j]);
      mesh.name = 'lamps';
      mesh.matrixAutoUpdate = false;
      mesh.frustumCulled = false;
      group.add(mesh);
      lampMeshes.push(mesh);
    });
  }

  // ---- api ------------------------------------------------------------------------------

  let k = null;

  return {
    group,
    lights: {hemi, key, fill},
    levelDetail,
    /** A new topology (or none): the lamps are placed again; the massif follows at the next fit(). */
    build(nextLayout, model) {
      layout = nextLayout || null;
      buildLamps(model);
      if (!layout) {
        clearMassif();
        box = null;
      } else if (k !== null) {
        buildMassif(k);
        placeLamps(k);
      }
      group.visible = Boolean(layout);
    },
    /** The spread of the slabs changed: the massif is cut again round the stack and the lamps go with their slabs. */
    fit(factor) {
      k = factor;
      if (!layout) return;
      buildMassif(k);
      placeLamps(k);
    },
    /**
     * Before every frame: the far walls for this camera, the rim from behind,
     * and the massif dimmed with the rest of the model while something is selected (the work light of the selection).
     */
    update(view) {
      camera.copy(view.position);
      pick();
      if (box) {
        const dx = camera.x - box.cx;
        const dz = camera.z - box.cz;
        const l = Math.hypot(dx, dz) || 1;
        fill.position.set((-dx / l) * 700, 320, (-dz / l) * 700);
      }
      rock.color.setScalar(Math.min(hemi.intensity / baseHemi, 1));
    },
    /** For tests: which walls are drawn, the box they stand on, the camera they were picked for, the lamps. */
    info() {
      const shown = Object.keys(walls).filter((name) => walls[name] && walls[name].visible);
      const meshes = group.children.filter((mesh) => mesh.visible);
      const triangles = meshes.reduce((sum, mesh) => sum + ((mesh.geometry.index ? mesh.geometry.index.count : mesh.geometry.attributes.position.count) / 3) * 1, 0);
      return {
        walls: shown,
        floor: Boolean(floor && floor.visible),
        box: box ? Object.fromEntries(Object.entries(box).filter(([, value]) => Number.isFinite(value)).map(([name, value]) => [name, Math.round(value * 100) / 100])) : null,
        camera: [camera.x, camera.y, camera.z].map((value) => Math.round(value * 100) / 100),
        lamps: lampSpots.length,
        // Draw calls and triangles of the massif and the lamps (the details of the slabs are counted with the slabs).
        calls: meshes.length,
        triangles: Math.round(triangles),
      };
    },
    dispose() {
      clearMassif();
      clearLamps();
      for (const material of [rock, detail, ...lampMaterials]) material.dispose();
      if (vignette) vignette.dispose();
      scene.background = null;
      scene.fog = null;
    },
  };
}
