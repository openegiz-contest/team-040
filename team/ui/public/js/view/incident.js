// The situation strip: an open incident as the sequence the dispatcher needs.
//   1 Что изменилось — the incident and its causes, with the tick
//   2 Где люди       — codes of the workers of the zone, without a route, in danger
//   3 Какие пути     — longer routes, missing routes, exits that are not available
//   4 Варианты       — the options of the model; opens the decision dock
// Counts are the published counters (top bar); lists of codes are read from the
// published fields of each worker and say so. Nothing is computed here. Every
// «показать» asks the stage to show the object; when the stage cannot, the
// object is selected instead.

import {h, setAttrs, setGlyph, setText} from '../dom.js';
import {causesOf, incidentOf, isUnderground, labelOf, thingByName, thingsOfKind, workersInZone} from '../model.js';

const STATE_GLYPH = {none: 'ok', active: 'attention', executing: 'clock', done: 'info'};
const OPEN = new Set(['active', 'executing', 'done']);
const LIST_LIMIT = 4;

function incidentTitle(text, model) {
  const incident = model ? incidentOf(model) : null;
  if (!model || !model.hasSnapshot || !incident) return {state: null, title: text.UI.status.noData};
  const {values} = incident;
  const state = typeof values.state === 'string' ? values.state : null;
  if (state === 'none') return {state, title: text.VOCAB.incidentState.none};
  const name = (local) => labelOf(model, local);
  let title = text.label('incidentState', state);
  if (typeof values.zone === 'string') title += `: ${name(values.zone)}`;
  const listed = causesOf(values);
  const causes = listed.length > 0 ? listed : (values.trigger ? [{trigger: values.trigger}] : []);
  const reasons = causes.map((cause) => {
    const trigger = text.label('incidentTrigger', cause.trigger);
    return typeof cause.subject === 'string' ? `${trigger} (${name(cause.subject)})` : trigger;
  });
  if (reasons.length > 0) title += ` — ${reasons.join('; ')}`;
  return {state, title};
}

/** "Р-03, Р-04, Р-05, Р-06 и ещё 2" */
function codes(things, limit = LIST_LIMIT) {
  const shown = things.slice(0, limit).map((thing) => thing.label);
  return things.length > limit ? `${shown.join(', ')} +${things.length - limit}` : shown.join(', ');
}

/**
 * The words of the four steps and what each «показать» points at.
 * @returns {Array<{body: string, meta: string, target: (string|null)}>}
 */
