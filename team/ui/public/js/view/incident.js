// The situation strip: an open incident as the sequence the dispatcher needs.
//   1 Что изменилось — the zone and what happened to it, the other causes, the moment by the model clock
//   2 Где люди       — the published count of people in danger with their codes
//   3 Какие пути     — who has no computed route (and whether any option brings them out), longer routes
//   4 Варианты       — how many options the model offers; opens the decision dock
// Counts are the published counters (top bar); lists of codes are read from the
// published fields of each worker, and the title of a step says so. Nothing is
// computed here. Step 1 «показать» selects the incident's zone (the card and
// «Действия диспетчера» follow) and asks the stage to frame it; the other
// «показать» ask the stage to show their object, or select it when it cannot.
// The strip unfolds once (180 ms) when an incident opens while the page is
// watching; never on load, never with old data, never under reduced motion.

import {h, setAttrs, setGlyph, setText} from '../dom.js';
import {causesOf, incidentOf, isUnderground, labelOf, thingByName, thingsOfKind, workersInZone} from '../model.js';
import {EASE_OUT, MS, motionAllowed, play} from '../motion.js';

const STATE_GLYPH = {none: 'ok', active: 'attention', executing: 'clock', done: 'info'};
const OPEN = new Set(['active', 'executing', 'done']);
const LIST_LIMIT = 4;

/** The state of the incident and its sentence for a title: «Инцидент: Участок Г — опасность на участке; …». */
function incidentTitle(text, model) {
  const incident = model ? incidentOf(model) : null;
  if (!model || !model.hasSnapshot || !incident) return {state: null, title: text.UI.status.noData};
  const {values} = incident;
  const state = typeof values.state === 'string' ? values.state : null;
  if (state === 'none') return {state, title: text.VOCAB.incidentState.none};
  const name = (local) => labelOf(model, local);
  let title = text.label('incidentState', state);
  if (typeof values.zone === 'string') title += `: ${name(values.zone)}`;
  const reasons = causesFor(values).map((cause) => {
    const trigger = text.label('incidentTrigger', cause.trigger);
    const at = typeof cause.tick === 'number' ? `, ${text.tickWords(cause.tick)}` : '';
    return typeof cause.subject === 'string' ? `${trigger} (${name(cause.subject)})${at}` : `${trigger}${at}`;
  });
  if (reasons.length > 0) title += ` — ${reasons.join('; ')}`;
  return {state, title};
}

/** Every cause when the model lists them, else the trigger of the incident. */
function causesFor(values) {
  const listed = causesOf(values);
  if (listed.length > 0) return listed;
  return values.trigger ? [{trigger: values.trigger, subject: values.zone, tick: values.opened_at_tick}] : [];
}

/** "Р-03, Р-04, Р-05, Р-06 +2" */
function codes(things, limit = LIST_LIMIT) {
  const shown = things.slice(0, limit).map((thing) => thing.label);
  return things.length > limit ? `${shown.join(', ')} +${things.length - limit}` : shown.join(', ');
}

/**
 * The words of the four steps (two lines each), their titles and what each «показать» points at.
 * @returns {Array<{lines: string[], meta: string, title: string, target: (string|null)}>}
 */
