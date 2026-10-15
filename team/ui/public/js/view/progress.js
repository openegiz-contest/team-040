// «Выполнение» and «Итог» of the right panel (mounted by view/decide.js), and
// the small helpers the panel shares: a worker as a button with the legend's
// figure, and «показать».
//
// Выполнение answers «Как идёт вывод?»: the published counter that the chosen
// option is about (people out; for «Наблюдать» people in a danger zone) next to
// what the model forecast for it, the people of the option's zones with their
// published status, the state of those zones, and the command that started it.
// The people listed are the workers whose home zone (attribute) or published
// position is in a zone of the option: a list of named workers, never a group
// size of our own.
//
// Итог answers «Чем закончилось?»: the fact of the run next to the forecast of
// the model for the executed option, in the same rows and units; the headline of
// the fact follows the same fixed rules as the forecast (decision.js headline()),
// so there is no time unless the model says that everyone is out, and an
// incomplete withdrawal is said as such. «Закрыть итог» hides the panel (UI only).

import {h, reconcile, s, setAttrs, setGlyph, setText} from '../dom.js';
import {symbol} from '../icons.js';
import {causesOf, incidentOf, isUnderground, labelOf, thingByName, thingsOfKind, workersInZone, zoneOfWorking} from '../model.js';
import {EASE, MS, motionAllowed, play} from '../motion.js';
import {decisionOf, headline, metricsTable, optionVerb, peopleOf, peoplePatterns, qualityMark} from './decision.js';
import {sentTitle} from './pending.js';

// ---- shared helpers -------------------------------------------------------------------------

/**
 * Show an object: select it and ask the stage to frame it (the scheme and the card follow the selection).
 * @param {Object} ctx
 * @param {string|null} thingId
 */
export function showThing(ctx, thingId) {
  if (!thingId) return;
  ctx.select(thingId);
  ctx.stage.focus(thingId);
}

/** Every cause when the model lists them, else the trigger of the incident. */
function causesFor(values) {
  const listed = causesOf(values);
  if (listed.length > 0) return listed;
  return values.trigger ? [{trigger: values.trigger, subject: values.zone, tick: values.opened_at_tick}] : [];
}

const HAZARD_GLYPH = {danger: 'danger', attention: 'attention', unknown: 'unknown', normal: 'ok'};

/**
 * What happened, in one sentence and a muted second line: «Участок Г — опасно»,
 * «+ потеряны данные Э-05 · в 00:21:00 (только что)». A hazard is said by the published state of its zone
 * (or working) now; a subject that is the zone itself is not repeated. `sign`: the glyph of the line.
 * @returns {{line: string, more: string, hazard: string, sign: string, opened: (number|null)}}
 */
export function incidentSentence(text, model) {
  const P = text.PANEL;
  const incident = incidentOf(model);
  const values = incident ? incident.values : {};
  const nowS = model.shift ? model.shift.values.sim_time_s : undefined;
  const zone = thingByName(model, values.zone);
  const name = (local) => labelOf(model, local);
  const causes = causesFor(values);
  const causeWords = (cause) => {
    const own = typeof cause.subject === 'string' && cause.subject !== values.zone ? name(cause.subject) : '';
    if (cause.trigger === 'hazard') {
      const where = thingByName(model, cause.subject) || zone;
      const words = where && where.hazard ? text.hazardText(where.hazard) : text.label('incidentTrigger', cause.trigger);
      return own ? `${own}: ${words}` : words;
    }
    const words = text.isKnown('incidentTrigger', cause.trigger) && P.cause[cause.trigger]
      ? P.cause[cause.trigger] : text.label('incidentTrigger', cause.trigger);
    return own ? `${words} ${own}` : words;
  };
  const first = causes.length > 0 ? causeWords(causes[0]) : text.label('incidentState', values.state);
  const hazard = zone && zone.hazard ? zone.hazard.state : 'unknown';
  const sign = causes.length > 0 && causes[0].trigger === 'passage_closed' ? 'blocked' : (HAZARD_GLYPH[hazard] || 'unknown');
  const ticks = causes.map((cause) => cause.tick).filter((tick) => typeof tick === 'number');
  const opened = typeof values.opened_at_tick === 'number' ? values.opened_at_tick : (ticks.length > 0 ? Math.min(...ticks) : null);
  const at = text.tickSeconds(opened);
  const more = causes.slice(1).map((cause) => P.more(causeWords(cause)));
  if (at !== null) {
    const ago = text.agoText(at, nowS);
    // Less than a second ago reads «только что» here rather than the bare age word.
    more.push(P.at(text.modelTime(at), typeof nowS === 'number' && nowS - at < 1 ? P.justNow : ago));
  }
  return {line: P.head(zone ? zone.label : '', first), more: more.join(' · '), hazard, sign, opened};
}

