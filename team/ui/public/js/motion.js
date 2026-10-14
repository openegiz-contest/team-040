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
