// What the right panel (view/decide.js, view/progress.js) and the archive of
// runs (view/runs.js) know about options and their results: the cells of the
// result metrics, the people bar of the common group, the table of metrics,
// the name of an option as a verb, the headline of a forecast or a fact by
// fixed rules, and the launch of an option. Forecast and fact never share a
// value: the forecast is outlined and hatched, the fact solid, each with its
// caption. A time until everyone is out is written only when the model says
// that everyone is out (CONTRACT.md, section 6). Nothing here ranks options.
//
// The rows of the table read as an answer (clarity pass, A3): people in danger
// at the end, is everyone out and when, how many out, without a route,
// exposures and downtime in minutes, and the people bar last as the summary.

import {h, reconcile, s, setAttrs, setText} from '../dom.js';
import {QUESTION} from '../icons.js';
import {labelOf, thingByName, thingsOfKind} from '../model.js';

/** The result metrics in reading order of the archive of runs: is everyone out, then people, then exposure, then cost. */
export const METRIC_ORDER = ['all_out', 'last_out_s', 'out', 'in_danger', 'danger_exposure_person_s',
  'unknown_exposure_person_s', 'no_route', 'downtime_s'];

/**
 * The rows of the table of options and of the fact of an executed option, in the order of the question:
 * who is in danger at the end, is everyone out (with the time, one row), how many are out, who has no route,
 * then the exposures and the downtime. `last_out_s` has no row of its own: it is the time of «все вышли».
 */
export const DECISION_ROWS = ['in_danger', 'all_out', 'out', 'no_route', 'danger_exposure_person_s',
  'unknown_exposure_person_s', 'downtime_s'];
const PER_MINUTE = new Set(['danger_exposure_person_s', 'unknown_exposure_person_s', 'downtime_s']);


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

/**
 * One row of the table of options. «все вышли» is «да, за 9 мин 40 с» only next to a published
 * `all_out = true` with its time, «да» without the time, «нет» when the model says not everyone is out.
 * Exposures and downtime are written in minutes; `title` keeps the published value and its unit.
 * @returns {{text: string, badge: (string|null), title: string}}
 */
