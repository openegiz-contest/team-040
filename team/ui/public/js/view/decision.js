// The decision panel: what opened the incident, the options of the model with
// their forecast and the choice in one table, and the facts of the executed
// option. Forecast and fact never share a cell, and a time until everyone is
// out is written only when the model says that everyone is out (CONTRACT.md,
// section 6).

import {h, reconcile, setAttrs, setGlyph, setText} from '../dom.js';
import {causesOf, incidentOf, labelOf, thingsOfKind} from '../model.js';
import {blockNote, commandButton, guard, showBlock, standing} from './pending.js';

/** The result metrics in reading order: is everyone out, then people, then exposure, then cost. */
export const METRIC_ORDER = ['all_out', 'last_out_s', 'out', 'in_danger', 'danger_exposure_person_s',
  'unknown_exposure_person_s', 'no_route', 'downtime_s'];

const capitalize = (words) => (words ? words[0].toUpperCase() + words.slice(1) : words);

/** True when the twin publishes at least one result metric with the prefix ("forecast_", "actual_" or none). */
export function hasMetrics(values, prefix) {
  return METRIC_ORDER.some((metric) => values[prefix + metric] !== undefined);
}

/**
 * One result metric as it is written, for an option (prefix "forecast_" or
 * "actual_") and for an archive run (no prefix). Nothing is derived: a value
 * that is not published is a dash, and the time until everyone is out is
 * shown only next to a published `all_out = true`.
 * @param {Object} text the module text.js
 * @param {{values: Object, units: Object}} twin
 * @param {string} prefix
 * @param {string} metric one of METRIC_ORDER
 * @param {boolean} [interrupted] the run was cut short: a missing result stays a dash
 * @returns {{text: string, badge: (string|null)}}
 */
export function metricCell(text, twin, prefix, metric, interrupted = false) {
  const field = prefix + metric;
  const value = twin.values[field];
  const allOut = twin.values[`${prefix}all_out`];
  const plain = (words, badge = null) => ({text: words, badge});
  if (metric === 'all_out') {
    if (value === true) return plain(text.yesNo(true));
    if (value === false) return plain(text.UI.decision.allOutNo, 'attention');
    return value === undefined ? plain(text.DASH) : plain(text.unknownCode(value), 'unknown');
  }
  if (metric === 'last_out_s') {
    if (allOut === true && typeof value === 'number') return plain(text.duration(value));
    return allOut === false && !interrupted ? plain(text.UI.decision.noLastOut, 'attention') : plain(text.DASH);
  }
  if (typeof value !== 'number') return plain(text.DASH);
  if (metric === 'in_danger') return plain(text.num(value), value > 0 ? 'danger' : null);
  if (metric === 'no_route') return plain(text.num(value), value > 0 ? 'blocked' : null);
  if (metric === 'out') return plain(text.num(value));
  return plain(text.quantity(value, twin.units[field]));
}

/**
 * @typedef {Object} Column one series of a metrics table
 * @property {string} key written to data-column of the heading
 * @property {string} head
 * @property {string[]} [sub] further lines of the heading
 * @property {{values: Object, units: Object, name: string}} twin
 * @property {string} prefix "forecast_" or "actual_"
 * @property {boolean} published false: the twin has no metric with the prefix, the cells are dashes
 * @property {{checked: boolean, disabled: boolean}} [pick] the column can be chosen with a radio button
 * @property {string} [state] written to data-state of the heading
 */

/**
 * A table of the result metrics: one row per metric, one column per series.
 * @param {Object} text
 * @param {Object<string, *>} attrs attributes of the table
 * @param {{label: string, words: (column: Column) => string}|null} [lead] a row above the metrics
 * @param {(key: string) => void} [onPick] a column was chosen
 * @returns {{table: HTMLTableElement, update: (columns: Column[], metrics: (boolean|undefined)) => void}}
 */
