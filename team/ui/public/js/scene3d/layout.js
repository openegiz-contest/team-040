// Where everything of the 3D model is, from twin attributes only. Pure: no
// three.js, no DOM, and no coordinate, identifier or label of any particular
// mine. Mine points are [x, y, z] in local metres (x east, y north, z up);
// scene points are [X, Y, Z] with X = x − cx, Y = (z − zTop)·k, Z = cy − y, where
// k is the vertical factor of the explode control. A level's own objects are
// built in its local frame: the origin on the floor of its channels.

import * as geo from '../geometry.js';
import {thingByName, thingsOfKind} from '../model.js';

/** Sizes of the model in scene metres. Not to scale, and the scale note says so. */
export const DIMS = {
  depth: 2.6,        // a channel is carved this deep into the top face of its slab
  thickness: 12,     // a slab, from its top face down
  half: 7,           // half the width of a channel
  margin: 26,        // stone around the outermost workings of a level
  zoneReach: 8,      // the frame of a zone stands this far outside its channels
  kCompact: 1,       // vertical factor of the compact stack: elevations to the scale of the plan
  kSpread: 3.4,      // vertical factor of the fully spread stack
  explodeDefault: 0.8,
  drift: 5,          // a real drift for a 10-t loader is about this wide, metres; the channels are drawn 2·half wide
};

/** How many times the channels are drawn wider than a real drift. */
export const WIDTH_FACTOR = (2 * DIMS.half) / DIMS.drift;
/** The loader (10 m) is drawn this many times larger: about as the channels are widened (WIDTH_FACTOR), readable at the overview; a longer machine would leave no free stretch for some zones of the fixtures. */
export const LOADER_SCALE = 2.5;

/** The vertical factor for an explode value in [0, 1]. */
export function verticalFactor(explode) {
  const e = Math.min(Math.max(Number(explode) || 0, 0), 1);
  return DIMS.kCompact + (DIMS.kSpread - DIMS.kCompact) * e;
}

const near = (a, b) => Math.abs(a - b) < 0.01;

/**
 * @typedef {Object} LayoutLevel
 * @property {string|null} name        local name of the level twin, null when the mine has none
 * @property {string|null} thingId
 * @property {string} label
 * @property {number} elevation
 * @property {number} index            0 is the upper level
 * @property {{minX: number, maxX: number, minZ: number, maxZ: number}} box   footprint of the slab, local plan
 * @property {string[]} workings       horizontal workings of the level
 */

/**
 * @typedef {Object} LayoutWorking
 * @property {string} name
 * @property {string} thingId
 * @property {string} kind            working_kind
 * @property {boolean} between        joins two levels
 * @property {string|null} level      the level of a horizontal working
 * @property {number[][]} mine        polyline, mine metres
 * @property {number[][]} plan        polyline as [X, Z]
 * @property {number[]} cum           running length along `mine`
 * @property {number} total
 * @property {number} lengthM         length_m of the attributes (offsets are measured in it)
 * @property {string} from
 * @property {string} to
 */

function levelOfNode(node, levels) {
  if (!node) return null;
  if (typeof node.level === 'string' && levels.some((level) => level.name === node.level)) return node.level;
  const match = levels.find((level) => near(level.elevation, node.z));
  return match ? match.name : null;
}

/**
 * Everything that does not depend on the state: levels, slabs, workings.
 * @param {import('../store.js').Model} model
 * @param {Object} mine attributes of the mine twin
 */
