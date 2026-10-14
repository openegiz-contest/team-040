// Geometry of the scheme. Pure: no DOM, and no coordinate, identifier or label
// of any particular mine: everything comes from twin attributes (nodes,
// levels, workings). Screen points are [x, y]; mine points are [x, y, z] in
// local metres, x and y in plan, z up.

const EPS = 1e-9;
const own = (map, key) => typeof key === 'string' && Object.prototype.hasOwnProperty.call(map, key);
const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
const r1 = (value) => Math.round(value * 10) / 10;

export const dist = (a, b) => Math.hypot(...a.map((value, k) => value - b[k]));
export const lerp = (a, b, t) => a.map((value, k) => value + (b[k] - value) * t);

/**
 * Levels from the upper one down.
 * @param {Array<{name: string, label: string, attrs: Object}>} levels twins of kind level
 * @returns {Array<{name: string, label: string, elevation: number}>}
 */
export function sortLevels(levels) {
  return levels
    .map((level) => ({name: level.name, label: level.label, elevation: level.attrs.elevation_m, order: level.attrs.order}))
    .filter((level) => Number.isFinite(level.elevation))
    .sort((a, b) => (b.elevation - a.elevation) || ((a.order || 0) - (b.order || 0)));
}

/** The position of a node, or null when the attribute does not give one. */
export function nodePoint(nodes, name) {
  const node = nodes && own(nodes, name) ? nodes[name] : null;
  return node && [node.x, node.y, node.z].every(Number.isFinite) ? [node.x, node.y, node.z] : null;
}

/**
 * The polyline of a working: its `from` node, its intermediate `points`, its `to` node.
 * @param {Object} attrs attributes of a working
 * @param {Object} nodes mine.attributes.nodes
 * @returns {number[][]|null} null when an end node has no position
 */
export function polyline3(attrs, nodes) {
  const a = nodePoint(nodes, attrs.from);
  const b = nodePoint(nodes, attrs.to);
  if (!a || !b) return null;
  const between = (Array.isArray(attrs.points) ? attrs.points : [])
    .filter((point) => Array.isArray(point) && point.length >= 3 && point.slice(0, 3).every(Number.isFinite))
    .map((point) => point.slice(0, 3));
  return [a, ...between, b];
}

/**
 * Add a vertex wherever a segment crosses one of the elevations. The
 * axonometric vertical is linear only between two neighbouring levels, so a
 * position interpolated along a split polyline stays exact.
 */
export function splitAtElevations(points, elevations) {
  const out = [points[0]];
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    const cuts = elevations.map((z) => (z - a[2]) / (b[2] - a[2])).filter((t) => t > 1e-6 && t < 1 - 1e-6);
    for (const t of cuts.sort((p, q) => p - q)) out.push(lerp(a, b, t));
    out.push(b);
  }
  return out;
}

/** Running length at every vertex; works for mine and for screen points. */
export function cumulative(points) {
  const cum = [0];
  for (let i = 1; i < points.length; i += 1) cum.push(cum[i - 1] + dist(points[i - 1], points[i]));
  return cum;
}

function seek(cum, length) {
  const last = cum.length - 1;
  const at = clamp(length, 0, cum[last]);
  let i = 0;
  while (i < last - 1 && cum[i + 1] < at) i += 1;
  const span = cum[i + 1] - cum[i];
  return {i, t: span > EPS ? (at - cum[i]) / span : 0};
}

/**
 * The point of `points` at `length` measured along `cum`, and the unit
 * direction of its segment. `cum` may belong to another space: screen points
 * with the lengths of the mine polyline give the place of a published offset.
 */
export function pointAt(points, cum, length) {
  const {i, t} = seek(cum, length);
  const a = points[i];
  const b = points[i + 1];
  const d = dist(a, b);
  return {point: lerp(a, b, t), dir: d > EPS ? a.map((value, k) => (b[k] - value) / d) : a.map((_, k) => (k === 0 ? 1 : 0))};
}

/** The part of `points` between two lengths along `cum`; walked backwards when `from` is the greater. */
export function cut(points, cum, from, to) {
  if (from > to) return cut(points, cum, to, from).reverse();
  const a = seek(cum, from);
  const b = seek(cum, to);
  const out = [lerp(points[a.i], points[a.i + 1], a.t)];
  for (let i = a.i + 1; i <= b.i; i += 1) out.push(points[i]);
  out.push(lerp(points[b.i], points[b.i + 1], b.t));
  return out;
}

