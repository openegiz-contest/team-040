// Labels of the scene: HTML buttons projected from 3D, placed greedily by
// priority so that text never overlaps text, a person or the stage controls.
// They are the accessible and testable mirror of the scene: each object label
// carries data-thing-id, data-kind and the state attributes of the list rows,
// and Enter or Space selects its object. Content changes only with the data;
// positions are written once per rendered frame.

import {h, reconcile, setAttrs, setText} from '../dom.js';
import {symbol} from '../icons.js';

const GAP = 10;

/**
 * @typedef {Object} LabelItem
 * @property {string} key
 * @property {string|null} thingId     null for a label that is not an object (a level, the decor)
 * @property {Object<string, *>} attrs state attributes (model.stateAttributes) and aria-label
 * @property {Array<{text: string, bold?: boolean, muted?: boolean}>} lines
 * @property {string[]} signs           names of icons.js signs before the first line
 * @property {number} rank              0 is placed first
 * @property {boolean} always           kept when it has room, at any zoom
 * @property {string[]} cls             modifiers of .s3-label
 * @property {number[]|(() => number[]|null)} anchor   scene point, or a function giving it for the current frame
 * @property {'around'|'centre'|'left'} place
 * @property {number} [minScale]        shown only when one metre at the anchor is at least this many pixels
 */

