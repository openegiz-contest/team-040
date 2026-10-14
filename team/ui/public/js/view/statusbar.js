// The two upper rows of the top bar: the permanent notice, the link to the
// platform and the age of the data; model time, run and the stand conditions.

import {h, reconcile, setAttrs, setGlyph, setText} from '../dom.js';
import {showsOldData} from '../link.js';
import {labelOf} from '../model.js';

const LINK_GLYPH = {ok: 'ok', degraded: 'attention', stale: 'clock', unavailable: 'danger'};

export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;

  const notice = h('strong', {class: 'notice', 'data-testid': 'status-notice', text: text.NOTICE});

  const commandsGlyph = h('span', {class: 'status__glyph'});
  const commandsReason = h('span', {class: 'status__reason'});
  const commands = h('span', {class: 'status status--commands', 'data-testid': 'status-commands', hidden: true},
    commandsGlyph, h('span', {text: UI.status.commandsBlocked}), commandsReason);
  setGlyph(commandsGlyph, 'blocked');

  const publications = h('span', {class: 'status', 'data-testid': 'status-publications'});
  const linkGlyph = h('span', {class: 'status__glyph'});
  const linkText = h('span');
  const link = h('span', {class: 'status status--link', 'data-testid': 'status-link'}, linkGlyph, linkText);
  const age = h('span', {class: 'status status--age', 'data-testid': 'status-age'});

  const oldTag = h('span', {class: 'old-tag', hidden: true, text: UI.status.oldTag});
  const modelTime = h('span', {class: 'status status--model', 'data-testid': 'status-model-time'});
  const runInfo = h('span', {class: 'run-box__info', id: 'run-info', 'data-testid': 'status-run'});
  const runToggle = h('button', {
    class: 'btn btn--small run-box__toggle', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'run-info',
    text: UI.tabs.runBox,
  });
  const runBox = h('span', {class: 'run-box'}, runToggle, ' ', runInfo);
  runToggle.addEventListener('click', () => {
    const open = runToggle.getAttribute('aria-expanded') !== 'true';
    runToggle.setAttribute('aria-expanded', String(open));
    runBox.classList.toggle('is-open', open);
  });

  const conditionsLabel = h('span', {class: 'status__label', text: `${UI.status.conditions}:`});
  const conditionsList = h('span', {class: 'chips'});
  const conditionsNone = h('span', {class: 'muted'});
  const conditions = h('span', {class: 'status status--conditions', 'data-testid': 'status-conditions'},
    conditionsLabel, ' ', conditionsList, conditionsNone);

  root.setAttribute('aria-label', UI.status.region);
  root.append(
    // The spaces keep the text of a row readable as plain text: the gaps on the screen are CSS.
    h('div', {class: 'topbar__row topbar__row--notice'}, notice, ' ',
      h('div', {class: 'topbar__right'}, commands, ' ', publications, ' ', link, ' ', age)),
    h('div', {class: 'topbar__row topbar__row--model'}, oldTag, ' ', modelTime, ' ', runBox, ' ', conditions),
  );

  store.watch((state) => [state.link, state.commandsBlocked, state.blockReason], () => {
    const state = store.getState();
    const status = state.link;
    setAttrs(link, {'data-link': status.link});
    setGlyph(linkGlyph, LINK_GLYPH[status.link] || 'unknown');
    const cause = status.link === 'ok' ? '' : text.failureText(status.failure);
    setText(linkText, `${UI.status.platform}: ${text.label('linkStatus', status.link)}${cause ? ` (${cause})` : ''}`);
    setText(age, text.ageText(status.dataAgeS));
    setAttrs(publications, {'data-publications': status.publications, text: text.label('publications', status.publications)});
    // Before the first data there is nothing to command: the notice appears only for a working screen.
    commands.hidden = !(state.commandsBlocked && state.boot === 'ready');
    setAttrs(commands, {'data-block-reason': state.blockReason});
    setText(commandsReason, state.blockReason ? `: ${text.label('blockReason', state.blockReason)}` : '');
    oldTag.hidden = !(showsOldData(status) && state.snapshot);
  });

  store.watch((state) => [state.snapshot, state.model], () => {
    const {snapshot, model} = store.getState();
    // The tick this view shows: a view that stopped following the state is told apart from the others.
    setAttrs(modelTime, {'data-tick': snapshot && model ? snapshot.tick : null});
    if (!snapshot || !model) {
      setText(modelTime, `${UI.status.model}: ${UI.status.noData}`);
      setText(runInfo, `${UI.status.run}: ${UI.status.noData}`);
      reconcile(conditionsList, [], () => '', () => null);
      setText(conditionsNone, UI.status.noData);
      return;
    }
    const values = snapshot.shift.values;
    const pause = snapshot.pauseReason !== 'none' && text.isKnown('pauseReason', snapshot.pauseReason)
      ? ` ${text.VOCAB.pauseReason[snapshot.pauseReason]}` : '';
    setText(modelTime, `${UI.status.model} ${text.tickTime(snapshot.simTimeS, snapshot.tick)} · `
      + `${UI.status.speed(values.speedup)} · ${text.label('runState', snapshot.runState)}${pause}`);
    setText(runInfo, `${UI.status.run} ${snapshot.run} · ${UI.status.seed} ${text.num(values.seed)}`);
    reconcile(conditionsList, model.conditions, (condition) => condition.raw,
      () => h('span', {class: 'chip chip--stand'}),
      (chip, condition) => setAttrs(chip, {
        'data-condition': condition.raw,
        text: text.conditionText(condition, (name) => labelOf(model, name)),
      }));
    setText(conditionsNone, model.conditions.length === 0 ? UI.status.noConditions : '');
  });
}
