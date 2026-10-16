// The right panel of «Пульт смены». It follows the situation of the shift
// (situation.js) and answers one question at a time:
//   decision   «Решение»     what happened, who is threatened, what can be done — three steps
//                            and one card per option of the model, ending in one primary launch button
//   executing  «Выполнение»  how the chosen option goes (view/progress.js)
//   done       «Итог»        the fact of the run next to the forecast of the model (view/progress.js)
// Nothing here is computed that the model did not publish: counts are the
// model's counters, lists of codes are read from the fields of each worker, and
// the sentence of an option comes from its published forecast by the fixed
// rules of headline() (view/decision.js). The model recommends nothing, and
// nothing here ranks the options.
//
// Contract with the layout (main.js, css/layout.css): this view renders into
// ctx.roots.panel (#panel); the column is shown while the situation is
// decision, executing or done and #panel is not [hidden]. «Закрыть итог» sets
// root.hidden until the incident or the run changes.
//
// Choosing a card (click, Enter/Space, arrows: a radio group) or pointing at it
// sets ui.hoverOption (ctx.hoverOption): the stage lights the zones of the
// option and the people in them. Motion (clarity pass, B): the panel switches
// decision → executing → done with one 200 ms slide; a chosen card draws its
// outline in 150 ms; nothing moves on load, over old data or under reduced
// motion.

import {h, reconcile, s, setAttrs, setGlyph, setText} from '../dom.js';
import {incidentOf, isUnderground, thingByName, thingsOfKind, workersInZone} from '../model.js';
import {EASE_POSTER, motionAllowed, play, playIn, stagger} from '../motion.js';
import {situationOf} from '../situation.js';
import {costFacts, costLine, decisionOf, hasCost, headline, launchOption, metricsTable, optionVerb, peopleBar, peopleOf, peoplePatterns, qualityMark,
  scopeText, secondaryFacts} from './decision.js';
import {blockNote, commandButton, guard, showBlock, standing} from './pending.js';
import {executingView, incidentSentence, resultView, showThing, updateWho, whoButton, workerFigure} from './progress.js';

const PANEL_MODES = new Set(['decision', 'executing', 'done']);
const CODES_LIMIT = 6;

// ---- «Решение» --------------------------------------------------------------------------

