// The content of the decision dock under the stage (the dock itself, its bar
// and its folding are view/dock.js's): what opened the incident, the options
// of the model side by side with identical metric rows, a people bar per
// option, the choice and the launch, and the facts of the executed option.
// The one-line summary in the bar of the dock is written here too. Forecast
// and fact never share a value: the forecast is outlined and hatched, the fact
// solid, each with its caption. A time until everyone is out is written only
// when the model says that everyone is out (CONTRACT.md, section 6). Nothing
// here ranks the options.

import {h, reconcile, s, setAttrs, setGlyph, setText} from '../dom.js';
import {QUESTION} from '../icons.js';
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
 * @returns {{text: string, badge: (string|null)}} badge: attention | danger | blocked | unknown
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

/** The class of a value: forecast (outlined) or fact (solid), and its mark. */
export function valueClass(series, badge) {
  return ['val', `val--${series}`, badge && `val--${badge}`];
}

// ---- people of the common group ------------------------------------------------------

/**
 * @typedef {Object} People counts of one series, as published
 * @property {number|undefined} out
 * @property {number|undefined} inDanger
 * @property {number|undefined} noRoute
 * @property {number|null} total the common group, when it is known (see commonGroup); null: not published
 */

const count = (value) => (typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.round(value) : undefined);

/** The published people counts of a twin for a prefix ("forecast_", "actual_" or none). */
export function peopleOf(values, prefix, total) {
  return {out: count(values[`${prefix}out`]), inDanger: count(values[`${prefix}in_danger`]),
    noRoute: count(values[`${prefix}no_route`]), total};
}

/**
 * The size of the common group, from published values only. The model does
 * not publish it; CONTRACT.md 6 defines `all_out = true` as "the whole common
 * group reached an exit" and `out` as the number of its people who did. So
 * where a series says `all_out = true`, its `out` is the group, and the group
 * is one for every series of one decision (or one comparison key). Two series
 * that disagree give no size: nothing is guessed.
 * @param {Array<{values: Object, label: string}>} twins options of one decision, or runs of one key
 * @param {string[]} prefixes
 * @returns {{total: number, from: string}|null}
 */
export function commonGroup(twins, prefixes) {
  let found = null;
  for (const twin of twins) {
    for (const prefix of prefixes) {
      const out = count(twin.values[`${prefix}out`]);
      if (twin.values[`${prefix}all_out`] !== true || out === undefined) continue;
      if (found && found.total !== out) return null;
      if (!found) found = {total: out, from: twin.label};
    }
  }
  return found;
}

/**
 * A bar of the common group: one cell per person. Out, in a danger zone at
 * the end, without a computed route, still under ground; when the size of the
 * group is not published, an open «?» end instead of the rest. A forecast is
 * drawn outlined and hatched, a fact solid.
 * @param {string} prefix of the pattern ids, unique in the document
 * @param {number} width of the bar in px
 */
