// DOM helpers. Platform strings reach the document only through textContent
// and setAttribute: nothing here parses markup.

const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * Apply attributes to an element. `null`, `undefined` and `false` remove an
 * attribute, `true` sets it empty. Special keys: `text` (textContent),
 * `class` (string or array, falsy entries dropped), `dataset` (object, same
 * removal rule), `on` (object of event listeners, added once at creation).
 * A value is written only when it differs, so a re-render does not disturb
 * focus, selection or an open <select>.
 * @param {Element} element
 * @param {Object<string, *>} [attrs]
 * @returns {Element}
 */
export function setAttrs(element, attrs) {
  if (!attrs) return element;
  for (const [name, value] of Object.entries(attrs)) {
    if (name === 'text') {
      setText(element, value);
    } else if (name === 'class') {
      const text = Array.isArray(value) ? value.filter(Boolean).join(' ') : (value || '');
      if (element.getAttribute('class') !== text) element.setAttribute('class', text);
    } else if (name === 'dataset') {
      for (const [key, item] of Object.entries(value || {})) setAttr(element, `data-${key}`, item);
    } else if (name === 'on') {
      for (const [type, listener] of Object.entries(value || {})) element.addEventListener(type, listener);
    } else {
      setAttr(element, name, value);
    }
  }
  return element;
}

function setAttr(element, name, value) {
  if (value === null || value === undefined || value === false) {
    if (element.hasAttribute(name)) element.removeAttribute(name);
    return;
  }
  const text = value === true ? '' : String(value);
  if (element.getAttribute(name) !== text) element.setAttribute(name, text);
}

/**
 * Set textContent only when it changed.
 * @param {Node} node
 * @param {*} value
 */
export function setText(node, value) {
  const text = value === null || value === undefined ? '' : String(value);
  if (node.textContent !== text) node.textContent = text;
}

function append(element, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(element, child);
    else element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

/**
 * Create an HTML element: `h('button', {class: 'btn', type: 'button'}, 'Текст')`.
 * @param {string} tag
 * @param {Object<string, *>} [attrs]
 * @param {...(Node|string|number|Array|null|false)} children
 * @returns {HTMLElement}
 */
export function h(tag, attrs, ...children) {
  return append(setAttrs(document.createElement(tag), attrs), children);
}

/**
 * Create an SVG element: `s('path', {d: 'M0 0L4 4'})`.
 * @param {string} tag
 * @param {Object<string, *>} [attrs]
 * @param {...(Node|string|number|Array|null|false)} children
 * @returns {SVGElement}
 */
export function s(tag, attrs, ...children) {
  return append(setAttrs(document.createElementNS(SVG_NS, tag), attrs), children);
}

/**
 * Remove every child of an element.
 * @param {Element} element
 */
export function clear(element) {
  element.replaceChildren();
}

const keyed = new WeakMap();

/**
 * Keyed reconciliation of the children of `parent`, which must hold nothing
 * but the nodes this function manages. A node whose key survives is reused
 * and updated in place; it is moved only when the order really changed, so a
 * focused element keeps focus and a <select> keeps its open state.
 * @template T
 * @param {Element} parent
 * @param {T[]} items
 * @param {(item: T, index: number) => string} keyOf
 * @param {(item: T, index: number) => Element} create
 * @param {(node: Element, item: T, index: number) => void} [update] also called for a new node
 * @returns {Element[]} the nodes in item order
 */
export function reconcile(parent, items, keyOf, create, update) {
  const previous = keyed.get(parent) || new Map();
  const next = new Map();
  const nodes = [];
  items.forEach((item, index) => {
    const key = String(keyOf(item, index));
    if (next.has(key)) throw new Error(`reconcile: duplicate key ${key}`);
    const node = previous.get(key) || create(item, index);
    if (update) update(node, item, index);
    next.set(key, node);
    nodes.push(node);
  });
  // Stale nodes go first: otherwise a surviving node would be moved around them and lose focus.
  for (const [key, node] of previous) {
    if (!next.has(key)) node.remove();
  }
  nodes.forEach((node, index) => {
    const current = parent.children[index];
    if (current !== node) parent.insertBefore(node, current || null);
  });
  keyed.set(parent, next);
  return nodes;
}

/**
 * Activate with the keyboard like a button: Enter or Space. For elements that
 * cannot be a real <button> (table rows, SVG groups).
 * @param {Element} element
 * @param {(event: Event) => void} activate
 */
export function onActivate(element, activate) {
  element.addEventListener('click', activate);
  element.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
      event.preventDefault();
      activate(event);
    }
  });
}