/** The figure of a worker in the legend's shapes: route ok, in a danger zone, no computed route, unknown. */
export function workerFigure(worker) {
  const {values} = worker;
  if (values.status === 'unknown' || values.egress_status === 'unknown' || values.location_hazard === 'unknown') return 'unknown';
  if (values.egress_status === 'none') return 'none';
  if (values.location_hazard === 'danger') return 'inDanger';
  return 'ok';
}

/**
 * A worker as a small button: the legend's figure of its state and its code. A click selects the worker.
 * @param {Object} ctx
 * @returns {HTMLButtonElement}
 */
export function whoButton(ctx) {
  const button = h('button', {type: 'button', class: 'dp-who'}, h('span', {class: 'dp-who__mark'}), h('span', {class: 'dp-who__code'}));
  button.addEventListener('click', () => showThing(ctx, button.getAttribute('data-thing-id')));
  return button;
}

/**
 * @param {HTMLButtonElement} button made by whoButton
 * @param {import('../store.js').Thing} worker
 * @param {string} [figure] one of the worker symbols; default: workerFigure(worker)
 * @param {string} [words] the state in words, for the title and the accessible name
 */
export function updateWho(button, worker, figure = workerFigure(worker), words = '') {
  const mark = button.firstChild;
  if (mark.getAttribute('data-figure') !== figure) {
    mark.replaceChildren(symbol('worker', figure, {size: 14}));
    mark.setAttribute('data-figure', figure);
  }
  setText(button.lastChild, worker.label);
  setAttrs(button, {'data-thing-id': worker.thingId, 'data-figure': figure, title: words ? `${worker.label}: ${words}` : worker.label,
    'aria-label': words ? `${worker.label}: ${words}` : worker.label});
}

/** One big published figure with its label; the number crossfades when the model publishes another one. */
function figure(text, testid) {
  const number = h('span', {class: 'dp-fig__num'});
  const node = h('p', {class: 'dp-fig', 'data-testid': testid}, number, h('span', {class: 'dp-fig__label'}));
  let shown = null;
  return {
    node,
    update(value, label, state, extra = {}) {
      const words = typeof value === 'number' ? text.num(value) : text.DASH;
      if (shown !== null && shown !== words && motionAllowed(state)) {
        play(number, [{opacity: 0.15}, {opacity: 1}], {duration: MS.digits, easing: EASE});
      }
      shown = words;
      setText(number, words);
      setText(node.lastChild, label);
      setAttrs(node, {'data-value': typeof value === 'number' ? value : null, ...extra});
    },
  };
}

/** The option the incident carries out or carried out: executing, or else the one the model names as selected. */
function chosenOption(model, decision) {
  if (decision.executing) return decision.executing;
  const incident = incidentOf(model);
  const selected = incident ? thingByName(model, incident.values.selected_option) : null;
  return selected && selected.kind === 'option' ? selected : null;
}

/** The zones an option acts on; for a zone withdrawal without an option, the zones whose withdrawal goes on. */
function zonesOf(model, option) {
  if (option) {
    const scope = Array.isArray(option.values.scope) ? option.values.scope : [];
    return scope.map((name) => thingByName(model, name)).filter((zone) => zone && zone.kind === 'zone');
  }
  return thingsOfKind(model, 'zone').filter((zone) => zone.values.withdrawal_state === 'in_progress');
}

/**
 * The workers of a set of zones: by their home zone (attribute) or their published position. For an
 * option without zones («Наблюдать»), the workers of the incident's zone and everyone the model places
 * in a danger zone.
 */