function metricsTable(text, attrs, lead = null, onPick = null) {
  const head = h('tr');
  const leadRow = lead ? h('tr', {'data-row': 'lead'}) : null;
  const rows = METRIC_ORDER.map((metric) => h('tr', {'data-metric-row': metric}));
  const table = h('table', {class: 'table table--metrics', ...attrs}, h('thead', null, head), h('tbody', null, leadRow, rows));
  const key = (column) => (column ? column.key : '');
  const chosenClass = (column) => (column.pick && column.pick.checked ? 'is-chosen' : null);

  function createHead(column) {
    if (!column) return h('th', {scope: 'col', text: text.UI.decision.metric});
    const pick = h('label', {class: 'th-pick'}, h('span'));
    if (onPick) {
      const radio = h('input', {type: 'radio', name: 'decision-option', value: column.key});
      radio.addEventListener('change', () => onPick(column.key));
      pick.prepend(radio);
    }
    return h('th', {scope: 'col'}, pick, h('span', {class: 'th-sub'}), h('span', {class: 'th-sub'}));
  }

  function updateHead(th, column) {
    if (!column) return;
    const radio = th.querySelector('input');
    const sub = column.sub || [];
    const checked = chosenClass(column) !== null;
    setText(th.firstChild.lastChild, column.head);
    setText(th.children[1], sub[0] || '');
    setText(th.children[2], sub[1] || '');
    if (radio) {
      radio.hidden = !column.pick;
      radio.disabled = !column.pick || column.pick.disabled;
      if (radio.checked !== checked) radio.checked = checked;
    }
    setAttrs(th, {'data-column': column.key, 'data-state': column.state, class: checked ? 'is-chosen' : null});
  }

  /** @param {Column[]} columns @param {boolean} [metrics] false: the metric rows are not shown at all */
  function update(columns, metrics = true) {
    const all = [null, ...columns];
    reconcile(head, all, key, createHead, updateHead);
    if (lead) {
      reconcile(leadRow, all, key, (column) => (column ? h('td') : h('th', {scope: 'row', text: lead.label})),
        (td, column) => column && setAttrs(td, {text: lead.words(column), class: chosenClass(column)}));
    }
    METRIC_ORDER.forEach((metric, index) => {
      rows[index].hidden = !metrics;
      reconcile(rows[index], metrics ? all : [], key,
        (column) => (column ? h('td', null, h('span'))
          : h('th', {scope: 'row'}, text.metricLabel(metric), metric === 'in_danger' ? ` ${text.UI.decision.atEnd}` : null)),
        (td, column) => {
          if (!column) return;
          const cell = column.published ? metricCell(text, column.twin, column.prefix, metric) : {text: text.DASH, badge: null};
          setText(td.firstChild, cell.text);
          setAttrs(td.firstChild, {class: cell.badge ? `badge badge--${cell.badge}` : null});
          setAttrs(td, {'data-metric': column.prefix + metric, 'data-option': column.twin.name, class: chosenClass(column)});
        });
    });
  }
  return {table, update};
}

/**
 * @param {HTMLElement} root the element of index.html this view owns
 * @param {Object} ctx store, text, roots and the action functions
 */
