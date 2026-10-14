// Outlines of carved channels and zone frames on a slab. Pure: no three.js.
// A distance field of the channel centre lines is sampled on a grid and its
// iso-line traced by marching squares with linear interpolation, so a channel
// gets round dead ends and clean junctions without any polygon clipping.
// Points are plan pairs [X, Z].

const BIG = 1e9;

/**
 * @typedef {Object} Field
 * @property {number} x0
 * @property {number} z0
 * @property {number} step
 * @property {number} nx  samples along X
 * @property {number} nz  samples along Z
 * @property {Float32Array} values  row-major, index = j * nx + i
 */

/** A grid over a box, `pad` steps wider on every side, filled with `init`. */
export function grid(box, step, pad = 2, init = BIG) {
  const x0 = box.minX - pad * step;
  const z0 = box.minZ - pad * step;
  const nx = Math.ceil((box.maxX - box.minX) / step) + 2 * pad + 1;
  const nz = Math.ceil((box.maxZ - box.minZ) / step) + 2 * pad + 1;
  const values = new Float32Array(nx * nz).fill(init);
  return {x0, z0, step, nx, nz, values};
}

/**
 * Lower the field to the signed distance from segments, each with its own half width:
 * negative inside a channel.
 * @param {Field} field
 * @param {Array<{a: number[], b: number[], half: number}>} segments
 */
export function carveSegments(field, segments) {
  const {x0, z0, step, nx, nz, values} = field;
  for (const {a, b, half} of segments) {
    const reach = half + 3 * step;
    const i0 = Math.max(0, Math.floor((Math.min(a[0], b[0]) - reach - x0) / step));
    const i1 = Math.min(nx - 1, Math.ceil((Math.max(a[0], b[0]) + reach - x0) / step));
    const j0 = Math.max(0, Math.floor((Math.min(a[1], b[1]) - reach - z0) / step));
    const j1 = Math.min(nz - 1, Math.ceil((Math.max(a[1], b[1]) + reach - z0) / step));
    const dx = b[0] - a[0];
    const dz = b[1] - a[1];
    const len2 = dx * dx + dz * dz;
    for (let j = j0; j <= j1; j += 1) {
      const z = z0 + j * step;
      for (let i = i0; i <= i1; i += 1) {
        const x = x0 + i * step;
        let t = len2 > 0 ? ((x - a[0]) * dx + (z - a[1]) * dz) / len2 : 0;
        t = t < 0 ? 0 : (t > 1 ? 1 : t);
        const d = Math.hypot(x - a[0] - t * dx, z - a[1] - t * dz) - half;
        const k = j * nx + i;
        if (d < values[k]) values[k] = d;
      }
    }
  }
  return field;
}

/**
 * The solid of a slab: inside its rectangle and outside every channel. Negative is stone.
 * @param {Field} channels a field from carveSegments (negative inside a channel)
 * @param {{minX: number, maxX: number, minZ: number, maxZ: number}} box
 */
export function solidField(channels, box) {
  const {x0, z0, step, nx, nz} = channels;
  const values = new Float32Array(nx * nz);
  for (let j = 0; j < nz; j += 1) {
    const z = z0 + j * step;
    for (let i = 0; i < nx; i += 1) {
      const x = x0 + i * step;
      const rect = Math.max(box.minX - x, x - box.maxX, box.minZ - z, z - box.maxZ);
      const k = j * nx + i;
      values[k] = Math.max(rect, -channels.values[k]);
    }
  }
  return {...channels, values};
}

/**
 * Closed iso-lines `value = 0` of a field, as loops of plan points.
 * @param {Field} field
 * @returns {number[][][]}
 */