export function peopleBar(prefix, width) {
  const HEIGHT = 14;
  // At most `width` wide; a narrower column scales the whole bar, so every cell keeps its shape.
  const svg = s('svg', {class: 'pb', viewBox: `0 0 ${width} ${HEIGHT}`, preserveAspectRatio: 'xMinYMid meet', role: 'img',
    focusable: 'false', 'data-testid': 'people-bar', style: `max-width: ${width}px`});
  /**
   * @param {People} people
   * @param {'forecast'|'fact'} series
   * @param {string} label the words of the bar, for assistive technology
   */
  function update(people, series, label) {
    const {out = 0, inDanger = 0, noRoute = 0, total} = people;
    // The rest under ground is drawn only when the group and all three counts are published.
    const known = typeof total === 'number' && [people.out, people.inDanger, people.noRoute].every((n) => n !== undefined);
    const left = known ? total - out - inDanger - noRoute : 0;
    const cells = [['out', out], ['in_danger', inDanger], ['no_route', noRoute], ['left', Math.max(left, 0)]]
      .flatMap(([kind, n]) => Array.from({length: n}, () => kind));
    const slots = cells.length + (known ? 0 : 3);
    const step = Math.max(Math.min(width / Math.max(slots, 1), 14), 2);
    const gap = step >= 7 ? 2 : (step >= 4 ? 1 : 0);
    const items = cells.map((kind, index) => ({kind, x: index * step}));
    if (!known) items.push({kind: 'unknown', x: cells.length * step});
    reconcile(svg, items, (item, index) => `${index}-${item.kind}`, (item) => (item.kind === 'no_route'
      ? s('g', {class: 'pb__cell pb__no_route'}, s('rect'), s('path'))
      : (item.kind === 'unknown' ? s('g', {class: 'pb__cell pb__unknown'}, s('rect'), s('path', {d: QUESTION}))
        : s('rect', {class: `pb__cell pb__${item.kind}`}))),
    (node, item) => {
      const w = item.kind === 'unknown' ? Math.min(width - item.x, Math.max(step * 3, 18)) - 1 : step - gap;
      const box = {x: item.x + 0.5, y: 0.5, width: Math.max(w, 1), height: HEIGHT - 1};
      const rect = node.tagName === 'rect' ? node : node.firstChild;
      setAttrs(rect, box);
      if (item.kind === 'out' || item.kind === 'in_danger') rect.style.fill = series === 'forecast' ? `url(#${prefix}-${item.kind})` : '';
      if (item.kind === 'no_route') {
        setAttrs(node.lastChild, {d: `M${box.x} ${box.y}l${box.width} ${box.height}M${box.x} ${box.y + box.height}l${box.width} ${-box.height}`});
      }
      if (item.kind === 'unknown') setAttrs(node.lastChild, {transform: `translate(${box.x + box.width / 2} ${HEIGHT / 2}) scale(.85)`});
    });
    setAttrs(svg, {
      'data-series': series, 'aria-label': label,
      'data-out': people.out, 'data-in-danger': people.inDanger, 'data-no-route': people.noRoute,
      'data-total': typeof total === 'number' ? total : null, 'data-overlap': left < 0 ? 'true' : null,
    });
  }
  return {svg, update};
}

/** Hatch patterns of the forecast cells of a people bar. */
export function peoplePatterns(prefix) {
  return [
    s('pattern', {id: `${prefix}-out`, class: 'pb-hatch pb-hatch--out', width: 4, height: 4, patternUnits: 'userSpaceOnUse',
      patternTransform: 'rotate(45)'}, s('rect', {width: 4, height: 4}), s('path', {d: 'M1 0V4'})),
    s('pattern', {id: `${prefix}-in_danger`, class: 'pb-hatch pb-hatch--danger', width: 4, height: 4, patternUnits: 'userSpaceOnUse'},
      s('rect', {width: 4, height: 4}), s('path', {d: 'M-1 -1L5 5M-1 5L5 -1'})),
  ];
}

/**
 * The people of a series in words: «вышли 12 из 14 · 2 без маршрута».
 * @param {Object} text
 * @param {People} people
 */
export function peopleWords(text, people) {
  const D = text.UI.decision;
  const {out, inDanger, noRoute, total} = people;
  if (out === undefined && inDanger === undefined && noRoute === undefined) return text.DASH;
  const complete = [out, inDanger, noRoute].every((n) => n !== undefined);
  const parts = [D.out(out === undefined ? text.DASH : out, typeof total === 'number' ? total : null)];
  if (inDanger > 0) parts.push(D.inDangerCount(inDanger));
  if (noRoute > 0) parts.push(D.noRouteCount(noRoute));
  if (typeof total === 'number' && complete) {
    const left = total - out - inDanger - noRoute;
    if (left > 0) parts.push(D.leftCount(left));
    if (left < 0) parts.push(D.overlap);
  }
  return parts.join(' · ');
}

// ---- the metrics table -------------------------------------------------------------

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
 * @property {People} [people] the counts of its people bar
 */

/**
 * A table of the result metrics: one row per metric, one column per series,
 * a row of people bars above the metrics.
 * @param {Object} text
 * @param {Object<string, *>} attrs attributes of the table
 * @param {{lead?: {label: string, words: (column: Column) => string}, people: string, prefix: string,
 *          barWidth: number, onPick?: (key: string) => void}} options
 * @returns {{table: HTMLTableElement, update: (columns: Column[], metrics: (boolean|undefined)) => void}}
 */