function steps(text, model, snapshot) {
  const {UI} = text;
  const S = UI.situation;
  const incident = incidentOf(model);
  const values = incident.values;
  const shift = model.shift ? model.shift.values : {};
  const zone = thingByName(model, values.zone);
  const name = (local) => labelOf(model, local);
  const causes = causesFor(values);
  const ticks = causes.map((cause) => cause.tick).filter((tick) => typeof tick === 'number');
  const opened = typeof values.opened_at_tick === 'number' ? values.opened_at_tick : (ticks.length > 0 ? Math.min(...ticks) : null);
  const options = thingsOfKind(model, 'option');
  const optionName = (option) => text.codeLabel('optionKind', option.attrs.option_kind);

  // 1. What changed: «Участок Г — опасно», then «+ потеряны данные Э-05». A hazard is said by the
  // published state of its zone (or working); a subject that is the zone itself is not repeated.
  const causeWords = (cause) => {
    const own = typeof cause.subject === 'string' && cause.subject !== values.zone ? name(cause.subject) : '';
    if (cause.trigger === 'hazard') {
      const where = thingByName(model, cause.subject) || zone;
      const words = where && where.hazard ? text.hazardText(where.hazard) : text.label('incidentTrigger', cause.trigger);
      return own ? `${own}: ${words}` : words;
    }
    const words = text.isKnown('incidentTrigger', cause.trigger) && S.cause[cause.trigger]
      ? S.cause[cause.trigger] : text.label('incidentTrigger', cause.trigger);
    return own ? `${words} ${own}` : words;
  };
  const first = causes.length > 0 ? causeWords(causes[0]) : text.label('incidentState', values.state);
  const what = [S.head(zone ? zone.label : '', first)];
  const running = options.find((option) => option.values.state === 'executing');
  const finished = options.filter((option) => option.values.state === 'done');
  if (values.state === 'executing') {
    what.push(S.executingOption(running ? optionName(running) : S.executing));
  } else if (values.state === 'done') {
    what.push([text.VOCAB.incidentState.done, finished.length > 0 ? S.doneOption(optionName(finished[0])) : '']
      .filter(Boolean).join(' · '));
  } else if (causes.length > 1) {
    what.push(causes.slice(1).map((cause) => S.more(causeWords(cause))).join(' '));
  }

  // 2. Where the people are: the published count of people in danger, with the codes of the workers whose
  // own fields say so; else the people of the zone. The people of zones of unknown state on the second line.
  const workers = thingsOfKind(model, 'worker').filter(isUnderground);
  const inDanger = workers.filter((worker) => worker.values.location_hazard === 'danger');
  // The people of the zones whose state is unknown, as the zones and the workers published it (a working without
  // sensors outside the zones is not a zone of unknown state).
  const unknown = thingsOfKind(model, 'zone').filter((item) => item.hasState && item.hazard.state === 'unknown')
    .flatMap((item) => workersInZone(model, item.name));
  const people = [];
  if (typeof shift.workers_in_danger === 'number' && shift.workers_in_danger > 0) {
    people.push(S.inDanger(shift.workers_in_danger, codes(inDanger)));
  } else if (zone) {
    const here = workersInZone(model, zone.name);
    people.push(here.length > 0 ? S.inZone(zone.label, codes(here)) : S.nobodyInZone(zone.label));
  }
  if (typeof shift.workers_unknown === 'number' && shift.workers_unknown > 0) {
    people.push(S.unknownPeople(shift.workers_unknown, codes(unknown)));
  }

  // 3. Which paths: who has no computed route, and whether an option of the model brings them out;
  // otherwise whether the people of step 2 have a route; longer routes and exits on the second line.
  const noRoute = workers.filter((worker) => worker.values.egress_status === 'none');
  const forecasts = options.filter((option) => typeof option.values.forecast_no_route === 'number');
  const paths = [];
  if (noRoute.length > 0) {
    const nobody = forecasts.length > 0 && forecasts.every((option) => option.values.forecast_no_route > 0);
    paths.push(nobody ? `${S.noRoute(codes(noRoute))} · ${S.nobodyLeads}` : S.noRoute(codes(noRoute)));
  } else {
    const concerned = inDanger.length > 0 ? inDanger : (zone ? workersInZone(model, zone.name) : []);
    const notComputed = concerned.filter((worker) => worker.values.egress_status !== 'ok');
    if (notComputed.length > 0) paths.push(S.unknown(codes(notComputed)));
    else if (concerned.length > 0) paths.push(S.hasRoute(codes(concerned)));
  }
  const second = [];
  const longer = workers.filter((worker) => worker.values.egress_status === 'ok'
    && typeof worker.values.egress_detour_m === 'number' && worker.values.egress_detour_m > 0);
  if (longer.length > 0) {
    const items = longer.slice(0, LIST_LIMIT).map((worker) => S.plus(worker.label, text.quantity(worker.values.egress_detour_m, 'm')));
    second.push(S.longer(longer.length > LIST_LIMIT ? `${items.join(', ')} +${longer.length - LIST_LIMIT}` : items.join(', ')));
  }
  const exits = thingsOfKind(model, 'exit');
  const notAvailable = exits.filter((exit) => exit.values.state !== 'available');
  if (notAvailable.length > 0) {
    second.push(S.exitsNot(notAvailable.map((exit) => `${exit.label} — ${text.label('exitState', exit.values.state)}`).join(', ')));
  }
  if (paths.length === 0) paths.push(longer.length > 0 ? second.shift() : S.routesUnchanged);
  if (second.length > 0) paths.push(second.join(' · '));
  if (paths.length === 1 && exits.length > 0 && notAvailable.length === 0) paths.push(S.exitsAvailable);

  // 4. The options the model published.
  const offered = options.filter((option) => option.hasState && option.values.state !== 'inactive');
  const optionWords = [offered.length > 0 ? S.options(offered.length) : S.noOptions];
  if (snapshot.runState === 'paused' && snapshot.pauseReason === 'decision') optionWords.push(S.paused);
  else if (values.state === 'executing') optionWords.push(S.executing);
  else if (values.state === 'done') optionWords.push(S.done);

  const focusZone = zone ? zone.thingId : null;
  const at = text.tickSeconds(opened);
  return [
    {lines: what, meta: at === null ? '' : text.UI.decision.at(text.modelTime(at)),
      title: incidentTitle(text, model).title, target: focusZone},
    {lines: people, meta: '', title: `${people.join('. ')}. ${S.honesty}`, target: focusZone},
    {lines: paths, meta: '', title: `${paths.join('. ')}. ${S.honesty}`, target: focusZone},
    {lines: [optionWords.join(' · ')], meta: '', title: optionWords.join(' · '), target: null},
  ];
}

