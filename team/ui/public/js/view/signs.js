// Signs of the three axes for the panels, as inline SVG (never a font glyph):
// the shapes of the legend. Decorative: the words next to a sign always say
// the same thing.

import {glyph, s} from '../dom.js';

const SIGN = {
  // Reachability of a worker: white crossed square (no route), arrow along a line (route of the model).
  noroute: () => [s('rect', {x: 2.2, y: 2.2, width: 11.6, height: 11.6}), s('path', {d: 'M2.2 2.2l11.6 11.6M13.8 2.2L2.2 13.8'})],
  route: () => [s('path', {d: 'M1.8 8h11'}), s('path', {d: 'M9.6 4.6L13 8l-3.4 3.4'})],
  // A closed passage: a barrier across the band.
  closed: () => [s('path', {d: 'M2 4v8M14 4v8'}), s('path', {d: 'M2 8h12', 'stroke-dasharray': '2.4 1.6'})],
  // Knowledge: a lost measurement is a crossed sensor head.
  lost: () => [s('circle', {cx: 8, cy: 8, r: 5.6, 'stroke-dasharray': '2 1.6'}), s('path', {d: 'M3 13L13 3'})],
  none: () => [s('path', {d: 'M2 8h12'})],
};

/**
 * A 16 px sign. Names of dom.js `glyph` (danger, attention, unknown, info, ok, pause, clock, blocked)
 * plus noroute, route, closed, lost, none.
 * @param {string} name
 * @returns {SVGElement}
 */
export function sign(name) {
  if (!SIGN[name]) return glyph(name);
  return s('svg', {
    class: `glyph glyph--${name}`, viewBox: '0 0 16 16', width: 16, height: 16, 'aria-hidden': 'true', focusable: 'false',
    fill: 'none', 'data-glyph': name,
  }, SIGN[name]());
}

/** Show the sign `name` as the only child of `holder`; nothing is touched when it is already there. */
export function setSign(holder, name) {
  const current = holder.firstElementChild;
  if (current && current.getAttribute('data-glyph') === name) return;
  holder.replaceChildren(sign(name));
}
