// The camera of art mode (mine-art SPEC §4): one OrthographicCamera with a fixed
// viewing direction (azimuth and elevation of the art's MainView, or the
// defaults of the spec), moved only by pan and zoom. It has the interface of
// createOrbit (camera.js), so the scene frames, fits and projects with either.
//
// Every move is a critically damped spring from where the camera is towards a
// goal (the target and the log of the distance): it never overshoots (a
// component that would cross its goal stops on it), it ends exactly on its goal
// (snapped once it is within a hundredth of a pixel or so) and nothing moves
// after that (no inertia, no idle drift). A glide takes its duration as the
// time to settle; under reduced motion every move is instant. The user's goals
// (drag, wheel, pinch, keys) are clamped: the distance between the overview's
// (1×, limits.distMax) and a quarter of it (4×), the target to the mine's
// bounds on the view plane (limits.box, setBounds).

import * as THREE from 'three';
import {placeCamera} from './camera.js';

const DEG = Math.PI / 180;
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
/** The default glide of the scene (camera.js GLIDE_MS). */
const GLIDE_MS = 600;
/** Settling time of a user's pan or zoom, and of a drag following the pointer (ms). */
const USER_MS = 360;
const DRAG_MS = 110;
/** ω·t at which a critically damped glide from rest has come to within about 0.5 % of its way: ω = SETTLE_WT / ms. */
const SETTLE_WT = 7.4;
/** Zoom range of art mode: 1× is the overview of the whole mine, ART_ZOOM_MAX the closest. */
export const ART_ZOOM_MAX = 4;

/**
 * @param {THREE.OrthographicCamera} camera  carries `fov` and `aspect` (camera.js placeCamera)
 * @param {{reducedMotion: () => boolean, az: number, el: number}} options
 */