/** A published offset (metres from the `from` node, of `lengthM`) as a length along a polyline of `total`. */
export function offsetLength(offsetM, lengthM, total) {
  return lengthM > 0 && Number.isFinite(offsetM) ? clamp(offsetM / lengthM, 0, 1) * total : 0;
}

/**
 * A published route as stretches of workings in walking order: the rest of
 * the current working from the worker towards the end the route names, then
 * whole workings. Nothing is searched or chosen here; a stretch whose
 * direction the data do not tell is left out.
 * @param {Array<{working: string, from: (string|null), to: (string|null)}>} segments model.routeOf
 * @param {{working: string, offsetM: number}|null} position the worker
 * @param {(name: string) => ({from: string, to: string, lengthM: number, total: number}|null)} lineOf
 * @returns {Array<{working: string, start: number, end: number}>} lengths along the polyline of each working
 */
export function routePieces(segments, position, lineOf) {
  const pieces = [];
  segments.forEach((segment, index) => {
    const line = lineOf(segment.working);
    if (!line) return;
    let forward = null;
    if (segment.to !== null) forward = segment.to === line.to ? true : (segment.to === line.from ? false : null);
    else if (segment.from !== null) forward = segment.from === line.from ? true : (segment.from === line.to ? false : null);
    if (forward === null) return;
    let start = forward ? 0 : line.total;
    if (index === 0 && position && position.working === segment.working) {
      start = offsetLength(position.offsetM, line.lengthM, line.total);
    }
    pieces.push({working: segment.working, start, end: forward ? line.total : 0});
  });
  return pieces;
}

/** @returns {{minX: number, minY: number, maxX: number, maxY: number}|null} the plan extent of points */
export function bounds(points) {
  if (points.length === 0) return null;
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  return {minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys)};
}

/** A plan extent widened by the same margin on every side. */
export function padded(box, share = 0.035) {
  const margin = Math.max(box.maxX - box.minX, box.maxY - box.minY, 1) * share;
  return {minX: box.minX - margin, minY: box.minY - margin, maxX: box.maxX + margin, maxY: box.maxY + margin};
}

/** @returns {{x: number, y: number, w: number, h: number}} the screen box of screen points */
export function boxOf(points) {
  const b = bounds(points);
  return {x: b.minX, y: b.minY, w: b.maxX - b.minX, h: b.maxY - b.minY};
}

/**
 * Axonometric projection: the levels are parallelograms stacked from the
 * upper one down and never overlap. The plan is drawn to one scale, sheared
 * to the right with depth; the vertical is NOT to scale: a height between two
 * levels is placed in proportion between their planes.
 * @param {{minX: number, minY: number, maxX: number, maxY: number}} box footprint shared by all levels
 * @param {number[]} elevations upper level first
 * @param {number} width
 * @param {number} height
 * @param {{top: number, right: number, bottom: number, left: number}} pad
 */
export function axoProjector(box, elevations, width, height, pad) {
  const SHEAR = 0.5;
  const xr = Math.max(box.maxX - box.minX, 1);
  const yr = Math.max(box.maxY - box.minY, 1);
  const n = Math.max(elevations.length, 1);
  const availW = Math.max(width - pad.left - pad.right, 50);
  const availH = Math.max(height - pad.top - pad.bottom, 50);
  let scale = availW / (xr + yr * SHEAR);
  // Depth is foreshortened so that all planes and the gaps between them fill the height.
  let plane = availH / (n + (n - 1) * 0.4);
  let depth = clamp(plane / (yr * scale), 0.3, 0.62);
  if (depth * yr * scale > plane) scale = plane / (yr * depth);
  plane = yr * depth * scale;
  const step = n > 1 ? plane + Math.min((availH - n * plane) / (n - 1), plane * 1.2) : 0;
  const left = pad.left + (availW - (xr + yr * SHEAR) * scale) / 2;
  const top = pad.top + (availH - plane - step * (n - 1)) / 2;
  const front = elevations.map((_, index) => top + plane + index * step);

  function baseOf(z) {
    if (n < 2 || elevations.length < 2) return (front[0] || top + plane) - (z - (elevations[0] || 0)) * scale * 0.5;
    let i = 0;
    while (i < n - 2 && z < elevations[i + 1]) i += 1;
    const span = elevations[i] - elevations[i + 1];
    return span > EPS ? front[i + 1] + (front[i] - front[i + 1]) * ((z - elevations[i + 1]) / span) : front[i];
  }
  const project = ([x, y, z]) => [
    left + (x - box.minX) * scale + (y - box.minY) * scale * SHEAR,
    baseOf(z) - (y - box.minY) * scale * depth,
  ];
  const corners = (z) => [[box.minX, box.minY, z], [box.maxX, box.minY, z], [box.maxX, box.maxY, z], [box.minX, box.maxY, z]].map(project);
  return {project, scale, planes: elevations.map(corners)};
}

