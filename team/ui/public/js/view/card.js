// The card. Nothing selected: the summary of the shift as the model published
// it. An object selected: its state from the same full snapshot the scheme
// shows (never a separate read), every published value with its label and
// unit, the reason of the state as a sentence, and the related twins as
// buttons that select them. Nothing is computed here.

import {unresolvedFor} from '../commands.js';
import {h, reconcile, setAttrs, setText} from '../dom.js';
import {
  exitAtNode, knownHazard, labelOf, placeOf, routeOf, sensorsOfWorking, sensorsOfZone, thingByName, thingsOfKind,
  workersAtExit, workersAtWorking, workersInZone, workingsOfZone,
} from '../model.js';

const BADGE = {normal: 'ok', attention: 'attention', danger: 'danger', unknown: 'unknown'};
/** Features and attributes whose value is a code: field -> vocabulary of text.js. */
const VOCAB_OF = {
  passability: 'passability', closed_by: 'closedBy', data_quality: 'quality', quality: 'quality',
  routing_restriction: 'restriction', last_known_hazard_state: 'hazard', work_state: 'workState',
  withdrawal_state: 'withdrawal', link_state: 'linkState', pos_quality: 'posQuality', location_hazard: 'hazard',
  egress_status: 'egress', egress_reason: 'egressReason', egress_crosses: 'hazard', reason_code: 'reasonCode',
  run_state: 'runState', pause_reason: 'pauseReason', forecast_quality: 'forecastQuality', trigger: 'incidentTrigger',
  working_kind: 'workingKind', sensor_kind: 'sensorKind', exit_kind: 'exitKind',
};
const STATE_VOCAB = {exit: 'exitState', incident: 'incidentState', option: 'optionState'};
/** Shown in the line of times, not as rows. */
const TIME_FIELDS = new Set(['tick', 'sim_time_s', 'idSimulationRun']);
const SKIPPED_ATTRS = new Set(['kind', 'label', '_parents', 'nodes', 'manifest', 'dynamic_ids', 'presets', 'thresholds',
  'counts', 'points', 'workings', 'sensors']);
const PEOPLE = ['workers_total', 'workers_out', 'workers_in_danger', 'workers_no_route', 'workers_unknown',
  'danger_exposure_person_s', 'unknown_exposure_person_s', 'all_out', 'downtime_s'];

