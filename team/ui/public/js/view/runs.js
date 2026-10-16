// The archive of finished runs, in the visual language of the decision dock.
// Runs are grouped by the comparison key the service published; only
// complete runs of one key are called a comparison. The fact and the forecast
// of a run are two labelled rows, never one value: the fact solid, the
// forecast outlined and hatched. A run cut short by a reset, or with an
// ending this interface does not know, is marked and keeps a dash where it
// has no result: it is never shown as a completed withdrawal.

import {h, s, setAttrs, setText} from '../dom.js';
import {localName} from '../model.js';
import {COST_FIELDS, METRIC_ORDER, commonGroup, hasMetrics, metricCell, peopleBar, peopleOf, peoplePatterns, peopleWords, valueClass} from './decision.js';

/** The completion reasons that mean a run came to its end with a result. */
export const COMPLETED_REASONS = ['withdrawal_done', 'horizon_reached'];

/**
 * Archive runs by comparison key, the group of the latest run first.
 *
 * A run takes part in a comparison only when all of this is published: it is
 * `finished`, its `completion_reason` is one of COMPLETED_REASONS, and the
 * service did not mark it incomparable. Of the others, `interrupted` is a run
 * cut short by a reset and `unclassified` a run whose ending is absent or not
 * known to this interface: neither is ever counted as a completed run.
 * @param {import('../store.js').ArchiveRun[]} runs
 * @param {string[]} order run names, oldest first; local names or full thingIds
 * @returns {Array<{key: (string|null), comparable: number,
 *           runs: Array<{run: Object, interrupted: boolean, unclassified: boolean, takesPart: boolean}>}>}
 */
export function groupRuns(runs, order) {
  const names = order.map((name) => (typeof name === 'string' ? localName(name) : name));
  const position = (run) => {
    const at = names.indexOf(run.name);
    return at < 0 ? names.length : at;
  };
  const groups = new Map();
  for (const run of [...runs].sort((a, b) => position(a) - position(b))) {
    const {values} = run;
    const key = typeof values.comparison_key === 'string' ? values.comparison_key : null;
    const group = groups.get(key) || {key, runs: [], comparable: 0, latest: 0};
    const interrupted = values.completion_reason === 'reset';
    // The simulation writes `horizon` where the fixtures of the contract draft write `horizon_reached`.
    const reason = values.completion_reason === 'horizon' ? 'horizon_reached' : values.completion_reason;
    const completed = values.state === 'finished' && COMPLETED_REASONS.includes(reason);
    const takesPart = key !== null && completed && values.comparable !== false;
    group.runs.push({run, interrupted, unclassified: !interrupted && !completed, takesPart});
    group.comparable += takesPart ? 1 : 0;
    group.latest = position(run);
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => b.latest - a.latest);
}

const PATTERNS = 'pbr';
const BAR_PX = 112;

/**
 * @param {HTMLElement} root the element of index.html this view owns
 * @param {Object} ctx store, text, roots and the action functions
 */