export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;
  const D = UI.decision;

  const optionName = (option) => `${option.label} — ${text.codeLabel('optionKind', option.attrs.option_kind)}`;
  /** The zones of an option by their codes; «все участки» when the published list names every zone twin. */
  function scopeOf(option) {
    const {model} = store.getState();
    const scope = Array.isArray(option.values.scope) ? option.values.scope : [];
    const zones = thingsOfKind(model, 'zone');
    if (scope.length === 0) return text.DASH;
    if (zones.length > 1 && scope.length === zones.length && zones.every((zone) => scope.includes(zone.name))) return D.allZones;
    return scope.map((zone) => labelOf(model, zone)).join(', ');
  }

  /** How complete a forecast is, as the mark next to its numbers; no words for a full one. Never silent about an absent value. */
  function qualityMark(quality) {
    if (quality === 'full') return {words: '', badge: null};
    if (quality === undefined) return {words: D.qualityNotPublished, badge: 'unknown'};
    return {words: text.label('forecastQuality', quality), badge: quality === 'partial' ? 'attention' : 'unknown'};
  }

  // ---- header ------------------------------------------------------------

  const stateText = h('span', {class: 'decision__state'});
  const causes = h('ul', {class: 'decision__causes'});
  const where = h('p', {class: 'note'});
  const pauseGlyph = h('span');
  setGlyph(pauseGlyph, 'pause');
  const pause = h('p', {class: 'decision__pause', 'data-testid': 'decision-pause', hidden: true},
    pauseGlyph, ' ', h('strong', {text: capitalize(`${text.VOCAB.runState.paused} ${text.VOCAB.pauseReason.decision}`)}));
  const noPath = h('p', {class: 'decision__alert', 'data-testid': 'decision-no-path', hidden: true});

  // ---- facts of executed options -----------------------------------------

  const facts = h('div', {class: 'decision__facts'});
  const factTables = new WeakMap();

  function createFact() {
    const table = metricsTable(text, {});
    const node = h('section', {class: 'decision__fact', 'data-testid': 'decision-fact'},
      h('h3', {class: 'group__sub'}), h('p', {class: 'decision__alert', hidden: true}), table.table);
    factTables.set(node, table);
    return node;
  }

  function updateFact(node, option) {
    const [title, incomplete] = node.children;
    node.setAttribute('data-option', option.name);
    setText(title, D.factOf(optionName(option)));
    const left = option.values.actual_no_route;
    incomplete.hidden = !(typeof left === 'number' && left > 0);
    setText(incomplete, incomplete.hidden ? '' : D.incomplete(left));
    const forecast = hasMetrics(option.values, 'forecast_');
    const quality = qualityMark(option.values.forecast_quality);
    factTables.get(node).update([
      {key: 'forecast', head: D.forecast, sub: forecast ? [quality.words] : [D.notPublished], twin: option, prefix: 'forecast_', published: forecast},
      {key: 'actual', head: D.actual, twin: option, prefix: 'actual_', published: true},
    ]);
  }

  // ---- the options: choice and forecast in one table ---------------------

  let chosen = null;
  let decisionSeen = null;
  const captions = h('ul', {class: 'decision__captions', 'data-testid': 'decision-caption'});
  const optionsTable = metricsTable(text, {'data-testid': 'decision-options'},
    {label: D.zones, words: (column) => scopeOf(column.twin)},
    (name) => {
      chosen = name;
      render();
    });
  // Said above the numbers: without one key for all options the columns are not a comparison.
  const keysDiffer = h('p', {class: 'decision__alert', 'data-testid': 'decision-keys-differ', hidden: true});
  const noForecast = h('p', {class: 'decision__alert', 'data-testid': 'decision-no-forecast', text: D.notPublished, hidden: true});
  const nobodyLeft = h('p', {class: 'decision__alert', 'data-testid': 'decision-nobody-left', text: D.nobodyLeft, hidden: true});
  const forecast = h('section', {class: 'decision__forecast', 'data-testid': 'decision-forecast'},
    captions, keysDiffer, optionsTable.table, noForecast, nobodyLeft);

  const block = blockNote();
  const picked = h('p', {class: 'decision__picked', hidden: true});
  const why = h('p', {class: 'note note--why', 'data-testid': 'decision-command', hidden: true});
  const execute = commandButton({
    class: 'btn btn--dispatch btn--block', 'data-testid': 'btn-execute', 'data-command-type': 'action.execute_option',
    text: `${D.execute}…`,
  }, async () => {
    const {model} = store.getState();
    const option = model ? model.byName[chosen] : null;
    if (!option) return;
    // The command carries the decision the user saw: if the conditions change under the open dialog, the model refuses it.
    const decisionId = option.values.decision_id;
    const message = D.confirmText(optionName(option), scopeOf(option));
    if (await ctx.confirm({title: D.confirmTitle, message, confirmLabel: D.execute})) {
      ctx.sendCommand('action.execute_option', option.name, {decisionId});
    }
  });
  const runBox = h('div', {class: 'decision__run'}, block, picked, execute, why);
  const ids = h('p', {class: 'note mono', 'data-testid': 'decision-ids'});

  const panel = h('div', {class: 'decision'},
    h('h2', {class: 'panel__title'}, D.title, ' · ', stateText),
    causes, where, pause, noPath, facts, forecast, runBox, ids,
    h('p', {class: 'note', text: `${D.sameGroup}. ${capitalize(D.downtimeNote)}. ${D.stopKeepsPause}`}));

  /** The caption of a group of options whose forecast has the same horizon, tick and quality. */
  function updateCaption(node, [, options], several) {
    const {forecast_horizon_s: horizon, forecast_tick: tick, forecast_quality: quality} = options[0].values;
    let words = typeof horizon === 'number' ? D.forecastFor(horizon) : capitalize(D.forecast);
    if (typeof tick === 'number') words += `, ${D.forecastTick(tick)}`;
    if (several) words += ` (${options.map((option) => option.label).join(', ')})`;
    setText(node.firstChild, words);
    const mark = node.lastChild;
    const shown = qualityMark(quality);
    mark.hidden = shown.words === '';
    setText(mark, shown.words);
    setAttrs(mark, {class: shown.badge ? `badge badge--${shown.badge}` : null});
    node.setAttribute('data-quality', quality === undefined ? '' : quality);
  }

  function render() {
    const state = store.getState();
    const {model, snapshot} = state;
    const incident = model ? incidentOf(model) : null;
    const incidentState = incident && incident.hasState ? incident.values.state : undefined;
    if (typeof incidentState !== 'string' || incidentState === 'none') {
      // No child nodes: the stylesheet hides the empty panel. Where the empty panel still takes room (the tab
      // of the compact layout) it shows this note: «no incident» only when the model published exactly that.
      if (root.firstChild) root.replaceChildren();
      setAttrs(root, {'data-empty-note': incidentState === 'none' ? D.noIncident : D.noData});
      chosen = null;
      return;
    }
    const name = (local) => labelOf(model, local);
    const options = thingsOfKind(model, 'option');
    setAttrs(panel, {'data-incident-state': incidentState});
    setText(stateText, text.label('incidentState', incidentState));

    // What opened the incident: every cause when the model lists them, else the trigger.
    const {values} = incident;
    const listed = causesOf(values);
    const shown = listed.length > 0 ? listed : [{trigger: values.trigger, tick: values.opened_at_tick}];
    reconcile(causes, shown, (cause, index) => index, () => h('li'), (node, cause) => {
      const parts = [text.label('incidentTrigger', cause.trigger)];
      if (typeof cause.subject === 'string') parts[0] += `: ${name(cause.subject)}`;
      if (typeof cause.tick === 'number') parts.push(D.tick(cause.tick));
      setText(node, parts.join(', '));
    });
    const place = [];
    if (typeof values.zone === 'string') place.push(`${text.fieldLabel('zone')}: ${name(values.zone)}`);
    if (typeof values.opened_at_tick === 'number') place.push(`${text.fieldLabel('opened_at_tick')} ${values.opened_at_tick}`);
    setText(where, place.join(' · '));
    pause.hidden = !(snapshot && snapshot.runState === 'paused' && snapshot.pauseReason === 'decision');

    const stranded = thingsOfKind(model, 'worker').filter((worker) => worker.values.egress_status === 'none');
    noPath.hidden = stranded.length === 0;
    setText(noPath, noPath.hidden ? '' : D.noPath(stranded.map((worker) => worker.label).join(', ')));

    reconcile(facts, options.filter((option) => hasMetrics(option.values, 'actual_')), (option) => option.name, createFact, updateFact);

    // Identifiers of the decision; a new decision of the model clears the choice made on the old numbers.
    const distinct = (field) => [...new Set(options.map((option) => option.values[field]).filter((id) => typeof id === 'string'))];
    const decisionIds = distinct('decision_id');
    const keys = distinct('comparison_key');
    if (decisionIds.join() !== decisionSeen) {
      decisionSeen = decisionIds.join();
      chosen = null;
    }
    const offered = options.filter((option) => option.values.state === 'offered');
    const chosenOption = offered.find((option) => option.name === chosen) || null;
    if (!chosenOption) chosen = null;
    // One key for all: every listed option publishes the same text. One option without a key is enough to break it.
    const shared = options.length > 0 && keys.length === 1 && options.every((option) => option.values.comparison_key === keys[0]);
    const lines = [`${text.fieldLabel('decision_id')}: ${decisionIds.join(', ') || text.DASH}`];
    if (shared) lines.push(`${text.fieldLabel('comparison_key')}: ${keys[0]} — ${D.sharedKey}`);
    setText(ids, lines.join(' · '));
    keysDiffer.hidden = shared || options.length === 0;
    setText(keysDiffer, keysDiffer.hidden ? '' : D.keysDiffer(options.map((option) => {
      const key = option.values.comparison_key;
      return `${option.label}: ${typeof key === 'string' && key !== '' ? key : D.keyNotPublished}`;
    }).join('; ')));
    setAttrs(panel, {
      'data-decision-id': decisionIds.length === 1 ? decisionIds[0] : null,
      'data-comparison': shared ? 'shared' : (options.length > 0 ? 'different' : null),
    });

    const published = options.filter((option) => hasMetrics(option.values, 'forecast_'));
    const groups = new Map();
    for (const option of published) {
      const key = [option.values.forecast_horizon_s, option.values.forecast_tick, option.values.forecast_quality].join('|');
      groups.set(key, [...(groups.get(key) || []), option]);
    }
    reconcile(captions, [...groups], ([key]) => key, () => h('li', null, h('span'), ' ', h('span')),
      (node, group) => updateCaption(node, group, groups.size > 1));
    noForecast.hidden = published.length > 0;
    optionsTable.update(options.map((option) => {
      const has = published.includes(option);
      return {
        key: option.name, head: option.label, twin: option, prefix: 'forecast_', published: has, state: option.values.state,
        sub: [text.codeLabel('optionKind', option.attrs.option_kind),
          text.label('optionState', option.values.state) + (has || published.length === 0 ? '' : `; ${D.notPublished.toLowerCase()}`)],
        // An option that is not offered stays in the table and cannot be chosen.
        pick: offered.length > 0 ? {checked: option === chosenOption, disabled: !offered.includes(option)} : undefined,
      };
    }), published.length > 0);
    nobodyLeft.hidden = !(published.length > 0 && published.every((option) => option.values.forecast_no_route > 0));

    runBox.hidden = offered.length === 0;
    const blocked = showBlock(block, text, state);
    // Next to the button: what is missing, or what became of the command for the chosen option (its buttons are in the left panel).
    const own = standing(text, state, 'action.execute_option', chosen);
    let reason = '';
    if (!chosenOption) reason = D.choose;
    else if (typeof chosenOption.values.decision_id !== 'string') reason = `${text.fieldLabel('decision_id')}: ${UI.card.notPublished}`;
    picked.hidden = !chosenOption;
    setText(picked, chosenOption ? `${capitalize(D.chosen)}: ${optionName(chosenOption)}` : '');
    setAttrs(execute, {'data-command-target': chosen});
    guard(execute, blocked || reason !== '' || own.bars, why, reason || own.words);

    if (!root.firstChild) root.append(panel);
  }

  store.watch((state) => [state.model, state.pending, state.commandsBlocked, state.blockReason], render);
}
