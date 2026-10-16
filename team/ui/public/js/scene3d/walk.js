// People walk by published positions only (honest motion): a playback buffer.
//
// The last few publications are kept with the wall time each one arrived. People
// are drawn at a playback time about one publication interval (measured from the
// arrivals, about 1 s) behind now, so a person is always drawn between two
// published places and never ahead of the newest one: nothing is extrapolated.
// Between two publications a person moves at a constant speed along the path
// from the earlier place to the later one, measured in metres of length_m:
//   - on one working, by offset_m;
//   - across workings, only along the sequence of workings that the route
//     published with the earlier place confirms ({working, from, to,
//     from_offset_m, to_offset_m}); without such a route the later place is
//     taken at once (no path is invented, nothing is searched);
//   - a stretch longer than MAX_STEP_M is a jump of the model, taken at once.
// The playback clock runs with the wall clock, a little faster or slower to keep
// its lag near one interval; it never goes back and never runs more than one
// interval behind (a late or an early publication is absorbed, no queue is
// replayed). The caller stops all motion at once (snap: the newest place) on a
// pause, old data, a failed read, reduced motion, a hidden page, and clears the
// buffer on a new run or topology. Facing follows the travel along the path.
//
// The loaders of the model play back in the same buffer (names MACHINE + local
// name), so a machine and the person walking ahead of it are drawn at one
// moment of the model; their path between two publications is given by the
// caller (publication.paths: actors.js machineLeg). moving() lists people only.
//
// Pure: no three.js, no DOM. Distances of the model are never changed: places
// are offsets of length_m on the workings of the layout (layout.js).

import {alongStep} from './layout.js';

/** A stretch between two publications longer than this (metres) is a jump of the model, not a walk. */
export const MAX_STEP_M = 80;
/** The names of the loaders in the buffer: MACHINE + the local name of the equipment twin. */
export const MACHINE = 'machine:';
/** A place this close to an end of its working stands at that node. */
const AT_NODE_M = 0.5;
/** A move shorter than this (metres) is no move. */
const STILL_M = 0.05;
/** Publications kept. */
const KEEP = 4;
/** A lag this far from one interval (ms) changes the playback rate by 100 % (clamped to RATE). */
const RATE_MS = 800;
const RATE = [0.5, 1.6];
/** The interval assumed before two arrivals were seen, and its bounds (ms). */
const INTERVAL = {start: 1000, min: 200, max: 3000};
/** The longest frame step of the playback clock (ms): the first frame after a pause of the page does not leap. */
const MAX_DT = 100;

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
};
const samePlace = (a, b) => a.working === b.working && Math.abs(a.offsetM - b.offsetM) <= STILL_M;

/**
 * A segment of a published route as offsets on its working: {working, start, end, startNode, endNode}, or null when
 * its direction cannot be read from its nodes. Offsets published with it (from_offset_m, to_offset_m) are kept.
 */
function spanOf(layout, segment) {
  const line = segment ? layout.workings.get(segment.working) : null;
  if (!line) return null;
  let forward = null;
  if (typeof segment.to === 'string') forward = segment.to === line.to ? true : (segment.to === line.from ? false : null);
  if (forward === null && typeof segment.from === 'string') forward = segment.from === line.from ? true : (segment.from === line.to ? false : null);
  if (forward === null) return null;
  return {
    working: line.name,
    start: Number.isFinite(segment.fromOffsetM) ? segment.fromOffsetM : (forward ? 0 : line.lengthM),
    end: Number.isFinite(segment.toOffsetM) ? segment.toOffsetM : (forward ? line.lengthM : 0),
    startNode: forward ? line.from : line.to,
    endNode: forward ? line.to : line.from,
  };
}

/** True when `offset` lies on the span, between its start and its end. */
const onSpan = (span, offset) => offset >= Math.min(span.start, span.end) - AT_NODE_M && offset <= Math.max(span.start, span.end) + AT_NODE_M;

/** The node a place stands at (within AT_NODE_M of an end of its working), or null. */
function nodeAt(layout, place) {
  const line = layout.workings.get(place.working);
  if (!line) return null;
  if (place.offsetM <= AT_NODE_M) return line.from;
  if (place.offsetM >= line.lengthM - AT_NODE_M) return line.to;
  return null;
}