function metricsTable(text, attrs, options) {
  const {lead = null, onPick = null} = options;
  const head = h('tr');
  const leadRow = lead ? h('tr', {'data-row': 'lead'}) : null;
  const peopleRow = h('tr', {'data-row': 'people'});
  const rows = METRIC_ORDER.map((metric) => h('tr', {'data-metric-row': metric}));
  const table = h('table', {class: 'metrics', ...attrs}, h('thead', null, head), h('tbody', null, leadRow, peopleRow, rows));
  const bars = new WeakMap();
  const key = (column) => (column ? column.key : '');
  const chosenClass = (column) => (column.pick && column.pick.checked ? 'is-chosen' : null);
  const series = (column) => (column.prefix === 'actual_' ? 'fact' : 'forecast');

  function createHead(column) {
    if (!column) return h('th', {scope: 'col', class: 'metrics__corner', text: text.UI.decision.metric});
    const pick = h('label', {class: 'th-pick'}, h('span', {class: 'th-name'}));
    if (onPick) {
      const radio = h('input', {type: 'radio', name: 'decision-option', value: column.key});
      radio.addEventListener('change', () => onPick(column.key));
      pick.prepend(radio);
    }
    // The name with its radio button and the state on the first line, the kind of the option on the second.
    return h('th', {scope: 'col'}, h('div', {class: 'th-box'}, pick, h('span', {class: 'th-sub'}), h('span', {class: 'th-sub'})));
  }

  function updateHead(th, column) {
    if (!column) return;
    const radio = th.querySelector('input');
    const sub = column.sub || [];
    const checked = chosenClass(column) !== null;
    const [pick, kind, state] = th.firstChild.children;
    setText(pick.lastChild, column.head);
    setText(kind, sub[0] || '');
    setText(state, sub[1] || '');
    if (radio) {
      radio.hidden = !column.pick;
      radio.disabled = !column.pick || column.pick.disabled;
      if (radio.checked !== checked) radio.checked = checked;
    }
    setAttrs(th, {'data-column': column.key, 'data-state': column.state, 'data-series': series(column),
      class: ['metrics__head', checked && 'is-chosen']});
  }

  function createPeople(column) {
    if (!column) return h('th', {scope: 'row', text: options.people});
    const bar = peopleBar(options.prefix, options.barWidth);
    const td = h('td', {class: 'metrics__people'}, bar.svg, h('span', {class: 'pb-words'}));
    bars.set(td, bar);
    return td;
  }

  function updatePeople(td, column) {
    if (!column) return;
    const shown = column.published && column.people;
    const words = shown ? peopleWords(text, column.people) : text.DASH;
    if (shown) bars.get(td).update(column.people, series(column), words);
    td.firstChild.style.display = shown ? '' : 'none';
    setText(td.lastChild, words);
    setAttrs(td, {'data-option': column.twin.name, 'data-series': series(column), class: ['metrics__people', chosenClass(column)]});
  }

  /** @param {Column[]} columns @param {boolean} [metrics] false: the metric rows are not shown at all */
  function update(columns, metrics = true) {
    const all = [null, ...columns];
    reconcile(head, all, key, createHead, updateHead);
    if (lead) {
      reconcile(leadRow, all, key, (column) => (column ? h('td') : h('th', {scope: 'row', text: lead.label})),
        (td, column) => column && setAttrs(td, {text: lead.words(column), class: chosenClass(column)}));
    }
    peopleRow.hidden = !metrics;
    reconcile(peopleRow, metrics ? all : [], key, createPeople, updatePeople);
    METRIC_ORDER.forEach((metric, index) => {
      rows[index].hidden = !metrics;
      reconcile(rows[index], metrics ? all : [], key,
        (column) => (column ? h('td', null, h('span'))
          : h('th', {scope: 'row'}, text.metricLabel(metric), metric === 'in_danger' ? ` ${text.UI.decision.atEnd}` : null)),
        (td, column) => {
          if (!column) return;
          const cell = column.published ? metricCell(text, column.twin, column.prefix, metric) : {text: text.DASH, badge: null};
          setText(td.firstChild, cell.text);
          setAttrs(td.firstChild, {class: valueClass(series(column), cell.text === text.DASH ? 'none' : cell.badge)});
          setAttrs(td, {'data-metric': column.prefix + metric, 'data-option': column.twin.name, class: chosenClass(column)});
        });
    });
  }
  return {table, update};
}