/** Plan projection: one level from above, x to the right, y up, one scale. */
export function planProjector(box, width, height, pad) {
  const xr = Math.max(box.maxX - box.minX, 1);
  const yr = Math.max(box.maxY - box.minY, 1);
  const availW = Math.max(width - pad.left - pad.right, 50);
  const availH = Math.max(height - pad.top - pad.bottom, 50);
  const scale = Math.min(availW / xr, availH / yr);
  const left = pad.left + (availW - xr * scale) / 2;
  const top = pad.top + (availH - yr * scale) / 2;
  const project = ([x, y]) => [left + (x - box.minX) * scale, top + (box.maxY - y) * scale];
  return {project, scale, planes: [[[box.minX, box.minY], [box.maxX, box.minY], [box.maxX, box.maxY], [box.minX, box.maxY]].map(project)]};
}

// ---- shapes on the screen ---------------------------------------------------

function distinct(points) {
  return points.filter((point, i) => i === 0 || dist(point, points[i - 1]) > 0.05);
}

/** "M x y L x y ..." */
export function linePath(points) {
  return points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${r1(x)} ${r1(y)}`).join('');
}

/** The closed outline of a band of `width` around a screen polyline, with mitred corners. */
export function bandPath(points, width) {
  const p = distinct(points);
  if (p.length < 2) return '';
  const half = width / 2;
  const normals = [];
  for (let i = 1; i < p.length; i += 1) {
    const d = dist(p[i - 1], p[i]);
    normals.push([-(p[i][1] - p[i - 1][1]) / d, (p[i][0] - p[i - 1][0]) / d]);
  }
  const left = [];
  const right = [];
  p.forEach(([x, y], i) => {
    const a = normals[Math.max(i - 1, 0)];
    const b = normals[Math.min(i, normals.length - 1)];
    let mx = a[0] + b[0];
    let my = a[1] + b[1];
    const m = Math.hypot(mx, my) || 1;
    mx /= m;
    my /= m;
    const reach = half / Math.max(mx * a[0] + my * a[1], 0.4);
    left.push([x + mx * reach, y + my * reach]);
    right.push([x - mx * reach, y - my * reach]);
  });
  return `${linePath([...left, ...right.reverse()])}Z`;
}

const FRAME_PX = 6;

/**
 * What a working needs to be drawn, from its screen polyline: the centre
 * line and the band whole, the same with a gap in the middle (a closed
 * passage), and places for signs along it: the middle first, then outwards.
 * `frame` is an outline around the whole working, `FRAME_PX` away from its band.
 * @returns {{line: string, band: string, lineSplit: string, bandSplit: string, frame: string,
 *            slots: Array<{x: number, y: number, angle: number}>}}
 */
export function workingShape(points, width, gap = 14) {
  const p = distinct(points);
  const cum = cumulative(p);
  const total = cum[cum.length - 1];
  const along = (point, dir, by) => [point[0] + dir[0] * by, point[1] + dir[1] * by];
  const first = pointAt(p, cum, 0);
  const last = pointAt(p, cum, total);
  const longer = [along(first.point, first.dir, -FRAME_PX), ...p, along(last.point, last.dir, FRAME_PX)];
  const half = Math.min(gap / 2, total / 4);
  const halves = [cut(p, cum, 0, total / 2 - half), cut(p, cum, total / 2 + half, total)];
  const spread = Math.min(17, total / 5);
  const slots = [0, -1, 1, -2, 2].map((k) => {
    const {point, dir} = pointAt(p, cum, total / 2 + k * spread);
    return {x: r1(point[0]), y: r1(point[1]), angle: Math.round(Math.atan2(dir[1], dir[0]) * 180 / Math.PI)};
  });
  return {
    line: linePath(p),
    band: bandPath(p, width),
    lineSplit: halves.map(linePath).join(''),
    bandSplit: halves.map((part) => bandPath(part, width)).join(''),
    frame: bandPath(longer, width + 2 * FRAME_PX),
    slots,
  };
}

/** Arrow heads along a screen polyline, every `step` and at its end, as one path. */
export function chevrons(points, step, size) {
  const p = distinct(points);
  if (p.length < 2) return '';
  const cum = cumulative(p);
  const total = cum[cum.length - 1];
  const marks = [];
  for (let at = step * 0.6; at < total - step * 0.5; at += step) marks.push(at);
  marks.push(total);
  return marks.map((at) => {
    const {point: [x, y], dir: [dx, dy]} = pointAt(p, cum, at);
    const bx = x - dx * size;
    const by = y - dy * size;
    const w = size * 0.75;
    return `M${r1(bx - dy * w)} ${r1(by + dx * w)}L${r1(x)} ${r1(y)}L${r1(bx + dy * w)} ${r1(by - dx * w)}`;
  }).join('');
}

/** Points of a screen polyline every `step`: what a label should not cover. */
export function sample(points, step) {
  const cum = cumulative(points);
  const total = cum[cum.length - 1];
  const out = [];
  for (let at = 0; at <= total; at += step) out.push(pointAt(points, cum, at).point);
  return out;
}

// ---- label placement ---------------------------------------------------------

/**
 * Greedy placement of label boxes {x, y, w, h}. A candidate is first moved
 * inside the picture, then costs by what it covers: other labels and markers
 * (blocks) and lines (sample points). Placement depends on the data and the
 * size of the picture only, so the same state always gives the same picture.
 * @param {number} width
 * @param {number} height
 * @param {number[][]} samples
 */
export function createPlacer(width, height, samples) {
  const blocks = [];
  function cost(box) {
    let total = 0;
    for (const block of blocks) {
      const w = Math.min(box.x + box.w, block.x + block.w) - Math.max(box.x, block.x);
      const h = Math.min(box.y + box.h, block.y + block.h) - Math.max(box.y, block.y);
      if (w > 0 && h > 0) total += block.weight * (1 + (w * h) / 40);
    }
    // Lines are kept at a distance: a label beside a band must not touch it.
    const m = box.clear || 5;
    const each = box.clear ? 9 : 4;
    for (const [x, y] of samples) {
      if (x > box.x - m && x < box.x + box.w + m && y > box.y - m && y < box.y + box.h + m) total += each;
    }
    return total;
  }
  return {
    /** Something a label must keep off. */
    block(box, weight = 30) {
      blocks.push({...box, weight});
    },
    /**
     * @param {Array<{x: number, y: number, w: number, h: number}>} candidates in order of preference
     * @param {number} [keep] the candidate chosen last time: it stays unless another is clearly better
     * @returns {number} index of the chosen candidate, which is blocked from now on
     */
    place(candidates, keep = -1) {
      let best = 0;
      let bestCost = Infinity;
      for (const box of candidates) {
        box.x = clamp(box.x, 2, Math.max(width - box.w - 2, 2));
        box.y = clamp(box.y, 2, Math.max(height - box.h - 2, 2));
      }
      candidates.forEach((box, index) => {
        const value = cost(box) + index * 0.6 - (index === keep ? 8 : 0);
        if (value < bestCost) {
          best = index;
          bestCost = value;
        }
      });
      blocks.push({...candidates[best], weight: 200});
      return best;
    },
  };
}

/**
 * Candidate boxes of size w x h around a point at `gap` from it: right, left,
 * above, below, the four diagonals, then above and below again, starting or
 * ending at the point (for long labels).
 */
export function around([x, y], w, h, gap) {
  const d = gap * 0.75;
  return [
    {x: x + gap, y: y - h / 2}, {x: x - gap - w, y: y - h / 2}, {x: x - w / 2, y: y - gap - h}, {x: x - w / 2, y: y + gap},
    {x: x + d, y: y - d - h}, {x: x - d - w, y: y - d - h}, {x: x + d, y: y + d}, {x: x - d - w, y: y + d},
    {x: x - 10, y: y - gap - h}, {x: x - w + 10, y: y - gap - h}, {x: x - 10, y: y + gap}, {x: x - w + 10, y: y + gap},
  ].map((corner) => ({...corner, w, h}));
}
