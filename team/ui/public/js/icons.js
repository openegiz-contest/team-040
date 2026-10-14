// The symbols of the scheme, as inline SVG. The scheme and the legend build
// their marks with the same functions, so a sample in the legend cannot
// differ from the object it explains. Every state differs by shape, hatch or
// sign (scheme.css adds colour as a second cue only).

import {s, setAttrs} from './dom.js';

const QUESTION = 'M-2 -1.6a2 2 0 1 1 2.9 1.8c-.6.3-.9.7-.9 1.4M0 3.6v.5';

/** Signs in a 16 px box centred on the origin: [tag, attributes]. */
const SIGNS = {
  danger: [['path', {d: 'M-2.8 -6.5h5.6l3.7 3.7v5.6l-3.7 3.7h-5.6l-3.7 -3.7v-5.6z'}], ['path', {d: 'M0 -3.6v4.4M0 2.9v.6'}]],
  attention: [['path', {d: 'M0 -6.2l6.6 12h-13.2z'}], ['path', {d: 'M0 -1.8v3.6M0 3.6v.5'}]],
  unknown: [['circle', {r: 6.4, 'stroke-dasharray': '2.2 1.8'}], ['path', {d: QUESTION}]],
  // The last known danger: the octagon of danger, dashed because it is no longer current.
  lastDanger: [['path', {d: 'M-2.8 -6.5h5.6l3.7 3.7v5.6l-3.7 3.7h-5.6l-3.7 -3.7v-5.6z', 'stroke-dasharray': '2.2 1.6'}],
    ['path', {d: 'M0 -3.6v4.4M0 2.9v.6'}]],
  pending: [['circle', {r: 7.2, 'stroke-dasharray': '2.6 2'}], ['path', {d: 'M0 -3.8V0l2.6 1.6'}]],
  blocked: [['circle', {r: 6.4}], ['path', {d: 'M-3.8 0h7.6', 'stroke-width': 2.4}]],
  stopped: [['rect', {x: -6.2, y: -6.2, width: 12.4, height: 12.4}], ['path', {d: 'M-2 -3v6M2 -3v6'}]],
  leaving: [['path', {d: 'M-6.5 0h8.5M-1.5 -3.5l3.5 3.5l-3.5 3.5M6 -6v12'}]],
  question: [['path', {d: QUESTION}]],
};

/**
 * @param {keyof typeof SIGNS} name
 * @param {number} [scale]
 * @returns {SVGGElement}
 */
export function sign(name, scale = 1) {
  return s('g', {class: `sign sign--${name}`, 'data-sign': name, transform: scale === 1 ? null : `scale(${scale})`},
    (SIGNS[name] || SIGNS.unknown).map(([tag, attrs]) => s(tag, attrs)));
}

/** The sign of a displayed hazard state; nothing for «норма». */
export function hazardSign(state) {
  return {attention: 'attention', danger: 'danger', unknown: 'unknown'}[state] || null;
}

/**
 * Hatch patterns of the hazard axis: sparse slanted lines for «внимание»,
 * dense crossed lines for «опасно». `prefix` keeps the ids apart when the
 * scheme and the legend are in one document.
 */
export function patterns(prefix) {
  return [
    s('pattern', {id: `${prefix}-attention`, class: 'hatch hatch--attention', width: 7, height: 7, patternUnits: 'userSpaceOnUse'},
      s('rect', {width: 7, height: 7}), s('path', {d: 'M-1 -1L8 8'})),
    s('pattern', {id: `${prefix}-danger`, class: 'hatch hatch--danger', width: 4, height: 4, patternUnits: 'userSpaceOnUse'},
      s('rect', {width: 4, height: 4}), s('path', {d: 'M-1 -1L5 5M-1 5L5 -1'})),
  ];
}

const parts = new WeakMap();

/** Keep the child `name` of `group` present exactly while `on` is true. */
function part(group, name, on, create) {
  let map = parts.get(group);
  if (!map) parts.set(group, map = new Map());
  let node = map.get(name) || null;
  if (on && !node) {
    node = create();
    map.set(name, node);
    group.append(node);
  } else if (!on && node) {
    node.remove();
    map.delete(name);
    node = null;
  }
  return node;
}

const at = (slot) => `translate(${slot.x} ${slot.y})`;

/**
 * @typedef {Object} WorkingLook
 * @property {'normal'|'attention'|'danger'|'unknown'} hazard the displayed hazard
 * @property {boolean} bare no sensors by design: a thin line instead of a band
 * @property {boolean} closed the passage is closed: a gap, a barrier and a cross
 * @property {boolean} lastDanger the state is unknown and the last known one was danger
 * @property {boolean} restricted the model forbids new entry
 * @property {boolean} pending an unconfirmed command of this page targets the working
 * @property {boolean} unknownPass the passability itself is not known
 */

/**
 * Draw or update a working inside its group. Children are created only for
 * the state they show and are updated in place.
 * @param {SVGGElement} group
 * @param {ReturnType<typeof import('./geometry.js').workingShape>} shape
 * @param {WorkingLook} look
 * @param {string} prefix of the hatch patterns in this SVG
 */