export function contours(field) {
  const {x0, z0, step, nx, nz, values} = field;
  const at = (i, j) => values[j * nx + i];
  // Edge ids: the horizontal edge from (i, j) to (i+1, j) is 2k, the vertical from (i, j) to (i, j+1) is 2k+1.
  const point = new Map();
  const edgePoint = (id) => {
    let p = point.get(id);
    if (p) return p;
    const k = id >> 1;
    const i = k % nx;
    const j = (k - i) / nx;
    const a = at(i, j);
    const b = id & 1 ? at(i, j + 1) : at(i + 1, j);
    const t = a === b ? 0.5 : a / (a - b);
    p = id & 1 ? [x0 + i * step, z0 + (j + t) * step] : [x0 + (i + t) * step, z0 + j * step];
    point.set(id, p);
    return p;
  };
  const links = new Map();
  const link = (p, q) => {
    if (!links.has(p)) links.set(p, []);
    if (!links.has(q)) links.set(q, []);
    links.get(p).push(q);
    links.get(q).push(p);
  };
  for (let j = 0; j < nz - 1; j += 1) {
    for (let i = 0; i < nx - 1; i += 1) {
      const a = at(i, j) < 0;
      const b = at(i + 1, j) < 0;
      const c = at(i + 1, j + 1) < 0;
      const d = at(i, j + 1) < 0;
      const code = (a ? 1 : 0) | (b ? 2 : 0) | (c ? 4 : 0) | (d ? 8 : 0);
      if (code === 0 || code === 15) continue;
      const k = j * nx + i;
      const bottom = 2 * k;
      const top = 2 * (k + nx);
      const left = 2 * k + 1;
      const right = 2 * (k + 1) + 1;
      switch (code) {
        case 1: case 14: link(left, bottom); break;
        case 2: case 13: link(bottom, right); break;
        case 3: case 12: link(left, right); break;
        case 4: case 11: link(right, top); break;
        case 6: case 9: link(bottom, top); break;
        case 7: case 8: link(left, top); break;
        case 5: case 10: {
          const centre = (at(i, j) + at(i + 1, j) + at(i + 1, j + 1) + at(i, j + 1)) / 4 < 0;
          // Corners a and c are inside for 5; the centre decides whether they join.
          if ((code === 5) === centre) {
            link(left, top);
            link(bottom, right);
          } else {
            link(left, bottom);
            link(right, top);
          }
          break;
        }
        default: break;
      }
    }
  }
  const loops = [];
  const used = new Set();
  for (const start of links.keys()) {
    if (used.has(start)) continue;
    const loop = [];
    let previous = null;
    let current = start;
    while (current !== undefined && !used.has(current)) {
      used.add(current);
      loop.push(edgePoint(current));
      const next = links.get(current).find((id) => id !== previous && !used.has(id));
      previous = current;
      current = next;
    }
    if (loop.length >= 3) loops.push(loop);
  }
  return loops;
}

/** Signed area of a loop (positive counter-clockwise in X right, Z down). */
export function area(loop) {
  let sum = 0;
  for (let i = 0; i < loop.length; i += 1) {
    const [x1, z1] = loop[i];
    const [x2, z2] = loop[(i + 1) % loop.length];
    sum += x1 * z2 - x2 * z1;
  }
  return sum / 2;
}

export function inside(point, loop) {
  let hit = false;
  for (let i = 0, j = loop.length - 1; i < loop.length; j = i, i += 1) {
    const [xi, zi] = loop[i];
    const [xj, zj] = loop[j];
    if ((zi > point[1]) !== (zj > point[1]) && point[0] < ((xj - xi) * (point[1] - zi)) / (zj - zi) + xi) hit = !hit;
  }
  return hit;
}

function simplifyOpen(points, tolerance) {
  if (points.length < 3) return points;
  const [ax, az] = points[0];
  const [bx, bz] = points[points.length - 1];
  const dx = bx - ax;
  const dz = bz - az;
  const len = Math.hypot(dx, dz) || 1;
  let worst = 0;
  let index = 0;
  for (let i = 1; i < points.length - 1; i += 1) {
    const d = Math.abs((points[i][0] - ax) * dz - (points[i][1] - az) * dx) / len;
    if (d > worst) {
      worst = d;
      index = i;
    }
  }
  if (worst <= tolerance) return [points[0], points[points.length - 1]];
  return [...simplifyOpen(points.slice(0, index + 1), tolerance).slice(0, -1), ...simplifyOpen(points.slice(index), tolerance)];
}

/** Douglas–Peucker for a closed loop: split at the point farthest from the first one. */
export function simplifyLoop(loop, tolerance) {
  if (loop.length < 8) return loop;
  let far = 0;
  let best = -1;
  loop.forEach((point, i) => {
    const d = Math.hypot(point[0] - loop[0][0], point[1] - loop[0][1]);
    if (d > best) {
      best = d;
      far = i;
    }
  });
  const first = simplifyOpen(loop.slice(0, far + 1), tolerance);
  const second = simplifyOpen([...loop.slice(far), loop[0]], tolerance);
  return [...first.slice(0, -1), ...second.slice(0, -1)];
}

/**
 * Loops sorted into outer outlines with their holes (by nesting depth).
 * @param {number[][][]} loops
 * @returns {Array<{outer: number[][], holes: number[][][]}>}
 */
export function nest(loops) {
  const sorted = loops.map((loop) => ({loop, size: Math.abs(area(loop))})).sort((a, b) => b.size - a.size);
  const shapes = [];
  const placed = [];
  for (const entry of sorted) {
    const containers = placed.filter((other) => inside(entry.loop[0], other.loop));
    const depth = containers.length;
    const record = {loop: entry.loop, depth, shape: null};
    if (depth % 2 === 0) {
      record.shape = {outer: entry.loop, holes: []};
      shapes.push(record.shape);
    } else {
      // The innermost container of odd depth minus one is the outline it belongs to.
      const parent = containers.reduce((best, other) => (other.depth > best.depth ? other : best), containers[0]);
      if (parent.shape) parent.shape.holes.push(entry.loop);
    }
    placed.push(record);
  }
  return shapes;
}