function steps(text, model, snapshot) {
  const {UI} = text;
  const S = UI.situation;
  const incident = incidentOf(model);
  const values = incident.values;
  const zone = thingByName(model, values.zone);
  const causes = causesOf(values);
  const subject = causes.map((cause) => thingByName(model, cause.subject)).find(Boolean) || null;
  const ticks = causes.map((cause) => cause.tick).filter((tick) => typeof tick === 'number');
  const opened = typeof values.opened_at_tick === 'number' ? values.opened_at_tick : (ticks.length > 0 ? Math.min(...ticks) : null);

  const workers = thingsOfKind(model, 'worker').filter(isUnderground);
  const noRoute = workers.filter((worker) => worker.values.egress_status === 'none');
  const unknown = workers.filter((worker) => worker.values.egress_status === 'unknown' || worker.values.status === 'unknown');
  const inDanger = workers.filter((worker) => worker.values.location_hazard === 'danger');

  // 2. Where the people are.
  const people = [];
  if (zone) {
    const here = workersInZone(model, zone.name);
    people.push(here.length > 0 ? S.inZone(zone.label, codes(here)) : S.nobodyInZone(zone.label));
  }
  if (inDanger.length > 0) people.push(S.inDanger(codes(inDanger)));
  if (noRoute.length > 0) people.push(S.noRoute(codes(noRoute)));
  if (unknown.length > 0) people.push(S.unknown(codes(unknown)));

  // 3. Which paths.
  const longer = workers.filter((worker) => worker.values.egress_status === 'ok'
    && typeof worker.values.egress_detour_m === 'number' && worker.values.egress_detour_m > 0);
  const paths = [];
  if (longer.length > 0) {
    const items = longer.slice(0, LIST_LIMIT).map((worker) => S.plus(worker.label, text.quantity(worker.values.egress_detour_m, 'm')));
    paths.push(S.longer(longer.length > LIST_LIMIT ? `${items.join(', ')} +${longer.length - LIST_LIMIT}` : items.join(', ')));
  }
  if (noRoute.length > 0) paths.push(S.noRoute(codes(noRoute)));
  if (paths.length === 0) paths.push(S.routesUnchanged);
  const exits = thingsOfKind(model, 'exit');
  const notAvailable = exits.filter((exit) => exit.values.state !== 'available');
  if (exits.length > 0) {
    paths.push(notAvailable.length === 0 ? S.exitsAvailable
      : S.exitsNot(notAvailable.map((exit) => `${exit.label} — ${text.label('exitState', exit.values.state)}`).join(', ')));
  }

  // 4. The options the model published.
  const options = thingsOfKind(model, 'option').filter((option) => option.hasState && option.values.state !== 'inactive');
  const optionWords = [options.length > 0 ? S.options(options.length) : S.noOptions];
  if (snapshot.runState === 'paused' && snapshot.pauseReason === 'decision') optionWords.push(S.paused);
  else if (values.state === 'executing') optionWords.push(S.executing);
  else if (values.state === 'done') optionWords.push(S.done);

  const focusZone = zone ? zone.thingId : null;
  return [
    {body: '', meta: opened === null ? '' : S.atTick(opened), target: subject ? subject.thingId : focusZone},
    {body: people.join(' · '), meta: '', target: focusZone},
    {body: paths.join(' · '), meta: '', target: focusZone},
    {body: optionWords.join(' · '), meta: '', target: null},
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

  function openOptions() {
    shell.set({dock: 'open'});
    const dock = ctx.roots.dock;
    if (dock && typeof dock.scrollIntoView === 'function') dock.scrollIntoView({block: 'nearest'});
    const handle = dock ? dock.querySelector('[data-testid="dock-toggle"]') : null;
    if (handle) handle.focus();
  }

  const glyphHolder = h('span', {class: 'incident__glyph'});
  const title = h('span', {class: 'incident__title'});
  const items = S.steps.map((label, index) => {
    const number = index + 1;
    const body = h('span', {class: 'step__body'});
    const meta = h('span', {class: 'step__meta mono'});
    // «показать маршруты»: the second word folds away in the compact layout, where the words of the step need the room.
    const action = number === 3
      ? h('button', {class: 'btn btn--link step__show', type: 'button', 'data-testid': `situation-show-${number}`, 'aria-label': S.showRoutes},
        S.show, h('span', {class: 'step__show-more', text: ` ${S.showRoutesWord}`}))
      : h('button', {class: 'btn btn--link step__show', type: 'button', 'data-testid': `situation-show-${number}`,
        text: number === 4 ? S.openOptions : S.show});
    const head = h('span', {class: 'step__head'}, h('span', {class: 'step__num mono', text: String(number)}), ' ',
      h('span', {class: 'step__label', text: label}), number === 2 ? h('span', {class: 'step__note', text: ` · ${S.fromWorkers}`}) : null);
    const content = number === 1
      ? h('span', {class: 'step__body step__body--title'}, glyphHolder, title, ' ', meta)
      : body;
    const node = h('div', {class: `step step--${number}`, 'data-testid': `situation-step-${number}`, 'data-step': number},
      head, ' ', content, ' ', action);
    let target = null;
    action.addEventListener('click', () => (number === 4 ? openOptions() : show(target)));
    return {node, body, meta, action, setTarget: (value) => { target = value; }};
  });
  const strip = h('div', {class: 'incident__strip', 'data-testid': 'incident-strip'},
    items.map((item, index) => [index > 0 ? h('span', {class: 'step__arrow', 'aria-hidden': 'true'}) : null, item.node, ' ']));
  root.setAttribute('aria-label', S.region);
  root.setAttribute('role', 'region');
  root.append(strip);

  store.watch((state) => [state.model, state.snapshot], () => {
    const {model, snapshot} = store.getState();
    const {state, title: words} = incidentTitle(text, model);
    const open = OPEN.has(state) && snapshot;
    setAttrs(strip, {'data-incident-state': state, 'data-open': open ? 'true' : null});
    setGlyph(glyphHolder, STATE_GLYPH[state] || 'unknown');
    setText(title, words);
    if (!open) {
      for (const item of items) {
        setText(item.body, '');
        setText(item.meta, '');
        item.setTarget(null);
      }
      return;
    }
    steps(text, model, snapshot).forEach((step, index) => {
      const item = items[index];
      setText(item.body, step.body);
      setAttrs(item.body, {title: step.body || null});
      setText(item.meta, step.meta);
      item.setTarget(step.target);
      item.action.hidden = index < 3 && !step.target;
    });
    setAttrs(title, {title: words});
  });
}
