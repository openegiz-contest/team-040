// The left rail «Люди» of «Пульт смены»: answers "is everyone all right, and
// where are they?" at a glance.
//
// On top, the five people counters the model published (never counted here),
// each with its caption: всего, вышли, в опасных зонах, без расчётного
// маршрута, состояние неизвестно. A counter above zero takes the shape of its
// axis (octagon, crossed square, dashed «?»); a changed value crossfades once.
//
// Then one row per zone in the order of the platform, a row «Вне участков», a
// row «Положение не опубликовано» when anybody has none, and «Вышли» grouped by
// exit. A zone row says its name, its displayed hazard (badge: shape and word),
// its work state in words and carries one dot per worker whose published
// position is in one of its workings. A dot is the worker marker of the stage
// and the legend: plain dot = computed route, red ring = in a danger zone,
// white crossed square = no computed route, dashed «?» = unknown. Dots are
// buttons named by the worker's code and state; a press selects the worker. A
// press on a zone row selects the zone and asks the stage to show it; its
// chevron unfolds the dispatcher actions of the zone (view/actions.js).
//
// The rail folds to a strip of figures (shell.rail = 'collapsed').
//
// Motion (clarity spec B): a changed counter crossfades (200 ms) with a fading
// underline (1 s); a zone row whose hazard changed flashes once (450 ms). Never
// on load, over old data or under reduced motion.

import {h, reconcile, s, setAttrs, setText} from '../dom.js';
import {workerMarker} from '../icons.js';
import {fullId, incidentOf, knownHazard, labelOf, thingsOfKind, zoneOfWorking} from '../model.js';
import {EASE, MS, motionAllowed, play} from '../motion.js';
import {zoneActions} from './actions.js';
import {setSign} from './signs.js';

/** The people counters: test id suffix, field of shift, caption key of UI.incident, the sign of a count above zero. */
const FIGURES = [
  ['total', 'workers_total', 'total', null],
  ['out', 'workers_out', 'out', null],
  ['in-danger', 'workers_in_danger', 'inDanger', 'danger'],
  ['no-route', 'workers_no_route', 'noRoute', 'noroute'],
  ['unknown', 'workers_unknown', 'unknown', 'unknown'],
];
const HAZARD_SIGN = {normal: null, attention: 'attention', danger: 'danger', unknown: 'unknown'};
const OPEN = new Set(['active', 'executing']);

/** The sign of a counter above zero: octagon (danger), crossed square (no route), dashed «?» (unknown). */
function figureSign(kind) {
  const svg = (children) => s('svg', {class: `rail-fig__sign rail-fig__sign--${kind}`, viewBox: '0 0 16 16', width: 16, height: 16,
    'aria-hidden': 'true', focusable: 'false'}, children);
  if (kind === 'danger') return svg([s('path', {d: 'M5.2 1.5h5.6l3.7 3.7v5.6l-3.7 3.7H5.2l-3.7-3.7V5.2z'}), s('path', {d: 'M8 4.6v4.2M8 11v.5'})]);
  if (kind === 'noroute') return svg([s('rect', {x: 2, y: 2, width: 12, height: 12}), s('path', {d: 'M2 2l12 12M14 2L2 14'})]);
  return svg([s('circle', {cx: 8, cy: 8, r: 6.3, 'stroke-dasharray': '2.2 1.8'}),
    s('path', {d: 'M6 6.4a2 2 0 1 1 2.9 1.8c-.6.3-.9.7-.9 1.4M8 11.5v.5'})]);
}

/** A worker as a dot: the marker of the stage in a 24 px box. */
function dotPicture(out) {
  return s('svg', {class: 'dot__pic', viewBox: '-12 -12 24 24', width: 24, height: 24, 'aria-hidden': 'true', focusable: 'false'},
    out ? s('g', {class: 'dot__out'}, s('circle', {r: 6}), s('path', {d: 'M-2.8 .2l2 2 3.8-4.2'}))
      : s('g', {class: 'worker'}, workerMarker()));
}