export function createArtRig(camera, options) {
  const state = {target: new THREE.Vector3(), az: options.az, el: options.el, dist: 800};
  const limits = {distMax: 6000, distMin: 6000 / ART_ZOOM_MAX, box: null, reach: 4000};
  const goal = {target: new THREE.Vector3(), log: Math.log(800)};
  const velocity = {target: new THREE.Vector3(), log: 0};
  let omega = SETTLE_WT / USER_MS;
  let moving = false;
  let lastStep = null;
  const axes = {right: new THREE.Vector3(1, 0, 0), up: new THREE.Vector3(0, 1, 0), forward: new THREE.Vector3(0, 0, -1)};

  /** The camera's axes for its direction (as Matrix4.lookAt builds them for a camera): x right, y up, z back. */
  function updateAxes() {
    const back = new THREE.Vector3(Math.sin(state.az) * Math.cos(state.el), Math.sin(state.el), Math.cos(state.az) * Math.cos(state.el));
    axes.right.crossVectors(new THREE.Vector3(0, 1, 0), back).normalize();
    axes.up.crossVectors(back, axes.right).normalize();
    axes.forward.copy(back).negate();
  }
  updateAxes();

  const halfHeight = (dist) => dist * Math.tan((camera.fov * DEG) / 2);
  const logRange = () => [Math.log(Math.max(limits.distMin, 1e-3)), Math.log(Math.max(limits.distMax, limits.distMin, 1e-3))];

  function apply() {
    placeCamera(camera, state.target, state.dist, state.az, state.el, camera.aspect, limits.reach);
  }

  function stop() {
    velocity.target.set(0, 0, 0);
    velocity.log = 0;
  }

  /** The user's goals stay in the range of art mode: 1× … 4×, the target over the mine. */
  function clampGoal() {
    const [lo, hi] = logRange();
    goal.log = clamp(goal.log, lo, hi);
    const b = limits.box;
    if (!b) return;
    const u = goal.target.dot(axes.right);
    const v = goal.target.dot(axes.up);
    goal.target.addScaledVector(axes.right, clamp(u, b.minU, b.maxU) - u).addScaledVector(axes.up, clamp(v, b.minV, b.maxV) - v);
  }

  function jumpToGoal() {
    state.target.copy(goal.target);
    state.dist = Math.exp(goal.log);
    stop();
    moving = false;
    lastStep = null;
    apply();
  }

  /** A goal from a view: every distance in the zoom range (a framing that would need more room is shown at 1×). */
  function setGoal(view, free = false) {
    if (view.target) goal.target.copy(view.target);
    if (Number.isFinite(view.dist) && view.dist > 0) goal.log = Math.log(view.dist);
    const [lo, hi] = logRange();
    if (!free) goal.log = clamp(goal.log, lo, hi);
  }

  /**
   * Jump to a view at once. The direction of art mode is fixed: only the target and the distance are taken.
   * `free`: outside the zoom range (the start of the intro, a little farther than the overview).
   */
  function set(view, free = false) {
    setGoal(view, free);
    jumpToGoal();
  }

  function start(ms) {
    if (options.reducedMotion() || ms <= 0) {
      jumpToGoal();
      return;
    }
    omega = SETTLE_WT / ms;
    if (!moving) lastStep = null;
    moving = true;
  }

  /** Glide to a view, settling in about `duration` ms; the distance of a framing is kept in the zoom range. */
  function glideTo(view, duration = GLIDE_MS) {
    setGoal(view);
    start(duration);
  }

  /** A new end for the running glide (its speed is kept); a jump when none runs. */
  function retarget(view) {
    if (!moving || options.reducedMotion()) {
      set(view);
      return;
    }
    setGoal(view);
  }

  /** A drag pans whatever the button: the point under the pointer follows it. There is no rotation in art mode. */
  function drag(kind, dx, dy, viewHeight) {
    const perPixel = (2 * halfHeight(Math.exp(goal.log))) / Math.max(viewHeight, 1);
    goal.target.addScaledVector(axes.right, -dx * perPixel).addScaledVector(axes.up, dy * perPixel);
    clampGoal();
    start(DRAG_MS);
  }

  function release() {}

  /**
   * Zoom by a factor of the distance (< 1 closer). With an `anchor` ({x, y, width, height} in stage pixels) the
   * point under it stays under it (the wheel and a pinch zoom towards the pointer); else towards the middle.
   */
  function zoom(factor, animate = true, anchor = null) {
    const before = Math.exp(goal.log);
    goal.log = Math.log(before * factor);
    const [lo, hi] = logRange();
    goal.log = clamp(goal.log, lo, hi);
    const after = Math.exp(goal.log);
    if (anchor && anchor.width > 0 && anchor.height > 0) {
      const perPixel = (2 * halfHeight(before)) / anchor.height;
      const keep = 1 - after / before;
      goal.target.addScaledVector(axes.right, (anchor.x - anchor.width / 2) * perPixel * keep)
        .addScaledVector(axes.up, (anchor.height / 2 - anchor.y) * perPixel * keep);
    }
    clampGoal();
    if (animate) start(USER_MS);
    else jumpToGoal();
  }

  /** No orbit in art mode. */
  function rotate() {}

  /** Pan by metres along the screen's right and up. */
  function pan(rightMetres, upMetres) {
    goal.target.addScaledVector(axes.right, rightMetres).addScaledVector(axes.up, upMetres);
    clampGoal();
    start(USER_MS);
  }

  /** Advance the spring by the time since the last frame; true while the camera still moves. */
  function step(now) {
    if (!moving) {
      apply();
      return false;
    }
    const dt = lastStep === null ? 16 : clamp(now - lastStep, 0, 64);
    lastStep = now;
    const e = Math.exp(-omega * dt);
    const advance = (x, g, v) => {
      const y = x - g;
      const t = (v + omega * y) * dt;
      let y1 = (y + t) * e;
      let v1 = (v - omega * t) * e;
      // From rest a critically damped spring never crosses its goal; a goal moved towards a moving camera could: stop on it.
      if (y !== 0 && y1 !== 0 && Math.sign(y1) !== Math.sign(y)) {
        y1 = 0;
        v1 = 0;
      }
      return [g + y1, v1];
    };
    for (const axis of ['x', 'y', 'z']) {
      const [x, v] = advance(state.target[axis], goal.target[axis], velocity.target[axis]);
      state.target[axis] = x;
      velocity.target[axis] = v;
    }
    const [log, vLog] = advance(Math.log(state.dist), goal.log, velocity.log);
    velocity.log = vLog;
    state.dist = Math.exp(log);
    // Ended: within about a hundredth of a pixel of a 1000-pixel stage, and the distance within 1e-5 of its goal.
    const eps = halfHeight(state.dist) * 2e-5;
    if (state.target.distanceTo(goal.target) < eps && velocity.target.length() * 16 < eps
      && Math.abs(log - goal.log) < 1e-5 && Math.abs(vLog * 16) < 1e-5) {
      jumpToGoal();
      return false;
    }
    apply();
    return true;
  }

  /**
   * The view that shows all `points` with margins (fractions of the half view, as createOrbit.fit): closed form,
   * the orthographic projection being affine. Returns {target, dist}.
   */
  function fit(points, aspect, margin = {x: 0.06, top: 0.1, bottom: 0.1}) {
    if (points.length === 0) return {target: state.target.clone(), dist: state.dist};
    let minU = Infinity; let maxU = -Infinity; let minV = Infinity; let maxV = -Infinity; let w = 0;
    for (const p of points) {
      const u = p.dot(axes.right);
      const v = p.dot(axes.up);
      minU = Math.min(minU, u); maxU = Math.max(maxU, u);
      minV = Math.min(minV, v); maxV = Math.max(maxV, v);
      w += p.dot(axes.forward);
    }
    w /= points.length;
    const halfH = Math.max((maxU - minU) / (Math.max(aspect, 1e-3) * (2 - 2 * margin.x)), (maxV - minV) / (2 - margin.top - margin.bottom), 1);
    const v = (minV + maxV) / 2 - halfH * ((margin.bottom - margin.top) / 2);
    const target = new THREE.Vector3().addScaledVector(axes.right, (minU + maxU) / 2).addScaledVector(axes.up, v).addScaledVector(axes.forward, w);
    return {target, dist: halfH / Math.tan((camera.fov * DEG) / 2)};
  }

  /** The pan bounds: the extent of `points` ([x, y, z]) on the view plane, grown by `grow` of its size on every side. */
  function setBounds(points, grow = 0.08) {
    let minU = Infinity; let maxU = -Infinity; let minV = Infinity; let maxV = -Infinity;
    const p = new THREE.Vector3();
    for (const point of points) {
      p.set(point[0], point[1], point[2]);
      const u = p.dot(axes.right);
      const v = p.dot(axes.up);
      minU = Math.min(minU, u); maxU = Math.max(maxU, u);
      minV = Math.min(minV, v); maxV = Math.max(maxV, v);
    }
    if (!Number.isFinite(minU)) {
      limits.box = null;
      return;
    }
    const gu = (maxU - minU) * grow;
    const gv = (maxV - minV) * grow;
    limits.box = {minU: minU - gu, maxU: maxU + gu, minV: minV - gv, maxV: maxV + gv};
  }

  /** A new viewing direction (the MainView of the art); the bounds must be set again (setBounds). */
  function setView(az, el) {
    state.az = az;
    state.el = el;
    updateAxes();
    apply();
  }

  /** Where the view plane coordinates of the target lie in the pan bounds (tests): [u, v] and the box. */
  function where() {
    return {u: state.target.dot(axes.right), v: state.target.dot(axes.up), box: limits.box};
  }

  return {
    art: true, state, limits, axes, apply, set, glideTo, retarget, drag, release, zoom, rotate, pan, step, fit, stop, setBounds, setView, where,
    get gliding() {
      return moving;
    },
    /** Where the camera is going: the goal of the spring. */
    get goal() {
      return {target: goal.target, az: state.az, el: state.el, dist: Math.exp(goal.log)};
    },
    /** The zoom now: 1 at the overview (limits.distMax) … ART_ZOOM_MAX. */
    get zoomFactor() {
      return limits.distMax / state.dist;
    },
  };
}
