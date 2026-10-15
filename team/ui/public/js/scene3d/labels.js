// Labels of the scene: HTML buttons projected from 3D, placed greedily by
// priority so that text never overlaps text, a person or the stage controls.
// They are the accessible and testable mirror of the scene: each object label
// carries data-thing-id, data-kind and the state attributes of the list rows,
// and Enter or Space selects its object. Content changes only with the data;
// positions are written once per rendered frame.
//
// A label the decluttering pushed away from its object keeps a leader: a thin
// line in the label's frame colour from its nearest edge to the object's mark,
// ending in a dot there, so a tag never reads as belonging to the horizon it
// happens to lie over. The leaders are one inline SVG under the labels, written
// in the same pass as the labels (no frame of their own).

import {h, reconcile, s, setAttrs, setText} from '../dom.js';
import {symbol} from '../icons.js';

const GAP = 10;
// A label whose nearest edge lies farther than this from its anchor was pushed away and gets a leader to its
// object's mark. The nearest ring of candidates lies 10–16 px from the anchor (GAP plus its offsets), the next
// one 36 px or more: a label in its own place carries no line, except a zone's tag (placed 'centre', lifted
// above its zone) whose box does not reach the zone's centre: it keeps a short stem down to its own horizon.
export const LEADER_MIN = 18;
// A mark this close to the pushed label needs no line.
const LEADER_SHORT = 4;
// The colour of a leader is the frame colour of its label (the first class that matches).
const LEADER_TONES = [['is-selected', 'selection'], ['s3-label--danger', 'danger'], ['s3-label--indanger', 'danger'],
  ['s3-label--attention', 'attention'], ['s3-label--unknown', 'unknown']];

/**
 * Fade an element in once (a passage just closed: its label and leader arrive with the barricade, M8).
 * A single finite Web Animation, not a CSS keyframe; skipped under reduced motion and over old data.
 */
function arrive(element) {
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced || element.closest('.s3[data-old]') || typeof element.animate !== 'function') return;
  element.animate([{opacity: 0}, {opacity: 1}], {duration: 200, easing: 'ease-out', iterations: 1});
}

/** The point of a box nearest to a point. */
function nearestOf(box, point) {
  return {x: Math.min(Math.max(point.x, box.x), box.x + box.w), y: Math.min(Math.max(point.y, box.y), box.y + box.h)};
}

/** Whether the segment a–b passes through the box (shrunk by 1 px: touching an edge is not crossing). */
function crosses(a, b, box) {
  const x0 = box.x + 1;
  const y0 = box.y + 1;
  const x1 = box.x + box.w - 1;
  const y1 = box.y + box.h - 1;
  if (x1 <= x0 || y1 <= y0) return false;
  let t0 = 0;
  let t1 = 1;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  for (const [p, q] of [[-dx, a.x - x0], [dx, x1 - a.x], [-dy, a.y - y0], [dy, y1 - a.y]]) {
    if (p === 0) {
      if (q < 0) return false;
    } else {
      const t = q / p;
      if (p < 0) t0 = Math.max(t0, t);
      else t1 = Math.min(t1, t);
      if (t0 > t1) return false;
    }
  }
  return true;
}

/**
 * @typedef {Object} LabelItem
 * @property {string} key
 * @property {string|null} thingId     null for a label that is not an object (a level, the sign of a loader)
 * @property {Array<{text: string}>} [tip]  every word of the object for its tooltip, when the label shows fewer
 * @property {Object<string, *>} attrs state attributes (model.stateAttributes) and aria-label
 * @property {Array<{text: string, bold?: boolean, muted?: boolean}>} lines
 * @property {string[]} signs           names of icons.js signs before the first line; "kind:state" for another symbol
 *                                     of icons.js (e.g. "worker:none", the crossed square of a person without a route)
 * @property {number} rank              0 is placed first
 * @property {boolean} always           kept when it has room, at any zoom
 * @property {boolean} [keep]           never left out by the decluttering: placed even where it has to overlap
 * @property {string[]} cls             modifiers of .s3-label
 * @property {number[]|(() => number[]|null)} anchor   scene point, or a function giving it for the current frame
 * @property {'around'|'centre'|'left'} place
 * @property {number} [minScale]        shown only when one metre at the anchor is at least this many pixels
 */

