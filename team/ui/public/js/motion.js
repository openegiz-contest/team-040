// Motion that explains a change (clarity pass, section B). Every motion of the
// panels is one finite Web Animation started here: nothing loops, nothing is a
// keyframe rule of a stylesheet, and no intermediate value is ever shown (a
// number crossfades from the old published value to the new one). Nothing
// moves under `prefers-reduced-motion: reduce`, on the first render, while the
// data are old or the link is lost, or while the publications stopped.

import {showsOldData} from './link.js';

/** True when the user asked the system for less motion. */
export function reducedMotion() {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * True when a change on the screen may be shown with motion: a full current snapshot over a working link.
 * @param {import('./store.js').State} state
 */
export function motionAllowed(state) {
  if (reducedMotion() || !state || state.boot !== 'ready' || !state.snapshot) return false;
  const {link} = state;
  return link.link === 'ok' && link.snapshot === 'ok' && link.publications !== 'stopped' && !showsOldData(link);
}

/**
 * Play one animation once. Returns null (and does nothing) when motion is off or the browser has no Web Animations.
 * @param {Element} element
 * @param {Keyframe[]} keyframes
 * @param {KeyframeAnimationOptions} options
 * @returns {Animation|null}
 */
export function play(element, keyframes, options) {
  if (!element || typeof element.animate !== 'function' || reducedMotion()) return null;
  return element.animate(keyframes, {...options, iterations: 1, fill: 'none'});
}

/** Durations of section B, in milliseconds. */
export const MS = {digits: 200, underline: 1000, strip: 180, drawer: 200, dock: 200, disclosure: 180, flash: 450, scope: 150};
export const EASE_OUT = 'cubic-bezier(0, 0, .2, 1)';
export const EASE = 'cubic-bezier(.4, 0, .2, 1)';

// ---- variant 3 «Глубина»: the kinetic language ------------------------------------------------
// Staggered word reveals behind a mask, numbers that slide from the old published value to the new
// one (never through intermediate values), cards that cascade in, lines that draw. Every motion is
// one finite Web Animation of at most LIMIT_MS, started once per change; under reduced motion none.

/** The easing of every motion of the variant: a fast start and a long, soft landing. */
export const EASE_POSTER = 'cubic-bezier(.2, .7, 0, 1)';
/** No motion of the interface lasts longer than this, delays included. */
export const LIMIT_MS = 600;

/**
 * Like play(), but a delayed animation holds its first frame while it waits (fill: backwards), so a stagger
 * never shows the end state first. Nothing remains applied after the end.
 */
export function playIn(element, keyframes, options) {
  if (!element || typeof element.animate !== 'function' || reducedMotion()) return null;
  return element.animate(keyframes, {...options, iterations: 1, fill: 'backwards'});
}

/**
 * One animation per element, one after another, the whole within LIMIT_MS.
 * @param {Element[]} elements
 * @param {Keyframe[]} keyframes
 * @param {{duration?: number, start?: number, step?: number, easing?: string}} [options]
 * @returns {Animation[]}
 */
export function stagger(elements, keyframes, options = {}) {
  const {duration = 420, start = 0, step = 50, easing = EASE_POSTER} = options;
  const length = Math.min(duration, LIMIT_MS - start);
  const room = Math.max(0, LIMIT_MS - length - start);
  const gap = elements.length > 1 ? Math.min(step, room / (elements.length - 1)) : 0;
  return elements.map((element, index) => playIn(element, keyframes, {duration: length, delay: start + index * gap, easing}))
    .filter(Boolean);
}

/**
 * A published number replaced by the next one: the old value leaves upward out of its mask and the new
 * one rises into place. `slot` is the masking box (overflow: hidden) that holds `value`; the ghost of the
 * old text is removed when it has left. Nothing in between is ever shown.
 * @param {HTMLElement} slot
 * @param {HTMLElement} value the node that already shows the new text
 * @param {string} before the old text
 * @param {number} [duration]
 */
export function slideValue(slot, value, before, duration = 380) {
  if (!slot || reducedMotion() || typeof slot.animate !== 'function') return;
  const ghost = document.createElement('span');
  ghost.className = 'k-ghost';
  ghost.setAttribute('aria-hidden', 'true');
  ghost.textContent = before;
  slot.append(ghost);
  const out = ghost.animate([{transform: 'translateY(0)', opacity: 1}, {transform: 'translateY(-100%)', opacity: 0}],
    {duration: Math.round(duration * 0.7), easing: EASE_POSTER, iterations: 1, fill: 'forwards'});
  const drop = () => ghost.remove();
  out.finished.then(drop, drop);
  value.animate([{transform: 'translateY(100%)', opacity: 0}, {transform: 'translateY(0)', opacity: 1}],
    {duration, easing: EASE_POSTER, iterations: 1, fill: 'backwards'});
}
