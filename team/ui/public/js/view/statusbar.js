// The top bar of «Пульт смены»: one calm line. The mark, «Пульт смены» and the
// permanent synthetic-data notice; the shift clock of the model and what the
// model is doing («модель на паузе для выбора действия»); the link to the
// platform with the age of the data; the chalk tags of the active stand
// conditions, the «Стенд» button and the slot of the menu (view/tabs.js fills
// ctx.roots.menuSlot). The people counters live in the rail (view/people.js).
// Nothing here is counted by the page.

import {h, reconcile, s, setAttrs, setGlyph, setText} from '../dom.js';
import {showsOldData} from '../link.js';
import {labelOf} from '../model.js';

const LINK_GLYPH = {ok: 'ok', degraded: 'attention', stale: 'clock', unavailable: 'danger'};

/** The mark: three slabs of a cutaway, stacked and spread apart, with the shaft through them. */
function mark() {
  const slab = (y) => s('path', {d: `M4 ${y}l10 -5 10 5 -10 5z`, class: 'mark__slab'});
  return s('svg', {class: 'mark', viewBox: '0 0 28 28', width: 28, height: 28, 'aria-hidden': 'true', focusable: 'false'},
    slab(7), slab(14), slab(21), s('path', {d: 'M14 2v24', class: 'mark__shaft'}));
}

export function mount(root, ctx) {
  const {store, text, shell} = ctx;
  const {UI} = text;
  const T = UI.top;

  // ---- mark and notice ------------------------------------------------------
  const notice = h('strong', {class: 'notice', 'data-testid': 'status-notice'},
    h('span', {text: text.NOTICE_PARTS[0]}), ' ', h('span', {text: text.NOTICE_PARTS[1]}));
  const brand = h('div', {class: 'top__brand'}, mark(), h('span', {class: 'top__name', text: T.brand}), notice);

  // ---- the shift clock -------------------------------------------------------
  const oldTag = h('span', {class: 'old-tag', hidden: true, text: UI.status.oldTag});
  const clock = h('b', {class: 'top__clock'});
  const runState = h('span', {class: 'top__state'});
  const run = h('span', {class: 'top__run mono', 'data-testid': 'status-run'});
  const time = h('div', {class: 'top__time', 'data-testid': 'status-model-time'},
    h('span', {class: 'top__cap', text: T.shift}), ' ', clock, ' ', h('span', {class: 'top__dot', 'aria-hidden': 'true', text: '·'}), ' ', runState);
  const timeBox = h('div', {class: 'top__cluster top__cluster--time'}, oldTag, time, run);

  // ---- link --------------------------------------------------------------------
  const linkGlyph = h('span', {class: 'status__glyph'});
  const linkWho = h('span', {class: 'status__who', text: `${UI.status.platform}:`});
  const linkText = h('span', {class: 'status__words'});
  const link = h('span', {class: 'status status--link', 'data-testid': 'status-link'}, linkGlyph, linkWho, ' ', linkText);
  const age = h('span', {class: 'status status--age', 'data-testid': 'status-age'});
  const publications = h('span', {class: 'status status--publications', 'data-testid': 'status-publications'});
  const commandsGlyph = h('span', {class: 'status__glyph'});
  const commandsReason = h('span', {class: 'status__reason'});
  const commands = h('span', {class: 'status status--commands', 'data-testid': 'status-commands', hidden: true},
    commandsGlyph, h('span', {text: UI.status.commandsBlocked}), commandsReason);
  setGlyph(commandsGlyph, 'blocked');
  const linkBox = h('div', {class: 'top__cluster top__cluster--link'}, link, ' ', age, ' ', publications, ' ', commands);

  // ---- stand: chalk tags of the active conditions and the drawer button; the menu slot -------
  const conditionsList = h('span', {class: 'chips'});
  const conditionsNone = h('span', {class: 'visually-hidden'});
  const conditions = h('span', {class: 'status status--conditions', 'data-testid': 'status-conditions'},
    h('span', {class: 'visually-hidden', text: `${UI.status.conditions}:`}), ' ', conditionsList, conditionsNone);
  const standCount = h('span', {class: 'stand-toggle__count mono', hidden: true});
  const standToggle = h('button', {
    class: 'btn btn--stand stand-toggle', type: 'button', 'data-testid': 'stand-toggle',
    'aria-controls': 'stand-drawer', 'aria-expanded': 'false',
  }, h('span', {text: UI.stand.toggle}), standCount);
  standToggle.addEventListener('click', () => shell.set({stand: shell.get().stand === 'open' ? 'closed' : 'open'}));
  const menuSlot = h('div', {class: 'top__menu'});
  ctx.roots.menuSlot = menuSlot;
  const tools = h('div', {class: 'top__cluster top__cluster--tools'}, conditions, ' ', standToggle, ' ', menuSlot);

  root.setAttribute('aria-label', UI.status.region);
  root.append(brand, ' ', timeBox, ' ', linkBox, ' ', tools);

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
    setAttrs(time, {'data-tick': snapshot && model ? snapshot.tick : null});
    const values = model && model.shift ? model.shift.values : {};
    if (!snapshot || !model) {
      setText(clock, text.DASH);
      setText(runState, UI.status.noData);
      setText(run, '');
      setAttrs(time, {'data-run-state': null, title: null});
      reconcile(conditionsList, [], () => '', () => null);
      setText(conditionsNone, UI.status.noData);
      standCount.hidden = true;
      return;
    }
    const pause = snapshot.pauseReason !== 'none' && text.isKnown('pauseReason', snapshot.pauseReason)
      ? ` ${text.VOCAB.pauseReason[snapshot.pauseReason]}` : '';
    const running = snapshot.runState === 'running' && typeof values.speedup === 'number' ? ` ${UI.status.speed(values.speedup)}` : '';
    setText(clock, text.modelTime(snapshot.simTimeS));
    setText(runState, `${text.label('runState', snapshot.runState)}${pause}${running}`);
    // The tick and the seed are for the curious: in the titles, not in the line.
    setAttrs(time, {'data-run-state': snapshot.runState, title: UI.status.timeTitle(snapshot.tick)});
    setText(run, T.run(snapshot.run));
    setAttrs(run, {title: UI.status.runTitle(snapshot.run, text.num(values.seed))});
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