function workersOf(model, zones) {
  const names = new Set(zones.map((zone) => zone.name));
  const workers = thingsOfKind(model, 'worker');
  if (names.size > 0) {
    return workers.filter((worker) => names.has(worker.attrs.home_zone)
      || (isUnderground(worker) && typeof worker.values.at_working === 'string'
        && names.has((zoneOfWorking(model, worker.values.at_working) || {}).name)));
  }
  const incident = incidentOf(model);
  const here = incident && typeof incident.values.zone === 'string' ? workersInZone(model, incident.values.zone) : [];
  return workers.filter((worker) => here.includes(worker) || (isUnderground(worker) && worker.values.location_hazard === 'danger'));
}

const CELL_ORDER = ['out', 'moving', 'waiting', 'working', 'noroute', 'danger', 'unknown'];

/** The cell of a worker in the bar of «Выполнение»: what its published fields say now. */
function cellOf(worker) {
  const {values} = worker;
  if (values.status === 'out') return 'out';
  if (values.status === 'unknown' || !['working', 'moving_to_exit', 'waiting'].includes(values.status)) return 'unknown';
  if (values.egress_status === 'none') return 'noroute';
  if (values.location_hazard === 'danger') return 'danger';
  if (values.status === 'moving_to_exit') return 'moving';
  return values.status === 'waiting' ? 'waiting' : 'working';
}

/** The state of a worker in words: «идёт к выходу», «вышел · Восстающий», «ждёт · нет расчётного маршрута». */
function workerWords(text, model, worker) {
  const P = text.PANEL;
  const {values} = worker;
  if (values.status === 'out') {
    const exit = thingByName(model, values.at_exit);
    return exit ? P.outAt(exit.label) : P.worker.out;
  }
  const parts = [Object.prototype.hasOwnProperty.call(P.worker, values.status) ? P.worker[values.status] : text.label('workerStatus', values.status)];
  // A working without sensors by design is not an unknown monitored zone (CONTRACT §7): say so instead.
  const working = typeof values.at_working === 'string' ? thingByName(model, values.at_working) : null;
  const unmonitored = working && working.values.data_quality === 'none';
  if (values.location_hazard === 'danger') parts.push(P.inDangerZone);
  else if (values.location_hazard === 'unknown') {
    parts.push(unmonitored ? `${text.label('kind', 'working')} ${text.UI.scheme.noSensors}` : P.placeUnknown);
  }
  if (values.egress_status === 'none') parts.push(P.noRouteWord);
  else if (values.egress_status === 'unknown') parts.push(text.label('egress', 'unknown'));
  return parts.join(' · ');
}

/** The state of a zone in words: «остановлен · вывод персонала идёт»; the hazard goes into its badge. */
function zoneWords(text, model, zone) {
  const {values} = zone;
  const parts = [];
  if (values.work_state !== undefined) parts.push(text.label('workState', values.work_state));
  if (values.withdrawal_state !== undefined && values.withdrawal_state !== 'none') parts.push(text.label('withdrawal', values.withdrawal_state));
  // A danger known before the data were lost stays in sight (CONTRACT.md 7).
  const last = text.lastKnownText(values, model.shift ? model.shift.values.sim_time_s : undefined);
  if (last && zone.hazard && zone.hazard.state === 'unknown') parts.push(last);
  return parts.join(' · ') || text.DASH;
}

function zoneLines(ctx, list) {
  const {text} = ctx;
  return (model, zones) => reconcile(list, zones, (zone) => zone.thingId, () => {
    const button = h('button', {type: 'button', class: 'btn btn--link dp-zone__name'});
    button.addEventListener('click', () => showThing(ctx, button.getAttribute('data-thing-id')));
    return h('li', {class: 'dp-zone'}, button, h('span', {class: 'dp-zone__hazard badge'}), h('span', {class: 'dp-zone__words'}));
  }, (node, zone) => {
    const [button, hazard, words] = node.children;
    setText(button, zone.label);
    setAttrs(button, {'data-thing-id': zone.thingId});
    setText(words, zoneWords(text, model, zone));
    const state = zone.hazard ? zone.hazard.state : 'unknown';
    setText(hazard, zone.hazard ? text.hazardText(zone.hazard) : text.DASH);
    setAttrs(hazard, {class: `dp-zone__hazard badge badge--${state}`});
    setAttrs(node, {'data-zone': zone.name, 'data-withdrawal': zone.values.withdrawal_state, 'data-work-state': zone.values.work_state,
      'data-hazard': state});
  });
}