export function buildLayout(model, mine) {
  const nodes = mine && mine.nodes && typeof mine.nodes === 'object' ? mine.nodes : {};
  const nodePoints = new Map();
  for (const name of Object.keys(nodes)) {
    const point = geo.nodePoint(nodes, name);
    if (point) nodePoints.set(name, point);
  }
  let levels = geo.sortLevels(thingsOfKind(model, 'level')).map((level) => ({
    name: level.name, label: level.label, elevation: level.elevation,
  }));
  if (levels.length === 0) {
    levels = [...new Set([...nodePoints.values()].map((point) => point[2]))].sort((a, b) => b - a)
      .map((elevation) => ({name: null, label: '', elevation}));
  }
  if (levels.length === 0) return null;

  const workings = new Map();
  const all = [...nodePoints.values()];
  for (const thing of thingsOfKind(model, 'working')) {
    const mineLine = geo.polyline3(thing.attrs, nodes);
    if (!mineLine) continue;
    const fromLevel = levelOfNode({...nodes[thing.attrs.from], z: mineLine[0][2]}, levels);
    const toLevel = levelOfNode({...nodes[thing.attrs.to], z: mineLine[mineLine.length - 1][2]}, levels);
    const flat = mineLine.every((point) => near(point[2], mineLine[0][2]));
    const between = !(flat && fromLevel !== null && fromLevel === toLevel);
    const cum = geo.cumulative(mineLine);
    all.push(...mineLine);
    workings.set(thing.name, {
      name: thing.name, thingId: thing.thingId, kind: String(thing.attrs.working_kind || ''),
      between, level: between ? null : fromLevel, mine: mineLine, plan: null, cum, total: cum[cum.length - 1],
      lengthM: Number.isFinite(thing.attrs.length_m) && thing.attrs.length_m > 0 ? thing.attrs.length_m : cum[cum.length - 1],
      from: thing.attrs.from, to: thing.attrs.to,
    });
  }
  if (all.length === 0) return null;
  const box = geo.bounds(all);
  const cx = (box.minX + box.maxX) / 2;
  const cy = (box.minY + box.maxY) / 2;
  const zTop = levels[0].elevation;
  const toPlan = (point) => [point[0] - cx, cy - point[1]];
  for (const working of workings.values()) working.plan = working.mine.map(toPlan);

  const layoutLevels = levels.map((level, index) => {
    const own = [...workings.values()].filter((working) => !working.between && working.level === level.name);
    const points = own.flatMap((working) => working.plan);
    for (const [name, point] of nodePoints) {
      if (levelOfNode({...nodes[name], z: point[2]}, levels) === level.name) points.push(toPlan(point));
    }
    const xs = points.map((point) => point[0]);
    const zs = points.map((point) => point[1]);
    const m = DIMS.margin;
    return {
      ...level,
      thingId: level.name ? (thingByName(model, level.name) || {}).thingId || null : null,
      index,
      workings: own.map((working) => working.name),
      box: points.length > 0
        ? {minX: Math.min(...xs) - m, maxX: Math.max(...xs) + m, minZ: Math.min(...zs) - m, maxZ: Math.max(...zs) + m}
        : {minX: -m, maxX: m, minZ: -m, maxZ: m},
    };
  });

  const nodeLevel = new Map();
  for (const [name, point] of nodePoints) nodeLevel.set(name, levelOfNode({...nodes[name], z: point[2]}, levels));

  return {
    levels: layoutLevels, workings, nodes: nodePoints, nodeLevel, cx, cy, zTop,
    zBottom: levels[levels.length - 1].elevation, toPlan,
  };
}

/** The floor of a level's channels in the scene for a vertical factor. */
export function levelY(layout, level, k) {
  return (level.elevation - layout.zTop) * k;
}

/** A mine point in the scene. */
export function toScene(layout, point, k) {
  return [point[0] - layout.cx, (point[2] - layout.zTop) * k, layout.cy - point[1]];
}

/** The polyline of a working in the scene. */
export function sceneLine(layout, working, k) {
  return working.mine.map((point) => toScene(layout, point, k));
}

/**
 * The scene point of a published offset on a working, with the unit direction there.
 * @returns {{point: number[], dir: number[]}|null}
 */
export function pointOnWorking(layout, name, offsetM, k) {
  const working = layout.workings.get(name);
  if (!working || !Number.isFinite(offsetM)) return null;
  return geo.pointAt(sceneLine(layout, working, k), working.cum, geo.offsetLength(offsetM, working.lengthM, working.total));
}

