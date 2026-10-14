// The top bar: one calm line of key figures. The mark and the permanent
// notice; model time and run; the people counters the model published; the
// link to the platform with the age of the data; the stand button with the
// chalk tags of the active conditions. Nothing here is counted by the page.

import {h, reconcile, s, setAttrs, setGlyph, setText} from '../dom.js';
import {showsOldData} from '../link.js';
import {labelOf} from '../model.js';

const LINK_GLYPH = {ok: 'ok', degraded: 'attention', stale: 'clock', unavailable: 'danger'};

/** The people counters: test id suffix, field of shift, caption key of UI.incident, the sign of a count above zero. */
const PEOPLE = [
  ['total', 'workers_total', 'total', null],
  ['out', 'workers_out', 'out', null],
  ['in-danger', 'workers_in_danger', 'inDanger', 'danger'],
  ['no-route', 'workers_no_route', 'noRoute', 'noroute'],
  ['unknown', 'workers_unknown', 'unknown', 'unknown'],
];

/** The mark: three slabs of a cutaway, stacked and spread apart, with the shaft through them. */
function mark() {
  const slab = (y) => s('path', {d: `M4 ${y}l10 -5 10 5 -10 5z`, class: 'mark__slab'});
  return s('svg', {class: 'mark', viewBox: '0 0 28 28', width: 28, height: 28, 'aria-hidden': 'true', focusable: 'false'},
    slab(7), slab(14), slab(21), s('path', {d: 'M14 2v24', class: 'mark__shaft'}));
}

/** The sign next to a people counter above zero: octagon (danger), crossed square (no route), dashed «?» (unknown). */
function peopleSign(kind) {
  const svg = (children) => s('svg', {class: `figure__sign figure__sign--${kind}`, viewBox: '0 0 16 16', width: 16, height: 16,
    'aria-hidden': 'true', focusable: 'false'}, children);
  if (kind === 'danger') return svg([s('path', {d: 'M5.2 1.5h5.6l3.7 3.7v5.6l-3.7 3.7H5.2l-3.7-3.7V5.2z'}), s('path', {d: 'M8 4.6v4.2M8 11v.5'})]);
  if (kind === 'noroute') return svg([s('rect', {x: 2, y: 2, width: 12, height: 12}), s('path', {d: 'M2 2l12 12M14 2L2 14'})]);
  return svg([s('circle', {cx: 8, cy: 8, r: 6.3, 'stroke-dasharray': '2.2 1.8'}),
    s('path', {d: 'M6 6.4a2 2 0 1 1 2.9 1.8c-.6.3-.9.7-.9 1.4M8 11.5v.5'})]);
}

/**
 * A figure: caption over a value, with an optional smaller part after the value. The text
 * nodes between the parts keep the figure readable as one line of plain text.
 */
function figure(className, testId) {
  const cap = h('span', {class: 'figure__cap'});
  const value = h('b', {class: 'figure__value'});
  const sep = h('span', {class: 'figure__sep'});
  const sub = h('span', {class: 'figure__sub'});
  const sep2 = h('span', {class: 'figure__sep'});
  const state = h('span', {class: 'figure__state'});
  const node = h('span', {class: `figure ${className}`, 'data-testid': testId}, cap, ' ', value, sep, sub, sep2, state);
  /** caption, main value, a secondary part, and a state that the compact layout keeps when it drops the secondary part */
  const set = (caption, main, rest = '', last = '') => {
    setText(cap, caption);
    setText(value, main);
    setText(sep, rest ? ' · ' : '');
    setText(sub, rest);
    setText(sep2, rest && last ? ' · ' : '');
    setText(state, last);
    setAttrs(node, {title: [caption, main, rest, last].filter(Boolean).join(' ')});
  };
  return {node, set};
}

