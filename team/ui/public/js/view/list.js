// The «Список» view: the same twins as the stage, as a dense table, so that
// the data can be checked without reading the drawing. One row per twin, one
// or two lines high, with the three axes in separate columns (hazard,
// knowledge, reachability) as the badges of the card.

import {unresolvedFor} from '../commands.js';
import {h, onActivate, reconcile, setAttrs, setText} from '../dom.js';
import {causesOf, knownHazard, labelOf, placeOf, stateAttributes, thingsOfKind} from '../model.js';
import {LIST_TYPES} from '../router.js';

const KINDS = LIST_TYPES.filter((type) => type !== 'all');
/** Cells that carry a state: the badge class follows the value. */
const HAZARD_BADGE = {normal: 'ok', attention: 'attention', danger: 'danger', unknown: 'unknown'};

/**
 * @typedef {Object} Cell
 * @property {string} text
 * @property {string|null} [badge] a badge modifier: ok | attention | danger | unknown | blocked
 * @property {string} [title] the full sentence when the cell shows a short label
 * @property {{text: string, badge: (string|null)}} [note] a second statement of the same cell, on its own line
 */

const plain = (text) => ({text});

function hazardCell(text, thing) {
  const cell = {text: text.hazardText(thing.hazard), badge: HAZARD_BADGE[thing.hazard.state]};
  // The last assessment before the data were lost keeps its own mark: a past danger must stay visible.
  const lastKnown = text.lastKnownText(thing.values);
  if (lastKnown) cell.note = {text: lastKnown, badge: HAZARD_BADGE[knownHazard(thing.values.last_known_hazard_state)]};
  return cell;
}

/**
 * The knowledge of a working or a zone. A twin without sensors gets the short «без датчиков»: the
 * hazard cell next to it says «состояние неизвестно», and the card gives the full sentence.
 */
function knowledgeCell(text, code) {
  const full = text.label('quality', code);
  return code === 'none' ? {text: text.UI.list.noSensors, badge: 'unknown', title: full} : {text: full, badge: knowledgeBadge(code)};
}

function knowledgeBadge(code) {
  if (code === 'fresh') return 'ok';
  if (code === 'stale') return 'attention';
  return 'unknown';
}

function passabilityBadge(code) {
  if (code === 'open') return null;
  return code === 'closed' ? 'blocked' : 'unknown';
}

/** The reason of the hazard state, unless the knowledge column already says the same. */
function reasonCell(text, values, name) {
  return values.reason_code === 'no_sensor' ? '' : text.reasonText(values, name);
}

function join(parts) {
  const shown = parts.filter((part) => part !== '' && part !== null && part !== undefined);
  return shown.length > 0 ? shown.join('; ') : null;
}

/**
 * The nine cells of a row: type, code, place, hazard, knowledge, reachability,
 * value and state, model time, platform time. A dash stands for "not published".
 * @returns {Cell[]}
 */