export function createLabels(layer, onSelect, onHover) {
  const sizes = new WeakMap();
  let items = [];
  let nodes = [];

  function create(item) {
    const button = h('button', {type: 'button', class: 's3-label'},
      h('span', {class: 's3-label__signs', 'aria-hidden': 'true'}), h('span', {class: 's3-label__lines'}));
    button.addEventListener('click', () => {
      const thingId = button.getAttribute('data-thing-id');
      if (thingId) onSelect(thingId);
    });
    button.addEventListener('pointerenter', () => onHover(button.getAttribute('data-thing-id')));
    button.addEventListener('pointerleave', () => onHover(null));
    return button;
  }

  function update(button, item) {
    const [signs, lines] = button.children;
    const before = button.textContent + button.className + signs.childElementCount;
    setAttrs(button, {...item.attrs, class: ['s3-label', ...item.cls], 'data-label': item.key, 'data-rank': item.rank});
    reconcile(signs, item.signs, (name, index) => `${index}:${name}`, (name) => symbol('sign', name, {size: 14}));
    reconcile(lines, item.lines, (line, index) => index, () => h('span', {class: 's3-label__line'}), (span, line) => {
      setAttrs(span, {class: ['s3-label__line', line.bold && 'is-bold', line.muted && 'is-muted']});
      setText(span, line.text);
    });
    if (button.textContent + button.className + signs.childElementCount !== before) sizes.delete(button);
  }

  /** New label content from the data. */
  function set(next) {
    items = next;
    nodes = reconcile(layer, items, (item) => item.key, create, update);
  }

  /** Full size, and the size of the brief form (the first line only) of a label of several lines. */
  function sizeOf(button) {
    let size = sizes.get(button);
    if (!size) {
      const brief = button.classList.contains('is-brief');
      if (brief) button.classList.remove('is-brief');
      size = {w: button.offsetWidth, h: button.offsetHeight};
      if (button.children[1].childElementCount > 1) {
        button.classList.add('is-brief');
        size.brief = {w: button.offsetWidth, h: button.offsetHeight};
        if (!brief) button.classList.remove('is-brief');
      } else if (brief) {
        button.classList.add('is-brief');
      }
      if (size.w > 0) sizes.set(button, size);
    }
    return size;
  }

  /**
   * Place every label for the current camera.
   * @param {(point: number[]) => ({x: number, y: number, visible: boolean, scale: number}|null)} project
   *        screen point of a scene point, and pixels per metre there
   * @param {number} width
   * @param {number} height
   * @param {Array<{x: number, y: number, w: number, h: number, key?: string}>} obstacles markers and controls
   * @param {{focused: string|null, selected: string|null, hovered: string|null}} keep labels that are never hidden
   */
  function place(project, width, height, obstacles, keep) {
    const placed = [];
    const order = items.map((item, index) => ({item, node: nodes[index]})).sort((a, b) => a.item.rank - b.item.rank);
    // Measure first, then write: no layout is forced between two writes.
    const measured = order.map((entry) => ({...entry, size: sizeOf(entry.node)}));
    const overlaps = (box) => placed.some((other) => box.x < other.x + other.w && box.x + box.w > other.x
      && box.y < other.y + other.h && box.y + box.h > other.y);
    const hitsObstacle = (box, own) => obstacles.some((other) => other.key !== own && box.x < other.x + other.w
      && box.x + box.w > other.x && box.y < other.y + other.h && box.y + box.h > other.y);
    const out = (box) => box.x < 2 || box.y < 2 || box.x + box.w > width - 2 || box.y + box.h > height - 2;
    let shown = 0;
    for (const {item, node, size} of measured) {
      const p = project(typeof item.anchor === 'function' ? item.anchor() : item.anchor);
      const pinned = node === keep.focused || item.key === keep.hovered
        || Boolean(item.thingId && (item.thingId === keep.selected || item.thingId === keep.hovered));
      let box = null;
      let brief = false;
      const scaleOk = !item.minScale || (p && p.scale >= item.minScale);
      const candidatesOf = (w, hh) => {
        const candidates = [];
        const rings = item.always || pinned ? [GAP, GAP + 26, GAP + 56] : [GAP];
        for (const gap of rings) {
          if (item.place === 'centre') candidates.push({x: p.x - w / 2, y: p.y - hh / 2});
          if (item.place === 'left') candidates.push({x: p.x - w - gap, y: p.y - hh / 2}, {x: p.x - w - gap, y: p.y - hh - gap / 2});
          candidates.push(
            {x: p.x - w / 2, y: p.y - hh - gap - 6}, {x: p.x + gap + 4, y: p.y - hh / 2}, {x: p.x - w - gap - 4, y: p.y - hh / 2},
            {x: p.x - w / 2, y: p.y + gap + 6}, {x: p.x + gap, y: p.y - hh - gap}, {x: p.x - w - gap, y: p.y - hh - gap},
            {x: p.x + gap, y: p.y + gap}, {x: p.x - w - gap, y: p.y + gap},
          );
        }
        return candidates;
      };
      const fit = (w, hh) => {
        for (const c of candidatesOf(w, hh)) {
          const candidate = {x: Math.round(c.x), y: Math.round(c.y), w, h: hh};
          if (!(out(candidate) || overlaps(candidate) || hitsObstacle(candidate, item.key))) return candidate;
        }
        return null;
      };
      if (p && p.visible && size.w > 0 && (scaleOk || pinned)) {
        const {w, h: hh} = size;
        const candidates = candidatesOf(w, hh);
        box = fit(w, hh);
        // A label that must stay and has no room in full keeps its first line (the state); the rest is in its
        // tooltip, its accessible name and the card. A pinned label is always shown in full.
        if (!box && item.always && !pinned && size.brief) {
          box = fit(size.brief.w, size.brief.h);
          brief = Boolean(box);
        }
        if (!box && pinned) {
          // The focused or selected label is shown even when it has to overlap: the user is on it.
          box = {x: Math.round(Math.min(Math.max(candidates[0].x, 2), width - w - 2)), y: Math.round(Math.min(Math.max(candidates[0].y, 2), height - hh - 2)), w, h: hh};
        }
      }
      if (node.classList.contains('is-brief') !== brief) node.classList.toggle('is-brief', brief);
      if (box) {
        placed.push(box);
        shown += 1;
        node.style.transform = `translate(${box.x}px, ${box.y}px)`;
        if (node.hasAttribute('data-culled')) node.removeAttribute('data-culled');
      } else if (!node.hasAttribute('data-culled')) {
        node.setAttribute('data-culled', '');
      }
    }
    return shown;
  }

  return {set, place, get items() {
    return items;
  }};
}
