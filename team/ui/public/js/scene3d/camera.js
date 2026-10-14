// The camera: an orbit around a target, with damped drag, glides and a fit
// that keeps a box in view. The azimuth is the angle of the camera around the
// vertical, 0 from the south (+Z), growing towards the east (+X). A glide
// moves target and distance (and elevation when asked) and never turns the
// azimuth, so orientation is kept between the overview and a close view.

import * as THREE from 'three';

const DEG = Math.PI / 180;
export const LIMITS = {elMin: 8 * DEG, elMax: 84 * DEG, distMin: 25};
const GLIDE_MS = 600;
const DAMP_MS = 140;

const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - ((-2 * t + 2) ** 3) / 2);
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

/**
 * @param {THREE.PerspectiveCamera} camera
 * @param {{reducedMotion: () => boolean}} options
 */
export function createOrbit(camera, options) {
  const state = {target: new THREE.Vector3(), az: 20 * DEG, el: 30 * DEG, dist: 800};
  const limits = {distMax: 6000, box: null};
  const velocity = {az: 0, el: 0, pan: new THREE.Vector3(), zoom: 0};
  let glide = null;
  let lastStep = null;

  function apply() {
    state.el = clamp(state.el, LIMITS.elMin, LIMITS.elMax);
    state.dist = clamp(state.dist, LIMITS.distMin, limits.distMax);
    if (limits.box) {
      const b = limits.box;
      state.target.set(clamp(state.target.x, b.minX, b.maxX), clamp(state.target.y, b.minY, b.maxY), clamp(state.target.z, b.minZ, b.maxZ));
    }
    const {target, az, el, dist} = state;
    camera.position.set(target.x + dist * Math.sin(az) * Math.cos(el), target.y + dist * Math.sin(el),
      target.z + dist * Math.cos(az) * Math.cos(el));
    camera.up.set(0, 1, 0);
    camera.lookAt(target);
    camera.near = Math.max(dist / 200, 0.5);
    camera.far = dist * 6 + 4000;
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
  }

  function stop() {
    velocity.az = 0;
    velocity.el = 0;
    velocity.pan.set(0, 0, 0);
    velocity.zoom = 0;
  }

  /** Jump to a view at once. */
  function set(view) {
    glide = null;
    stop();
    if (view.target) state.target.copy(view.target);
    if (Number.isFinite(view.az)) state.az = view.az;
    if (Number.isFinite(view.el)) state.el = view.el;
    if (Number.isFinite(view.dist)) state.dist = view.dist;
    apply();
  }

  /** Glide to a view; instant under reduced motion. Fields not given keep their value. */
  function glideTo(view, duration = GLIDE_MS) {
    stop();
    if (options.reducedMotion() || duration <= 0) {
      set(view);
      return;
    }
    glide = {
      start: null, duration,
      from: {target: state.target.clone(), az: state.az, el: state.el, dist: state.dist},
      to: {
        target: view.target ? view.target.clone() : state.target.clone(),
        az: Number.isFinite(view.az) ? view.az : state.az,
        el: Number.isFinite(view.el) ? view.el : state.el,
        dist: Number.isFinite(view.dist) ? view.dist : state.dist,
      },
    };
  }

  /** A new end for the running glide (the stage changed under it); a jump when none runs. */
  function retarget(view) {
    if (!glide || options.reducedMotion()) {
      set(view);
      return;
    }
    if (view.target) glide.to.target.copy(view.target);
    for (const name of ['az', 'el', 'dist']) if (Number.isFinite(view[name])) glide.to[name] = view[name];
  }

  /** Right and forward unit vectors of the ground plane as seen from the camera. */
  function groundAxes() {
    const right = new THREE.Vector3(Math.cos(state.az), 0, -Math.sin(state.az));
    const forward = new THREE.Vector3(-Math.sin(state.az), 0, -Math.cos(state.az));
    return {right, forward};
  }

  /** Move the target by screen pixels (drag) at the current distance. */
  function panPixels(dx, dy, viewHeight) {
    const perPixel = (2 * state.dist * Math.tan((camera.fov * DEG) / 2)) / Math.max(viewHeight, 1);
    const {right, forward} = groundAxes();
    const move = right.multiplyScalar(-dx * perPixel).add(forward.multiplyScalar(dy * perPixel / Math.max(Math.sin(state.el), 0.35)));
    state.target.add(move);
    return move;
  }

  /** Rotation, pan and zoom from a drag, with velocities kept for the damping after release. */
  function drag(kind, dx, dy, viewHeight, dt) {
    glide = null;
    if (kind === 'rotate') {
      const daz = -dx * 0.006;
      const del = dy * 0.005;
      state.az += daz;
      state.el += del;
      velocity.az = dt > 0 ? daz / dt : 0;
      velocity.el = dt > 0 ? del / dt : 0;
    } else {
      const move = panPixels(dx, dy, viewHeight);
      velocity.pan.copy(move).multiplyScalar(dt > 0 ? 1 / dt : 0);
    }
    apply();
  }

  function release() {
    if (options.reducedMotion()) stop();
    lastStep = null;
  }

  /** Zoom by a factor around the target. */
  function zoom(factor, animate = false) {
    const dist = clamp(state.dist * factor, LIMITS.distMin, limits.distMax);
    if (animate) glideTo({dist}, 220);
    else {
      glide = null;
      state.dist = dist;
      apply();
    }
  }

  function rotate(daz, del) {
    glideTo({az: state.az + daz, el: clamp(state.el + del, LIMITS.elMin, LIMITS.elMax)}, 260);
  }

  function pan(dxMetres, dzMetres) {
    const {right, forward} = groundAxes();
    const target = state.target.clone().add(right.multiplyScalar(dxMetres)).add(forward.multiplyScalar(dzMetres));
    glideTo({target}, 260);
  }

  /** Advance glides and damping; true while something still moves. */
  function step(now) {
    let active = false;
    if (glide) {
      if (glide.start === null) glide.start = now;
      const t = clamp((now - glide.start) / glide.duration, 0, 1);
      const e = ease(t);
      state.target.lerpVectors(glide.from.target, glide.to.target, e);
      state.az = glide.from.az + (glide.to.az - glide.from.az) * e;
      state.el = glide.from.el + (glide.to.el - glide.from.el) * e;
      // Distance changes geometrically: a close view does not rush in at the end.
      state.dist = glide.from.dist * ((glide.to.dist / glide.from.dist) ** e);
      if (t >= 1) glide = null;
      else active = true;
      lastStep = now;
    } else {
      const moving = Math.abs(velocity.az) + Math.abs(velocity.el) > 1e-6 || velocity.pan.lengthSq() > 1e-6;
      if (moving && !options.reducedMotion()) {
        const dt = lastStep === null ? 16 : clamp(now - lastStep, 1, 64);
        state.az += velocity.az * dt;
        state.el += velocity.el * dt;
        state.target.addScaledVector(velocity.pan, dt);
        const decay = Math.exp(-dt / DAMP_MS);
        velocity.az *= decay;
        velocity.el *= decay;
        velocity.pan.multiplyScalar(decay);
        if (Math.abs(velocity.az) < 2e-6 && Math.abs(velocity.el) < 2e-6 && velocity.pan.length() < 2e-4) stop();
        else active = true;
        lastStep = now;
      } else {
        stop();
        lastStep = null;
      }
    }
    apply();
    return active;
  }

  /**
   * The view that shows all `points` with margins (fractions of the half view).
   * Keeps azimuth and elevation; returns {target, dist}.
   */
  function fit(points, aspect, margin = {x: 0.06, top: 0.1, bottom: 0.1}, az = state.az, el = state.el) {
    const probe = camera.clone();
    probe.aspect = aspect;
    const centre = new THREE.Vector3();
    for (const p of points) centre.add(p);
    centre.multiplyScalar(1 / Math.max(points.length, 1));
    let target = centre.clone();
    let dist = 1000;
    const place = (t, d) => {
      probe.position.set(t.x + d * Math.sin(az) * Math.cos(el), t.y + d * Math.sin(el), t.z + d * Math.cos(az) * Math.cos(el));
      probe.up.set(0, 1, 0);
      probe.lookAt(t);
      probe.near = Math.max(d / 200, 0.5);
      probe.far = d * 6 + 4000;
      probe.updateProjectionMatrix();
      probe.updateMatrixWorld();
    };
    const extent = (t, d) => {
      place(t, d);
      const box = {minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity};
      const v = new THREE.Vector3();
      for (const p of points) {
        v.copy(p).project(probe);
        box.minX = Math.min(box.minX, v.x); box.maxX = Math.max(box.maxX, v.x);
        box.minY = Math.min(box.minY, v.y); box.maxY = Math.max(box.maxY, v.y);
      }
      return box;
    };
    for (let round = 0; round < 6; round += 1) {
      // Distance: scale so the projected extent fills the allowed part of the view.
      const box = extent(target, dist);
      const needX = (box.maxX - box.minX) / (2 - 2 * margin.x);
      const needY = (box.maxY - box.minY) / (2 - margin.top - margin.bottom);
      dist *= Math.max(needX, needY, 0.05);
      // Centre: shift the target so the projected box sits in the middle of the allowed area.
      const after = extent(target, dist);
      const cxNdc = (after.minX + after.maxX) / 2;
      const cyNdc = (after.minY + after.maxY) / 2 - (margin.bottom - margin.top) / 2;
      const right = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 1);
      const halfH = dist * Math.tan((probe.fov * DEG) / 2);
      target = target.clone().addScaledVector(right, cxNdc * halfH * aspect).addScaledVector(up, cyNdc * halfH);
    }
    return {target, dist};
  }

  return {
    state, limits, apply, set, glideTo, retarget, drag, release, zoom, rotate, pan, step, fit, stop,
    get gliding() {
      return glide !== null;
    },
    /** Where the camera is going: the end of the running glide, or where it is. */
    get goal() {
      return glide ? glide.to : {target: state.target, az: state.az, el: state.el, dist: state.dist};
    },
  };
}