function rowCells(text, model, thing, snapshot) {
  const {values, units, attrs} = thing;
  const name = (local) => labelOf(model, local);
  const DASH = plain(text.DASH);
  const kind = plain(text.label('kind', thing.kind));
  const code = plain(thing.label);
  const place = plain(text.placeText(placeOf(model, thing)));
  const modelTime = plain(text.tickTime(values.sim_time_s, values.tick));
  const platformTime = plain(thing.hasState && snapshot ? text.utcTime(snapshot.modifiedMs) : text.DASH);
  let hazard = DASH;
  let knowledge = DASH;
  let reach = DASH;
  let value = null;

  if (!thing.hasState && thing.kind !== 'level') {
    value = text.UI.list.noState;
  } else if (thing.kind === 'level') {
    place.text = typeof attrs.elevation_m === 'number' ? `${text.fieldLabel('elevation_m')} ${text.quantity(attrs.elevation_m, 'm')}` : text.DASH;
  } else if (thing.kind === 'working') {
    hazard = hazardCell(text, thing);
    knowledge = knowledgeCell(text, values.data_quality);
    const restriction = values.routing_restriction && values.routing_restriction !== 'allowed'
      ? text.label('restriction', values.routing_restriction) : '';
    reach = {
      text: join([text.passabilityText(values), restriction]),
      badge: passabilityBadge(values.passability),
    };
    value = join([
      typeof values.instability_index === 'number'
        ? `${text.fieldLabel('instability_index')} ${text.quantity(values.instability_index, units.instability_index)}` : '',
      reasonCell(text, values, name),
      typeof attrs.length_m === 'number' ? `${text.fieldLabel('length_m')} ${text.quantity(attrs.length_m, 'm')}` : '',
    ]);
  } else if (thing.kind === 'zone') {
    hazard = hazardCell(text, thing);
    knowledge = knowledgeCell(text, values.data_quality);
    const restriction = values.routing_restriction && values.routing_restriction !== 'allowed'
      ? text.label('restriction', values.routing_restriction) : '';
    if (restriction) reach = plain(restriction);
    value = join([
      text.label('workState', values.work_state),
      text.label('withdrawal', values.withdrawal_state),
      typeof values.workers_count === 'number' ? text.counted(values.workers_count, text.FORMS.worker) : '',
      typeof values.production_rate === 'number' ? text.quantity(values.production_rate, units.production_rate) : '',
      typeof values.instability_index === 'number'
        ? `${text.fieldLabel('instability_index')} ${text.quantity(values.instability_index, units.instability_index)}` : '',
      reasonCell(text, values, name),
      typeof values.downtime_s === 'number' && values.downtime_s > 0
        ? `${text.fieldLabel('downtime_s', 'zone')} ${text.quantity(values.downtime_s, units.downtime_s)}` : '',
    ]);
  } else if (thing.kind === 'sensor') {
    knowledge = {
      text: join([text.label('quality', values.quality), text.label('linkState', values.link_state)]),
      badge: knowledgeBadge(values.quality),
    };
    value = join([
      text.label('sensorKind', attrs.sensor_kind),
      typeof values.value === 'number' ? text.quantity(values.value, units.value) : '',
      typeof values.rate === 'number' ? text.quantity(values.rate, units.rate) : '',
      typeof values.events_count === 'number' ? text.counted(values.events_count, text.FORMS.event) : '',
    ]);
    modelTime.text = `${text.UI.list.measured} ${text.tickTime(values.measured_at_sim_s, values.measured_at_tick)}`;
  } else if (thing.kind === 'worker') {
    if (values.location_hazard !== undefined) {
      hazard = {
        text: `${text.UI.incident.zone}: ${text.hazardCodeText(values.location_hazard)}`,
        badge: HAZARD_BADGE[knownHazard(values.location_hazard)],
      };
    }
    if (values.pos_quality !== undefined) {
      knowledge = {text: text.label('posQuality', values.pos_quality), badge: knowledgeBadge(values.pos_quality)};
    }
    const reachBadge = {ok: 'ok', none: 'blocked'}[values.egress_status] || 'unknown';
    reach = {text: join([text.egressText(values, name), text.crossesText(values)]), badge: reachBadge};
    value = text.label('workerStatus', values.status);
  } else if (thing.kind === 'exit') {
    reach = {
      text: text.label('exitState', values.state),
      badge: {available: 'ok', unavailable: 'blocked'}[values.state] || 'unknown',
    };
    value = join([
      text.label('exitKind', attrs.exit_kind),
      typeof values.workers_out === 'number' ? text.UI.scheme.out(values.workers_out) : '',
    ]);
  } else if (thing.kind === 'incident') {
    const causes = causesOf(values).map((cause) => (typeof cause.subject === 'string'
      ? `${text.label('incidentTrigger', cause.trigger)} (${name(cause.subject)})` : text.label('incidentTrigger', cause.trigger)));
    value = join([
      text.label('incidentState', values.state),
      ...causes,
      typeof values.selected_option === 'string' ? `${text.fieldLabel('selected_option')} ${name(values.selected_option)}` : '',
    ]);
  } else if (thing.kind === 'option') {
    const fields = Object.keys(values)
      .filter((field) => /^(forecast|actual)_/.test(field) && !['forecast_tick', 'forecast_quality', 'forecast_horizon_s'].includes(field))
      .sort();
    const metrics = fields.map((field) => {
      const shown = typeof values[field] === 'boolean' ? text.yesNo(values[field])
        : (field.endsWith('last_out_s') ? text.duration(values[field]) : text.quantity(values[field], units[field]));
      return `${text.fieldLabel(field)} ${shown}`;
    });
    const published = Object.keys(values).some((field) => field.startsWith('forecast_'));
    // Forecast numbers never stand without a word on how complete the forecast is.
    let quality = '';
    if (typeof values.forecast_quality === 'string') quality = `${text.UI.decision.forecast} ${text.label('forecastQuality', values.forecast_quality)}`;
    else if (fields.some((field) => field.startsWith('forecast_'))) quality = text.UI.decision.qualityNotPublished;
    value = join([
      text.codeLabel('optionKind', attrs.option_kind),
      text.label('optionState', values.state),
      values.state !== 'inactive' && !published ? text.UI.decision.notPublished : '',
      quality,
      ...metrics,
    ]);
  } else if (thing.kind === 'journal') {
    value = join([
      Array.isArray(values.events) ? text.counted(values.events.length, text.FORMS.event) : '',
      typeof values.last_seq === 'number' ? `${text.fieldLabel('last_seq')} ${text.num(values.last_seq)}` : '',
    ]);
  }
  for (const cell of [hazard, knowledge, reach]) {
    if (cell.text === null) cell.text = text.DASH;
  }
  return [kind, code, place, hazard, knowledge, reach, plain(value === null ? text.DASH : value), modelTime, platformTime];
}