// ---- «Выполнение» --------------------------------------------------------------------------

/** @param {Object} ctx */
export function executingView(ctx) {
  const {store, text} = ctx;
  const P = text.PANEL;
  const main = figure(text, 'progress-main');
  const second = figure(text, 'progress-second');
  const third = figure(text, 'progress-third');
  const expect = h('p', {class: 'dp-expect', 'data-testid': 'progress-expect'});
  const figures = h('div', {class: 'dp-figs'}, main.node, second.node, third.node);
  const cells = h('div', {class: 'dp-cells', role: 'img', 'data-testid': 'progress-bar'});
  const peopleTitle = h('h3', {class: 'dp-sub'});
  const peopleNote = h('p', {class: 'dp-note', text: P.peopleNote});
  const list = h('ul', {class: 'dp-list', 'data-testid': 'progress-people'});
  const nobody = h('p', {class: 'dp-note', text: P.nobodyListed, hidden: true});
  const zones = h('ul', {class: 'dp-zones', 'data-testid': 'progress-zones'});
  const ack = h('p', {class: 'dp-ack', 'data-testid': 'progress-ack'}, h('span', {class: 'dp-ack__glyph'}), h('span', {class: 'dp-ack__words'}));
  const body = h('div', {class: 'dp-progress'},
    h('section', {class: 'dp-block'}, figures, expect, cells),
    h('section', {class: 'dp-block'}, zones),
    h('section', {class: 'dp-block'}, peopleTitle, list, nobody, peopleNote),
    ack);
  const foot = h('div', {class: 'dp-foot dp-foot--executing'});
  const updateZones = zoneLines(ctx, zones);

  function render(state) {
    const {model} = state;
    const shift = model.shift ? model.shift.values : {};
    const decision = decisionOf(model);
    const option = chosenOption(model, decision);
    const kind = option ? option.attrs.option_kind : null;
    const scopeZones = zonesOf(model, option);
    const observe = kind === 'observe' || (option !== null && scopeZones.length === 0);
    const verb = option ? optionVerb(text, model, option) : '';

    // The published counter the option is about, and what the model forecast for it.
    if (observe) {
      main.update(shift.workers_in_danger, P.inDangerNow, state, {'data-figure': 'in_danger'});
      const unknown = shift.workers_unknown;
      second.update(unknown, P.unknownNow, state, {'data-figure': 'unknown'});
      second.node.hidden = !(typeof unknown === 'number' && unknown > 0);
      third.node.hidden = true;
    } else {
      main.update(shift.workers_out, P.outNow, state, {'data-figure': 'out'});
      second.update(shift.workers_in_danger, P.inDangerNow, state, {'data-figure': 'in_danger'});
      second.node.hidden = !(typeof shift.workers_in_danger === 'number' && shift.workers_in_danger > 0);
      third.update(shift.workers_unknown, P.unknownNow, state, {'data-figure': 'unknown'});
      third.node.hidden = !(typeof shift.workers_unknown === 'number' && shift.workers_unknown > 0);
    }
    setAttrs(main.node, {'data-tone': observe && shift.workers_in_danger > 0 ? 'danger' : null});
    setAttrs(second.node, {'data-tone': observe ? 'unknown' : 'danger'});
    setAttrs(third.node, {'data-tone': 'unknown'});
    let expected = '';
    if (option) {
      const values = option.values;
      if (observe) {
        const forecast = headline(text, values, 'forecast_');
        expected = forecast ? P.expect(forecast.text) : P.notPublished;
      } else if (values.forecast_all_out === true) {
        expected = P.expectAllOut(values.forecast_last_out_s);
      } else if (typeof values.forecast_out === 'number') {
        expected = P.expectOut(values.forecast_out);
      } else {
        expected = P.notPublished;
      }
      const quality = qualityMark(text, values.forecast_quality);
      if (quality.words && expected !== P.notPublished) expected += ` · ${quality.words}`;
    }
    setText(expect, expected);
    expect.hidden = expected === '';

    // The people of the option's zones, with their published status.
    const workers = workersOf(model, scopeZones)
      .map((worker) => ({worker, cell: cellOf(worker)}))
      .sort((a, b) => CELL_ORDER.indexOf(a.cell) - CELL_ORDER.indexOf(b.cell));
    reconcile(cells, workers, (item) => item.worker.thingId, () => h('span', {class: 'dp-cell'}), (node, item) => {
      setAttrs(node, {'data-cell': item.cell, 'data-thing-id': item.worker.thingId,
        'data-place': item.worker.values.location_hazard === 'unknown' ? 'unknown' : null,
        title: `${item.worker.label}: ${workerWords(text, model, item.worker)}`});
    });
    setAttrs(cells, {'aria-label': workers.map((item) => `${item.worker.label}: ${workerWords(text, model, item.worker)}`).join('; ') || text.DASH});
    cells.hidden = workers.length === 0;
    const zoneNames = scopeZones.map((zone) => zone.label).join(', ');
    setText(peopleTitle, P.peopleOf(zoneNames || labelOf(model, (incidentOf(model) || {values: {}}).values.zone)));
    reconcile(list, workers, (item) => item.worker.thingId, () => h('li', {class: 'dp-list__row'}, whoButton(ctx), h('span', {class: 'dp-list__words'})),
      (node, item) => {
        const words = workerWords(text, model, item.worker);
        updateWho(node.firstChild, item.worker, workerFigure(item.worker), words);
        setText(node.lastChild, words);
        setAttrs(node, {'data-cell': item.cell, 'data-status': item.worker.values.status});
      });
    nobody.hidden = workers.length > 0;

    // The zones of the option, or for «Наблюдать» the zone of the incident.
    const incident = incidentOf(model);
    const incidentZone = incident ? thingByName(model, incident.values.zone) : null;
    updateZones(model, scopeZones.length > 0 ? scopeZones : (incidentZone ? [incidentZone] : []));

    // The command that started it, as this page knows it; else what the model says was chosen.
    const entry = [...state.pending].reverse().find((item) => item.type === 'action.execute_option'
      || item.type === 'action.withdraw_zone');
    const [glyphHolder, words] = ack.children;
    if (entry) {
      const target = entry.type === 'action.execute_option' ? thingByName(model, entry.target) : null;
      const what = target && target.kind === 'option' ? P.launched(optionVerb(text, model, target)) : sentTitle(text, state, entry.type, entry.target);
      setText(words, `${what} — ${text.pendingText(entry)}`);
      setGlyph(glyphHolder, entry.phase === 'applied' ? 'ok' : (entry.phase === 'rejected' || entry.phase === 'not_sent' ? 'blocked' : 'clock'));
      setAttrs(ack, {'data-phase': entry.phase});
    } else {
      setText(words, option ? P.selected(verb) : '');
      setGlyph(glyphHolder, 'info');
      setAttrs(ack, {'data-phase': null});
    }
    ack.hidden = words.textContent === '';

    const title = option ? P.executing(verb) : P.withdrawing(zoneNames || text.DASH);
    // What the option answers: the incident in one line.
    const said = incident ? incidentSentence(text, model) : null;
    return {title, subtitle: said ? [said.line, said.more].filter(Boolean).join(' · ') : ''};
  }

  return {body, foot, render, leave() {}};
}