export function decisionCell(text, twin, prefix, metric) {
  const D = text.UI.decision;
  const field = prefix + metric;
  const value = twin.values[field];
  if (metric === 'all_out') {
    const last = twin.values[`${prefix}last_out_s`];
    if (value === true) {
      return typeof last === 'number' && Number.isFinite(last) && last >= 0
        ? {text: D.allOutYesIn(last), badge: null, title: `${text.fieldLabel(`${prefix}last_out_s`)}: ${text.quantity(last, 's')}`}
        : {text: D.allOutYes, badge: null, title: ''};
    }
    if (value === false) return {text: D.allOutNot, badge: 'attention', title: D.allOutNo};
    return value === undefined ? {text: text.DASH, badge: null, title: ''} : {text: text.unknownCode(value), badge: 'unknown', title: ''};
  }
  if (PER_MINUTE.has(metric)) {
    const shown = text.perMinute(value, twin.units[field]);
    return {text: shown.text, badge: null, title: shown.title};
  }
  return {...metricCell(text, twin, prefix, metric), title: ''};
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
 * The people of a series in words: «вышли 12 из 14 · 10 ещё под землёй», or without a published size of
 * the common group «вышли 0 · для 2 чел. выход не рассчитан».
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
 * @property {boolean} [chosen] the column of the option the dispatcher chose
 * @property {string} [state] written to data-state of the heading
 * @property {People} [people] the counts of its people bar
 */

/**
 * A table of the result metrics: one row per metric of DECISION_ROWS, one column per series,
 * the row of people bars under the metrics as their visual summary.
 * @param {Object} text
 * @param {Object<string, *>} attrs attributes of the table
 * @param {{lead?: {label: string, words: (column: Column) => string}, people: string, prefix: string, barWidth: number}} options
 * @returns {{table: HTMLTableElement, update: (columns: Column[], people: (string|undefined)) => void}}
 */
export function metricsTable(text, attrs, options) {
  const {lead = null} = options;
  const head = h('tr');
  const leadRow = lead ? h('tr', {'data-row': 'lead'}) : null;
  const peopleRow = h('tr', {'data-row': 'people'});
  const rows = DECISION_ROWS.map((metric) => h('tr', {'data-metric-row': metric}));
  const table = h('table', {class: 'metrics', ...attrs}, h('thead', null, head), h('tbody', null, leadRow, rows, peopleRow));
  let peopleLabel = options.people;
  const bars = new WeakMap();
  const key = (column) => (column ? column.key : '');
  const chosenClass = (column) => (column.chosen ? 'is-chosen' : null);
  const series = (column) => (column.prefix === 'actual_' ? 'fact' : 'forecast');

  function createHead(column) {
    if (!column) return h('th', {scope: 'col', class: 'metrics__corner', text: text.UI.decision.metric});
    return h('th', {scope: 'col'}, h('div', {class: 'th-box'}, h('span', {class: 'th-name'}), h('span', {class: 'th-sub'})));
  }

  function updateHead(th, column) {
    if (!column) return;
    const [name, sub] = th.firstChild.children;
    setText(name, column.head);
    setText(sub, (column.sub || []).filter(Boolean).join(' · '));
    setAttrs(th, {'data-column': column.key, 'data-state': column.state, 'data-series': series(column),
      class: ['metrics__head', chosenClass(column)]});
  }

  function createPeople(column) {
    if (!column) return h('th', {scope: 'row', text: options.people});
    const bar = peopleBar(options.prefix, options.barWidth);
    const td = h('td', {class: 'metrics__people'}, bar.svg, h('span', {class: 'pb-words'}));
    bars.set(td, bar);
    return td;
  }

  function updatePeople(td, column) {
    if (!column) {
      setText(td, peopleLabel);
      return;
    }
    const shown = column.published && column.people;
    const words = shown ? peopleWords(text, column.people) : text.DASH;
    if (shown) bars.get(td).update(column.people, series(column), words);
    td.firstChild.style.display = shown ? '' : 'none';
    setText(td.lastChild, words);
    setAttrs(td.lastChild, {title: words});
    setAttrs(td, {'data-option': column.twin.name, 'data-series': series(column), class: ['metrics__people', chosenClass(column)]});
  }

  /**
   * @param {Column[]} columns
   * @param {string} [people] the heading of the row of people bars
   */
  function update(columns, people = options.people) {
    const all = [null, ...columns];
    peopleLabel = people;
    reconcile(head, all, key, createHead, updateHead);
    if (lead) {
      reconcile(leadRow, all, key, (column) => (column ? h('td') : h('th', {scope: 'row', text: lead.label})),
        (td, column) => column && setAttrs(td, {text: lead.words(column), class: chosenClass(column)}));
    }
    reconcile(peopleRow, all, key, createPeople, updatePeople);
    DECISION_ROWS.forEach((metric, index) => {
      reconcile(rows[index], all, key,
        (column) => (column ? h('td', null, h('span'))
          : h('th', {scope: 'row'}, text.metricLabel(metric), metric === 'in_danger' ? ` ${text.UI.decision.atEnd}` : null)),
        (td, column) => {
          if (!column) return;
          const cell = column.published ? decisionCell(text, column.twin, column.prefix, metric) : {text: text.DASH, badge: null, title: ''};
          setText(td.firstChild, cell.text);
          setAttrs(td.firstChild, {class: valueClass(series(column), cell.text === text.DASH ? 'none' : cell.badge), title: cell.title || null});
          setAttrs(td, {'data-metric': column.prefix + metric, 'data-option': column.twin.name, class: chosenClass(column)});
        });
    });
  }
  return {table, update};
}

// ---- one option in words ------------------------------------------------------------

const lowerFirst = (words) => (words ? words[0].toLowerCase() + words.slice(1) : words);

/**
 * What an option does, as the title of its card and of the launch button: «Наблюдать»,
 * «Остановить участок Г и вывести людей», «Вывести всех». The zone comes from the published
 * `scope`; an option kind the interface does not know keeps its code (with the option's label).
 * @param {Object} text
 * @param {import('../store.js').Model} model
 * @param {import('../store.js').Thing} option
 */
export function optionVerb(text, model, option) {
  const kind = option.attrs.option_kind;
  const verb = typeof kind === 'string' && Object.prototype.hasOwnProperty.call(text.PANEL.verb, kind) ? text.PANEL.verb[kind] : null;
  if (typeof verb === 'string') return verb;
  const scope = Array.isArray(option.values.scope) ? option.values.scope : [];
  if (typeof verb === 'function') {
    const place = scope.length === 1 ? thingByName(model, scope[0]) : null;
    return verb(place ? lowerFirst(place.label) : '');
  }
  return `${option.label}: ${text.codeLabel('optionKind', kind)}`;
}

/** The zones of an option by their codes; «все участки» when the published list names every zone twin. */
export function scopeText(text, model, option) {
  const scope = Array.isArray(option.values.scope) ? option.values.scope : [];
  const zones = thingsOfKind(model, 'zone');
  if (scope.length === 0) return text.PANEL.noZones;
  if (zones.length > 1 && scope.length === zones.length && zones.every((zone) => scope.includes(zone.name))) return text.PANEL.allZones;
  return scope.map((zone) => labelOf(model, zone)).join(', ');
}

const isCount = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0;

/**
 * The one sentence of a forecast ("forecast_") or of a fact ("actual_"), by fixed rules over the published
 * fields, in this order:
 *   all_out = true      → «Все выйдут за 9 мин 40 с» (the time only with a published last_out_s)
 *   in_danger > 0       → «3 человека останутся в опасной зоне»
 *   no_route > 0        → «Для 2 человек выход не рассчитан · вышли 12» (out when published)
 *   in_danger = 0       → «В опасной зоне никого · вышли 4»
 * Nothing published with the prefix → null (the caller says «Прогноз не опубликован»). When the fields a
 * rule needs are missing, that rule says nothing; a dash stands where no rule applies. Nothing is guessed.
 * @param {Object} text
 * @param {Object<string, *>} values
 * @param {'forecast_'|'actual_'} prefix
 * @returns {{text: string, rule: ('all_out'|'in_danger'|'no_route'|'clear'|'none')}|null}
 */
export function headline(text, values, prefix) {
  if (!hasMetrics(values, prefix)) return null;
  const words = prefix === 'actual_' ? text.PANEL.fact : text.PANEL.forecast;
  const get = (metric) => values[prefix + metric];
  if (get('all_out') === true) {
    const last = get('last_out_s');
    return {text: isCount(last) ? words.allOutIn(last) : words.allOut, rule: 'all_out'};
  }
  if (isCount(get('in_danger')) && get('in_danger') > 0) return {text: words.inDanger(Math.round(get('in_danger'))), rule: 'in_danger'};
  const out = isCount(get('out')) ? get('out') : undefined;
  if (isCount(get('no_route')) && get('no_route') > 0) return {text: words.noRoute(Math.round(get('no_route')), out), rule: 'no_route'};
  if (get('in_danger') === 0) return {text: words.clear(out), rule: 'clear'};
  return {text: text.DASH, rule: 'none'};
}

/** At most two secondary facts of a forecast or fact: exposure in a danger zone and downtime, in minutes. */
export function secondaryFacts(text, twin, prefix) {
  const facts = [];
  const field = (metric) => `${prefix}${metric}`;
  const exposure = text.perMinute(twin.values[field('danger_exposure_person_s')], twin.units[field('danger_exposure_person_s')] || 'person*s');
  if (exposure.text !== text.DASH) facts.push({key: 'exposure', text: text.PANEL.exposure(exposure.text), title: exposure.title});
  const downtime = text.perMinute(twin.values[field('downtime_s')], twin.units[field('downtime_s')] || 'zone*s');
  if (downtime.text !== text.DASH) facts.push({key: 'downtime', text: text.PANEL.downtime(downtime.text), title: downtime.title});
  return facts;
}

/** How complete a forecast is: no words for a full one; never silent about an absent value. */
export function qualityMark(text, quality) {
  if (quality === 'full') return {words: '', badge: null};
  if (quality === undefined) return {words: text.PANEL.qualityNotPublished, badge: 'unknown'};
  if (quality === 'partial') return {words: text.PANEL.partial, badge: 'attention'};
  return {words: text.label('forecastQuality', quality), badge: 'unknown'};
}

/**
 * The options of the incident as the model published them, and what follows from them without
 * computing anything: the identifiers of the decision, one comparison key or not, the size of the
 * common group where a series says that everyone is out (commonGroup).
 * @param {import('../store.js').Model} model
 */
export function decisionOf(model) {
  const options = thingsOfKind(model, 'option');
  const distinct = (field) => [...new Set(options.map((option) => option.values[field]).filter((id) => typeof id === 'string'))];
  const decisionIds = distinct('decision_id');
  const keys = distinct('comparison_key');
  // One key for all: every listed option publishes the same text. One option without a key is enough to break it.
  const sharedKey = options.length > 0 && keys.length === 1 && options.every((option) => option.values.comparison_key === keys[0]);
  const group = decisionIds.length === 1 && options.every((option) => option.values.decision_id === decisionIds[0])
    ? commonGroup(options, ['forecast_', 'actual_']) : null;
  return {
    options, decisionIds, sharedKey, total: group ? group.total : null,
    offered: options.filter((option) => option.values.state === 'offered'),
    published: options.filter((option) => hasMetrics(option.values, 'forecast_')),
    executing: options.find((option) => option.values.state === 'executing') || null,
    executed: options.filter((option) => hasMetrics(option.values, 'actual_')),
  };
}

/**
 * Launch an option: the confirmation dialog, then `action.execute_option` with the option's own
 * `decision_id` — the decision the user saw; if the conditions change under the open dialog, the model
 * refuses it as stale.
 * @param {Object} ctx
 * @param {import('../store.js').Thing} option
 * @returns {Promise<boolean>} true when the command was handed to the command engine
 */
export async function launchOption(ctx, option) {
  const {text, store} = ctx;
  const P = text.PANEL;
  const {model} = store.getState();
  const verb = optionVerb(text, model, option);
  const decisionId = option.values.decision_id;
  const message = P.confirmText(verb, scopeText(text, model, option));
  if (!await ctx.confirm({title: P.confirmTitle, message, confirmLabel: P.confirmLabel})) return false;
  ctx.sendCommand('action.execute_option', option.name, {decisionId});
  return true;
}
