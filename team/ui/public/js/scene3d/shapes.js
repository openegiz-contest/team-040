// Geometry of the stone model: slabs with carved channels, flat ribbons on a
// surface, casings and road bands of the inter-level workings, portals, barricades.
// Every builder returns a three.js BufferGeometry in the frame it is given;
// several pieces of one material are merged by the caller.

import * as THREE from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
import {area, carveSegments, contours, grid, nest, simplifyLoop, solidField} from './carve.js';
import {DIMS} from './layout.js';

/**
 * Collects triangles; `build()` gives a non-indexed geometry with normals, uvs and a grey vertex colour (1 unless
 * given: ambient occlusion for a material that asks for vertex colours; the scene's own materials bake it into their
 * textures instead, which costs no shader of its own). Every geometry of this module has the same attributes, so any
 * of them can be merged with any other.
 */
class Mesher {
  constructor() {
    this.position = [];
    this.normal = [];
    this.uv = [];
    this.color = [];
  }

  vertex(p, n, uv, shade = 1) {
    this.position.push(p[0], p[1], p[2]);
    this.normal.push(n[0], n[1], n[2]);
    this.uv.push(uv[0], uv[1]);
    this.color.push(shade, shade, shade);
  }

  /** A quad a-b-c-d (counter-clockwise seen from the side of `n`); `shades` the grey of each corner. */
  quad(a, b, c, d, n, uvs, shades = [1, 1, 1, 1]) {
    this.vertex(a, n, uvs[0], shades[0]); this.vertex(b, n, uvs[1], shades[1]); this.vertex(c, n, uvs[2], shades[2]);
    this.vertex(a, n, uvs[0], shades[0]); this.vertex(c, n, uvs[2], shades[2]); this.vertex(d, n, uvs[3], shades[3]);
  }

  build() {
    if (this.position.length === 0) return null;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(this.position, 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(this.normal, 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(this.uv, 2));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(this.color, 3));
    return geometry;
  }
}

/** Baked ambient occlusion of the slabs: the grey at the foot of a channel wall, under a slab, under a ramp. */
export const AO = {wallFoot: 0.5, wallTop: 1.05, underSlab: 0.42, cutTop: 1, rampFoot: 0.6};

