// The top bar: one calm line of key figures. The mark and the permanent
// notice; model time and run; the people counters the model published, under
// one caption «Люди»; the link to the platform with the age of the data; the
// stand button with the chalk tags of the active conditions. Nothing here is
// counted by the page. A counter whose published value changed crossfades
// from the old number to the new one (200 ms) and keeps a fading underline
// for a second (motion.js); never an intermediate number, never on load.

import {h, reconcile, s, setAttrs, setGlyph, setText} from '../dom.js';
import {showsOldData} from '../link.js';
import {labelOf} from '../model.js';
import {EASE, MS, motionAllowed, play} from '../motion.js';

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
  const set = (caption, main, rest = '', last = '', title = '') => {
    setText(cap, caption);
    setText(value, main);
    setText(sep, rest ? ' · ' : '');
    setText(sub, rest);
    setText(sep2, rest && last ? ' · ' : '');
    setText(state, last);
    setAttrs(node, {title: title || [caption, main, rest, last].filter(Boolean).join(' ')});
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
  const runFigure = figure('figure--run', 'status-run');
  const time = h('div', {class: 'topbar__cluster topbar__time'}, oldTag, ' ', modelTime.node, ' ', runFigure.node);

  // ---- people ------------------------------------------------------------------
  const people = PEOPLE.map(([id, field, caption, sign]) => {
    const value = h('b', {class: 'figure__value', 'data-testid': `incident-${id}`});
    // The value and what its change leaves for a moment: the old number fading out over it, an underline.
    const mark = h('span', {class: 'figure__mark', 'aria-hidden': 'true'});
    const slot = h('span', {class: 'figure__slot'}, value, mark);
    const node = h('span', {class: 'figure figure--people', 'data-figure': id},
      h('span', {class: 'figure__cap', text: UI.incident[caption]}), ' ', slot, sign ? peopleSign(sign) : null);
    return {field, sign, value, slot, mark, node};
  });
  const peopleGroup = h('div', {
    class: 'topbar__cluster topbar__people', role: 'group', 'aria-label': UI.incident.peopleTitle, title: UI.incident.peopleTitle,
  }, h('span', {class: 'topbar__people-cap', text: UI.incident.people}), ' ',
  h('span', {class: 'topbar__people-row'},
    people.slice(0, 2).map((item) => [item.node, ' ']), h('span', {class: 'topbar__rule', 'aria-hidden': 'true'}),
    people.slice(2).map((item) => [' ', item.node])));

  /** A new published value: the old number crossfades into the new one and an underline fades out. Never on the first value. */
  function changed(item, before) {
    const ghost = h('span', {class: 'figure__ghost', 'aria-hidden': 'true', text: before});
    item.slot.append(ghost);
    const out = play(ghost, [{opacity: 1}, {opacity: 0}], {duration: MS.digits, easing: EASE});
    if (!out) {
      ghost.remove();
      return;
    }
    out.finished.then(() => ghost.remove(), () => ghost.remove());
    play(item.value, [{opacity: 0}, {opacity: 1}], {duration: MS.digits, easing: EASE});
    play(item.mark, [{opacity: 1}, {opacity: 0}], {duration: MS.underline, easing: 'ease-out'});
  }
  let shownRun = null;

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
    // Motion only for a change within one run of a current snapshot: not the first value, not a new run, not old data.
    const run = snapshot && model && model.hasSnapshot ? snapshot.run : null;
    const animate = run !== null && run === shownRun && motionAllowed(store.getState());
    shownRun = run;
    for (const item of people) {
      const value = values[item.field];
      const published = typeof value === 'number';
      const before = item.value.textContent;
      const words = published ? text.num(value) : text.DASH;
      setText(item.value, words);
      if (animate && published && before !== words && before !== '' && before !== text.DASH) changed(item, before);
      setAttrs(item.node, {
        class: ['figure', 'figure--people', item.sign && published && value > 0 && `is-alert is-alert--${item.sign}`],
        'data-value': published ? value : null,
      });
    }
    if (!snapshot || !model) {
      modelTime.set(`${UI.status.model}:`, UI.status.noData);
      runFigure.set(`${UI.status.run}:`, UI.status.noData);
      reconcile(conditionsList, [], () => '', () => null);
      setText(conditionsNone, UI.status.noData);
      standCount.hidden = true;
      return;
    }
    const pause = snapshot.pauseReason !== 'none' && text.isKnown('pauseReason', snapshot.pauseReason)
      ? ` ${text.VOCAB.pauseReason[snapshot.pauseReason]}` : '';
    // The tick and the seed are for the curious: in the titles, not in the line.
    modelTime.set(UI.status.model, text.modelTime(snapshot.simTimeS), UI.status.speed(values.speedup),
      `${text.label('runState', snapshot.runState)}${pause}`, UI.status.timeTitle(snapshot.tick));
    setAttrs(modelTime.node, {'data-run-state': snapshot.runState});
    runFigure.set(UI.status.run, snapshot.run, '', '', UI.status.runTitle(snapshot.run, text.num(values.seed)));
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