/**
 * The path walked between two published places of a person, confirmed by what was published: one working, or the
 * sequence of workings of `route` (the route published with the earlier place). Null: the later place is taken at
 * once.
 * @param {{workings: Map}} layout
 * @param {{working: string, offsetM: number}} from
 * @param {{working: string, offsetM: number}} to
 * @param {Array<{working: string, from: ?string, to: ?string, fromOffsetM?: number, toOffsetM?: number}>|null} route
 * @returns {{pieces: Array<{working: string, start: number, end: number}>, length: number}|null}
 */
export function legBetween(layout, from, to, route) {
  const a = layout.workings.get(from.working);
  const b = layout.workings.get(to.working);
  if (!a || !b || !Number.isFinite(from.offsetM) || !Number.isFinite(to.offsetM)) return null;
  const finish = (pieces) => {
    const kept = pieces.filter((piece, index) => Math.abs(piece.end - piece.start) > 1e-6 || index === pieces.length - 1);
    const length = kept.reduce((sum, piece) => sum + Math.abs(piece.end - piece.start), 0);
    return length <= MAX_STEP_M ? {pieces: kept, length} : null;
  };
  if (a === b) return finish([{working: a.name, start: from.offsetM, end: to.offsetM}]);
  if (!Array.isArray(route) || route.length === 0) return null;
  const spans = route.map((segment) => spanOf(layout, segment));
  const pieces = [];
  // Where the path starts: on the working of the earlier place, or at the node it stood on where the route begins.
  let i = spans.findIndex((span) => span && span.working === a.name && onSpan(span, from.offsetM));
  if (i >= 0) {
    pieces.push({working: a.name, start: from.offsetM, end: spans[i].end});
  } else {
    const node = nodeAt(layout, from);
    if (node === null || !spans[0] || spans[0].startNode !== node) return null;
    i = -1;
  }
  for (let j = i + 1; j < spans.length; j += 1) {
    const span = spans[j];
    // The segments must join end to start: a route that does not lead on from where the path is confirms nothing.
    if (!span || (j > 0 && spans[j - 1] && spans[j - 1].endNode !== span.startNode)) return null;
    if (span.working === b.name && onSpan(span, to.offsetM)) {
      pieces.push({working: b.name, start: span.start, end: to.offsetM});
      return finish(pieces);
    }
    pieces.push({working: span.working, start: span.start, end: span.end});
    // The later place stands at the node where this segment ends (published on the next working, or on another).
    const node = nodeAt(layout, to);
    if (node !== null && span.endNode === node) return finish(pieces);
  }
  return null;
}

/** The piece of a path reached after `metres`. */
function pieceAt(pieces, metres) {
  let left = Math.max(metres, 0);
  for (const piece of pieces) {
    const span = Math.abs(piece.end - piece.start);
    if (left <= span) return piece;
    left -= span;
  }
  return pieces[pieces.length - 1];
}

/**
 * The playback buffer of the people's places.
 */