/** Merge geometries that may be null; null when nothing is left. */
export function merge(list) {
  const parts = list.filter(Boolean);
  if (parts.length === 0) return null;
  if (parts.length === 1) return parts[0];
  const merged = mergeGeometries(parts, false);
  for (const part of parts) part.dispose();
  return merged;
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const len2d = (v) => Math.hypot(v[0], v[1]);

/**
 * The outline of the slab's stone after carving, and the stone of the zone frames.
 * @param {{minX: number, maxX: number, minZ: number, maxZ: number}} box
 * @param {Array<{a: number[], b: number[], half: number}>} segments channel centre lines, plan
 */
export function carveSlab(box, segments, step = 1) {
  const channels = carveSegments(grid(box, step), segments);
  const solid = solidField(channels, box);
  const loops = contours(solid).map((loop) => simplifyLoop(loop, 0.12)).filter((loop) => Math.abs(area(loop)) > 0.5);
  return {loops, shapes: nest(loops)};
}

/** Outer loops of the frame around a set of channels, `reach` outside their walls. */
export function frameLoops(segments, reach, step = 1.5) {
  if (segments.length === 0) return [];
  const xs = segments.flatMap((s) => [s.a[0], s.b[0]]);
  const zs = segments.flatMap((s) => [s.a[1], s.b[1]]);
  const r = Math.max(...segments.map((s) => s.half)) + reach + 4;
  const box = {minX: Math.min(...xs) - r, maxX: Math.max(...xs) + r, minZ: Math.min(...zs) - r, maxZ: Math.max(...zs) + r};
  const field = carveSegments(grid(box, step), segments.map((s) => ({...s, half: s.half + reach})));
  const loops = contours(field).map((loop) => simplifyLoop(loop, 0.25)).filter((loop) => Math.abs(area(loop)) > 4);
  return nest(loops).map((shape) => shape.outer);
}

/**
 * Pieces of one slab in its local frame (origin on the channel floor).
 * @returns {{top: THREE.BufferGeometry, rim: THREE.BufferGeometry, walls: THREE.BufferGeometry,
 *            sides: THREE.BufferGeometry, floor: THREE.BufferGeometry, bottom: THREE.BufferGeometry}}
 */
export function slabGeometry(box, carved) {
  const d = DIMS.depth;
  const bottomY = d - DIMS.thickness;
  const {minX, maxX, minZ, maxZ} = box;

  // Top face: the stone left between the channels.
  const top = new Mesher();
  for (const shape of carved.shapes) {
    const outer = shape.outer.map(([x, z]) => new THREE.Vector2(x, z));
    const holes = shape.holes.map((hole) => hole.map(([x, z]) => new THREE.Vector2(x, z)));
    const flat = [...shape.outer, ...shape.holes.flat()];
    const faces = THREE.ShapeUtils.triangulateShape(outer, holes);
    for (const [i, j, k] of faces) {
      let [a, b, c] = [flat[i], flat[j], flat[k]];
      // Facing up: (b - a) x (c - a) has a positive Y component when X x Z is clockwise seen from above.
      const cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
      if (cross > 0) [b, c] = [c, b];
      for (const p of [a, b, c]) top.vertex([p[0], d, p[1]], [0, 1, 0], [p[0] / 96, p[1] / 96]);
    }
  }

  // The band between floor and top along every outline: channel walls, and the upper strip of the cut faces.
  const walls = new Mesher();
  const rim = new Mesher();
  const onEdge = (p) => Math.min(Math.abs(p[0] - minX), Math.abs(p[0] - maxX), Math.abs(p[1] - minZ), Math.abs(p[1] - maxZ)) < 0.3;
  const perimeter = (p) => {
    // Distance along the rectangle, so that the strata of the strip meet those of the face below.
    const w = maxX - minX;
    const h = maxZ - minZ;
    if (Math.abs(p[1] - maxZ) < 0.3) return p[0] - minX;
    if (Math.abs(p[0] - maxX) < 0.3) return w + (maxZ - p[1]);
    if (Math.abs(p[1] - minZ) < 0.3) return w + h + (maxX - p[0]);
    return 2 * w + h + (p[1] - minZ);
  };
  for (const loop of carved.loops) {
    let run = 0;
    for (let i = 0; i < loop.length; i += 1) {
      const a = loop[i];
      const b = loop[(i + 1) % loop.length];
      const along = sub(b, a);
      const length = len2d(along);
      if (length < 1e-4) continue;
      const n = [along[1] / length, 0, -along[0] / length];
      if (onEdge(a) && onEdge(b)) {
        const ua = perimeter(a) / 40;
        let ub = perimeter(b) / 40;
        if (Math.abs(ub - ua) > length / 40 + 0.5) ub = ua + length / 40;
        const va = (0 - bottomY) / DIMS.thickness;
        rim.quad([a[0], 0, a[1]], [b[0], 0, b[1]], [b[0], d, b[1]], [a[0], d, a[1]], n,
          [[ua, va], [ub, va], [ub, 1], [ua, 1]]);
      } else {
        const ua = run / 6;
        const ub = (run + length) / 6;
        walls.quad([a[0], 0, a[1]], [b[0], 0, b[1]], [b[0], d, b[1]], [a[0], d, a[1]], n, [[ua, 0], [ub, 0], [ub, 1], [ua, 1]],
          [AO.wallFoot, AO.wallFoot, AO.wallTop, AO.wallTop]);
      }
      run += length;
    }
  }

  // Cut faces below the floor: four rectangles, strata running round the slab.
  const sides = new Mesher();
  const w = maxX - minX;
  const h = maxZ - minZ;
  const faces = [
    [[minX, maxZ], [maxX, maxZ], [0, 0, 1], 0],
    [[maxX, maxZ], [maxX, minZ], [1, 0, 0], w],
    [[maxX, minZ], [minX, minZ], [0, 0, -1], w + h],
    [[minX, minZ], [minX, maxZ], [-1, 0, 0], 2 * w + h],
  ];
  for (const [a, b, n, start] of faces) {
    const length = len2d(sub(b, a));
    const ua = start / 40;
    const ub = (start + length) / 40;
    const v0 = 0;
    const v1 = (0 - bottomY) / DIMS.thickness;
    sides.quad([a[0], bottomY, a[1]], [b[0], bottomY, b[1]], [b[0], 0, b[1]], [a[0], 0, a[1]], n,
      [[ua, v0], [ub, v0], [ub, v1], [ua, v1]], [AO.underSlab, AO.underSlab, AO.cutTop, AO.cutTop]);
  }

  const floor = new Mesher();
  floor.quad([minX, 0, maxZ], [maxX, 0, maxZ], [maxX, 0, minZ], [minX, 0, minZ], [0, 1, 0],
    [[minX / 8, maxZ / 8], [maxX / 8, maxZ / 8], [maxX / 8, minZ / 8], [minX / 8, minZ / 8]]);
  const bottom = new Mesher();
  bottom.quad([minX, bottomY, minZ], [maxX, bottomY, minZ], [maxX, bottomY, maxZ], [minX, bottomY, maxZ], [0, -1, 0],
    [[0, 0], [1, 0], [1, 1], [0, 1]]);

  return {top: top.build(), rim: rim.build(), walls: walls.build(), sides: sides.build(), floor: floor.build(), bottom: bottom.build()};
}

/**
 * A flat ribbon of `width` along a plan polyline at height `y` (local frame).
 * u runs along the ribbon in metres / `period`, v across it from 0 to 1.
 * @param {number[][]} points plan [X, Z]
 * @param {{closed?: boolean, period?: number, offset?: number}} [options]
 *        offset: shift of the centre line sideways (positive to the left of the direction)
 */
export function ribbon(points, width, y, options = {}) {
  const {closed = false, period = 10, offset = 0} = options;
  const p = points.filter((point, i) => i === 0 || len2d(sub(point, points[i - 1])) > 1e-3);
  if (closed && p.length > 2 && len2d(sub(p[0], p[p.length - 1])) < 1e-3) p.pop();
  if (p.length < 2) return null;
  const count = p.length;
  const dirAt = (i) => {
    const a = p[i];
    const b = p[(i + 1) % count];
    const v = sub(b, a);
    const l = len2d(v) || 1;
    return [v[0] / l, v[1] / l];
  };
  const left = [];
  const right = [];
  for (let i = 0; i < count; i += 1) {
    let prev;
    let next;
    if (closed) {
      prev = dirAt((i - 1 + count) % count);
      next = dirAt(i);
    } else {
      prev = dirAt(Math.max(i - 1, 0));
      next = dirAt(Math.min(i, count - 2));
    }
    const na = [-prev[1], prev[0]];
    const nb = [-next[1], next[0]];
    let m = [na[0] + nb[0], na[1] + nb[1]];
    const ml = len2d(m) || 1;
    m = [m[0] / ml, m[1] / ml];
    const scale = 1 / Math.max(m[0] * nb[0] + m[1] * nb[1], 0.35);
    const half = width / 2;
    left.push([p[i][0] + m[0] * (offset + half) * scale, p[i][1] + m[1] * (offset + half) * scale]);
    right.push([p[i][0] + m[0] * (offset - half) * scale, p[i][1] + m[1] * (offset - half) * scale]);
  }
  const mesher = new Mesher();
  let run = 0;
  const last = closed ? count : count - 1;
  for (let i = 0; i < last; i += 1) {
    const j = (i + 1) % count;
    const length = len2d(sub(p[j], p[i]));
    const u0 = run / period;
    const u1 = (run + length) / period;
    mesher.quad([right[i][0], y, right[i][1]], [right[j][0], y, right[j][1]], [left[j][0], y, left[j][1]], [left[i][0], y, left[i][1]],
      [0, 1, 0], [[u0, 0], [u1, 0], [u1, 1], [u0, 1]]);
    run += length;
  }
  return fixUp(mesher.build());
}

/** Flip the triangles of a flat geometry that face down. */
function fixUp(geometry) {
  if (!geometry) return null;
  const pos = geometry.attributes.position.array;
  const uv = geometry.attributes.uv.array;
  for (let t = 0; t < pos.length; t += 9) {
    const ax = pos[t]; const az = pos[t + 2];
    const cross = (pos[t + 3] - ax) * (pos[t + 8] - az) - (pos[t + 5] - az) * (pos[t + 6] - ax);
    if (cross > 0) {
      for (let k = 0; k < 3; k += 1) {
        const tmp = pos[t + 3 + k]; pos[t + 3 + k] = pos[t + 6 + k]; pos[t + 6 + k] = tmp;
      }
      const u = (t / 3) * 2;
      for (let k = 0; k < 2; k += 1) {
        const tmp = uv[u + 2 + k]; uv[u + 2 + k] = uv[u + 4 + k]; uv[u + 4 + k] = tmp;
      }
    }
  }
  return geometry;
}

/** Pieces of a polyline: on for `on` metres, off for `off`, as separate plan polylines. */
export function dashes(points, on, off, closed = false) {
  const p = closed ? [...points, points[0]] : points;
  const out = [];
  let current = [p[0]];
  let state = true;
  let left = on;
  for (let i = 1; i < p.length; i += 1) {
    let a = p[i - 1];
    const b = p[i];
    let seg = len2d(sub(b, a));
    while (seg > left) {
      const t = left / seg;
      const cutPoint = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      if (state) {
        current.push(cutPoint);
        out.push(current);
      }
      current = [cutPoint];
      state = !state;
      seg -= left;
      a = cutPoint;
      left = state ? on : off;
    }
    left -= seg;
    if (state) current.push(b);
  }
  if (state && current.length > 1) out.push(current);
  return out;
}

// ---- inter-level workings (scene frame) -----------------------------------------------

function frameAlong(points) {
  // Unit tangent and a horizontal side vector for every segment.
  return points.slice(1).map((b, i) => {
    const a = points[i];
    const t = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const l = Math.hypot(...t) || 1;
    const tan = t.map((v) => v / l);
    let side = [-tan[2], 0, tan[0]];
    const sl = Math.hypot(side[0], side[2]);
    side = sl > 1e-3 ? side.map((v) => v / sl) : [1, 0, 0];
    return {a, b, tan, side, length: l};
  });
}

function box(center, xAxis, yAxis, zAxis, size) {
  // An oriented box: axes are unit vectors, size [sx, sy, sz].
  const mesher = new Mesher();
  const corner = (sx, sy, sz) => [0, 1, 2].map((k) => center[k] + xAxis[k] * sx * size[0] / 2
    + yAxis[k] * sy * size[1] / 2 + zAxis[k] * sz * size[2] / 2);
  const faces = [
    [[1, -1, -1], [1, 1, -1], [1, 1, 1], [1, -1, 1], xAxis],
    [[-1, -1, 1], [-1, 1, 1], [-1, 1, -1], [-1, -1, -1], xAxis.map((v) => -v)],
    [[-1, 1, -1], [-1, 1, 1], [1, 1, 1], [1, 1, -1], yAxis],
    [[-1, -1, 1], [-1, -1, -1], [1, -1, -1], [1, -1, 1], yAxis.map((v) => -v)],
    [[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1], zAxis],
    [[1, -1, -1], [-1, -1, -1], [-1, 1, -1], [1, 1, -1], zAxis.map((v) => -v)],
  ];
  for (const [a, b, c, d, n] of faces) {
    mesher.quad(corner(...a), corner(...b), corner(...c), corner(...d), n, [[0, 0], [1, 0], [1, 1], [0, 1]]);
  }
  return mesher.build();
}

const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm3 = (v) => {
  const l = Math.hypot(...v) || 1;
  return v.map((x) => x / l);
};

/** A bar from a to b with a square section of `thickness`. */
export function bar(a, b, thickness) {
  const t = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const length = Math.hypot(...t);
  if (length < 1e-3) return null;
  const tan = t.map((v) => v / length);
  const helper = Math.abs(tan[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0];
  const x = norm3(cross3(helper, tan));
  const y = norm3(cross3(tan, x));
  const centre = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
  return box(centre, x, y, tan, [thickness, thickness, length]);
}

/**
 * The casing of a shaft or a raise: corner posts along the line and solid collars of lining at
 * intervals, heavy enough to read from the overview, open between the collars so that the people
 * and the routes inside stay visible.
 * @param {number[][]} points scene points
 * @param {{half: number, every: number, collar: number, wall: number, post: number}} style
 */
export function casing(points, style) {
  const parts = [];
  for (const seg of frameAlong(points)) {
    const up = Math.abs(seg.tan[1]) > 0.9 ? [0, 0, 1] : [0, 1, 0];
    const x = norm3(cross3(up, seg.tan));
    const y = norm3(cross3(seg.tan, x));
    const h = style.half;
    const corners = [[h, h], [-h, h], [-h, -h], [h, -h]];
    const at = (base, [ox, oy]) => [0, 1, 2].map((k) => base[k] + x[k] * ox + y[k] * oy);
    for (const corner of corners) parts.push(bar(at(seg.a, corner), at(seg.b, corner), style.post));
    const count = Math.max(1, Math.round(seg.length / style.every));
    for (let i = 0; i <= count; i += 1) {
      const t = Math.min(Math.max((seg.length * i) / count, style.collar / 2), seg.length - style.collar / 2);
      const c = [0, 1, 2].map((k) => seg.a[k] + seg.tan[k] * t);
      // Four walls of the collar, each a box: its outer face on the line of the posts.
      const w = style.wall;
      parts.push(
        box(at(c, [h - w / 2, 0]), x, y, seg.tan, [w, 2 * h, style.collar]),
        box(at(c, [-h + w / 2, 0]), x, y, seg.tan, [w, 2 * h, style.collar]),
        box(at(c, [0, h - w / 2]), x, y, seg.tan, [2 * h - 2 * w, w, style.collar]),
        box(at(c, [0, -h + w / 2]), x, y, seg.tan, [2 * h - 2 * w, w, style.collar]),
      );
    }
  }
  return merge(parts);
}

/**
 * A ramp road as a solid band: a deck `2·half` wide with a cut face `depth` deep on both sides, and
 * kerbs; it reads as one continuous road between the levels.
 * @returns {{deck: THREE.BufferGeometry, sides: THREE.BufferGeometry, steel: THREE.BufferGeometry}}
 */
export function rampBand(points, half, depth) {
  const deck = new Mesher();
  const sides = new Mesher();
  const steel = [];
  let run = 0;
  for (const seg of frameAlong(points)) {
    const {a, b, side: s, tan} = seg;
    const edge = (p, sign, dy = 0) => [p[0] + s[0] * half * sign, p[1] + dy, p[2] + s[2] * half * sign];
    let n = norm3(cross3(tan, s));
    if (n[1] < 0) n = n.map((v) => -v);
    const u0 = run / 10;
    const u1 = (run + seg.length) / 10;
    deck.quad(edge(a, -1), edge(b, -1), edge(b, 1), edge(a, 1), n, [[u0, 0], [u1, 0], [u1, 1], [u0, 1]]);
    for (const sign of [-1, 1]) {
      const outward = s.map((v) => v * sign);
      const v0 = 0;
      const v1 = depth / DIMS.thickness;
      sides.quad(edge(a, sign, -depth), edge(b, sign, -depth), edge(b, sign), edge(a, sign), outward,
        [[u0 / 4, v0], [u1 / 4, v0], [u1 / 4, v1], [u0 / 4, v1]], [AO.rampFoot, AO.rampFoot, 1, 1]);
      steel.push(bar(edge(a, sign, 0.7), edge(b, sign, 0.7), 0.9));
    }
    run += seg.length;
  }
  return {deck: deck.build(), sides: sides.build(), steel: merge(steel)};
}

/** A tube of radius r along scene points; `sides` around. Vertices run along the line, for a draw range. */
export function tube(points, radius, sides = 6) {
  const p = points.filter((point, i) => i === 0 || Math.hypot(point[0] - points[i - 1][0], point[1] - points[i - 1][1], point[2] - points[i - 1][2]) > 1e-3);
  if (p.length < 2) return null;
  const mesher = new Mesher();
  for (let i = 0; i < p.length - 1; i += 1) {
    const a = p[i];
    const b = p[i + 1];
    const tan = norm3([b[0] - a[0], b[1] - a[1], b[2] - a[2]]);
    const helper = Math.abs(tan[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0];
    const x = norm3(cross3(helper, tan));
    const y = norm3(cross3(tan, x));
    for (let s = 0; s < sides; s += 1) {
      const a0 = (s / sides) * Math.PI * 2;
      const a1 = ((s + 1) / sides) * Math.PI * 2;
      const o0 = [0, 1, 2].map((k) => x[k] * Math.cos(a0) + y[k] * Math.sin(a0));
      const o1 = [0, 1, 2].map((k) => x[k] * Math.cos(a1) + y[k] * Math.sin(a1));
      const n = norm3([o0[0] + o1[0], o0[1] + o1[1], o0[2] + o1[2]]);
      const at = (base, o) => [0, 1, 2].map((k) => base[k] + o[k] * radius);
      mesher.quad(at(a, o0), at(b, o0), at(b, o1), at(a, o1), n, [[0, 0], [1, 0], [1, 1], [0, 1]]);
    }
  }
  return mesher.build();
}

/** An arrow head (a flat-sided pyramid) at `tip`, pointing along `dir`. */
export function arrowHead(tip, dir, size) {
  const tan = norm3(dir);
  const helper = Math.abs(tan[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0];
  const x = norm3(cross3(helper, tan));
  const y = norm3(cross3(tan, x));
  const base = tip.map((v, k) => v - tan[k] * size * 1.6);
  const corners = [0, 1, 2, 3].map((i) => {
    const a = (i / 4) * Math.PI * 2 + Math.PI / 4;
    return base.map((v, k) => v + (x[k] * Math.cos(a) + y[k] * Math.sin(a)) * size);
  });
  const mesher = new Mesher();
  for (let i = 0; i < 4; i += 1) {
    const a = corners[i];
    const b = corners[(i + 1) % 4];
    const n = norm3(cross3([b[0] - a[0], b[1] - a[1], b[2] - a[2]], [tip[0] - a[0], tip[1] - a[1], tip[2] - a[2]]));
    mesher.vertex(a, n, [0, 0]); mesher.vertex(b, n, [1, 0]); mesher.vertex(tip, n, [0.5, 1]);
  }
  return mesher.build();
}

/**
 * A portal of an exit: two posts, a lintel and a small roof, standing on the floor
 * at the origin, its opening facing along `facing` (plan direction).
 */
export function portal(at, facing, size) {
  const f = norm3([facing[0], 0, facing[1]]);
  const s = [-f[2], 0, f[0]];
  const w = size * 0.55;
  const h = size;
  const parts = [];
  for (const sign of [-1, 1]) {
    const base = [at[0] + s[0] * w * sign, at[1], at[2] + s[2] * w * sign];
    parts.push(box([base[0], base[1] + h / 2, base[2]], s, [0, 1, 0], f, [1.4, h, 1.4]));
  }
  parts.push(box([at[0], at[1] + h, at[2]], s, [0, 1, 0], f, [2 * w + 2.4, 1.6, 2]));
  parts.push(box([at[0], at[1] + h + 1.6, at[2]], s, [0, 1, 0], f, [2 * w + 0.6, 1.2, 1.2]));
  return merge(parts);
}

/** A barricade across a working at a point: a block with a striped face, as wide as the channel. */
export function barricade(at, dir, width, height) {
  let f = norm3(dir);
  if (Math.abs(f[1]) > 0.9) {
    // Across a vertical shaft: a horizontal plate.
    return box(at, [1, 0, 0], [0, 0, 1], [0, 1, 0], [width, width, 2.2]);
  }
  f = norm3([f[0], 0, f[2]]);
  const s = [-f[2], 0, f[0]];
  return box([at[0], at[1] + height / 2, at[2]], s, [0, 1, 0], f, [width, height, 3.6]);
}

/** A flat disc on the floor (local frame), for the mouth of a working that leaves through the floor. */
export function disc(at, radius, y, segments = 20) {
  const mesher = new Mesher();
  for (let i = 0; i < segments; i += 1) {
    const a0 = (i / segments) * Math.PI * 2;
    const a1 = ((i + 1) / segments) * Math.PI * 2;
    const p0 = [at[0] + Math.cos(a0) * radius, y, at[1] + Math.sin(a0) * radius];
    const p1 = [at[0] + Math.cos(a1) * radius, y, at[1] + Math.sin(a1) * radius];
    mesher.vertex([at[0], y, at[1]], [0, 1, 0], [0.5, 0.5]);
    mesher.vertex(p1, [0, 1, 0], [0, 0]);
    mesher.vertex(p0, [0, 1, 0], [1, 0]);
  }
  return mesher.build();
}

/** A flat rectangle (local or scene frame) for the desk and its soft shadow. */
export function plane(minX, maxX, minZ, maxZ, y) {
  const mesher = new Mesher();
  mesher.quad([minX, y, maxZ], [maxX, y, maxZ], [maxX, y, minZ], [minX, y, minZ], [0, 1, 0], [[0, 0], [1, 0], [1, 1], [0, 1]]);
  return mesher.build();
}

// ---- stylised edges (variant 3) ------------------------------------------------------------

/** '#RRGGBB' as sRGB components 0…1 (the edge shader writes them as they are). */
function srgb(hex) {
  const value = parseInt(hex.slice(1), 16);
  return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255];
}

/**
 * The crisp edges of one slab as line segments in its local frame: the lips of every cut on the top face (the
 * channels), the sawn outline of the top face, the vertical corners and the bottom outline of the cut faces.
 * Attributes: position, aColor (sRGB and alpha per vertex) and aT, the fraction 0…1 along its own loop, so that
 * every loop can be drawn in from its start at once (the intro of scene.js). One draw call per slab.
 * @param {{minX: number, maxX: number, minZ: number, maxZ: number}} box
 * @param {{loops: number[][][]}} carved shapes.carveSlab
 * @param {{lip: [string, number], rim: [string, number], cut: [string, number]}} tones colour and alpha of each kind
 */
export function edgeLines(box, carved, tones) {
  const d = DIMS.depth;
  const bottomY = d - DIMS.thickness;
  const {minX, maxX, minZ, maxZ} = box;
  const position = [];
  const t = [];
  const colour = [];
  const tone = Object.fromEntries(Object.entries(tones).map(([name, [hex, alpha]]) => [name, [...srgb(hex), alpha]]));
  const push = (a, b, ta, tb, c) => {
    position.push(a[0], a[1], a[2], b[0], b[1], b[2]);
    t.push(ta, tb);
    colour.push(...c, ...c);
  };
  const onEdge = (p) => Math.min(Math.abs(p[0] - minX), Math.abs(p[0] - maxX), Math.abs(p[1] - minZ), Math.abs(p[1] - maxZ)) < 0.3;
  // A hair above the face it lies on: never in the depth of the stone.
  const lift = d + 0.14;
  for (const loop of carved.loops) {
    if (loop.length < 2) continue;
    const outer = loop.every(onEdge);
    const lengths = loop.map((a, i) => len2d(sub(loop[(i + 1) % loop.length], a)));
    const total = lengths.reduce((sum, value) => sum + value, 0) || 1;
    let run = 0;
    loop.forEach((a, i) => {
      const b = loop[(i + 1) % loop.length];
      push([a[0], lift, a[1]], [b[0], lift, b[1]], run / total, (run + lengths[i]) / total, outer ? tone.rim : tone.lip);
      run += lengths[i];
    });
  }
  // The cut faces: four vertical corners (drawn in from the top down) and the bottom outline, pushed a hair outwards.
  const out = 0.16;
  const corners = [[minX - out, minZ - out], [maxX + out, minZ - out], [maxX + out, maxZ + out], [minX - out, maxZ + out]];
  for (const c of corners) push([c[0], d, c[1]], [c[0], bottomY, c[1]], 0, 1, tone.cut);
  corners.forEach((a, i) => {
    const b = corners[(i + 1) % 4];
    push([a[0], bottomY, a[1]], [b[0], bottomY, b[1]], i / 4, (i + 1) / 4, tone.cut);
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(position, 3));
  geometry.setAttribute('aT', new THREE.Float32BufferAttribute(t, 1));
  geometry.setAttribute('aColor', new THREE.Float32BufferAttribute(colour, 4));
  return geometry;
}

/** The material of edgeLines: per-vertex colour, drawn in up to uProgress, washed towards uGlowColor by uGlow. */
export function edgeMaterial(glowHex) {
  return new THREE.ShaderMaterial({
    uniforms: {uProgress: {value: 1}, uGlow: {value: 0}, uDim: {value: 1}, uGlowColor: {value: new THREE.Vector3(...srgb(glowHex))}},
    vertexShader: `
attribute float aT;
attribute vec4 aColor;
varying float vT;
varying vec4 vColor;
void main() {
  vT = aT;
  vColor = aColor;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`,
    fragmentShader: `
uniform float uProgress;
uniform float uGlow;
uniform float uDim;
uniform vec3 uGlowColor;
varying float vT;
varying vec4 vColor;
void main() {
  if (vT > uProgress) discard;
  gl_FragColor = vec4(mix(vColor.rgb * uDim, uGlowColor, uGlow), mix(vColor.a, 1.0, uGlow));
}`,
    transparent: true,
    depthWrite: false,
  });
}