export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;
  const status = h('span', {class: 'badge', 'data-testid': 'runs-status', hidden: true});
  const note = h('p', {class: 'empty-note', hidden: true});
  // The columns: the result metrics; those of the cost (CONTRACT.md §9) only when a run of the archive publishes them.
  let columns = METRIC_ORDER.filter((metric) => !COST_FIELDS.includes(metric));
  const headRow = h('tr');
  const writeHead = () => headRow.replaceChildren(
    h('th', {scope: 'col', text: UI.runs.run}), h('th', {scope: 'col', text: UI.runs.series}),
    ...columns.map((metric) => h('th', {scope: 'col', text: text.metricLabel(metric, true), title: text.metricLabel(metric)})));
  writeHead();
  const table = h('table', {class: 'runs', 'data-testid': 'runs-table'}, h('thead', null, headRow));
  root.append(
    s('svg', {class: 'pb-defs', width: 0, height: 0, 'aria-hidden': 'true', focusable: 'false'}, s('defs', null, peoplePatterns(PATTERNS))),
    h('div', {class: 'view__bar runs-bar'},
      h('h2', {class: 'runs-bar__title', text: UI.runs.title}),
      h('span', {class: 'runs-bar__limit', text: UI.runs.limit}), status),
    h('p', {class: 'runs-lead', text: UI.runs.lead}),
    h('div', {class: 'view__scroll runs-scroll'}, table, note));

  function seriesRow(run, prefix, label, interrupted, published, total) {
    const series = prefix ? 'forecast' : 'fact';
    const labelCell = h('th', {scope: 'row', class: 'runs-series'}, h('span', {class: 'runs-series__name', text: label}));
    if (published) {
      // The people of the common group, drawn like the dock; the numbers are in the cells of the row.
      const people = peopleOf(run.values, prefix, total);
      const bar = peopleBar(PATTERNS, BAR_PX);
      bar.update(people, series, peopleWords(text, people));
      labelCell.append(bar.svg);
    }
    return h('tr', {class: `runs-row runs-row--${prefix ? 'forecast' : 'actual'}`, 'data-run': run.name, 'data-series': prefix ? 'forecast' : 'actual'},
      labelCell,
      columns.map((metric) => {
        const cell = published ? metricCell(text, run, prefix, metric, interrupted) : {text: text.DASH, badge: null};
        return h('td', {'data-metric': metric},
          h('span', {class: valueClass(series, cell.text === text.DASH ? 'none' : cell.badge), text: cell.text}));
      }));
  }

  function runRows({run, interrupted, unclassified, takesPart}, group, model, total) {
    const {values} = run;
    // A run without a classified ending has no final result either: its missing values stay dashes.
    const cut = interrupted || unclassified;
    const option = typeof values.executed_option === 'string' ? (model && model.byName[values.executed_option]) : null;
    const optionText = option ? `${option.label} — ${text.codeLabel('optionKind', option.attrs.option_kind)}`
      : (values.executed_option === undefined ? text.DASH : String(values.executed_option));
    // The ending as published: its code in words, or as it came. A twin that is not `finished` says that as well.
    const stateWords = text.label('archiveRunState', values.state);
    let ending = stateWords;
    if (values.completion_reason !== undefined) {
      ending = text.codeLabel('completionReason', values.completion_reason);
      if (values.state !== 'finished') ending += ` · ${text.fieldLabel('state')}: ${stateWords}`;
    }
    let mark = '';
    if (interrupted) mark = UI.runs.interrupted;
    else if (unclassified) mark = UI.runs.unclassified;
    else if (values.comparable === false) mark = UI.runs.incomparable(text.codeLabel('incomparableReason', values.incomparable_reason));
    else if (group.comparable < 2) mark = UI.runs.alone;
    let endingKind = 'done';
    if (interrupted) endingKind = 'interrupted';
    else if (unclassified) endingKind = 'unclassified';
    const about = h('th', {scope: 'rowgroup', rowspan: 2, class: 'runs-about'},
      h('strong', {class: 'runs-about__name mono', text: run.label}),
      h('span', {class: `run-ending run-ending--${endingKind}`, 'data-testid': 'run-ending', text: ending}),
      h('span', {class: 'runs-about__note', text: `${UI.status.seed} ${text.num(values.seed)} · ${optionText}`}),
      mark ? h('span', {class: `run-mark${takesPart ? '' : ' run-mark--out'}`, 'data-testid': 'run-mark', text: mark}) : null);
    const forecast = hasMetrics(values, 'forecast_');
    // Forecast numbers never stand without a word on how complete the forecast was.
    let forecastLabel = UI.decision.notPublished;
    if (forecast) {
      const quality = values.forecast_quality;
      forecastLabel = quality === 'full' ? UI.decision.forecast
        : `${UI.decision.forecast}: ${quality === undefined ? UI.decision.qualityNotPublished : text.label('forecastQuality', quality)}`;
    }
    const actual = seriesRow(run, '', UI.decision.actual, cut, true, total);
    actual.prepend(about);
    setAttrs(actual, {
      'data-completion': values.completion_reason, 'data-comparable': String(takesPart), 'data-ending': endingKind,
      'data-comparison-key': group.key,
    });
    return [actual, seriesRow(run, 'forecast_', forecastLabel, false, forecast, total)];
  }

  // The archive changes only when a run ends: the table is built anew then, not on every poll.
  store.watch((state) => [state.archive, state.attributes], () => {
    const {archive, model} = store.getState();
    const groups = groupRuns(archive.runs, archive.ids);
    const costed = (metric) => archive.runs.some((run) => ['', 'forecast_'].some((prefix) => run.values[prefix + metric] !== undefined));
    columns = METRIC_ORDER.filter((metric) => !COST_FIELDS.includes(metric) || costed(metric));
    writeHead();
    table.replaceChildren(table.tHead, ...groups.map((group) => {
      const title = group.key === null ? UI.runs.noKey
        : (group.comparable >= 2 ? UI.runs.comparison(text.counted(group.comparable, text.FORMS.run), group.key) : UI.runs.single(group.key));
      // One key means one common group: its size is known where a run of the key says that everyone was out.
      const size = group.key === null ? null : commonGroup(group.runs.map((item) => item.run), ['', 'forecast_']);
      return h('tbody', {'data-comparison-key': group.key, 'data-group': group.comparable >= 2 ? 'comparison' : 'single'},
        h('tr', {class: 'runs-group'}, h('th', {scope: 'rowgroup', colspan: columns.length + 2},
          h('span', {class: 'runs-group__title', text: title}),
          size ? h('span', {class: 'runs-group__size', text: UI.runs.groupFrom(size.total)}) : null)),
        group.runs.flatMap((item) => runRows(item, group, model, size ? size.total : null)));
    }));
    table.hidden = groups.length === 0;

    let words = '';
    if (archive.status === 'loading') words = UI.runs.loading;
    else if (archive.status === 'error') words = [UI.runs.error, text.failureText(archive.failure)].filter(Boolean).join(': ');
    status.hidden = words === '';
    setText(status, words);
    setAttrs(status, {class: `badge badge--${archive.status === 'error' ? 'danger' : 'info'}`, 'data-status': archive.status});
    note.hidden = groups.length > 0 || archive.status === 'loading' || archive.status === 'error';
    setText(note, archive.status === 'ready' ? UI.runs.empty : text.shownDataText(null));
  });
}