export function createWalk() {
  /** Publications, oldest first: {at, places: Map<name, {working, offsetM}>, routes: Map<name, segments>, legs} */
  let snaps = [];
  let playT = 0;
  let lastNow = null;
  const gaps = [];
  let interval = INTERVAL.start;
  let clears = 0;
  /** person -> {working, facing}: the way the person last walked (+1 towards growing offsets). */
  const facings = new Map();

  /** The publication whose bracket holds `t`: index of the later one, or -1 when `t` is at or past the newest. */
  function bracket(t) {
    for (let j = 1; j < snaps.length; j += 1) if (t < snaps[j].at) return j;
    return -1;
  }

  /** True while a person still has metres to walk between the playback time and the newest publication. */
  function pending() {
    const j = bracket(playT);
    if (j < 0) return false;
    for (let k = j; k < snaps.length; k += 1) {
      for (const leg of snaps[k].legs.values()) if (leg && leg.length > STILL_M) return true;
    }
    return false;
  }

  /** Drop what lies wholly behind the playback time; never run more than one interval behind. */
  function prune() {
    if (snaps.length >= 2) playT = Math.max(playT, snaps[snaps.length - 2].at);
    while (snaps.length > 2 && snaps[1].at <= playT) snaps.shift();
    while (snaps.length > KEEP) snaps.shift();
  }

  function still(snap, name) {
    const place = snap.places.get(name);
    if (!place) return null;
    const last = facings.get(name);
    return {working: place.working, offsetM: place.offsetM, facing: last && last.working === place.working ? last.facing : 1, moving: false};
  }

  return {
    /**
     * A new publication arrived at `at` (wall ms) with the people's places and the routes published with them.
     * `allow`: motion is allowed (the model runs, fresh data, the same run, no reduced motion, the page shown); else
     * the buffer is reset to this publication and everyone stands where published. True while someone walks.
     * @param {Object} layout
     * @param {{at: number, places: Map<string, {working: string, offsetM: number}>, routes: Map<string, Array>,
     *          paths?: Map<string, (from: Object, to: Object) => ({pieces: Array, length: number}|null)>}} publication
     *        paths: the path of a name between its two places, instead of a published route (the loaders)
     * @param {boolean} allow
     */
    publish(layout, publication, allow) {
      const {at, places, routes, paths = null} = publication;
      const prev = snaps[snaps.length - 1] || null;
      if (prev) {
        const gap = at - prev.at;
        if (gap > 0 && gap < 5000) {
          gaps.push(gap);
          if (gaps.length > 6) gaps.shift();
          interval = clamp(median(gaps), INTERVAL.min, INTERVAL.max);
        }
      }
      if (!allow || !prev || !layout) {
        snaps = [{at, places, routes, legs: new Map()}];
        playT = at;
        lastNow = null;
        return false;
      }
      const legs = new Map();
      for (const [name, place] of places) {
        const before = prev.places.get(name);
        if (!before || samePlace(before, place)) continue;
        const path = paths ? paths.get(name) : null;
        legs.set(name, path ? path(before, place) : legBetween(layout, before, place, prev.routes.get(name) || null));
      }
      const wasIdle = !pending();
      snaps.push({at, places, routes, legs});
      if (wasIdle) {
        // Everyone stood still: the walk starts from the places drawn now, with the clock of this arrival.
        playT = prev.at;
        lastNow = at;
      }
      prune();
      return pending();
    },

    /** Advance the playback clock to `now`; true while someone still walks (frames are needed). */
    step(now) {
      if (snaps.length === 0) return false;
      const newest = snaps[snaps.length - 1].at;
      if (!pending()) {
        playT = newest;
        lastNow = now;
        prune();
        return false;
      }
      const dt = lastNow === null ? 16 : clamp(now - lastNow, 0, MAX_DT);
      lastNow = now;
      const rate = clamp(1 + (now - playT - interval) / RATE_MS, RATE[0], RATE[1]);
      playT = Math.min(playT + dt * rate, newest);
      prune();
      return pending();
    },

    /** Everyone to the newest published place at once (pause, old data, a failed read, the page shown again). */
    snap() {
      const walking = pending();
      if (snaps.length > 1) snaps = [snaps[snaps.length - 1]];
      if (snaps.length > 0) {
        snaps[0].legs = new Map();
        playT = snaps[0].at;
      }
      lastNow = null;
      return walking;
    },

    /** Forget every publication (a new run, another topology). */
    clear() {
      clears += 1;
      snaps = [];
      facings.clear();
      lastNow = null;
    },

    /** Where a person is drawn at the playback time: {working, offsetM, facing, moving}, or null when not published. */
    place(name) {
      if (snaps.length === 0) return null;
      const j = bracket(playT);
      if (j < 0) return still(snaps[snaps.length - 1], name);
      const older = snaps[j - 1];
      const newer = snaps[j];
      const leg = newer.legs.get(name);
      if (!leg) return still(newer, name);
      const f = clamp((playT - older.at) / Math.max(newer.at - older.at, 1), 0, 1);
      const metres = leg.length * f;
      const at = alongStep(leg.pieces, metres);
      const piece = pieceAt(leg.pieces, metres);
      const sign = Math.sign(piece.end - piece.start);
      if (sign !== 0) facings.set(name, {working: piece.working, facing: sign});
      else if (!facings.has(name)) facings.set(name, {working: at.working, facing: 1});
      const facing = facings.get(name).working === at.working ? facings.get(name).facing : 1;
      return {working: at.working, offsetM: at.offsetM, facing, moving: leg.length > STILL_M};
    },

    /** The people walking now (between two different published places at the playback time). */
    moving() {
      const j = bracket(playT);
      if (j < 0) return [];
      return [...snaps[j].legs].filter(([name, leg]) => leg && leg.length > STILL_M && !name.startsWith(MACHINE)).map(([name]) => name).sort();
    },

    /** For tests: the buffer as it is. */
    info(now = performance.now()) {
      return {
        snapshots: snaps.length, interval: Math.round(interval), lag: snaps.length ? Math.round(now - playT) : null,
        behind: snaps.length ? Math.round(snaps[snaps.length - 1].at - playT) : null, walking: pending(), clears,
        moving: this.moving(),
      };
    },
  };
}