// ---- «Итог» ----------------------------------------------------------------------------------

/** @param {Object} ctx */
export function resultView(ctx) {
  const {text} = ctx;
  const P = text.PANEL;
  const fact = h('p', {class: 'dp-result', 'data-testid': 'result-fact'}, h('span', {class: 'dp-result__label', text: text.UI.decision.actual}),
    h('span', {class: 'dp-result__line'}));
  const forecast = h('p', {class: 'dp-result dp-result--forecast', 'data-testid': 'result-forecast'},
    h('span', {class: 'dp-result__label', text: text.UI.decision.forecast}), h('span', {class: 'dp-result__line'}));
  const alerts = h('ul', {class: 'dp-alerts', 'data-testid': 'result-alerts'});
  const zones = h('ul', {class: 'dp-zones', 'data-testid': 'result-zones'});
  const table = metricsTable(text, {class: 'metrics dp-table dp-table--fact', 'data-testid': 'result-table'},
    {people: text.UI.decision.peopleShort, prefix: 'pbr', barWidth: 150});
  const noFact = h('p', {class: 'dp-alert dp-alert--unknown', 'data-testid': 'result-no-fact', text: P.factNotPublished, hidden: true});
  const body = h('div', {class: 'dp-done'},
    s('svg', {class: 'pb-defs', width: 0, height: 0, 'aria-hidden': 'true', focusable: 'false'}, s('defs', null, peoplePatterns('pbr'))),
    h('section', {class: 'dp-block'}, fact, forecast, noFact, alerts),
    h('section', {class: 'dp-block'}, h('h3', {class: 'dp-sub', text: P.vsForecast}), table.table),
    h('section', {class: 'dp-block'}, zones));
  const close = h('button', {type: 'button', class: 'btn btn--quiet btn--block dp-close', 'data-testid': 'result-close', text: P.close,
    title: P.closeTitle});
  const foot = h('div', {class: 'dp-foot dp-foot--done'}, close);
  const updateZones = zoneLines(ctx, zones);
  let onClose = () => {};
  close.addEventListener('click', () => onClose());

  function render(state) {
    const {model} = state;
    const decision = decisionOf(model);
    const option = decision.executed[decision.executed.length - 1] || chosenOption(model, decision)
      || decision.options.find((item) => item.values.state === 'done') || null;
    const incident = incidentOf(model);
    const verb = option ? optionVerb(text, model, option) : '';
    const factLine = option ? headline(text, option.values, 'actual_') : null;
    const forecastLine = option ? headline(text, option.values, 'forecast_') : null;
    fact.hidden = !factLine;
    setText(fact.lastChild, factLine ? factLine.text : '');
    setAttrs(fact, {'data-rule': factLine ? factLine.rule : null});
    setText(forecast.lastChild, forecastLine ? forecastLine.text : P.notPublished);
    setAttrs(forecast, {'data-rule': forecastLine ? forecastLine.rule : 'not_published'});
    forecast.hidden = !option;
    noFact.hidden = Boolean(factLine) || !option;

    // What the model says did not end well: a withdrawal that is not complete, and who has no route.
    const incomplete = thingsOfKind(model, 'zone').filter((zone) => zone.values.withdrawal_state === 'incomplete');
    const stranded = thingsOfKind(model, 'worker').filter((worker) => isUnderground(worker) && worker.values.egress_status === 'none');
    const items = incomplete.map((zone) => ({key: zone.name, words: P.incomplete(zone.label)}));
    if (stranded.length > 0) items.push({key: 'noroute', words: P.noRoute(stranded.map((worker) => worker.label).join(', '))});
    reconcile(alerts, items, (item) => item.key, () => h('li', {class: 'dp-alert dp-alert--noroute'}), (node, item) => setText(node, item.words));

    if (option) {
      table.update([
        {key: 'forecast', head: text.UI.decision.forecast, twin: option, prefix: 'forecast_',
          published: Boolean(forecastLine), people: peopleOf(option.values, 'forecast_', decision.total)},
        {key: 'actual', head: text.UI.decision.actual, twin: option, prefix: 'actual_',
          published: Boolean(factLine), people: peopleOf(option.values, 'actual_', decision.total)},
      ]);
    }
    table.table.hidden = !option;
    const scope = option ? zonesOf(model, option) : [];
    const incidentZone = incident ? thingByName(model, incident.values.zone) : null;
    updateZones(model, scope.length > 0 ? scope : (incidentZone ? [incidentZone] : []));
    return {title: option ? P.done(verb) : P.doneUnknown, subtitle: incident ? text.label('incidentState', incident.values.state) : ''};
  }

  return {
    body, foot, render, leave() {},
    /** @param {() => void} fn what «Закрыть итог» does (view/decide.js hides the panel) */
    onClose(fn) {
      onClose = fn;
    },
  };
}