export function mount(root, ctx) {
  const {store, text, shell} = ctx;
  const {UI} = text;
  const S = UI.situation;

  /** Show an object on the stage; when the stage cannot, select it (the scheme and the card show it). */
  function show(target) {
    if (!target) return;
    if (!ctx.stage.focus(target)) ctx.select(target);
  }

  /** Step 1: the incident's zone becomes the selection (card, actions), and the stage frames it. */
  function showIncident(target) {
    if (!target) return;
    ctx.select(target);
    ctx.stage.focus(target);
  }

  function openOptions() {
    shell.set({dock: 'open'});
    const dock = ctx.roots.dock;
    if (dock && typeof dock.scrollIntoView === 'function') dock.scrollIntoView({block: 'nearest'});
    const handle = dock ? dock.querySelector('[data-testid="dock-toggle"]') : null;
    if (handle) handle.focus();
  }

  const glyphHolder = h('span', {class: 'incident__glyph'});
  // The state of the incident when no incident is open («Инцидентов нет»); the open one is said by its steps.
  const title = h('span', {class: 'incident__title'});
  const items = S.steps.map((label, index) => {
    const number = index + 1;
    const lines = [h('span', {class: 'step__line'}), h('span', {class: 'step__line step__line--more'})];
    const meta = h('span', {class: 'step__meta mono'});
    const body = number === 1
      ? h('span', {class: 'step__body step__body--title'}, glyphHolder, h('span', {class: 'step__lines'}, title, lines[0], lines[1]), ' ', meta)
      : h('span', {class: 'step__body'}, h('span', {class: 'step__lines'}, lines[0], lines[1]));
    // «показать маршруты»: the second word folds away in the compact layout, where the words of the step need the room.
    const action = number === 3
      ? h('button', {class: 'btn btn--link step__show', type: 'button', 'data-testid': `situation-show-${number}`, 'aria-label': S.showRoutes},
        S.show, h('span', {class: 'step__show-more', text: ` ${S.showRoutesWord}`}))
      : h('button', {class: 'btn btn--link step__show', type: 'button', 'data-testid': `situation-show-${number}`,
        text: number === 4 ? S.openOptions : S.show});
    const head = h('span', {class: 'step__head'}, h('span', {class: 'step__num mono', text: String(number)}), ' ',
      h('span', {class: 'step__label', text: label}));
    const node = h('div', {class: `step step--${number}`, 'data-testid': `situation-step-${number}`, 'data-step': number},
      head, ' ', body, ' ', action);
    let target = null;
    action.addEventListener('click', () => {
      if (number === 4) openOptions();
      else if (number === 1) showIncident(target);
      else show(target);
    });
    return {node, body, lines, meta, action, setTarget: (value) => { target = value; }};
  });
  const strip = h('div', {class: 'incident__strip', 'data-testid': 'incident-strip'},
    items.map((item, index) => [index > 0 ? h('span', {class: 'step__arrow', 'aria-hidden': 'true'}) : null, item.node, ' ']));
  root.setAttribute('aria-label', S.region);
  root.setAttribute('role', 'region');
  root.append(strip);

  // The strip unfolds when an incident opens while the page watches (not when the page opens on one).
  const situation = ctx.roots.situation;
  let wasOpen = null;
  function unfold() {
    if (!situation) return;
    const height = situation.getBoundingClientRect().height;
    if (height <= 0) return;
    document.body.setAttribute('data-strip-motion', 'running');
    const done = () => {
      document.body.removeAttribute('data-strip-motion');
      situation.dispatchEvent(new CustomEvent('situation-settled', {bubbles: true}));
    };
    const motion = play(situation, [{height: '0px', overflow: 'hidden'}, {height: `${height}px`, overflow: 'hidden'}],
      {duration: MS.strip, easing: EASE_OUT});
    if (motion) motion.finished.then(done, done);
    else done();
  }

  store.watch((state) => [state.model, state.snapshot], () => {
    const state = store.getState();
    const {model, snapshot} = state;
    const {state: incidentState, title: words} = incidentTitle(text, model);
    const open = Boolean(OPEN.has(incidentState) && snapshot);
    setAttrs(strip, {'data-incident-state': incidentState, 'data-open': open ? 'true' : null});
    setGlyph(glyphHolder, STATE_GLYPH[incidentState] || 'unknown');
    setText(title, open ? '' : words);
    title.hidden = open;
    if (!open) {
      for (const item of items) {
        for (const line of item.lines) setText(line, '');
        setText(item.meta, '');
        setAttrs(item.body, {title: null});
        item.setTarget(null);
      }
    } else {
      steps(text, model, snapshot).forEach((step, index) => {
        const item = items[index];
        item.lines.forEach((line, at) => {
          setText(line, step.lines[at] || '');
          line.hidden = !step.lines[at];
        });
        setAttrs(item.body, {title: step.title || null});
        setText(item.meta, step.meta);
        item.setTarget(step.target);
        item.action.hidden = index < 3 && !step.target;
      });
    }
    // Motion: from closed to open over a working link, after the first picture of the page.
    // Measured after every view of this update has drawn (the banners of the strip come later in the same round).
    if (open && wasOpen === false && motionAllowed(state)) Promise.resolve().then(unfold);
    if (snapshot) wasOpen = open;
  });
}