const GLYPHS = {
  // Each sign differs by outline, not by colour: octagon, triangle, dashed ring, ring, square.
  danger: [
    ['path', {d: 'M5.2 1.5h5.6l3.7 3.7v5.6l-3.7 3.7H5.2l-3.7-3.7V5.2z', fill: 'none'}],
    ['path', {d: 'M8 4.4v4.4M8 10.9v.6', fill: 'none'}],
  ],
  attention: [
    ['path', {d: 'M8 1.8l6.6 12H1.4z', fill: 'none'}],
    ['path', {d: 'M8 6.2v3.6M8 11.6v.5', fill: 'none'}],
  ],
  unknown: [
    ['circle', {cx: 8, cy: 8, r: 6.4, fill: 'none', 'stroke-dasharray': '2.2 1.8'}],
    ['path', {d: 'M6 6.4a2 2 0 1 1 2.9 1.8c-.6.3-.9.7-.9 1.4M8 11.5v.5', fill: 'none'}],
  ],
  info: [
    ['circle', {cx: 8, cy: 8, r: 6.4, fill: 'none'}],
    ['path', {d: 'M8 7.2v4.2M8 4.6v.6', fill: 'none'}],
  ],
  ok: [
    ['circle', {cx: 8, cy: 8, r: 6.4, fill: 'none'}],
    ['path', {d: 'M4.8 8.2l2.2 2.2 4.2-4.6', fill: 'none'}],
  ],
  pause: [
    ['rect', {x: 1.6, y: 1.6, width: 12.8, height: 12.8, fill: 'none'}],
    ['path', {d: 'M6.2 5v6M9.8 5v6', fill: 'none'}],
  ],
  clock: [
    ['circle', {cx: 8, cy: 8, r: 6.4, fill: 'none'}],
    ['path', {d: 'M8 4.4V8l2.6 1.6', fill: 'none'}],
  ],
  blocked: [
    ['circle', {cx: 8, cy: 8, r: 6.4, fill: 'none'}],
    ['path', {d: 'M3.6 12.4l8.8-8.8', fill: 'none'}],
  ],
};

/**
 * A 16 px inline SVG sign for banners and status texts; decorative, the text
 * next to it always says the same thing.
 * @param {'danger'|'attention'|'unknown'|'info'|'ok'|'pause'|'clock'|'blocked'} name
 * @returns {SVGElement}
 */
export function glyph(name) {
  const parts = GLYPHS[name] || GLYPHS.unknown;
  return s('svg', {
    class: 'glyph', viewBox: '0 0 16 16', width: 16, height: 16, 'aria-hidden': 'true', focusable: 'false',
    'data-glyph': GLYPHS[name] ? name : 'unknown',
  }, parts.map(([tag, attrs]) => s(tag, attrs)));
}

/**
 * Show the sign `name` as the only child of `holder`; nothing is touched when it is already there.
 * @param {Element} holder
 * @param {string} name
 */
export function setGlyph(holder, name) {
  const shown = GLYPHS[name] ? name : 'unknown';
  const current = holder.firstElementChild;
  if (current && current.getAttribute('data-glyph') === shown) return;
  holder.replaceChildren(glyph(shown));
}
