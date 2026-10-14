// The legend, always visible under the scheme: the three axes (hazard,
// knowledge, reachability) as three labelled groups, then exits and commands.
// Every sample is built by the functions that draw the scheme (icons.js), so
// it cannot differ from the object it explains. The compact layout keeps the
// states of the three axes and leaves out the samples marked `more`
// (scheme.css); the card says them in words in the summary of the shift.

import {h, s} from '../dom.js';
import {chevrons, linePath, workingShape} from '../geometry.js';
import {drawWorking, exitMarker, patterns, sensorMarker, sign, workerMarker} from '../icons.js';

const PATTERNS = 'lg';
const LINE = [[-13, 0], [13, 0]];

const frame = (width, ...children) => s('svg', {
  width, height: 16, viewBox: `${-width / 2} -8 ${width} 16`, 'aria-hidden': 'true', focusable: 'false',
}, children);

function working(look, attrs = {}) {
  const g = s('g', {class: ['working', look.lastDanger && 'working--last-danger'],
    'data-hazard': look.hazard || 'unknown', ...attrs});
  drawWorking(g, workingShape(LINE, 9), {hazard: 'unknown', ...look}, PATTERNS);
  return frame(30, g);
}

const worker = (attrs, width = 18) => frame(width, s('g', {class: 'worker', ...attrs}, workerMarker()));
const sensor = (quality) => frame(20, s('g', {class: 'sensor', 'data-quality': quality}, sensorMarker()));
const exit = (state) => frame(20, s('g', {class: 'exit', 'data-state': state, transform: 'scale(.72)'}, exitMarker()));
const mark = (name) => frame(18, sign(name));

export function mount(root, ctx) {
  const {text} = ctx;
  const {UI, VOCAB} = text;
  const L = UI.legend;
  const route = [[-18, 0], [18, 0]];

  /** [sample, label, more?] — `more`: left out of the compact legend. */
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
      [sensor('stale'), L.stale],
      [sensor('lost'), L.lost],
      [working({bare: true}), VOCAB.quality.none],
    ]],
    [L.reach, [
      [worker({'data-egress': 'ok'}), VOCAB.egress.ok],
      [worker({'data-egress': 'none'}), VOCAB.egress.none],
      [worker({'data-egress': 'unknown'}), VOCAB.egress.unknown],
      [worker({'data-egress': 'ok', 'data-location-hazard': 'danger'}, 24), L.inDangerZone, true],
      [worker({'data-egress': 'ok', class: 'worker is-going'}, 30), VOCAB.workerStatus.moving_to_exit, true],
      [worker({'data-egress': 'ok'}), `${UI.scheme.grouped(3)} ${L.group}`, true],
      [frame(40, s('g', {class: 'route'}, s('path', {class: 'route__casing', d: linePath(route)}),
        s('path', {class: 'route__line', d: linePath(route)}), s('path', {class: 'route__arrows', d: chevrons(route, 18, 5)}))), L.route, true],
      [working({bare: true, closed: true}), VOCAB.passability.closed],
      [mark('blocked'), VOCAB.restriction.blocked, true],
    ]],
    [L.exit, [
      [exit('available'), L.exitAvailable],
      [exit('unavailable'), L.exitUnavailable],
      [exit('unknown'), L.exitUnknown],
    ]],
    [null, [
      [mark('pending'), L.pending],
    ]],
  ];

  const item = ([sample, label, more]) => h('span', {class: ['legend__item', more && 'legend__item--more']}, sample, label);
  root.append(
    // The hatch patterns of the samples; the scheme has its own copy under another prefix.
    s('svg', {width: 0, height: 0, 'aria-hidden': 'true', focusable: 'false', style: 'position:absolute'}, s('defs', null, patterns(PATTERNS))),
    h('div', {class: 'legend__groups', role: 'group', 'aria-label': L.title},
      groups.map(([title, items]) => h('span', {class: 'legend__group', 'data-legend-group': title || ''},
        // The title never ends a line alone: it wraps together with its first sample.
        title ? h('span', {class: 'legend__head'}, h('span', {class: 'legend__title', text: `${title}:`}), item(items[0])) : item(items[0]),
        items.slice(1).map(item)))),
  );
}
