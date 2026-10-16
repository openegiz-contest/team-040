// The symbols of the mine, as inline SVG. The scheme, the legend and the 3D
// labels build their marks with the same functions, so a sample in the legend
// cannot differ from the object it explains. Every state differs by shape,
// hatch or sign; scheme.css adds colour as a second cue only.
//
// Public API for other views (the 3D stage reuses it for its sprites):
//   symbol(kind, state, options?)        -> <svg class="symbol"> styled by scheme.css
//   symbolMarkup(kind, state, options?)  -> the same as self-contained SVG text, styles inlined
//   SYMBOLS                              -> {kind: [states]} that symbol() knows
// Lower-level builders used by the scheme: sign, hazardSign, patterns,
// drawWorking, focusFrame, workerMarker, sensorMarker, exitMarker.

import {s, setAttrs} from './dom.js';
import {chevrons, linePath, workingShape} from './geometry.js';

/** A question mark in a 16 px box centred on the origin. */
export const QUESTION = 'M-2 -1.6a2 2 0 1 1 2.9 1.8c-.6.3-.9.7-.9 1.4M0 3.6v.5';
const OCTAGON = 'M-2.8 -6.5h5.6l3.7 3.7v5.6l-3.7 3.7h-5.6l-3.7 -3.7v-5.6z';