/** The level a scene height belongs to: the nearest floor. */
export function levelAt(layout, y, k) {
  let best = layout.levels[0];
  for (const level of layout.levels) {
    if (Math.abs(levelY(layout, level, k) - y) < Math.abs(levelY(layout, best, k) - y)) best = level;
  }
  return best;
}

/** Bounds of the whole model in the scene for a vertical factor (slabs, inter-level workings, exits). */
export function sceneBounds(layout, k) {
  const box = {minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity, minZ: Infinity, maxZ: -Infinity};
  const add = (x, y, z) => {
    box.minX = Math.min(box.minX, x); box.maxX = Math.max(box.maxX, x);
    box.minY = Math.min(box.minY, y); box.maxY = Math.max(box.maxY, y);
    box.minZ = Math.min(box.minZ, z); box.maxZ = Math.max(box.maxZ, z);
  };
  for (const level of layout.levels) {
    const y = levelY(layout, level, k);
    add(level.box.minX, y + DIMS.depth + 10, level.box.minZ);
    add(level.box.maxX, y + DIMS.depth - DIMS.thickness, level.box.maxZ);
  }
  for (const working of layout.workings.values()) {
    if (!working.between) continue;
    for (const point of sceneLine(layout, working, k)) add(point[0], point[1], point[2]);
  }
  return box;
}

/** Points whose silhouette is the model: slab corners, inter-level workings, exit marks above the upper slab. */
export function silhouette(layout, k) {
  const points = [];
  for (const level of layout.levels) {
    const y = levelY(layout, level, k);
    const b = level.box;
    for (const x of [b.minX, b.maxX]) {
      for (const z of [b.minZ, b.maxZ]) points.push([x, y + DIMS.depth, z], [x, y + DIMS.depth - DIMS.thickness, z]);
    }
  }
  for (const working of layout.workings.values()) {
    if (working.between) points.push(...sceneLine(layout, working, k));
  }
  const upper = layout.levels[0];
  const b = upper.box;
  const top = levelY(layout, upper, k) + DIMS.depth + 18;
  points.push([b.minX, top, b.minZ], [b.maxX, top, b.minZ], [b.minX, top, b.maxZ], [b.maxX, top, b.maxZ]);
  return points;
}

/**
 * Nodes where a zone meets the workings outside it: where a model restriction of entry is drawn.
 * @returns {string[]}
 */
export function zoneEntrances(layout, zoneWorkings) {
  const inside = new Set(zoneWorkings);
  const ends = (working) => [working.from, working.to];
  const zoneNodes = new Set();
  for (const name of inside) {
    const working = layout.workings.get(name);
    if (working) ends(working).forEach((node) => zoneNodes.add(node));
  }
  const entrances = new Set();
  for (const working of layout.workings.values()) {
    if (inside.has(working.name)) continue;
    for (const node of ends(working)) if (zoneNodes.has(node)) entrances.add(node);
  }
  return [...entrances].sort();
}

/**
 * The stretch walked between two published positions of a worker: along one
 * working, or along two workings that share a node. Null when the two
 * positions are not neighbours in the attributes: the marker then jumps.
 * Nothing is searched: no route is computed here.
 * @returns {Array<{working: string, start: number, end: number}>|null} offsets in metres of length_m
 */
export function stepBetween(layout, from, to) {
  const a = layout.workings.get(from.working);
  const b = layout.workings.get(to.working);
  if (!a || !b || !Number.isFinite(from.offsetM) || !Number.isFinite(to.offsetM)) return null;
  if (a === b) return [{working: a.name, start: from.offsetM, end: to.offsetM}];
  const shared = [a.from, a.to].find((node) => node === b.from || node === b.to);
  if (shared === undefined) return null;
  return [
    {working: a.name, start: from.offsetM, end: shared === a.from ? 0 : a.lengthM},
    {working: b.name, start: shared === b.from ? 0 : b.lengthM, end: to.offsetM},
  ];
}

/** Length in metres of a stretch of stepBetween. */
export function stepLength(pieces) {
  return pieces.reduce((sum, piece) => sum + Math.abs(piece.end - piece.start), 0);
}