function decisionView(ctx) {
  const {store, text} = ctx;
  const P = text.PANEL;

  const step = (number, extra) => {
    const show = number < 3
      ? h('button', {type: 'button', class: 'btn btn--link dp-step__show', 'data-testid': `decide-show-${number}`, text: P.show}) : null;
    const title = h('h3', {class: 'dp-step__title', id: `dp-step-${number}`, text: P.steps[number - 1]});
    const node = h('section', {class: `dp-step dp-step--${number}`, 'data-testid': `decide-step-${number}`, 'aria-labelledby': title.id},
      h('header', {class: 'dp-step__head'}, h('span', {class: 'dp-step__num', 'aria-hidden': 'true', text: String(number)}), title, show),
      extra);
    return {node, show};
  };

  // 1. What happened.
  const whatGlyph = h('span', {class: 'dp-what__glyph'});
  const whatLine = h('span', {class: 'dp-what__line'});
  const what = h('p', {class: 'dp-what', 'data-testid': 'decide-what'}, whatGlyph, whatLine);
  const whatMore = h('p', {class: 'dp-what-more', 'data-testid': 'decide-what-more'});
  const step1 = step(1, [what, whatMore]);
  let incidentZone = null;
  step1.show.addEventListener('click', () => showThing(ctx, incidentZone));

  // 2. Who is threatened: a sentence per group, the workers as buttons with the legend's figures.
  const groups = h('ul', {class: 'dp-people', 'data-testid': 'decide-people'});
  const step2 = step(2, groups);
  step2.show.addEventListener('click', () => showThing(ctx, incidentZone));

  // 3. What can be done.
  const caption = h('p', {class: 'dp-caption', 'data-testid': 'decide-caption'}, h('span', {class: 'dp-caption__what'}), ' ',
    h('span', {class: 'dp-caption__quality'}), h('span', {class: 'dp-caption__advice'}),
    h('span', {class: 'dp-caption__cost', 'data-testid': 'decide-no-cost', hidden: true}));
  const keysDiffer = h('p', {class: 'dp-alert', 'data-testid': 'decide-keys-differ', text: P.keysDiffer, hidden: true});
  const noForecast = h('p', {class: 'dp-alert dp-alert--unknown', 'data-testid': 'decide-no-forecast', text: P.notPublished, hidden: true});
  const cards = h('div', {class: 'dp-cards', role: 'radiogroup', 'aria-labelledby': 'dp-step-3', 'data-testid': 'decide-options'});
  const table = metricsTable(text, {class: 'metrics dp-table', 'data-testid': 'decide-table'},
    {lead: {label: text.UI.decision.zones, words: (column) => scopeText(text, store.getState().model, column.twin)},
      people: text.UI.decision.people, prefix: 'pbp', barWidth: 112});
  const details = h('details', {class: 'dp-details', 'data-testid': 'decide-details'},
    h('summary', {class: 'dp-details__title', text: P.details}), h('p', {class: 'dp-details__lead', text: P.detailsTitle}), table.table);
  const step3 = step(3, [caption, keysDiffer, noForecast, cards, details]);
  // The table opens below the cards: bring it into sight inside the panel (no smooth scroll: no motion of our own).
  details.addEventListener('toggle', () => {
    const scroller = details.closest('.dp__body');
    if (details.open && scroller) scroller.scrollTop += details.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
  });

  const body = h('div', {class: 'dp-decision'},
    s('svg', {class: 'pb-defs', width: 0, height: 0, 'aria-hidden': 'true', focusable: 'false'}, s('defs', null, peoplePatterns('pbp'))),
    step1.node, step2.node, step3.node);

  // The launch: one primary button, the note of what is missing, the block of all commands.
  const block = blockNote();
  const why = h('p', {class: 'dp-why', 'data-testid': 'decide-why'});
  const execute = commandButton({
    class: 'btn btn--dispatch btn--block dp-launch', 'data-testid': 'btn-execute', 'data-command-type': 'action.execute_option',
    text: P.launchIdle,
  }, () => {
    const {model} = store.getState();
    const option = model && chosen ? thingByName(model, chosen) : null;
    if (option) launchOption(ctx, option);
  });
  const foot = h('div', {class: 'dp-foot dp-foot--decision'}, block, execute, why);

  // ---- choice and pointing: ui.hoverOption --------------------------------------------
  let chosen = null;
  let hovered = null;
  let decisionSeen = null;
  let cascaded = null;

  function pointAt() {
    const {model} = store.getState();
    const option = model ? thingByName(model, hovered || chosen) : null;
    const id = option && option.kind === 'option' ? option.thingId : null;
    if (store.getState().ui.hoverOption !== id) ctx.hoverOption(id);
  }

  const cardOf = (target) => (target && target.closest ? target.closest('.dp-card') : null);
  const selectable = () => [...cards.querySelectorAll('.dp-card:not([aria-disabled="true"])')];

  function choose(card) {
    if (!card || card.getAttribute('aria-disabled') === 'true') return;
    const name = card.getAttribute('data-option');
    if (name === chosen) return;
    const wasIdle = chosen === null;
    chosen = name;
    render(store.getState());
    if (motionAllowed(store.getState())) {
      // The chosen card expands: a short push towards the stage, its facts unfold; the launch wakes up once.
      play(card, [{transform: 'translateX(-10px)'}, {transform: 'none'}], {duration: 320, easing: EASE_POSTER});
      const facts = card.querySelector('.dp-card__facts');
      if (facts) playIn(facts, [{opacity: 0, transform: 'translateY(-6px)'}, {opacity: 1, transform: 'none'}], {duration: 300, delay: 60, easing: EASE_POSTER});
      if (wasIdle) play(execute, [{opacity: 0.4, transform: 'translateY(8px)'}, {opacity: 1, transform: 'none'}], {duration: 360, easing: EASE_POSTER});
    }
  }

  cards.addEventListener('click', (event) => {
    const card = cardOf(event.target);
    if (card) {
      choose(card);
      card.focus();
    }
  });
  cards.addEventListener('keydown', (event) => {
    const card = cardOf(event.target);
    if (!card) return;
    const list = selectable();
    const at = list.indexOf(card);
    let next = null;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = list[(at + 1) % list.length];
    else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = list[(at - 1 + list.length) % list.length];
    else if (event.key === 'Home') next = list[0];
    else if (event.key === 'End') next = list[list.length - 1];
    else if (event.key === ' ' || event.key === 'Enter' || event.key === 'Spacebar') {
      event.preventDefault();
      choose(card);
      return;
    } else {
      return;
    }
    event.preventDefault();
    if (next) {
      choose(next);
      next.focus();
    }
  });
  const enter = (event) => {
    const card = cardOf(event.target);
    const name = card ? card.getAttribute('data-option') : null;
    if (name === hovered) return;
    hovered = name;
    pointAt();
  };
  cards.addEventListener('mouseover', enter);
  cards.addEventListener('focusin', enter);
  cards.addEventListener('mouseleave', () => {
    hovered = null;
    pointAt();
  });
  cards.addEventListener('focusout', (event) => {
    if (cards.contains(event.relatedTarget)) return;
    hovered = null;
    pointAt();
  });

  // ---- a card -------------------------------------------------------------------------
  const bars = new WeakMap();
  function createCard() {
    const bar = peopleBar('pbp', 220);
    const node = h('div', {class: 'dp-card', role: 'radio', 'aria-checked': 'false', tabindex: -1, 'data-testid': 'option-card'},
      h('div', {class: 'dp-card__top'}, h('span', {class: 'dp-card__radio', 'aria-hidden': 'true'}),
        h('span', {class: 'dp-card__verb'}), h('span', {class: 'dp-card__state'})),
      h('p', {class: 'dp-card__headline', 'data-testid': 'option-headline'}),
      h('div', {class: 'dp-card__bar'}, bar.svg),
      // Beside the people of the headline, on every card and with the same weight: the time in a danger zone (the
      // benefit) and the cost in one line (CONTRACT.md §9); the chosen card unfolds the whole cost. No verdict.
      h('p', {class: 'dp-card__sum', 'data-testid': 'option-sum'}, h('span', {class: 'dp-card__benefit'}), h('span', {class: 'dp-card__cost-line'})),
      h('p', {class: 'dp-card__facts'}),
      h('div', {class: 'dp-card__cost', 'data-testid': 'option-cost'},
        h('span', {class: 'dp-card__cost-label'}), h('ul', {class: 'dp-card__cost-list'})),
      h('p', {class: 'dp-card__quality'}));
    bars.set(node, bar);
    return node;
  }

  function updateCard(node, option, info) {
    const {model, decision, sameQuality} = info;
    const [top, line, barBox, sumBox, factsBox, costBox, qualityBox] = node.children;
    const [, verbNode, stateNode] = top.children;
    const verb = optionVerb(text, model, option);
    const offered = option.values.state === 'offered';
    const forecast = headline(text, option.values, 'forecast_');
    const ids = {verb: `dp-verb-${option.name}`, line: `dp-line-${option.name}`, facts: `dp-facts-${option.name}`, cost: `dp-cost-${option.name}`,
      sum: `dp-sum-${option.name}`};
    setText(verbNode, verb);
    setAttrs(verbNode, {id: ids.verb});
    setText(stateNode, offered ? '' : (option.values.state === undefined ? text.DASH : text.label('optionState', option.values.state)));
    stateNode.hidden = offered;
    // A forecast the model did not publish has no sentence and no numbers.
    setText(line, forecast ? forecast.text : P.notPublished);
    setAttrs(line, {id: ids.line, 'data-rule': forecast ? forecast.rule : 'not_published', title: forecast ? text.UI.decision.forecast : null,
      'data-long': forecast && forecast.text.length > 36 ? 'true' : null});
    const people = peopleOf(option.values, 'forecast_', decision.total);
    barBox.hidden = !forecast;
    if (forecast) bars.get(node).update(people, 'forecast', `${text.UI.decision.forecast}: ${forecast.text}`);
    const facts = forecast ? secondaryFacts(text, option, 'forecast_', {unknown: info.unknownShown}) : [];
    // With the cost published, the exposures are in the summary of every card and the chosen card unfolds the rest;
    // without it (an older model) the chosen card unfolds the facts as before.
    const unfolded = info.anyCost ? facts.filter((fact) => fact.key !== 'exposure' && fact.key !== 'unknown') : facts;
    reconcile(factsBox, unfolded, (fact) => fact.key, () => h('span', {class: 'dp-card__fact'}), (span, fact) => {
      setText(span, fact.text);
      setAttrs(span, {title: fact.title || null});
    });
    factsBox.hidden = unfolded.length === 0;
    setAttrs(factsBox, {id: ids.facts});
    // The summary of every card: the exposure (benefit) and the cost in one line; never a zero for a missing value.
    const [benefitNode, costNode] = sumBox.children;
    const exposure = facts.filter((fact) => fact.key === 'exposure' || fact.key === 'unknown');
    setText(benefitNode, exposure.map((fact) => fact.text).join(' · '));
    setAttrs(benefitNode, {title: exposure.map((fact) => fact.title).filter(Boolean).join('; ') || null});
    benefitNode.hidden = exposure.length === 0;
    const summary = forecast ? costLine(text, option, 'forecast_') : null;
    setText(costNode, summary ? summary.text : P.costNotPublished);
    setAttrs(costNode, {'data-badge': summary ? summary.badge : null, 'data-cost': summary ? 'published' : 'not_published'});
    sumBox.hidden = !forecast || !info.anyCost;
    setAttrs(sumBox, {id: ids.sum});
    // The whole cost on the chosen card: published fields only; a forecast without them says so, never a zero.
    const cost = forecast ? costFacts(text, option, 'forecast_') : null;
    const [costLabel, costList] = costBox.children;
    setText(costLabel, cost ? `${P.costLabel}:` : P.costNotPublished);
    reconcile(costList, cost || [], (fact) => fact.key, () => h('li', {class: 'dp-card__cost-item'}), (item, fact) => {
      setText(item, fact.text);
      setAttrs(item, {title: fact.title || null, 'data-cost': fact.key, 'data-badge': fact.badge || null});
    });
    costBox.hidden = !forecast || !info.anyCost;
    setAttrs(costBox, {id: ids.cost, 'data-cost': cost ? 'published' : 'not_published'});
    const quality = forecast ? qualityMark(text, option.values.forecast_quality) : {words: '', badge: null};
    // A partial forecast is said on the card itself when the options differ; else once in the caption.
    const ownQuality = quality.words !== '' && !sameQuality;
    setText(qualityBox, ownQuality ? quality.words : '');
    setAttrs(qualityBox, {class: ['dp-card__quality', quality.badge && `badge badge--${quality.badge}`]});
    qualityBox.hidden = !ownQuality;
    const checked = option.name === chosen;
    setAttrs(node, {
      'data-option': option.name, 'data-thing-id': option.thingId, 'data-state': option.values.state,
      'data-option-kind': option.attrs.option_kind,
      'aria-checked': checked ? 'true' : 'false', 'aria-disabled': offered ? null : 'true',
      'aria-labelledby': ids.verb, 'aria-describedby': `${ids.line} ${ids.sum} ${ids.facts} ${ids.cost}`,
      class: ['dp-card', checked && 'is-chosen', !offered && 'is-unavailable', !forecast && 'is-unpublished'],
    });
  }

  // ---- render -------------------------------------------------------------------------
  function render(state) {
    const {model} = state;
    const incident = incidentOf(model);
    const values = incident ? incident.values : {};
    const zone = thingByName(model, values.zone);
    incidentZone = zone ? zone.thingId : null;

    // 1. «Участок Г — опасно», then «+ потеряны данные Э-05 · в 00:21:00 (только что)».
    const said = incidentSentence(text, model);
    setText(whatLine, said.line);
    setGlyph(whatGlyph, said.sign);
    setAttrs(what, {'data-hazard': said.hazard, 'data-sign': said.sign});
    setText(whatMore, said.more);
    setAttrs(whatMore, {title: said.opened === null ? null : text.UI.decision.tick(said.opened)});
    step1.show.hidden = !incidentZone;
    step2.show.hidden = !incidentZone;

    // 2. Who is threatened.
    const shift = model.shift ? model.shift.values : {};
    const workers = thingsOfKind(model, 'worker').filter(isUnderground);
    const rows = [];
    const inDanger = workers.filter((worker) => worker.values.location_hazard === 'danger');
    if (typeof shift.workers_in_danger === 'number' && shift.workers_in_danger > 0) {
      rows.push({key: 'danger', words: P.inDanger(shift.workers_in_danger, ''), workers: inDanger, figure: 'inDanger'});
    } else if (zone) {
      const here = workersInZone(model, zone.name);
      rows.push(here.length > 0
        ? {key: 'zone', words: P.inZone(zone.label, ''), workers: here}
        : {key: 'zone', words: P.nobodyInZone(zone.label), workers: []});
    } else {
      rows.push({key: 'danger', words: P.nobodyInDanger, workers: []});
    }
    if (typeof shift.workers_unknown === 'number' && shift.workers_unknown > 0) {
      // The people of the zones whose state is unknown, as the zones and the workers published it.
      const unknown = thingsOfKind(model, 'zone').filter((item) => item.hasState && item.hazard.state === 'unknown')
        .flatMap((item) => workersInZone(model, item.name));
      rows.push({key: 'unknown', words: P.unknownPeople(shift.workers_unknown, ''), workers: unknown, figure: 'unknown'});
    }
    // Who has no computed route, and whether any option of the model brings them out (clarity pass, A4/A5).
    const decision = decisionOf(model);
    const stranded = workers.filter((worker) => worker.values.egress_status === 'none');
    const strandedCodes = stranded.map((worker) => worker.label).join(', ');
    const nobody = decision.published.length > 0 && stranded.length > 0
      && decision.published.every((option) => typeof option.values.forecast_no_route === 'number' && option.values.forecast_no_route > 0);
    if (stranded.length > 0) {
      rows.push({key: 'noroute', words: nobody ? P.nobodyLeads(strandedCodes) : P.noRoute(strandedCodes), workers: [], figure: 'none'});
    }
    reconcile(groups, rows, (row) => row.key, () => h('li', {class: 'dp-people__row'},
      h('span', {class: 'dp-people__words'}), h('span', {class: 'dp-people__who'})), (node, row) => {
      const [words, who] = node.children;
      // «3 человека в опасной зоне:» — the codes follow as buttons.
      setText(words, row.workers.length > 0 ? `${row.words.replace(/: $/, '')}:` : row.words);
      setAttrs(node, {'data-row': row.key, title: P.peopleTitle, 'data-testid': row.key === 'noroute' ? 'decide-no-path' : null});
      const shown = row.workers.slice(0, CODES_LIMIT);
      reconcile(who, shown, (worker) => worker.thingId, () => whoButton(ctx),
        (button, worker) => updateWho(button, worker, row.figure || workerFigure(worker)));
      if (row.workers.length > CODES_LIMIT) who.setAttribute('data-more', `+${row.workers.length - CODES_LIMIT}`);
      else who.removeAttribute('data-more');
    });

    // 3. What can be done.
    const {options, offered} = decision;
    if (decision.decisionIds.join() !== decisionSeen) {
      // A new decision of the model clears a choice made on the old numbers.
      decisionSeen = decision.decisionIds.join();
      chosen = null;
    }
    if (!offered.some((option) => option.name === chosen)) chosen = null;
    const qualities = [...new Set(decision.published.map((option) => option.values.forecast_quality))];
    const horizons = [...new Set(decision.published.map((option) => option.values.forecast_horizon_s))];
    const [captionWhat, captionQuality, captionAdvice] = caption.children;
    setText(captionWhat, horizons.length === 1 && typeof horizons[0] === 'number' ? P.forecastFor(horizons[0]) : P.forecastNoHorizon);
    const quality = qualities.length === 1 ? qualityMark(text, qualities[0]) : {words: '', badge: null};
    setText(captionQuality, quality.words);
    setAttrs(captionQuality, {class: ['dp-caption__quality', quality.badge && `badge badge--${quality.badge}`]});
    captionQuality.hidden = quality.words === '';
    setText(captionAdvice, ` · ${P.noRecommendation}`);
    const forecastTick = decision.published.map((option) => option.values.forecast_tick).find((tick) => typeof tick === 'number');
    setAttrs(caption, {title: text.UI.decision.forecastTitle(horizons[0], forecastTick) || null,
      'data-quality': qualities.length === 1 && qualities[0] !== undefined ? qualities[0] : null});
    caption.hidden = decision.published.length === 0;
    // Each card says «Прогноз не опубликован» itself; the alert is for a decision without any option.
    noForecast.hidden = options.length > 0;
    setText(noForecast, P.noOptions);
    keysDiffer.hidden = decision.sharedKey || options.length < 2;

    // The time in zones of unknown state is said on every card once one option publishes it above zero.
    const unknownShown = decision.published.some((option) => option.values.forecast_unknown_exposure_person_s > 0);
    // The cost on the cards once one option publishes it; else «цена не опубликована» once, in the caption.
    const anyCost = decision.published.some((option) => hasCost(option.values, 'forecast_'));
    const noCost = caption.querySelector('.dp-caption__cost');
    setText(noCost, ` · ${P.costNotPublished}`);
    noCost.hidden = anyCost || decision.published.length === 0;
    const info = {model, decision, sameQuality: qualities.length <= 1, unknownShown, anyCost};
    reconcile(cards, options, (option) => option.name, createCard, (node, option) => updateCard(node, option, info));
    // A decision that appears (or a new one of the model): its cards cascade in from the right, once.
    const cascadeKey = `${decision.decisionIds.join()}|${options.map((option) => option.name).join()}`;
    if (cascadeKey !== cascaded && options.length > 0) {
      cascaded = cascadeKey;
      if (motionAllowed(state)) {
        stagger([...cards.children], [{opacity: 0, transform: 'translateX(72px)'}, {opacity: 1, transform: 'none'}],
          {duration: 460, step: 80, easing: EASE_POSTER});
      }
    }
    // Roving tab stop: the chosen card, or else the first that can be chosen.
    const tabStop = cards.querySelector('.dp-card.is-chosen') || selectable()[0] || null;
    for (const card of cards.children) setAttrs(card, {tabindex: card === tabStop ? 0 : -1});
    details.hidden = decision.published.length === 0;
    table.update(options.map((option) => ({
      key: option.name, head: optionVerb(text, model, option), twin: option, prefix: 'forecast_', chosen: option.name === chosen,
      published: decision.published.includes(option), state: option.values.state,
      sub: [option.values.state === 'offered' ? '' : text.label('optionState', option.values.state)],
      people: peopleOf(option.values, 'forecast_', decision.total),
    })), horizons.length === 1 && typeof horizons[0] === 'number' ? text.UI.decision.peopleIn(horizons[0]) : text.UI.decision.people);

    // The launch.
    const chosenOption = chosen ? thingByName(model, chosen) : null;
    const blocked = showBlock(block, text, state);
    const own = standing(text, state, 'action.execute_option', chosen);
    let reason = '';
    if (offered.length === 0) reason = P.noOptions;
    else if (!chosenOption) reason = P.chooseFirst;
    else if (typeof chosenOption.values.decision_id !== 'string') reason = `${text.fieldLabel('decision_id')}: ${text.UI.card.notPublished}`;
    setText(execute, chosenOption ? P.launch(optionVerb(text, model, chosenOption)) : P.launchIdle);
    setAttrs(execute, {'data-command-target': chosen});
    guard(execute, blocked || reason !== '' || own.bars, why, reason || own.words);
    pointAt();
  }

  return {
    body, foot, render,
    leave() {
      chosen = null;
      hovered = null;
      cascaded = null;
      if (store.getState().ui.hoverOption !== null) ctx.hoverOption(null);
    },
  };
}