export function createLabels(layer, onSelect, onHover) {
  const sizes = new WeakMap();
  let items = [];
  let nodes = [];
  let changed = false;
  // The leaders: one SVG just under the labels and over the canvas, never read by assistive technology.
  const leaderLayer = s('svg', {class: 's3__leaders', 'aria-hidden': 'true', focusable: 'false'});
  if (layer.parentNode) layer.parentNode.insertBefore(leaderLayer, layer);
  const leaders = new Map();
  // The last placement, for tests: each shown label, its box, its anchor, how far it was pushed, its leader.
  let placement = [];

  function create(item) {
    const button = h('button', {type: 'button', class: 's3-label'},
      h('span', {class: 's3-label__signs', 'aria-hidden': 'true'}), h('span', {class: 's3-label__lines'}));
    // A label that is not an object itself (the sign of a zone's loader) selects the object it stands for.
    const target = () => button.getAttribute('data-thing-id') || button.getAttribute('data-select');
    button.addEventListener('click', () => {
      const thingId = target();
      if (thingId) onSelect(thingId);
    });
    button.addEventListener('pointerenter', () => onHover(target()));
    button.addEventListener('pointerleave', () => onHover(null));
    return button;
  }

  function update(button, item) {
    const [signs, lines] = button.children;
    const before = button.textContent + button.className + signs.childElementCount;
    const wasArriving = button.classList.contains('is-arriving');
    // The brief form is the placement's choice (place()): new content keeps it until the next placement.
    setAttrs(button, {...item.attrs, class: ['s3-label', ...item.cls, button.classList.contains('is-brief') && 'is-brief'],
      'data-label': item.key, 'data-rank': item.rank});
    if (!wasArriving && button.classList.contains('is-arriving')) arrive(button);
    reconcile(signs, item.signs, (name, index) => `${index}:${name}`, (name) => {
      const [kind, state] = name.includes(':') ? name.split(':') : ['sign', name];
      return symbol(kind, state, {size: 14});
    });
    reconcile(lines, item.lines, (line, index) => index, () => h('span', {class: 's3-label__line'}), (span, line) => {
      setAttrs(span, {class: ['s3-label__line', line.bold && 'is-bold', line.muted && 'is-muted']});
      setText(span, line.text);
    });
    if (button.textContent + button.className + signs.childElementCount !== before) {
      sizes.delete(button);
      changed = true;
    }
  }

  /** New label content from the data; true when a label was added, removed or changed its words or look. */
  function set(next) {
    changed = next.length !== items.length;
    items = next;
    nodes = reconcile(layer, items, (item) => item.key, (item) => {
      changed = true;
      return create(item);
    }, update);
    return changed;
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
   * @param {(thingId: string) => (number[]|null)} [markOf] scene point of an object's mark (its marker, the centre
   *        of a zone's floor) where the leader of a displaced label ends; the label's anchor when there is none
   */
  function place(project, width, height, obstacles, keep, markOf = null) {
    const placed = [];
    const drawn = [];
    placement = [];
    const order = items.map((item, index) => ({item, node: nodes[index]})).sort((a, b) => a.item.rank - b.item.rank);
    // Measure first, then write: no layout is forced between two writes.
    const measured = order.map((entry) => ({...entry, size: sizeOf(entry.node)}));
    const overlaps = (box) => placed.some((other) => box.x < other.x + other.w && box.x + box.w > other.x
      && box.y < other.y + other.h && box.y + box.h > other.y);
    const hitsObstacle = (box, own) => obstacles.some((other) => other.key !== own && box.x < other.x + other.w
      && box.x + box.w > other.x && box.y < other.y + other.h && box.y + box.h > other.y);
    const out = (box) => box.x < 2 || box.y < 2 || box.x + box.w > width - 2 || box.y + box.h > height - 2;
    const distance = (box, point) => {
      const near = nearestOf(box, point);
      return Math.hypot(point.x - near.x, point.y - near.y);
    };
    // The leader of a box pushed away from its anchor, or of a tag meant to sit on its object (a zone's, placed
    // 'centre') that floats off it: from the box's point nearest to the mark, to the mark.
    const leaderOf = (box, anchor, mark, centre) => {
      if (!anchor || !mark) return null;
      const off = distance(box, mark);
      if (off <= LEADER_SHORT || (distance(box, anchor) <= LEADER_MIN && !(centre && off > LEADER_MIN))) return null;
      return {from: nearestOf(box, mark), to: {x: mark.x, y: mark.y}};
    };
    const leaderClear = (leader) => !leader || !placed.some((other) => crosses(leader.from, leader.to, other));
    const hitsLeader = (box) => drawn.some((other) => crosses(other.from, other.to, box));
    let shown = 0;
    for (const {item, node, size} of measured) {
      const p = project(typeof item.anchor === 'function' ? item.anchor() : item.anchor);
      const marked = p && p.visible && item.thingId && markOf ? project(markOf(item.thingId)) : null;
      const mark = marked && marked.visible ? marked : p;
      const pinned = node === keep.focused || item.key === keep.hovered || Boolean(item.keep)
        || Boolean(item.thingId && (item.thingId === keep.selected || item.thingId === keep.hovered));
      let box = null;
      let brief = false;
      const scaleOk = !item.minScale || (p && p.scale >= item.minScale);
      const candidatesOf = (w, hh) => {
        const candidates = [];
        // Poster-scale markers (variant 3) crowd a cluster of people: a label that must stay may go farther, on its leader.
        const rings = item.always || pinned ? [GAP, GAP + 26, GAP + 56, GAP + 96, GAP + 140] : [GAP];
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
      // A free place, preferring one whose leader runs clear of the labels already placed; no box covers a leader.
      const fit = (w, hh) => {
        let crossing = null;
        for (const c of candidatesOf(w, hh)) {
          const candidate = {x: Math.round(c.x), y: Math.round(c.y), w, h: hh};
          if (out(candidate) || overlaps(candidate) || hitsObstacle(candidate, item.key) || hitsLeader(candidate)) continue;
          if (leaderClear(leaderOf(candidate, p, mark, item.place === 'centre'))) return candidate;
          if (!crossing) crossing = candidate;
        }
        return crossing;
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
        const leader = leaderOf(box, p, mark, item.place === 'centre');
        if (leader) drawn.push({...leader, key: item.key, node});
        placement.push({key: item.key, thingId: item.thingId, box, anchor: [Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10],
          off: Math.round(distance(box, p) * 10) / 10, leader: leader ? [leader.from.x, leader.from.y, leader.to.x, leader.to.y].map((v) => Math.round(v * 10) / 10) : null});
        shown += 1;
        node.style.transform = `translate(${box.x}px, ${box.y}px)`;
        if (node.hasAttribute('data-culled')) node.removeAttribute('data-culled');
      } else if (!node.hasAttribute('data-culled')) {
        node.setAttribute('data-culled', '');
      }
    }
    drawLeaders(drawn, width, height);
    return shown;
  }

  /** Write the leaders of this placement (a line from the label's edge, a dot on the mark), reusing the elements. */
  function drawLeaders(drawn, width, height) {
    setAttrs(leaderLayer, {width, height, viewBox: `0 0 ${width} ${height}`});
    const seen = new Set();
    const r = (v) => Math.round(v * 10) / 10;
    for (const {from, to, key, node} of drawn) {
      seen.add(key);
      let leader = leaders.get(key);
      if (!leader) {
        // A dark casing under the line keeps it readable over the pale stone (a flat stroke, not a glow).
        const casing = s('line', {class: 's3-leader__casing'});
        const line = s('line', {class: 's3-leader__line'});
        const dot = s('circle', {class: 's3-leader__dot', r: 2.5});
        leader = {g: s('g', {'data-leader': key}, casing, line, dot), casing, line, dot};
        leaders.set(key, leader);
        leaderLayer.append(leader.g);
      }
      const tone = (LEADER_TONES.find(([cls]) => node.classList.contains(cls)) || [null, 'normal'])[1];
      const leaderWasArriving = leader.g.classList.contains('is-arriving');
      setAttrs(leader.g, {class: ['s3-leader', `s3-leader--${tone}`, node.classList.contains('is-arriving') && 'is-arriving']});
      if (!leaderWasArriving && leader.g.classList.contains('is-arriving')) arrive(leader.g);
      const ends = {x1: r(from.x), y1: r(from.y), x2: r(to.x), y2: r(to.y)};
      setAttrs(leader.casing, ends);
      setAttrs(leader.line, ends);
      setAttrs(leader.dot, {cx: r(to.x), cy: r(to.y)});
    }
    for (const [key, leader] of leaders) {
      if (seen.has(key)) continue;
      leader.g.remove();
      leaders.delete(key);
    }
  }

  return {set, place, get items() {
    return items;
  }, get placement() {
    return {min: LEADER_MIN, labels: placement};
  }};
}