/** The offset reached after `metres` along a stretch: {working, offsetM}. */
export function alongStep(pieces, metres) {
  let left = Math.max(metres, 0);
  for (const piece of pieces) {
    const span = Math.abs(piece.end - piece.start);
    if (left <= span || piece === pieces[pieces.length - 1]) {
      const t = span > 0 ? Math.min(left / span, 1) : 1;
      return {working: piece.working, offsetM: piece.start + (piece.end - piece.start) * t};
    }
    left -= span;
  }
  return null;
}

/**
 * Places for the loader of each zone, best first: the ends of the zone's horizontal workings
 * that end in a dead end (farthest from every inter-level working first), then their other ends,
 * then their middles. A place whose stretch holds a sensor (attributes) is left out. Static: the
 * same attributes always give the same lists. The scene takes, once per run, the first place
 * that nothing published occupies (people, routes, a closed or pending working) and keeps it.
 * @param {Array<{name: string, workings: string[]}>} zones
 * @param {Object<string, *>} nodesAttr mine.attributes.nodes
 * @param {Map<string, number[]>} sensorOffsets offsets (metres of length_m) of the sensors per working
 * @param {number} length the length of the loader in scene metres
 * @returns {Map<string, Array<{working: string, offsetM: number, facing: 1|-1, span: number[]}>>} facing: +1 looks
 *          towards growing offsets; span: the offsets the loader and the light ahead of it cover
 */
export function loaderPlaces(layout, nodesAttr, zones, sensorOffsets, length) {
  const degree = new Map();
  for (const working of layout.workings.values()) {
    for (const node of [working.from, working.to]) degree.set(node, (degree.get(node) || 0) + 1);
  }
  const shafts = [...layout.workings.values()].filter((working) => working.between)
    .flatMap((working) => [working.from, working.to]).map((node) => layout.nodes.get(node)).filter(Boolean);
  const out = new Map();
  for (const zone of zones) {
    const candidates = [];
    for (const name of zone.workings) {
      const working = layout.workings.get(name);
      if (!working || working.between) continue;
      // Offsets are metres of length_m; the loader is measured in scene metres along the drawn line.
      const perScene = working.lengthM / Math.max(working.total, 1e-6);
      const reach = (length + 2) * perScene;
      const centre = (length / 2 + 1.5) * perScene;
      const sensors = sensorOffsets.get(name) || [];
      const clear = (span) => !sensors.some((offset) => offset >= span[0] - 4 && offset <= span[1] + 4);
      for (const node of [working.from, working.to]) {
        const point = layout.nodes.get(node);
        if (!point || working.lengthM < reach * 1.4) continue;
        const attrs = nodesAttr[node] || {};
        const deadEnd = attrs.node_kind === 'dead_end' || degree.get(node) === 1;
        const away = Math.min(...shafts.map((shaft) => Math.hypot(shaft[0] - point[0], shaft[1] - point[1])), 1e6);
        const atEnd = node === working.to;
        const span = atEnd ? [working.lengthM - reach, working.lengthM] : [0, reach];
        // The machine stands at the end and looks out of it, along the drift: its light falls on the floor ahead.
        if (clear(span)) {
          candidates.push({working: name, offsetM: atEnd ? working.lengthM - centre : centre, facing: atEnd ? -1 : 1, span,
            rank: deadEnd ? 0 : 1, away});
        }
      }
      if (working.lengthM >= reach * 2) {
        const mid = working.lengthM / 2;
        const span = [mid - reach / 2, mid + reach / 2];
        if (clear(span)) candidates.push({working: name, offsetM: mid, facing: 1, span, rank: 2, away: 0});
      }
    }
    candidates.sort((p, q) => (p.rank - q.rank) || (q.away - p.away) || (p.working < q.working ? -1 : (p.working > q.working ? 1 : p.offsetM - q.offsetM)));
    out.set(zone.name, candidates.map(({working, offsetM, facing, span}) => ({working, offsetM, facing, span})));
  }
  return out;
}
