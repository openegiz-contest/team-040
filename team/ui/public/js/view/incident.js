// The incident strip: always present, with the three counters of the model
// and the total. The numbers are the published ones; nothing is counted here.

import {h, setAttrs, setGlyph, setText} from '../dom.js';
import {causesOf, incidentOf, labelOf} from '../model.js';

const STATE_GLYPH = {none: 'ok', active: 'attention', executing: 'attention', done: 'info'};

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

export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;

  const glyphHolder = h('span', {class: 'incident__glyph'});
  const title = h('span', {class: 'incident__title'});
  const counter = (testId, caption) => {
    const value = h('b', {class: 'counter__value mono', 'data-testid': testId});
    return {value, node: h('span', {class: 'counter'}, h('span', {class: 'counter__label', text: `${caption}:`}), ' ', value)};
  };
  const inDanger = counter('incident-in-danger', UI.incident.inDanger);
  const noRoute = counter('incident-no-route', UI.incident.noRoute);
  const unknown = counter('incident-unknown', UI.incident.unknown);
  const out = counter('incident-out', UI.incident.out);
  const total = counter('incident-total', UI.incident.total);
  const strip = h('div', {class: 'incident__strip', 'data-testid': 'incident-strip'},
    h('span', {class: 'incident__head'}, glyphHolder, title),
    ' ', inDanger.node, ' ', noRoute.node, ' ', unknown.node, ' ', out.node, ' ', total.node, ' ',
    h('span', {class: 'incident__note muted', text: UI.incident.overlap}));
  root.setAttribute('aria-label', UI.incident.region);
  root.append(strip);

  const show = (item, value, alerting) => {
    const published = typeof value === 'number';
    setText(item.value, published ? text.num(value) : text.DASH);
    item.node.classList.toggle('is-alert', alerting && published && value > 0);
  };

  store.watch((state) => state.model, (model) => {
    const {state, title: words} = incidentTitle(text, model);
    setAttrs(strip, {'data-incident-state': state});
    setGlyph(glyphHolder, STATE_GLYPH[state] || 'unknown');
    setText(title, words);
    const values = model && model.shift ? model.shift.values : {};
    show(inDanger, values.workers_in_danger, true);
    show(noRoute, values.workers_no_route, true);
    show(unknown, values.workers_unknown, true);
    show(out, values.workers_out, false);
    show(total, values.workers_total, false);
  });
}
