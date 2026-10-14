// The legend of the stage: a one-row chip at its bottom left with the key
// symbols of the three axes (hazard, knowledge, reachability), the exit, the
// closed passage and the route; a press unfolds the full legend above it.
// It serves the 3D scene and the scheme alike: both draw the same semantics.
// Every sample is built by the functions that draw the scheme (icons.js), so
// it cannot differ from the object it explains.

import {h, s} from '../dom.js';
import {chevrons, linePath, workingShape} from '../geometry.js';
import {drawWorking, exitMarker, patterns, sensorMarker, sign, workerMarker} from '../icons.js';

const LINE = [[-13, 0], [13, 0]];
const PANEL_ID = 'legend-panel';

const frame = (width, ...children) => s('svg', {
  width, height: 16, viewBox: `${-width / 2} -8 ${width} 16`, 'aria-hidden': 'true', focusable: 'false',
}, children);

export function mount(root, ctx) {
  const {text} = ctx;
  const {UI, VOCAB} = text;
  const L = UI.legend;
  /** A working on a piece of its slab; `prefix` names the hatch patterns (the panel and the chip have one set each). */
  function working(look, prefix = 'lg') {
    const g = s('g', {class: ['working', look.lastDanger && 'working--last-danger'], 'data-hazard': look.hazard || 'unknown'});
    drawWorking(g, workingShape(LINE, 9), {hazard: 'unknown', ...look}, prefix);
    // The working lies on a piece of its slab, as on the drawing; the slab is not part of the symbol.
    return frame(30, s('rect', {class: 'legend__slab', x: -15, y: -8, width: 30, height: 16}), g);
  }
  const worker = (attrs, width = 18) => frame(width, s('g', {class: 'worker', ...attrs}, workerMarker()));
  const sensor = (quality) => frame(20, s('g', {class: 'sensor', 'data-quality': quality}, sensorMarker()));
  const exit = (state) => frame(20, s('g', {class: 'exit', 'data-state': state, transform: 'scale(.72)'}, exitMarker()));
  const mark = (name) => frame(18, sign(name));
  const route = (width = 40) => {
    const line = [[-width / 2 + 2, 0], [width / 2 - 2, 0]];
    return frame(width, s('g', {class: 'route'}, s('path', {class: 'route__casing', d: linePath(line)}),
      s('path', {class: 'route__line', d: linePath(line)}), s('path', {class: 'route__arrows', d: chevrons(line, 18, 5)})));
  };

  // ---- the full legend ------------------------------------------------------------
  /** [title, [sample, words]] */
  const groups = [
    [L.hazard, [
      [working({hazard: 'normal'}), VOCAB.hazard.normal],
      [working({hazard: 'attention'}), VOCAB.hazard.attention],
      [working({hazard: 'danger'}), VOCAB.hazard.danger],
      [working({hazard: 'unknown'}), VOCAB.hazard.unknown],
      [working({hazard: 'unknown', lastDanger: true}), text.lastKnownText({last_known_hazard_state: 'danger'})],
    ]],
    [L.knowledge, [
      [sensor('fresh'), VOCAB.quality.fresh],
      [sensor('stale'), VOCAB.quality.stale],
      [sensor('lost'), VOCAB.quality.lost],
      [working({bare: true}), VOCAB.quality.none],
    ]],
    [L.reach, [
      [worker({'data-egress': 'ok'}), L.workerOk],
      [worker({'data-egress': 'none'}), VOCAB.egress.none],
      [worker({'data-egress': 'unknown'}), VOCAB.egress.unknown],
      [worker({'data-egress': 'ok', 'data-location-hazard': 'danger'}, 24), L.inDangerZone],
      [worker({'data-egress': 'ok', class: 'worker is-going'}, 30), VOCAB.workerStatus.moving_to_exit],
      [worker({'data-egress': 'ok'}), `${UI.scheme.grouped(3)} ${L.group}`],
      [route(), L.route],
      [working({bare: true, closed: true}), VOCAB.passability.closed],
      [mark('blocked'), VOCAB.restriction.blocked],
    ]],
    [L.exit, [
      [exit('available'), L.exitAvailable],
      [exit('unavailable'), L.exitUnavailable],
      [exit('unknown'), L.exitUnknown],
    ]],
    [L.commands, [
      [mark('pending'), L.pending],
    ]],
  ];
  const item = ([sample, words]) => h('span', {class: 'legend__item'}, sample, h('span', {text: words}));
  const panel = h('div', {class: 'legend__panel', id: PANEL_ID, role: 'group', 'aria-label': L.title, hidden: true},
    h('p', {class: 'legend__heading'}, L.title, h('span', {class: 'legend__hint', text: L.hint})),
    groups.map(([title, items]) => h('div', {class: 'legend__group', 'data-legend-group': title},
      h('span', {class: 'legend__title', text: `${title}:`}), items.map(item))));

  // ---- the chip: the key symbols in one row ----------------------------------------
  const key = (sample, words, hint) => h('span', {class: 'legend__item', title: hint || words}, sample,
    words ? h('span', {class: 'legend__words', text: words}) : null);
  const chipGroup = (title, ...items) => h('span', {class: 'legend__group'}, h('span', {class: 'legend__title', text: `${title}:`}), items);
  const caret = s('svg', {class: 'legend__caret', viewBox: '0 0 10 10', 'aria-hidden': 'true', focusable: 'false'},
    s('path', {d: 'M1.5 6.5L5 3l3.5 3.5'}));
  const chip = h('button', {
    type: 'button', class: 'legend__chip', 'data-testid': 'legend-toggle',
    'aria-expanded': 'false', 'aria-controls': PANEL_ID, 'aria-label': L.chipLabel,
  },
  chipGroup(L.hazard,
    key(working({hazard: 'normal'}, 'lc'), '', VOCAB.hazard.normal), key(working({hazard: 'attention'}, 'lc'), '', VOCAB.hazard.attention),
    key(working({hazard: 'danger'}, 'lc'), '', VOCAB.hazard.danger), key(working({hazard: 'unknown'}, 'lc'), '', VOCAB.hazard.unknown)),
  chipGroup(L.knowledge,
    key(sensor('fresh'), '', VOCAB.quality.fresh), key(sensor('stale'), '', VOCAB.quality.stale),
    key(sensor('lost'), '', VOCAB.quality.lost), key(working({bare: true}, 'lc'), '', VOCAB.quality.none)),
  chipGroup(L.reach,
    key(worker({'data-egress': 'ok'}), '', L.workerOk), key(worker({'data-egress': 'none'}), '', VOCAB.egress.none),
    key(worker({'data-egress': 'unknown'}), '', VOCAB.egress.unknown)),
  chipGroup(L.exit, key(exit('available'), '', L.exitAvailable)),
  key(working({bare: true, closed: true}, 'lc'), L.closedShort, VOCAB.passability.closed),
  key(route(30), L.routeShort, L.route),
  h('span', {class: 'legend__more', text: L.more}), caret);

  function show(open) {
    if (open) {
      // The room above the chip, under the controls at the top of the stage: the column never leaves the stage.
      const stage = ctx.roots.stage ? ctx.roots.stage.getBoundingClientRect() : null;
      const room = stage ? root.getBoundingClientRect().top - stage.top - 56 : 0;
      panel.style.setProperty('--legend-room', `${Math.max(Math.round(room), 160)}px`);
    }
    panel.hidden = !open;
    chip.setAttribute('aria-expanded', String(open));
  }
  chip.addEventListener('click', () => show(panel.hidden));
  root.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !panel.hidden) {
      event.stopPropagation();
      show(false);
      chip.focus();
    }
  });

  root.append(
    // The hatch patterns of the samples; the scheme has its own copy under another prefix.
    s('svg', {class: 'legend__defs', width: 0, height: 0, 'aria-hidden': 'true', focusable: 'false'},
      s('defs', null, patterns('lg'), patterns('lc'))),
    // The panel comes first: it opens above the chip, and it is read before it.
    panel,
    chip,
  );
}