export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;

  const select = h('select', {class: 'select', id: 'list-type', 'data-testid': 'list-type'},
    LIST_TYPES.map((type) => h('option', {value: type, text: text.VOCAB.kindPlural[type]})));
  select.addEventListener('change', () => ctx.setListType(select.value));
  const count = h('span', {class: 'muted', 'data-testid': 'list-count'});
  const body = h('tbody');
  const note = h('p', {class: 'empty-note', hidden: true});
  const table = h('table', {class: 'table table--list', 'data-testid': 'list-table'},
    h('thead', null, h('tr', null, UI.list.columns.map((title) => h('th', {scope: 'col', text: title})))),
    body);
  root.append(
    h('div', {class: 'view__bar'},
      h('h2', {class: 'panel__title', text: UI.list.title}),
      h('label', {class: 'field', for: 'list-type'}, UI.list.filter),
      select, count),
    h('div', {class: 'view__scroll'}, table, note),
  );

  function createRow(thing) {
    const row = h('tr', {tabindex: 0, class: 'row'},
      UI.list.columns.map(() => h('td', null, h('span', {class: 'cell'}), h('span', {class: 'cell-note', hidden: true}))));
    row.cells[1].classList.add('mono');
    row.cells[7].classList.add('mono');
    row.cells[8].classList.add('mono');
    onActivate(row, () => ctx.select(thing.thingId));
    return row;
  }

  store.watch((state) => [state.model, state.snapshot, state.ui.listType, state.ui.selected, state.pending], () => {
    const state = store.getState();
    const {model, snapshot, ui} = state;
    if (select.value !== ui.listType) select.value = ui.listType;
    const kinds = ui.listType === 'all' ? KINDS : [ui.listType];
    const things = model ? kinds.flatMap((kind) => thingsOfKind(model, kind)) : [];
    // The tick this view shows: a view that stopped following the state is told apart from the others.
    setAttrs(table, {'data-tick': snapshot && model && model.hasSnapshot ? snapshot.tick : null});
    reconcile(body, things, (thing) => thing.thingId, createRow, (row, thing) => {
      const pending = unresolvedFor(state.pending, thing.name).length > 0;
      const selected = thing.thingId === ui.selected;
      setAttrs(row, {
        ...stateAttributes(thing, pending),
        'aria-selected': String(selected),
        class: ['row', selected && 'is-selected'],
      });
      const cells = rowCells(text, model, thing, snapshot);
      // A twin with nothing to say about reachability gives that column to its value: a long state
      // of a zone or an option then takes three lines instead of eight.
      const wide = cells[5].text === text.DASH;
      row.cells[5].hidden = wide;
      row.cells[6].colSpan = wide ? 2 : 1;
      cells.forEach((cell, index) => {
        const [span, note] = row.cells[index].children;
        let shown = cell.text;
        if (index === 1 && selected) shown += ` (${UI.list.selected})`;
        if (index === 6 && pending) shown += `; ${UI.list.pending}`;
        setText(span, shown);
        // The value cell is clamped to two lines: its whole text is also its title.
        setAttrs(span, {class: ['cell', cell.badge && `badge badge--${cell.badge}`], title: cell.title || (index === 6 ? shown : null)});
        setText(note, cell.note ? cell.note.text : '');
        setAttrs(note, {hidden: !cell.note, class: ['cell-note', cell.note && cell.note.badge && `badge badge--${cell.note.badge}`]});
      });
    });
    setText(count, model ? UI.list.count(things.length) : '');
    note.hidden = things.length > 0;
    setText(note, model ? UI.list.empty : UI.list.noAttributes);
  });
}