export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;

  const kind = h('span', {class: 'card__kind'});
  const code = h('span', {class: 'card__code mono'});
  const close = h('button', {class: 'btn btn--small card__close', type: 'button', 'data-testid': 'card-close', text: UI.card.close});
  close.addEventListener('click', () => ctx.select(null));
  const hint = h('p', {class: 'card__hint'});
  const lead = h('div', {class: 'card__lead', 'data-testid': 'card-lead'});
  const sections = h('div');
  const times = h('p', {class: 'card__times mono', 'data-testid': 'card-times'});
  root.append(h('div', {class: 'card'}, h('div', {class: 'card__head'}, kind, code, close), hint, lead, sections, times));

  function draw(view) {
    setText(kind, view.kind);
    setText(code, view.code);
    close.hidden = !view.selected;
    setText(hint, view.hint);
    hint.hidden = !view.hint;
    reconcile(lead, view.lead, (line, index) => index, () => h('span'), (span, line) => {
      setText(span, line.text);
      setAttrs(span, {class: [line.main && 'card__main', line.badge && `badge badge--${line.badge}`]});
    });
    lead.hidden = view.lead.length === 0;
    reconcile(sections, view.sections, (section) => section.key, (section) => h('section', {class: 'card__section', 'data-section': section.key},
      h('h3', {class: 'panel__title'}),
      section.rows ? h('dl', {class: 'kv'})
        : (section.notes ? h('ul', {class: 'card__notes'}) : h('div', {class: section.wide ? 'card__rows' : 'card__links'})),
    ), (node, section) => {
      setText(node.firstChild, section.title);
      const body = node.lastChild;
      if (section.rows) {
        reconcile(body, section.rows, (row) => row[2], () => h('div', null, h('dt'), h('dd')), (row, [label, value]) => {
          setText(row.firstChild, label);
          setText(row.lastChild, value);
        });
      } else if (section.notes) {
        reconcile(body, section.notes, (note, index) => index, () => h('li'), (item, note) => {
          setText(item, note.text);
          setAttrs(item, {class: note.compact ? 'card__note--compact' : null});
        });
      } else {
        // Buttons keep their node from poll to poll, so the one in focus stays in focus.
        reconcile(body, section.links, (link, index) => link.id || `text-${index}`, (link) => {
          if (!link.id) return h('span', {class: 'chip'});
          const button = h('button', {class: 'btn btn--small', type: 'button', 'data-select': link.id}, h('span', {class: 'muted'}), h('span'));
          button.addEventListener('click', () => ctx.select(link.id));
          return button;
        }, (node_, link) => {
          if (!link.id) {
            setText(node_, link.text);
            setAttrs(node_, {class: ['chip', link.stand && 'chip--stand']});
            return;
          }
          setText(node_.firstChild, link.prefix ? `${link.prefix} ` : '');
          setText(node_.lastChild, link.text);
          setAttrs(node_.lastChild, {class: [link.badge && `badge badge--${link.badge}`]});
        });
      }
    });
    setText(times, view.times.join('  |  '));
    times.hidden = view.times.length === 0;
  }

  function build(state) {
    const {model, snapshot, ui} = state;
    const view = {kind: UI.card.title, code: '', selected: false, hint: '', lead: [], sections: [], times: []};
    if (!model) return view;
    const name = (local) => labelOf(model, local);
    const link = (thing, words, badge) => ({
      id: thing.thingId, prefix: words === undefined ? text.label('kind', thing.kind) : '', text: words === undefined ? thing.label : words, badge,
    });
    if (snapshot) {
      view.times.push(`${UI.card.modelTime}: ${text.tickTime(snapshot.simTimeS, snapshot.tick)}`,
        `${UI.card.platformTime}: ${text.utcTime(snapshot.modifiedMs)}`);
    }

    const thing = ui.selected ? model.things[ui.selected] : null;
    if (ui.selected && !thing) {
      view.selected = true;
      view.hint = UI.card.notFound;
      return view;
    }
    if (!thing) return summary(view, state, name, link);

    const {values, units, attrs} = thing;
    view.selected = true;
    view.kind = `${UI.card.title} · ${text.label('kind', thing.kind)}`;
    view.code = thing.label;
    if (!thing.hasState && !['level', 'mine'].includes(thing.kind)) view.hint = UI.list.noState;
    const say = (words, badge, main) => {
      if (words && words !== text.DASH) view.lead.push({text: words, badge, main});
    };

    /** A value as the screen shows it: a code in words, a number with its unit, a twin by its code. */
    const show = (field, value, unit) => {
      if (field === 'hazard_state' && thing.hazard) return text.hazardText(thing.hazard) + (thing.hazard.defensive ? UI.card.defensive : '');
      let vocab = VOCAB_OF[field];
      if (field === 'state') vocab = STATE_VOCAB[thing.kind];
      if (field === 'status' && thing.kind === 'worker') vocab = 'workerStatus';
      if (field === 'option_kind') return text.codeLabel('optionKind', value);
      if (vocab && typeof value === 'string') return text.label(vocab, value) || UI.card.none;
      if (typeof value === 'boolean') return text.yesNo(value);
      if (typeof value === 'number') {
        if (field.endsWith('_at_sim_s')) return `${text.modelTime(value)} (${text.quantity(value, 's')})`;
        const shown = text.quantity(value, unit);
        return unit === 's' && value >= 60 ? `${shown} (${text.duration(value)})` : shown;
      }
      if (typeof value === 'string') return thingByName(model, value) ? text.codeAndName(value, name) : value;
      if (Array.isArray(value)) {
        if (field === 'route') return routeOf(model, thing).map((segment) => name(segment.working)).join(' → ') || UI.card.none;
        if (value.length === 0) return UI.card.none;
        return value.every((item) => typeof item === 'string') ? value.map(name).join(', ') : UI.card.records(value.length);
      }
      return JSON.stringify(value);
    };

    // The state in sentences.
    if (thing.hazard) {
      say(text.hazardText(thing.hazard) + (thing.hazard.defensive ? UI.card.defensive : ''), BADGE[thing.hazard.state], true);
      say(text.label('quality', values.data_quality));
      say(text.lastKnownText(values), BADGE[knownHazard(values.last_known_hazard_state)]);
      const reason = text.reasonText(values, name);
      if (reason && values.reason_code !== 'no_sensor') say(`${text.fieldLabel('reason_code')}: ${reason}`);
      if (typeof values.instability_index === 'number') {
        const at = typeof values.index_at_tick !== 'number' ? ''
          : ` (${thing.hazard.state === 'unknown' ? UI.card.indexLastComputed(values.index_at_tick) : UI.card.indexAt(values.index_at_tick)})`;
        say(`${text.fieldLabel('instability_index')}: ${text.quantity(values.instability_index, units.instability_index)}${at}`);
      }
      if (values.routing_restriction !== undefined && values.routing_restriction !== 'allowed') {
        say(text.label('restriction', values.routing_restriction), values.routing_restriction === 'blocked' ? 'blocked' : 'unknown');
      }
    }
    if (thing.kind === 'working') {
      say(text.passabilityText(values), values.passability === 'closed' ? 'blocked' : (values.passability === 'open' ? null : 'unknown'));
    } else if (thing.kind === 'zone') {
      say([text.label('workState', values.work_state), text.label('withdrawal', values.withdrawal_state)]
        .filter((words) => words !== text.DASH).join('; '));
    } else if (thing.kind === 'sensor') {
      say(text.label('quality', values.quality), {fresh: 'ok', stale: 'attention'}[values.quality] || 'unknown', true);
      say(text.label('linkState', values.link_state));
      if (typeof values.measured_at_sim_s === 'number') {
        say((values.quality === 'fresh' ? UI.card.measuredAt : UI.card.lastMeasurement)(text.modelTime(values.measured_at_sim_s)));
      }
    } else if (thing.kind === 'worker') {
      const status = values.egress_status;
      if (values.status === 'out' || status === 'ok') {
        say(text.egressText(values, name), 'ok', true);
        say(text.crossesText(values), BADGE[knownHazard(values.egress_crosses)]);
      } else {
        const noPath = status === 'none' && values.egress_reason === 'no_open_path';
        say(noPath ? UI.card.noRoute(thing.label) : text.egressText(values, name), status === 'none' ? 'blocked' : 'unknown', true);
        if (status === 'none') say(UI.card.graphOnly);
      }
      if (values.location_hazard !== undefined) {
        say(`${UI.incident.zone}: ${text.hazardCodeText(values.location_hazard)}`, BADGE[knownHazard(values.location_hazard)]);
      }
      say(text.label('workerStatus', values.status));
      say(text.placeText(placeOf(model, thing)));
    } else if (thing.kind === 'exit') {
      say(text.label('exitState', values.state), {available: 'ok', unavailable: 'blocked'}[values.state] || 'unknown', true);
      if (typeof values.workers_out === 'number') say(UI.scheme.out(values.workers_out));
    }
    if (unresolvedFor(state.pending, thing.name).length > 0) say(UI.scheme.pending, 'info');

    // Every published value, then the attributes.
    const stateRows = Object.keys(values).filter((field) => !TIME_FIELDS.has(field) && !field.startsWith('reason_') && field !== 'scene')
      .map((field) => [text.fieldLabel(field, thing.kind), show(field, values[field], units[field]), field]);
    if (stateRows.length > 0) view.sections.push({key: 'state', title: UI.card.state, rows: stateRows});
    const unitOf = (field) => (field.endsWith('_m') ? 'm' : (field.endsWith('_s') ? 's' : undefined));
    const attrRows = Object.keys(attrs).filter((field) => !SKIPPED_ATTRS.has(field))
      .map((field) => [text.fieldLabel(field, thing.kind), show(field, attrs[field], unitOf(field)), field]);
    if (attrRows.length > 0) view.sections.push({key: 'attributes', title: UI.card.attributes, rows: attrRows});

    // Related twins.
    const related = [];
    const add = (other) => {
      if (other && other !== thing && !related.includes(other)) related.push(other);
    };
    const place = placeOf(model, thing);
    if (thing.kind === 'working') {
      add(place.zone);
      sensorsOfWorking(model, thing.name).forEach(add);
      workersAtWorking(model, thing.name).forEach(add);
      [attrs.from, attrs.to].forEach((node) => add(exitAtNode(model, node)));
    } else if (thing.kind === 'zone') {
      workingsOfZone(model, thing.name).forEach(add);
      sensorsOfZone(model, thing.name).forEach(add);
      workersInZone(model, thing.name).forEach(add);
    } else if (thing.kind === 'sensor') {
      add(place.working);
      add(place.zone);
    } else if (thing.kind === 'worker') {
      add(place.working);
      add(place.zone);
      add(place.exit);
      add(thingByName(model, values.egress_exit));
      routeOf(model, thing).forEach((segment) => add(thingByName(model, segment.working)));
    } else if (thing.kind === 'exit') {
      thingsOfKind(model, 'working').filter((working) => working.attrs.from === attrs.node || working.attrs.to === attrs.node).forEach(add);
      workersAtExit(model, thing.name).forEach(add);
    } else if (thing.kind === 'level') {
      thingsOfKind(model, 'zone').filter((zone) => zone.attrs.level === thing.name).forEach(add);
    } else if (thing.kind === 'incident') {
      add(place.zone);
      (Array.isArray(values.causes) ? values.causes : []).forEach((cause) => add(thingByName(model, cause && cause.subject)));
      thingsOfKind(model, 'option').forEach(add);
    } else if (thing.kind === 'option') {
      (Array.isArray(values.scope) ? values.scope : []).forEach((zone) => add(thingByName(model, zone)));
    }
    add(place.level);
    if (related.length > 0) view.sections.push({key: 'related', title: UI.card.related, links: related.map((other) => link(other))});
    if (typeof values.sim_time_s === 'number' && snapshot && values.tick !== snapshot.tick) {
      view.times[0] = `${UI.card.modelTime}: ${text.tickTime(values.sim_time_s, values.tick)}`;
    }
    return view;
  }

  /** Thresholds are a setting of the demonstration: shown as the mine twin gives them, never applied here. */
  function thresholdRows(thresholds) {
    const rows = [];
    for (const [quantity, levels] of Object.entries(thresholds && typeof thresholds === 'object' ? thresholds : {})) {
      if (!levels || typeof levels !== 'object') continue;
      const shown = Object.keys(levels).filter((level) => level !== 'unit')
        .map((level) => `${text.codeLabel('thresholdLevel', level)} ${text.quantity(levels[level], levels.unit)}`);
      rows.push([text.codeLabel('threshold', quantity), shown.join(', '), quantity]);
    }
    return rows;
  }

  function summary(view, state, name, link) {
    const {model} = state;
    view.kind = UI.card.summary;
    view.hint = model.hasSnapshot ? UI.card.nothingSelected : UI.list.noState;
    const shift = model.shift;
    if (shift && model.hasSnapshot) {
      view.sections.push({key: 'people', title: text.VOCAB.kindPlural.worker, rows: PEOPLE.filter((field) => shift.values[field] !== undefined).map((field) => {
        const value = shift.values[field];
        const label = text.METRICS.includes(field) ? text.metricLabel(field) : text.fieldLabel(field);
        return [label, typeof value === 'boolean' ? text.yesNo(value) : text.quantity(value, shift.units[field]), field];
      })});
    }
    view.sections.push({key: 'exits', title: text.VOCAB.kindPlural.exit, wide: true, links: thingsOfKind(model, 'exit').map((exit) => link(exit,
      [`${exit.label}: ${text.label('exitState', exit.values.state)}`,
        typeof exit.values.workers_out === 'number' ? UI.scheme.out(exit.values.workers_out) : ''].filter(Boolean).join('; '),
      exit.values.state === 'available' ? null : (exit.values.state === 'unavailable' ? 'blocked' : 'unknown')))});
    view.sections.push({key: 'zones', title: text.VOCAB.kindPlural.zone, wide: true, links: thingsOfKind(model, 'zone').map((zone) => link(zone,
      [`${zone.label}: ${text.hazardText(zone.hazard)}`, text.label('workState', zone.values.work_state), text.label('withdrawal', zone.values.withdrawal_state),
        typeof zone.values.workers_count === 'number' ? text.counted(zone.values.workers_count, text.FORMS.worker) : '']
        .filter((words) => words && words !== text.DASH).join('; '),
      zone.hazard.state === 'normal' ? null : BADGE[zone.hazard.state]))});
    view.sections.push({key: 'conditions', title: UI.status.conditions, links: model.conditions.length > 0
      ? model.conditions.map((condition) => ({text: text.conditionText(condition, name), stand: true}))
      : [{text: UI.status.noConditions}]});
    const thresholds = thresholdRows(state.attributes ? state.attributes.mine.thresholds : null);
    if (thresholds.length > 0) view.sections.push({key: 'thresholds', title: UI.card.thresholds, rows: thresholds});
    view.sections.push({key: 'marks', title: UI.card.marks, notes: [
      ...UI.card.marksCompact.map((words) => ({text: words, compact: true})), {text: UI.card.otherCodes}]});
    return view;
  }

  store.watch((state) => [state.model, state.snapshot, state.ui.selected, state.pending], () => draw(build(store.getState())));
}