/** Signs in a 16 px box centred on the origin: [tag, attributes]. */
const SIGNS = {
  danger: [['path', {d: OCTAGON}], ['path', {d: 'M0 -3.6v4.4M0 2.9v.6'}]],
  attention: [['path', {d: 'M0 -6.2l6.6 12h-13.2z'}], ['path', {d: 'M0 -1.8v3.6M0 3.6v.5'}]],
  unknown: [['circle', {r: 6.4, 'stroke-dasharray': '2.2 1.8'}], ['path', {d: QUESTION}]],
  // The last known danger: the octagon of danger, dashed because it is no longer current.
  lastDanger: [['path', {d: OCTAGON, 'stroke-dasharray': '2.2 1.6'}], ['path', {d: 'M0 -3.6v4.4M0 2.9v.6'}]],
  pending: [['circle', {r: 7.2, 'stroke-dasharray': '2.6 2'}], ['path', {d: 'M0 -3.8V0l2.6 1.6'}]],
  blocked: [['circle', {r: 6.4}], ['path', {d: 'M-3.8 0h7.6', 'stroke-width': 2.4}]],
  stopped: [['rect', {x: -6.2, y: -6.2, width: 12.4, height: 12.4}], ['path', {d: 'M-2 -3v6M2 -3v6'}]],
  leaving: [['path', {d: 'M-6.5 0h8.5M-1.5 -3.5l3.5 3.5l-3.5 3.5M6 -6v12'}]],
  question: [['path', {d: QUESTION}]],
  // No computed route: the white crossed square of the worker marker, first in his label.
  noroute: [['rect', {x: -5.6, y: -5.6, width: 11.2, height: 11.2}], ['path', {d: 'M-5.6 -5.6l11.2 11.2M-5.6 5.6l11.2 -11.2'}]],
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

/**
 * A loader in 22 × 14 px (the depth rail): the body, the bucket ahead (+x), two wheels; the ring of a danger place and
 * the pause bar of a stopped machine are drawn by its state (poster.css). Distinct from the round marker of a person.
 */
export function loaderGlyph() {
  return s('svg', {class: 'hz__machine-pic', viewBox: '-12 -8 24 16', width: 22, height: 14, 'aria-hidden': 'true', focusable: 'false'},
    s('rect', {class: 'loader__ring', x: -11, y: -7.5, width: 22, height: 15, rx: 3}),
    s('path', {class: 'loader__body', d: 'M-8 2.5V-2.5h3.5l1.5-3h4.5v5.5h3.5l3 -2.5h1.5v5z'}),
    s('circle', {class: 'loader__wheel', cx: -4.5, cy: 3.6, r: 2.1}), s('circle', {class: 'loader__wheel', cx: 3.5, cy: 3.6, r: 2.1}),
    s('path', {class: 'loader__pause', d: 'M-1.5 -5.5v5M1.5 -5.5v5'}),
    s('path', {class: 'loader__question', d: 'M-1.4 -5.6a1.6 1.6 0 1 1 2.3 1.4c-.5.3-.7.6-.7 1.1M0 -0.7v.4'}));
}

/** The sign of a displayed hazard state; nothing for «норма». */
export function hazardSign(state) {
  return {attention: 'attention', danger: 'danger', unknown: 'unknown'}[state] || null;
}

/**
 * Hatch patterns of the floor of a working: sparse stripes for «внимание»,
 * dense crossed lines for «опасно», a fine fog hatch for «неизвестно».
 * `prefix` keeps the ids apart when several SVGs share one document.
 */
export function patterns(prefix) {
  return [
    s('pattern', {id: `${prefix}-attention`, class: 'hatch hatch--attention', width: 8, height: 8, patternUnits: 'userSpaceOnUse',
      patternTransform: 'rotate(45)'},
    s('rect', {width: 8, height: 8}), s('path', {d: 'M2 -1V9'})),
    s('pattern', {id: `${prefix}-danger`, class: 'hatch hatch--danger', width: 4, height: 4, patternUnits: 'userSpaceOnUse'},
      s('rect', {width: 4, height: 4}), s('path', {d: 'M-1 -1L5 5M-1 5L5 -1'})),
    s('pattern', {id: `${prefix}-unknown`, class: 'hatch hatch--unknown', width: 5, height: 5, patternUnits: 'userSpaceOnUse',
      patternTransform: 'rotate(-45)'},
    s('rect', {width: 5, height: 5}), s('path', {d: 'M0 2.5H5'})),
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
 * @property {boolean} bare no sensors by design: a narrow groove instead of a channel with a floor
 * @property {boolean} closed the passage is closed: a gap, a barricade and a cross
 * @property {boolean} lastDanger the state is unknown and the last known one was danger
 * @property {boolean} restricted the model forbids new entry
 * @property {boolean} pending an unconfirmed command of this page targets the working
 * @property {boolean} unknownPass the passability itself is not known
 */

/**
 * Draw or update a working inside its group: a channel carved in the stone of
 * its level, a dark recess around a floor that carries the hazard (plain,
 * striped, cross-hatched, fog). Children are created only for the state they
 * show and are updated in place.
 * @param {SVGGElement} group
 * @param {ReturnType<typeof import('./geometry.js').workingShape>} shape
 * @param {WorkingLook} look
 * @param {string} prefix of the hatch patterns in this SVG
 */
export function drawWorking(group, shape, look, prefix) {
  setAttrs(part(group, 'hit', true, () => s('path', {class: 'working__hit'})), {d: shape.line});
  setAttrs(part(group, 'focus', true, () => s('path', {class: 'obj__focus'})), {d: shape.frame});
  const split = look.closed ? 'Split' : '';
  // The recess: the dark walls of the channel, under the floor. A groove without sensors has none.
  const recess = part(group, 'recess', !look.bare, () => s('path', {class: 'working__recess'}));
  if (recess) setAttrs(recess, {d: shape[`line${split}`]});
  const hatch = !look.bare && ['attention', 'danger', 'unknown'].includes(look.hazard) ? `url(#${prefix}-${look.hazard})` : '';
  const body = setAttrs(part(group, 'body', true, () => s('path')), {
    class: look.bare ? 'working__line' : 'working__band',
    d: shape[(look.bare ? 'line' : 'band') + split],
  });
  // Inline, because a stylesheet rule would win over a fill attribute.
  if (body.style.fill !== hatch) body.style.fill = hatch;
  const barrier = part(group, 'barrier', look.closed, () => s('g', {class: 'working__barrier'},
    s('rect', {class: 'working__plate', x: -9, y: -10, width: 18, height: 20}),
    s('path', {class: 'working__bars', d: 'M-6 -9v18M6 -9v18'}), s('path', {class: 'working__cross', d: 'M-3.6 -4.5l7.2 9M-3.6 4.5l7.2 -9'})));
  if (barrier) setAttrs(barrier, {transform: `${at(shape.slots[0])} rotate(${shape.slots[0].angle})`});

  const marks = [];
  if (look.unknownPass) marks.push('question');
  else if (look.lastDanger) marks.push('lastDanger');
  else if (look.hazard === 'unknown' && !look.bare) marks.push('unknown');
  if (look.restricted) marks.push('blocked');
  // The barricade takes the middle; signs stand beside it.
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

/** The outer ring of the selection: with the solid `__hit` ring inside it, a chalk-white double outline (scheme.css). */
function selectionRing(r) {
  return s('circle', {class: 'obj__sel', r});
}

/** Children of a worker marker; scheme.css shows the ones that fit `data-egress`, `data-status`, `data-location-hazard`. */
export function workerMarker() {
  return [
    focusFrame(-14, -14, 28, 28),
    selectionRing(14.5),
    s('circle', {class: 'worker__hit', r: 11}),
    s('circle', {class: 'worker__danger', r: 10.5}),
    s('path', {class: 'worker__go', d: 'M9 -4.5l5 4.5l-5 4.5'}),
    s('circle', {class: 'worker__shape worker__ok', r: 6.5}),
    s('g', {class: 'worker__none'}, s('rect', {class: 'worker__shape', x: -6.5, y: -6.5, width: 13, height: 13}), s('path', {d: 'M-6.5 -6.5l13 13M-6.5 6.5l13 -13'})),
    s('g', {class: 'worker__unknown'}, s('circle', {class: 'worker__shape', r: 6.5, 'stroke-dasharray': '2.4 2'}), s('path', {d: QUESTION, transform: 'scale(.82)'})),
  ];
}

/** Children of a sensor marker, an instrument post seen from above; scheme.css follows `data-quality`. */
export function sensorMarker() {
  return [
    focusFrame(-13, -13, 26, 26),
    selectionRing(12.5),
    s('circle', {class: 'sensor__hit', r: 9}),
    s('path', {class: 'sensor__body', d: 'M0 -6L6 0L0 6L-6 0z'}),
    s('circle', {class: 'sensor__dot', r: 1.8}),
    s('g', {class: 'sensor__stale', transform: 'translate(6 -6) scale(.62)'}, s('circle', {class: 'sensor__plate', r: 6.4}), s('path', {d: 'M0 -3.6V0l2.6 1.6'})),
    s('path', {class: 'sensor__lost', d: 'M-8 8L8 -8'}),
    s('path', {class: 'sensor__unknown', d: QUESTION, transform: 'scale(.7)'}),
  ];
}

/** Children of an exit marker: a portal with an upward chevron; scheme.css follows `data-state`. */
export function exitMarker() {
  return [
    focusFrame(-15, -16, 30, 32),
    s('rect', {class: 'obj__sel', x: -14.5, y: -15.5, width: 29, height: 31}),
    s('rect', {class: 'exit__hit', x: -11, y: -12, width: 22, height: 24}),
    s('path', {class: 'exit__body', d: 'M0 -10L8.5 -3.5V9h-17V-3.5z'}),
    s('path', {class: 'exit__arrow', d: 'M0 5.5v-9M-3.5 -1l3.5 -3.5l3.5 3.5'}),
    s('path', {class: 'exit__unavailable', d: 'M-11 11L11 -12'}),
    s('path', {class: 'exit__unknown', d: QUESTION, transform: 'translate(0 .5) scale(.95)'}),
  ];
}

// ---- standalone symbols ------------------------------------------------------

/** What symbol() can draw: kind -> states. */
export const SYMBOLS = {
  hazard: ['normal', 'attention', 'danger', 'unknown', 'lastDanger'],
  knowledge: ['fresh', 'stale', 'lost', 'none'],
  worker: ['ok', 'none', 'unknown', 'inDanger', 'moving'],
  exit: ['available', 'unavailable', 'unknown'],
  passage: ['open', 'closed'],
  route: ['model'],
  sign: Object.keys(SIGNS),
};

let serial = 0;
const SAMPLE = [[-13, 0], [13, 0]];

/**
 * One symbol as a standalone `<svg>`, built by the same functions as the
 * scheme. Its shapes carry the classes of the scheme (`.working`, `.worker`,
 * `.sensor`, `.exit`, `.sign`, `.route`), so scheme.css styles it wherever it
 * is in the document. The hatch patterns it needs are inside it.
 * @param {keyof typeof SYMBOLS} kind
 * @param {string} state one of SYMBOLS[kind]
 * @param {{size?: number, title?: string}} [options] size: height in px (default 16)
 * @returns {SVGSVGElement}
 */
export function symbol(kind, state, options = {}) {
  const prefix = `sym${serial += 1}`;
  let width = 20;
  let body;
  if (kind === 'hazard' || (kind === 'knowledge' && state === 'none') || kind === 'passage') {
    const look = {hazard: 'unknown', bare: false, closed: false, lastDanger: false};
    if (kind === 'hazard') Object.assign(look, state === 'lastDanger' ? {hazard: 'unknown', lastDanger: true} : {hazard: state});
    else Object.assign(look, {bare: true, closed: state === 'closed'});
    body = s('g', {class: ['working', look.lastDanger && 'working--last-danger'], 'data-hazard': look.hazard});
    drawWorking(body, workingShape(SAMPLE, 9), look, prefix);
    width = 30;
  } else if (kind === 'knowledge') {
    body = s('g', {class: 'sensor', 'data-quality': state}, sensorMarker());
  } else if (kind === 'worker') {
    const attrs = {
      ok: {'data-egress': 'ok'}, none: {'data-egress': 'none'}, unknown: {'data-egress': 'unknown'},
      inDanger: {'data-egress': 'ok', 'data-location-hazard': 'danger'}, moving: {'data-egress': 'ok', class: 'worker is-going'},
    }[state] || {'data-egress': 'unknown'};
    body = s('g', {class: 'worker', ...attrs}, workerMarker());
    width = state === 'moving' ? 30 : (state === 'inDanger' ? 24 : 18);
  } else if (kind === 'exit') {
    body = s('g', {class: 'exit', 'data-state': state, transform: 'scale(.72)'}, exitMarker());
  } else if (kind === 'route') {
    const line = [[-18, 0], [18, 0]];
    body = s('g', {class: 'route'}, s('path', {class: 'route__casing', d: linePath(line)}),
      s('path', {class: 'route__line', d: linePath(line)}), s('path', {class: 'route__arrows', d: chevrons(line, 18, 5)}));
    width = 40;
  } else {
    body = sign(state);
    width = 18;
  }
  const size = options.size || 16;
  return s('svg', {
    class: `symbol symbol--${kind}`, 'data-symbol': `${kind}:${state}`,
    width: Math.round(width * size / 16), height: size, viewBox: `${-width / 2} -8 ${width} 16`,
    role: options.title ? 'img' : null, 'aria-label': options.title || null, 'aria-hidden': options.title ? null : 'true',
    focusable: 'false',
  }, s('defs', null, patterns(prefix)), body);
}

const INLINED = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-linecap', 'stroke-linejoin', 'opacity', 'display'];

/**
 * A symbol as self-contained SVG text: the computed style of every shape is
 * written into attributes, so the text can be used as an image source (a
 * sprite texture) without the stylesheet. Needs the document with scheme.css.
 * @param {keyof typeof SYMBOLS} kind
 * @param {string} state
 * @param {{size?: number}} [options]
 * @returns {string}
 */
export function symbolMarkup(kind, state, options = {}) {
  const svg = symbol(kind, state, options);
  const host = document.createElement('div');
  host.className = 'symbol-host';
  host.style.cssText = 'position:absolute;left:-9999px;top:0;';
  host.append(svg);
  document.body.append(host);
  for (const node of svg.querySelectorAll('*')) {
    const style = getComputedStyle(node);
    for (const name of INLINED) {
      const value = style.getPropertyValue(name);
      if (value) node.setAttribute(name, value);
    }
    node.removeAttribute('style');
  }
  host.remove();
  svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  return new XMLSerializer().serializeToString(svg);
}