export function mount(root, ctx) {
  const {store, text, shell} = ctx;
  const {UI} = text;
  const R = UI.rail;

  // ---- head ----------------------------------------------------------------------
  const toggle = h('button', {
    class: 'btn btn--quiet rail__toggle', type: 'button', 'data-testid': 'rail-toggle', 'aria-controls': 'rail-region',
  }, s('svg', {class: 'rail__chevron', viewBox: '0 0 12 12', width: 12, height: 12, 'aria-hidden': 'true', focusable: 'false'},
    s('path', {d: 'M7.5 2.5L4 6l3.5 3.5'})));
  toggle.addEventListener('click', () => shell.set({rail: shell.get().rail === 'collapsed' ? 'open' : 'collapsed'}));
  const head = h('div', {class: 'rail__head'}, h('h2', {class: 'rail__title', id: 'rail-title', text: R.title}), toggle);

  // ---- figures -------------------------------------------------------------------
  const figures = FIGURES.map(([id, field, caption, sign]) => {
    const value = h('b', {class: 'rail-fig__value', 'data-testid': `incident-${id}`});
    const mark = h('span', {class: 'rail-fig__mark', 'aria-hidden': 'true'});
    const slot = h('span', {class: 'rail-fig__slot'}, value, mark);
    const node = h('div', {class: 'rail-fig', 'data-figure': id, title: UI.incident[caption]},
      h('span', {class: 'rail-fig__num'}, slot, sign ? figureSign(sign) : null), ' ',
      h('span', {class: 'rail-fig__cap', text: UI.incident[caption]}));
    return {field, sign, value, slot, mark, node};
  });
  const figureBox = h('div', {class: 'rail-figs', role: 'group', 'aria-label': UI.incident.peopleTitle, title: UI.incident.peopleTitle},
    h('div', {class: 'rail-figs__main'}, figures[0].node, figures[1].node),
    h('div', {class: 'rail-figs__alerts'}, figures.slice(2).map((item) => item.node)));

  // ---- where the people are ----------------------------------------------------------
  const rows = h('ol', {class: 'zrows', 'data-testid': 'rail-zones'});
  const where = h('section', {class: 'rail__where', 'aria-labelledby': 'rail-where-title'},
    h('h3', {class: 'rail__sub', id: 'rail-where-title', title: R.whereTitle, text: R.where}),
    rows);
  root.append(h('div', {class: 'rail__inner', role: 'region', 'aria-labelledby': 'rail-title'}, head, figureBox, where));

  /** A new published value: the old number crossfades into the new one and an underline fades out. Never on the first value. */
  function changed(item, before) {
    const ghost = h('span', {class: 'rail-fig__ghost', 'aria-hidden': 'true', text: before});
    item.slot.append(ghost);
    const out = play(ghost, [{opacity: 1}, {opacity: 0}], {duration: MS.digits, easing: EASE});
    if (!out) {
      ghost.remove();
      return;
    }
    out.finished.then(() => ghost.remove(), () => ghost.remove());
    play(item.value, [{opacity: 0}, {opacity: 1}], {duration: MS.digits, easing: EASE});
    play(item.mark, [{opacity: 1}, {opacity: 0}], {duration: MS.underline, easing: 'ease-out'});
  }
  let shownRun = null;

  function drawFigures(state) {
    const {snapshot, model} = state;
    const values = model && model.shift ? model.shift.values : {};
    const run = snapshot && model && model.hasSnapshot ? snapshot.run : null;
    const animate = run !== null && run === shownRun && motionAllowed(state);
    shownRun = run;
    for (const item of figures) {
      const value = values[item.field];
      const published = typeof value === 'number';
      const before = item.value.textContent;
      const words = published ? text.num(value) : text.DASH;
      setText(item.value, words);
      if (animate && published && before !== words && before !== '' && before !== text.DASH) changed(item, before);
      setAttrs(item.node, {
        class: ['rail-fig', item.sign && published && value > 0 && `is-alert is-alert--${item.sign}`],
        'data-value': published ? value : null,
      });
    }
  }

  // ---- rows ---------------------------------------------------------------------------
  const expanded = new Set();

  /** The work state of a zone in words: «работает · 38 т/ч», «остановлен · вывод идёт». */
  function workWords(zone) {
    const {values, units} = zone;
    if (!zone.hasState) return R.noState;
    const parts = [];
    if (values.work_state === 'working') {
      const rate = typeof values.production_rate === 'number' ? text.quantity(values.production_rate, units.production_rate) : '';
      parts.push(R.working(rate));
    } else if (values.work_state === 'stopped') {
      parts.push(R.stopped);
    } else {
      parts.push(`${text.fieldLabel('work_state', 'zone')}: ${text.label('workState', values.work_state)}`);
    }
    const withdrawal = {in_progress: R.withdrawing, done: R.withdrawn, incomplete: R.incomplete}[values.withdrawal_state];
    if (withdrawal) parts.push(withdrawal);
    else if (values.withdrawal_state !== undefined && !text.isKnown('withdrawal', values.withdrawal_state)) {
      parts.push(text.label('withdrawal', values.withdrawal_state));
    }
    return parts.join(' · ');
  }

  /** What a dot says: its code and the published state of the worker. */
  function workerWords(worker, model) {
    const {values} = worker;
    if (!worker.hasState) return R.worker(worker.label, UI.list.noState);
    if (values.status === 'out') {
      const exit = typeof values.at_exit === 'string' ? labelOf(model, values.at_exit) : '';
      return R.worker(worker.label, [text.label('workerStatus', 'out'), exit].filter(Boolean).join(' · '));
    }
    const parts = [text.label('workerStatus', values.status)];
    const working = typeof values.at_working === 'string' ? model.byName[values.at_working] : null;
    if (knownHazard(values.location_hazard) === 'danger') parts.push(UI.legend.inDangerZone);
    else if (values.location_hazard === 'unknown' && working && working.values.data_quality === 'none') {
      parts.push(`${text.label('kind', 'working')} ${UI.scheme.noSensors}`);
    } else if (values.location_hazard !== undefined) parts.push(`${UI.incident.zone}: ${text.hazardCodeText(values.location_hazard)}`);
    parts.push(text.label('egress', values.egress_status));
    if (values.pos_quality !== undefined && values.pos_quality !== 'fresh') parts.push(text.label('posQuality', values.pos_quality));
    return R.worker(worker.label, parts.join('; '));
  }

  /** The groups of the rail, from the published position and status of every worker. */
  function groupsOf(model) {
    const zones = thingsOfKind(model, 'zone');
    const byZone = new Map(zones.map((zone) => [zone.name, []]));
    const outside = [];
    const noPosition = [];
    const out = new Map();
    for (const worker of thingsOfKind(model, 'worker')) {
      const {values} = worker;
      if (!worker.hasState) {
        noPosition.push(worker);
      } else if (values.status === 'out') {
        const exit = typeof values.at_exit === 'string' ? values.at_exit : '';
        if (!out.has(exit)) out.set(exit, []);
        out.get(exit).push(worker);
      } else if (typeof values.at_working === 'string') {
        const zone = zoneOfWorking(model, values.at_working);
        if (zone && byZone.has(zone.name)) byZone.get(zone.name).push(worker);
        else outside.push(worker);
      } else {
        noPosition.push(worker);
      }
    }
    const groups = zones.map((zone) => ({key: zone.thingId, type: 'zone', zone, workers: byZone.get(zone.name)}));
    groups.push({key: 'outside', type: 'outside', title: R.outside, workers: outside});
    if (noPosition.length > 0) groups.push({key: 'no-position', type: 'outside', title: R.noPosition, workers: noPosition});
    groups.push({key: 'out', type: 'out', title: R.out,
      exits: [...out.entries()].map(([exit, workers]) => ({key: exit || '-', exit, workers}))});
    return groups;
  }

  function createDot(worker, out) {
    const button = h('button', {class: ['dot', out && 'dot--out'], type: 'button', 'data-testid': 'rail-worker'}, dotPicture(out));
    button.addEventListener('click', () => ctx.select(button.getAttribute('data-rail-worker')));
    return button;
  }

  function drawDots(holder, workers, state, out = false) {
    const {model, ui} = state;
    reconcile(holder, workers, (worker) => worker.thingId, (worker) => createDot(worker, out), (button, worker) => {
      const {values} = worker;
      const words = workerWords(worker, model);
      setAttrs(button, {
        'data-rail-worker': worker.thingId,
        'aria-label': words, title: words,
        'aria-pressed': String(ui.selected === worker.thingId),
        class: ['dot', out && 'dot--out', ui.selected === worker.thingId && 'is-selected'],
      });
      const marker = button.querySelector('.worker');
      if (marker) {
        // A working without sensors by design (data_quality = none) is not an unknown monitored zone: no fog ring
        // there, as the model does not count such workers in «состояние неизвестно» either (CONTRACT §7).
        const working = typeof values.at_working === 'string' ? model.byName[values.at_working] : null;
        const unmonitored = values.location_hazard === 'unknown' && working && working.values.data_quality === 'none';
        setAttrs(marker, {
          'data-egress': values.egress_status === undefined ? null : String(values.egress_status),
          'data-location-hazard': values.location_hazard === undefined || unmonitored ? null : String(values.location_hazard),
          'data-pos-quality': values.pos_quality === undefined ? null : String(values.pos_quality),
          class: ['worker', values.status === 'moving_to_exit' && 'is-going'],
        });
      }
      setAttrs(button, {'data-status': typeof values.status === 'string' ? values.status : null,
        'data-egress': typeof values.egress_status === 'string' ? values.egress_status : null,
        'data-location-hazard': typeof values.location_hazard === 'string' ? values.location_hazard : null});
    });
  }

  function createRow(group) {
    if (group.type === 'zone') {
      const name = h('span', {class: 'zrow__name'});
      const badge = h('span', {class: 'badge zrow__badge'}, h('span', {class: 'badge__sign'}), h('span', {class: 'badge__words'}));
      const words = h('span', {class: 'zrow__state'});
      const note = h('span', {class: 'zrow__note', hidden: true});
      // The row is one big target (the button lies under its words); the dots and the chevron are their own buttons.
      const main = h('button', {class: 'zrow__main', type: 'button', 'data-testid': 'rail-zone'});
      main.addEventListener('click', () => {
        const id = group.zone.thingId;
        ctx.select(id);
        ctx.stage.focus(id);
      });
      const actionsId = `rail-actions-${group.zone.name}`;
      const more = h('button', {
        class: 'btn btn--quiet zrow__more', type: 'button', 'data-testid': 'rail-zone-actions', 'aria-expanded': 'false',
        'aria-controls': actionsId,
      }, s('svg', {class: 'zrow__chevron', viewBox: '0 0 12 12', width: 12, height: 12, 'aria-hidden': 'true', focusable: 'false'},
        s('path', {d: 'M2.5 4.5L6 8l3.5-3.5'})));
      const block = zoneActions(ctx, group.zone.name);
      const panel = h('div', {class: 'zrow__actions', id: actionsId, hidden: true}, block.node);
      more.addEventListener('click', () => {
        const name = group.zone.name;
        if (expanded.has(name)) expanded.delete(name);
        else expanded.add(name);
        draw();
      });
      const dots = h('div', {class: 'zrow__dots'});
      const row = h('li', {class: 'zrow zrow--zone'}, main,
        h('div', {class: 'zrow__top'}, name, ' ', badge, h('span', {class: 'zrow__gap'}), more),
        h('div', {class: 'zrow__sub'}, words, ' ', dots), note, panel);
      row.railParts = {name, badge, words, note, main, more, dots, panel, block};
      return row;
    }
    const title = h('span', {class: 'zrow__name'});
    const count = h('span', {class: 'zrow__state'});
    const body = h('div', {class: group.type === 'out' ? 'zrow__exits' : 'zrow__dots'});
    const row = group.type === 'out'
      ? h('li', {class: 'zrow zrow--out'}, h('div', {class: 'zrow__top'}, title, ' ', count), body)
      : h('li', {class: 'zrow zrow--outside'}, h('div', {class: 'zrow__top'}, title, ' ', count, ' ', body));
    row.railParts = {title, count, body};
    return row;
  }

  function updateRow(row, group, state) {
    const parts = row.railParts;
    const {model, ui, snapshot} = state;
    if (group.type === 'zone') {
      const {zone} = group;
      const hazard = zone.hazard.state;
      setText(parts.name, zone.label);
      setAttrs(parts.badge, {class: ['badge', 'zrow__badge', `badge--${hazard}`], title: text.hazardText(zone.hazard)});
      const [signHolder, badgeWords] = parts.badge.children;
      signHolder.hidden = !HAZARD_SIGN[hazard];
      if (HAZARD_SIGN[hazard]) setSign(signHolder, HAZARD_SIGN[hazard]);
      setText(badgeWords, zone.hasState ? R.hazardShort[hazard] : text.DASH);
      setText(parts.words, workWords(zone));
      // A past danger stays in sight after the data were lost; a past «норма» is not repeated here (the card has it):
      // next to «состояние неизвестно» it would read as reassurance.
      const past = knownHazard(zone.values.last_known_hazard_state);
      const lastKnown = zone.hasState && (past === 'attention' || past === 'danger')
        ? text.lastKnownText(zone.values, snapshot ? snapshot.simTimeS : undefined) : '';
      setText(parts.note, lastKnown);
      parts.note.hidden = !lastKnown;
      setAttrs(parts.note, {'data-last-known': zone.values.last_known_hazard_state || null, title: lastKnown ? text.lastKnownTitle(zone.values) : null});
      setAttrs(parts.main, {'aria-label': `${R.selectZone(zone.label)}. ${text.hazardText(zone.hazard)}; ${workWords(zone)}`,
        'aria-pressed': String(ui.selected === zone.thingId)});
      const open = expanded.has(zone.name);
      setAttrs(parts.more, {'aria-expanded': String(open), title: R.actionsTitle(zone.label), 'aria-label': R.actionsTitle(zone.label)});
      parts.panel.hidden = !open;
      if (open) parts.block.render(state);
      // A zone whose published hazard changed while the page watched flashes once (450 ms).
      const before = row.getAttribute('data-hazard');
      if (before && before !== hazard && flashing) {
        play(row, [{backgroundColor: 'rgba(232, 227, 218, .22)'}, {backgroundColor: 'rgba(232, 227, 218, 0)'}],
          {duration: MS.flash, easing: 'ease-out'});
      }
      setAttrs(row, {
        'data-rail-zone': zone.thingId,
        'data-hazard': hazard,
        'data-quality': typeof zone.values.data_quality === 'string' ? zone.values.data_quality : null,
        'data-work-state': typeof zone.values.work_state === 'string' ? zone.values.work_state : null,
        'data-withdrawal': typeof zone.values.withdrawal_state === 'string' ? zone.values.withdrawal_state : null,
        'data-count': group.workers.length,
        'data-open': open ? 'true' : null,
        class: ['zrow', 'zrow--zone', ui.selected === zone.thingId && 'is-selected'],
      });
      drawDots(parts.dots, group.workers, state);
      setAttrs(parts.dots, {'data-empty': group.workers.length === 0 ? R.nobody : null});
      return;
    }
    setText(parts.title, group.title);
    setAttrs(row, {'data-rail-group': group.key});
    if (group.type === 'out') {
      const total = group.exits.reduce((sum, item) => sum + item.workers.length, 0);
      setAttrs(row, {'data-count': total});
      setText(parts.count, total === 0 ? R.nobodyOut : '');
      reconcile(parts.body, group.exits, (item) => item.key, () => {
        const line = h('div', {class: 'zrow__exit'}, h('span', {class: 'zrow__exit-name'}), h('div', {class: 'zrow__dots'}));
        return line;
      }, (line, item) => {
        setText(line.firstChild, item.exit ? R.exitGroup(labelOf(model, item.exit)) : text.DASH);
        setAttrs(line, {'data-exit': item.exit || null});
        drawDots(line.lastChild, item.workers, state, true);
      });
      return;
    }
    setAttrs(row, {'data-count': group.workers.length});
    setText(parts.count, group.workers.length === 0 ? R.nobody : '');
    drawDots(parts.body, group.workers, state);
  }

  /** Bring a row into the visible part of the list (the list scrolls; nothing else does). */
  function reveal(row) {
    const box = where.getBoundingClientRect();
    const rect = row.getBoundingClientRect();
    const head = where.firstElementChild.getBoundingClientRect().height;
    if (rect.bottom > box.bottom) where.scrollTop += rect.bottom - box.bottom + 8;
    else if (rect.top < box.top + head) where.scrollTop -= box.top + head - rect.top + 8;
  }

  // The zone of an incident that opened: its row is brought into sight once per incident (small screens).
  let revealedIncident = null;

  // Set by every drawing: a change may flash only within one run of a current snapshot, never on the first picture.
  let flashing = false;
  let drawnRun = null;

  function draw() {
    const state = store.getState();
    const run = state.snapshot ? state.snapshot.run : null;
    flashing = run !== null && run === drawnRun && motionAllowed(state);
    drawnRun = run;
    drawFigures(state);
    const groups = state.model && state.model.hasSnapshot ? groupsOf(state.model) : [];
    reconcile(rows, groups, (group) => group.key, createRow, (row, group) => updateRow(row, group, state));
    setAttrs(rows, {'data-state': state.model && state.model.hasSnapshot ? null : 'empty'});
    const incident = state.model && state.model.hasSnapshot ? incidentOf(state.model) : null;
    const open = incident && OPEN.has(incident.values.state) && typeof incident.values.zone === 'string';
    const key = open ? `${state.snapshot.run}:${incident.values.zone}:${incident.values.opened_at_tick}` : null;
    if (key !== revealedIncident) {
      revealedIncident = key;
      const row = key ? rows.querySelector(`[data-rail-zone="${CSS.escape(fullId(incident.values.zone))}"]`) : null;
      if (row && where.offsetParent !== null) reveal(row);
    }
  }

  shell.watch((frame) => {
    const collapsed = frame.rail === 'collapsed';
    setAttrs(toggle, {'aria-expanded': String(!collapsed), title: collapsed ? R.expandTitle : R.collapseTitle,
      'aria-label': collapsed ? R.expandTitle : R.collapseTitle});
  });
  store.watch((state) => [state.model, state.snapshot, state.ui.selected, state.pending, state.commandsBlocked, state.blockReason], draw);
}