export function drawWorking(group, shape, look, prefix) {
  setAttrs(part(group, 'hit', true, () => s('path', {class: 'working__hit'})), {d: shape.line});
  setAttrs(part(group, 'focus', true, () => s('path', {class: 'obj__focus'})), {d: shape.frame});
  const hatch = look.hazard === 'attention' || look.hazard === 'danger' ? `url(#${prefix}-${look.hazard})` : null;
  const split = look.closed ? 'Split' : '';
  const body = setAttrs(part(group, 'body', true, () => s('path')), {
    class: look.bare ? 'working__line' : 'working__band',
    d: shape[(look.bare ? 'line' : 'band') + split],
  });
  // Inline, because a stylesheet rule would win over a fill attribute.
  const fill = look.bare || !hatch ? '' : hatch;
  if (body.style.fill !== fill) body.style.fill = fill;
  const barrier = part(group, 'barrier', look.closed, () => s('g', {class: 'working__barrier'},
    s('path', {class: 'working__bars', d: 'M-7 -8v16M7 -8v16'}), s('path', {class: 'working__cross', d: 'M-4.5 -4.5l9 9M-4.5 4.5l9 -9'})));
  if (barrier) setAttrs(barrier, {transform: `${at(shape.slots[0])} rotate(${shape.slots[0].angle})`});

  const marks = [];
  if (look.unknownPass) marks.push('question');
  else if (look.lastDanger) marks.push('lastDanger');
  else if (look.hazard === 'unknown' && !look.bare) marks.push('unknown');
  if (look.restricted) marks.push('blocked');
  // The barrier takes the middle; signs stand beside it.
  const free = look.closed ? shape.slots.slice(1) : shape.slots;
  for (const name of ['question', 'lastDanger', 'unknown', 'blocked']) {
    const index = marks.indexOf(name);
    const node = part(group, name, index >= 0, () => s('g', {class: 'working__mark'}, s('circle', {class: 'working__plate', r: 7.5}), sign(name, 0.8)));
    if (node) setAttrs(node, {transform: at(free[Math.min(index, free.length - 1)])});
  }
  const pending = part(group, 'pending', look.pending, () => s('g', {class: 'working__mark working__mark--pending'},
    s('circle', {class: 'working__plate', r: 9}), sign('pending')));
  if (pending) {
    // Above the working, so that the state under the unconfirmed command stays readable.
    const slot = shape.slots[0];
    const turn = slot.angle * Math.PI / 180;
    const up = Math.cos(turn) >= 0 ? -1 : 1;
    setAttrs(pending, {transform: `translate(${slot.x - Math.sin(turn) * 15 * up} ${slot.y + Math.cos(turn) * 15 * up})`});
  }
}

/**
 * The mark of keyboard focus of a symbol: a dashed frame around its box, an
 * element of its own. Selection is drawn on the symbol itself (its `__hit`
 * shape, solid), so the two differ by structure and can be seen together.
 */
export function focusFrame(x, y, width, height) {
  return s('rect', {class: 'obj__focus', x, y, width, height});
}

/** Children of a worker marker; scheme.css shows the ones that fit `data-egress`, `data-status`, `data-location-hazard`. */
export function workerMarker() {
  return [
    focusFrame(-14, -14, 28, 28),
    s('circle', {class: 'worker__hit', r: 11}),
    s('circle', {class: 'worker__danger', r: 10.5}),
    s('path', {class: 'worker__go', d: 'M9 -4.5l5 4.5l-5 4.5'}),
    s('circle', {class: 'worker__shape worker__ok', r: 6.5}),
    s('g', {class: 'worker__none'}, s('rect', {class: 'worker__shape', x: -6.5, y: -6.5, width: 13, height: 13}), s('path', {d: 'M-6.5 -6.5l13 13M-6.5 6.5l13 -13'})),
    s('g', {class: 'worker__unknown'}, s('circle', {class: 'worker__shape', r: 6.5, 'stroke-dasharray': '2.4 2'}), s('path', {d: QUESTION, transform: 'scale(.82)'})),
  ];
}

/** Children of a sensor marker; scheme.css follows `data-quality`. */
export function sensorMarker() {
  return [
    focusFrame(-13, -13, 26, 26),
    s('circle', {class: 'sensor__hit', r: 9}),
    s('path', {class: 'sensor__body', d: 'M0 -6L6 0L0 6L-6 0z'}),
    s('circle', {class: 'sensor__dot', r: 1.6}),
    s('g', {class: 'sensor__stale', transform: 'translate(6 -6) scale(.62)'}, s('circle', {class: 'sensor__plate', r: 6.4}), s('path', {d: 'M0 -3.6V0l2.6 1.6'})),
    s('path', {class: 'sensor__lost', d: 'M-8 8L8 -8'}),
    s('path', {class: 'sensor__unknown', d: QUESTION, transform: 'scale(.7)'}),
  ];
}

/** Children of an exit marker: a gate pointing up; scheme.css follows `data-state`. */
export function exitMarker() {
  return [
    focusFrame(-15, -16, 30, 32),
    s('rect', {class: 'exit__hit', x: -11, y: -12, width: 22, height: 24}),
    s('path', {class: 'exit__body', d: 'M0 -10L8.5 -3.5V9h-17V-3.5z'}),
    s('path', {class: 'exit__arrow', d: 'M0 5.5v-9M-3.5 -1l3.5 -3.5l3.5 3.5'}),
    s('path', {class: 'exit__unavailable', d: 'M-11 11L11 -12'}),
    s('path', {class: 'exit__unknown', d: QUESTION, transform: 'translate(0 .5) scale(.95)'}),
  ];
}