// ---- the panel ----------------------------------------------------------------------------

/**
 * @param {HTMLElement} root the element of index.html this view owns (#panel)
 * @param {Object} ctx store, text, roots and the action functions
 */
export function mount(root, ctx) {
  const {store, text} = ctx;
  const P = text.PANEL;

  const title = h('h2', {class: 'dp__title', 'data-testid': 'panel-title'});
  const pauseGlyph = h('span', {class: 'dp__pause-glyph'});
  setGlyph(pauseGlyph, 'pause');
  const pause = h('p', {class: 'dp__pause', 'data-testid': 'panel-pause', hidden: true}, pauseGlyph, h('span', {text: P.paused}));
  const subtitle = h('p', {class: 'dp__subtitle', 'data-testid': 'panel-subtitle'});
  const body = h('div', {class: 'dp__body'});
  const foot = h('div', {class: 'dp__foot'});
  const panel = h('div', {class: 'dp', 'data-testid': 'decide'},
    h('header', {class: 'dp__head'}, h('div', {class: 'dp__head-row'}, title, pause), subtitle), body, foot);
  root.setAttribute('role', 'region');
  root.setAttribute('aria-label', P.region);

  const views = {decision: decisionView(ctx), executing: executingView(ctx), done: resultView(ctx)};
  let mode = null;
  let closedKey = null;

  /** What «Закрыть итог» remembers: the run, the incident and its result. */
  function resultKey(state) {
    const incident = incidentOf(state.model);
    const values = incident ? incident.values : {};
    return [state.snapshot ? state.snapshot.run : '', values.opened_at_tick, values.selected_option, values.zone].join('|');
  }
  views.done.onClose(() => {
    closedKey = resultKey(store.getState());
    root.hidden = true;
  });

  function slide() {
    panel.setAttribute('data-panel-motion', 'running');
    const done = () => panel.removeAttribute('data-panel-motion');
    const motion = play(body, [{opacity: 0, transform: 'translateX(56px)'}, {opacity: 1, transform: 'none'}],
      {duration: 440, easing: EASE_POSTER});
    if (motion) motion.finished.then(done, done);
    else done();
  }

  function render() {
    const state = store.getState();
    const situation = situationOf(state);
    const next = PANEL_MODES.has(situation) ? situation : null;
    if (next !== mode) {
      const previous = mode;
      if (previous) views[previous].leave();
      mode = next;
      if (!mode) {
        if (root.firstChild) root.replaceChildren();
      } else {
        body.replaceChildren(views[mode].body);
        foot.replaceChildren(views[mode].foot);
        setAttrs(panel, {'data-mode': mode});
        if (!root.firstChild) root.append(panel);
        // The switch explains a change: once, only from one panel to the next while the page watches.
        if (previous && motionAllowed(state)) slide();
      }
    }
    // «Закрыть итог» holds until the incident or the run changes; any other situation brings the panel back.
    const closed = mode === 'done' && closedKey !== null && closedKey === resultKey(state);
    if (!closed && mode !== 'done') closedKey = null;
    if (root.hidden !== closed) root.hidden = closed;
    setAttrs(root, {'data-panel-mode': mode || 'none'});
    if (!mode) return;
    const {snapshot} = state;
    pause.hidden = !(mode === 'decision' && snapshot && snapshot.runState === 'paused' && snapshot.pauseReason === 'decision');
    const words = views[mode].render(state) || {};
    setText(title, words.title || P.title[mode]);
    setText(subtitle, words.subtitle || '');
    subtitle.hidden = !words.subtitle;
  }

  store.watch((state) => [state.model, state.snapshot, state.pending, state.commandsBlocked, state.blockReason], render);
}