export function mount(root, ctx) {
  const {store, text, shell} = ctx;
  const {UI} = text;

  // ---- mark and notice ------------------------------------------------------
  const notice = h('strong', {class: 'notice', 'data-testid': 'status-notice'},
    h('span', {text: text.NOTICE_PARTS[0]}), ' ', h('span', {text: text.NOTICE_PARTS[1]}));
  const brand = h('div', {class: 'topbar__brand'}, mark(),
    h('div', {class: 'brand'}, h('span', {class: 'brand__name', text: UI.status.brand}), ' ', notice));

  // ---- model time and run ----------------------------------------------------
  const oldTag = h('span', {class: 'old-tag', hidden: true, text: UI.status.oldTag});
  const modelTime = figure('figure--time', 'status-model-time');
  const run = figure('figure--run', 'status-run');
  const time = h('div', {class: 'topbar__cluster topbar__time'}, oldTag, ' ', modelTime.node, ' ', run.node);

  // ---- people ------------------------------------------------------------------
  const people = PEOPLE.map(([id, field, caption, sign]) => {
    const value = h('b', {class: 'figure__value', 'data-testid': `incident-${id}`});
    const node = h('span', {class: 'figure figure--people', 'data-figure': id},
      h('span', {class: 'figure__cap', text: UI.incident[caption]}), ' ', value, sign ? peopleSign(sign) : null);
    return {field, sign, value, node};
  });
  const peopleGroup = h('div', {
    class: 'topbar__cluster topbar__people', role: 'group', 'aria-label': UI.incident.peopleTitle, title: UI.incident.peopleTitle,
  }, people.slice(0, 2).map((item) => [item.node, ' ']), h('span', {class: 'topbar__rule', 'aria-hidden': 'true'}),
  people.slice(2).map((item) => [' ', item.node]));

  // ---- link --------------------------------------------------------------------
  const linkGlyph = h('span', {class: 'status__glyph'});
  const linkWho = h('span', {class: 'status__who', text: `${UI.status.platform}:`});
  const linkText = h('span');
  const link = h('span', {class: 'status status--link', 'data-testid': 'status-link'}, linkGlyph, linkWho, ' ', linkText);
  const age = h('span', {class: 'status status--age', 'data-testid': 'status-age'});
  const publications = h('span', {class: 'status status--publications', 'data-testid': 'status-publications'});
  const commandsGlyph = h('span', {class: 'status__glyph'});
  const commandsReason = h('span', {class: 'status__reason'});
  const commands = h('span', {class: 'status status--commands', 'data-testid': 'status-commands', hidden: true},
    commandsGlyph, h('span', {text: UI.status.commandsBlocked}), commandsReason);
  setGlyph(commandsGlyph, 'blocked');
  const linkBox = h('div', {class: 'topbar__cluster topbar__link'},
    h('div', {class: 'topbar__line'}, link, ' ', commands), ' ',
    h('div', {class: 'topbar__line topbar__line--sub'}, age, h('span', {class: 'topbar__dot', text: ' · '}), publications));

  // ---- stand: chalk tags of the active conditions and the drawer button --------------------
  const conditionsList = h('span', {class: 'chips'});
  const conditionsNone = h('span', {class: 'visually-hidden'});
  const conditions = h('span', {class: 'status status--conditions', 'data-testid': 'status-conditions'},
    h('span', {class: 'visually-hidden', text: `${UI.status.conditions}:`}), ' ', conditionsList, conditionsNone);
  const standCount = h('span', {class: 'stand-toggle__count mono', hidden: true});
  const chevron = s('svg', {class: 'stand-toggle__chevron', viewBox: '0 0 12 12', width: 12, height: 12, 'aria-hidden': 'true', focusable: 'false'},
    s('path', {d: 'M4.5 2.5L8 6l-3.5 3.5'}));
  const standToggle = h('button', {
    class: 'btn btn--stand stand-toggle', type: 'button', 'data-testid': 'stand-toggle',
    'aria-controls': 'stand-drawer', 'aria-expanded': 'false',
  }, chevron, h('span', {text: UI.stand.toggle}), standCount);
  standToggle.addEventListener('click', () => shell.set({stand: shell.get().stand === 'open' ? 'closed' : 'open'}));
  const stand = h('div', {class: 'topbar__cluster topbar__stand'}, conditions, ' ', standToggle);

  root.setAttribute('aria-label', UI.status.region);
  root.append(brand, ' ', time, ' ', peopleGroup, ' ', linkBox, ' ', stand);

  shell.watch((frame) => {
    const open = frame.stand === 'open';
    setAttrs(standToggle, {'aria-expanded': String(open), title: open ? UI.stand.closeTitle : UI.stand.openTitle});
  });

  store.watch((state) => [state.link, state.commandsBlocked, state.blockReason, state.boot], () => {
    const state = store.getState();
    const status = state.link;
    setAttrs(link, {'data-link': status.link});
    setGlyph(linkGlyph, LINK_GLYPH[status.link] || 'unknown');
    const cause = status.link === 'ok' ? '' : text.failureText(status.failure);
    setText(linkText, `${text.label('linkStatus', status.link)}${cause ? ` (${cause})` : ''}`);
    setText(age, text.ageText(status.dataAgeS));
    setAttrs(publications, {'data-publications': status.publications, text: text.label('publications', status.publications)});
    // Before the first data there is nothing to command: the mark appears only for a working screen.
    commands.hidden = !(state.commandsBlocked && state.boot === 'ready');
    setAttrs(commands, {'data-block-reason': state.blockReason});
    setText(commandsReason, state.blockReason ? `: ${text.label('blockReason', state.blockReason)}` : '');
    setAttrs(commands, {title: commands.hidden ? null : text.blockText(state.blockReason)});
    oldTag.hidden = !(showsOldData(status) && state.snapshot);
  });

  store.watch((state) => [state.snapshot, state.model], () => {
    const {snapshot, model} = store.getState();
    // The tick this view shows: a view that stopped following the state is told apart from the others.
    setAttrs(modelTime.node, {'data-tick': snapshot && model ? snapshot.tick : null});
    const values = model && model.shift ? model.shift.values : {};
    for (const item of people) {
      const value = values[item.field];
      const published = typeof value === 'number';
      setText(item.value, published ? text.num(value) : text.DASH);
      setAttrs(item.node, {class: ['figure', 'figure--people', item.sign && published && value > 0 && `is-alert is-alert--${item.sign}`]});
    }
    if (!snapshot || !model) {
      modelTime.set(`${UI.status.model}:`, UI.status.noData);
      run.set(`${UI.status.run}:`, UI.status.noData);
      reconcile(conditionsList, [], () => '', () => null);
      setText(conditionsNone, UI.status.noData);
      standCount.hidden = true;
      return;
    }
    const pause = snapshot.pauseReason !== 'none' && text.isKnown('pauseReason', snapshot.pauseReason)
      ? ` ${text.VOCAB.pauseReason[snapshot.pauseReason]}` : '';
    modelTime.set(UI.status.model, text.modelTime(snapshot.simTimeS),
      `${text.tickTime(null, snapshot.tick)} · ${UI.status.speed(values.speedup)}`, `${text.label('runState', snapshot.runState)}${pause}`);
    setAttrs(modelTime.node, {'data-run-state': snapshot.runState});
    run.set(UI.status.run, snapshot.run, `${UI.status.seed} ${text.num(values.seed)}`);
    reconcile(conditionsList, model.conditions, (condition) => condition.raw,
      () => h('span', {class: 'chip chip--stand'}),
      (chip, condition) => setAttrs(chip, {
        'data-condition': condition.raw,
        text: text.conditionText(condition, (name) => labelOf(model, name)),
      }));
    setText(conditionsNone, model.conditions.length === 0 ? UI.status.noConditions : '');
    standCount.hidden = model.conditions.length === 0;
    setText(standCount, text.num(model.conditions.length));
    setAttrs(standToggle, {'aria-label': `${UI.stand.toggle}: ${UI.stand.active(model.conditions.length)}`});
  });
}