// ---- the dock --------------------------------------------------------------------------

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

  // ---- the head: what opened the incident -------------------------------------------

  const stateText = h('span', {class: 'decision__state'});
  const causes = h('ul', {class: 'decision__causes'});
  const where = h('span', {class: 'decision__where'});
  const pauseGlyph = h('span', {class: 'decision__glyph'});
  setGlyph(pauseGlyph, 'pause');
  const pause = h('p', {class: 'decision__pause', 'data-testid': 'decision-pause', hidden: true},
    pauseGlyph, h('span', {text: capitalize(`${text.VOCAB.runState.paused} ${text.VOCAB.pauseReason.decision}`)}));
  const captions = h('ul', {class: 'decision__captions', 'data-testid': 'decision-caption'});
  // Why the dock is open (state and causes of the incident) and the pause: the top of the side column, so that
  // the table of options starts at the top of the dock and the stage keeps its height.
  const head = h('div', {class: 'decision__head'}, stateText, causes, where, pause);
  // The line in the bar of the dock: what is asked of the dispatcher, or what became of the decision.
  const summary = h('span', {class: 'decision__summary'});
  if (ctx.roots.decisionSummary) ctx.roots.decisionSummary.append(summary);

  // ---- facts of executed options ----------------------------------------------------

  const facts = h('div', {class: 'decision__facts'});
  const factTables = new WeakMap();

  function createFact() {
    const table = metricsTable(text, {class: 'metrics metrics--fact'}, {people: D.peopleShort, prefix: 'pbd', barWidth: 112});
    const node = h('section', {class: 'decision__fact', 'data-testid': 'decision-fact'},
      h('h3', {class: 'decision__fact-title'}), h('p', {class: 'decision__alert', hidden: true}), table.table);
    factTables.set(node, table);
    return node;
  }

  function updateFact(node, option, total) {
    const [title, incomplete] = node.children;
    node.setAttribute('data-option', option.name);
    setText(title, D.factOf(optionName(option)));
    const left = option.values.actual_no_route;
    incomplete.hidden = !(typeof left === 'number' && left > 0);
    setText(incomplete, incomplete.hidden ? '' : D.incomplete(left));
    const forecast = hasMetrics(option.values, 'forecast_');
    const quality = qualityMark(option.values.forecast_quality);
    factTables.get(node).update([
      {key: 'forecast', head: D.forecast, sub: forecast ? [quality.words] : [D.notPublished], twin: option, prefix: 'forecast_',
        published: forecast, people: peopleOf(option.values, 'forecast_', total)},
      {key: 'actual', head: D.actual, twin: option, prefix: 'actual_', published: true, people: peopleOf(option.values, 'actual_', total)},
    ]);
  }

  // ---- the options: choice and forecast in one table -----------------------------------

  let chosen = null;
  let decisionSeen = null;
  const optionsTable = metricsTable(text, {'data-testid': 'decision-options'}, {
    lead: {label: D.zones, words: (column) => scopeOf(column.twin)},
    people: D.people, prefix: 'pbd', barWidth: 196,
    onPick: (name) => {
      chosen = name;
      render();
    },
  });
  // Said above the numbers: without one key for all options the columns are not a comparison.
  const keysDiffer = h('p', {class: 'decision__alert', 'data-testid': 'decision-keys-differ', hidden: true});
  const noForecast = h('p', {class: 'decision__alert', 'data-testid': 'decision-no-forecast', text: D.notPublished, hidden: true});
  const nobodyLeft = h('p', {class: 'decision__alert', 'data-testid': 'decision-nobody-left', text: D.nobodyLeft, hidden: true});
  const forecast = h('section', {class: 'decision__forecast', 'data-testid': 'decision-forecast'},
    keysDiffer, optionsTable.table, noForecast);
  const noPath = h('p', {class: 'decision__alert', 'data-testid': 'decision-no-path', hidden: true});

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
  const ids = h('p', {class: 'decision__ids mono', 'data-testid': 'decision-ids'});
  const groupNote = h('p', {class: 'decision__note', 'data-testid': 'decision-group'});
  const notes = h('p', {class: 'decision__note', text: `${D.sameGroup}. ${capitalize(D.downtimeNote)}. ${D.stopKeepsPause}`});

  // How the numbers are counted, the size of the group and the identifiers: one line folded under the button.
  const more = h('details', {class: 'decision__more', 'data-testid': 'decision-more'},
    h('summary', {class: 'decision__more-title', text: D.howCounted}), groupNote, notes, ids);

  const panel = h('div', {class: 'decision'},
    s('svg', {class: 'pb-defs', width: 0, height: 0, 'aria-hidden': 'true', focusable: 'false'}, s('defs', null, peoplePatterns('pbd'))),
    // The options and their numbers on the left; on the right why the dock is open, what the model cannot do
    // (next to the numbers it is about), what the numbers are, and the launch.
    h('div', {class: 'decision__main'}, forecast,
      h('div', {class: 'decision__side'}, head, noPath, nobodyLeft, captions, facts, runBox, more)));

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
      // No child nodes: view/dock.js hides the dock and the stage takes its room. The note says why
      // to whoever reads the element: «no incident» only when the model published exactly that.
      if (root.firstChild) root.replaceChildren();
      setAttrs(root, {'data-empty-note': incidentState === 'none' ? D.noIncident : D.noData});
      setText(summary, '');
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

    // The common group of one decision: one size for every option and for its fact (CONTRACT.md 6).
    const group = decisionIds.length === 1 && options.every((option) => option.values.decision_id === decisionIds[0])
      ? commonGroup(options, ['forecast_', 'actual_']) : null;
    const total = group ? group.total : null;
    setText(groupNote, group ? D.groupFrom(group.total, group.from) : D.groupUnknown);
    setAttrs(groupNote, {'data-total': total});

    const executed = options.filter((option) => hasMetrics(option.values, 'actual_'));
    reconcile(facts, executed, (option) => option.name, createFact, (node, option) => updateFact(node, option, total));

    const published = options.filter((option) => hasMetrics(option.values, 'forecast_'));
    const groups = new Map();
    for (const option of published) {
      const key = [option.values.forecast_horizon_s, option.values.forecast_tick, option.values.forecast_quality].join('|');
      groups.set(key, [...(groups.get(key) || []), option]);
    }
    reconcile(captions, [...groups], ([key]) => key, () => h('li', null, h('span'), ' ', h('span')),
      (node, entry) => updateCaption(node, entry, groups.size > 1));
    noForecast.hidden = published.length > 0;
    optionsTable.update(options.map((option) => {
      const has = published.includes(option);
      return {
        key: option.name, head: option.label, twin: option, prefix: 'forecast_', published: has, state: option.values.state,
        sub: [text.codeLabel('optionKind', option.attrs.option_kind),
          text.label('optionState', option.values.state) + (has || published.length === 0 ? '' : `; ${D.notPublished.toLowerCase()}`)],
        // An option that is not offered stays in the table and cannot be chosen.
        pick: offered.length > 0 ? {checked: option === chosenOption, disabled: !offered.includes(option)} : undefined,
        people: peopleOf(option.values, 'forecast_', total),
      };
    }), published.length > 0);
    nobodyLeft.hidden = !(published.length > 0 && published.every((option) => option.values.forecast_no_route > 0));
    // The note on the size of the group explains the bars: without a number of the model there are none.
    groupNote.hidden = published.length === 0 && executed.length === 0;

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

    const running = options.find((option) => option.values.state === 'executing');
    const fact = executed[executed.length - 1];
    let line = D.summaryStates;
    if (offered.length > 0) line = chosenOption ? D.summaryChosen(optionName(chosenOption)) : D.summaryOffered(offered.length);
    else if (running) line = D.summaryExecuting(optionName(running));
    else if (fact) line = D.summaryFact(optionName(fact), peopleWords(text, peopleOf(fact.values, 'actual_', total)));
    setText(summary, line);
    if (!root.firstChild) root.append(panel);
  }

  store.watch((state) => [state.model, state.pending, state.commandsBlocked, state.blockReason], render);
}
