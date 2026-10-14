// «Условия сценария (стенд)»: what happens to the mine, in the stand drawer.
// Presets that start a new run, three manual conditions, the active conditions
// with their undo, and (in ctx.roots.reset) the full reset of the run. Every
// control here is chalk mark-up (.btn--stand with the «стенд» tag), never the
// copper of a dispatcher action. A press only creates a pending command; the
// list of active conditions is what the model published.

import {RESET_TARGET} from '../commands.js';
import {h, reconcile, setAttrs, setText} from '../dom.js';
import {CONDITION_COMMANDS, labelOf, thingsOfKind} from '../model.js';
import {blockNote, commandButton, commandTitle, guard, presetsOf, showBlock, standing} from './pending.js';

/**
 * @param {HTMLElement} root the element of index.html this view owns
 * @param {Object} ctx store, text, roots and the action functions
 */
export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;
  const LABELS = {working_closed: UI.conditions.closeWorking, sensor_lost: UI.conditions.sensorLost, instability: UI.conditions.instability};

  /**
   * Ask about ending the run on the screen. When the run changed while the
   * dialog was open, the question is asked again about the new one.
   */
  async function confirmEndOfRun(optionsFor) {
    for (;;) {
      const {snapshot} = store.getState();
      if (!snapshot) return false;
      if (!(await ctx.confirm({...optionsFor(snapshot.run), confirmLabel: UI.reset.confirm, cancelLabel: UI.reset.cancel, danger: true}))) {
        return false;
      }
      const now = store.getState().snapshot;
      if (now && now.run === snapshot.run) return true;
    }
  }

  // ---- presets -----------------------------------------------------------

  const presetList = h('ul', {class: 'stack'});
  const presetBox = h('div', {class: 'group__part', hidden: true},
    h('h3', {class: 'group__sub', text: UI.conditions.presets}), presetList);

  function createPreset(preset) {
    const button = commandButton({
      class: 'btn btn--stand btn--block btn--preset', 'data-command-type': 'run.start_preset', 'data-command-target': preset.id,
      'data-tag': UI.stand.tag,
    }, async () => {
      const label = button.textContent;
      if (await confirmEndOfRun((run) => ({title: UI.reset.presetDialogTitle, message: UI.reset.presetDialogText(run, label)}))) {
        ctx.sendCommand('run.start_preset', preset.id);
      }
    });
    return h('li', {'data-preset': preset.id}, button, h('p', {class: 'note'}), h('p', {class: 'note note--why', hidden: true}));
  }

  function updatePreset(node, preset, state, blocked) {
    const [button, about, why] = node.children;
    setText(button, preset.label);
    const steps = preset.schedule.map((step) => {
      const what = commandTitle(text, state, step.type, step.target);
      return typeof step.at_sim_s === 'number' ? `${what} — ${UI.conditions.presetAt(step.at_sim_s)}` : what;
    });
    const expect = preset.expect === undefined ? [] : [text.codeLabel('presetExpect', preset.expect)];
    setText(about, [...expect, ...steps].join(' · '));
    const own = standing(text, state, 'run.start_preset', preset.id);
    guard(button, blocked || own.bars, why, own.words);
  }

  // ---- manual conditions -------------------------------------------------

  const rows = Object.entries(CONDITION_COMMANDS).map(([kind, commands]) => {
    const id = `condition-${kind}`;
    const select = h('select', {class: 'select select--stand', id, 'data-condition': kind});
    const button = commandButton({class: 'btn btn--stand', 'data-command-type': commands.set, 'data-tag': UI.stand.tag, text: UI.conditions.set},
      () => ctx.sendCommand(commands.set, select.value));
    const why = h('p', {class: 'note note--why', hidden: true});
    select.addEventListener('change', render);
    return {
      kind, commands, select, button, why,
      node: h('div', {class: 'group__part'},
        h('label', {class: 'field', for: id, text: LABELS[kind]}),
        h('div', {class: 'pick'}, select, button), why),
    };
  });

  // ---- active conditions -------------------------------------------------

  const activeList = h('ul', {class: 'stack', 'data-testid': 'conditions-active'});
  const activeNone = h('p', {class: 'muted', text: UI.conditions.none});

  function createActive(condition) {
    const node = h('li', {class: 'active', 'data-condition': condition.raw}, h('span', {class: 'chip chip--stand'}));
    if (condition.undoType) {
      node.append(' ', commandButton({
        class: 'btn btn--stand btn--small', 'data-command-type': condition.undoType, 'data-command-target': condition.target,
        'data-tag': UI.stand.tag,
        text: UI.conditions.undo[condition.kind],
      }, () => ctx.sendCommand(condition.undoType, condition.target)), h('p', {class: 'note note--why', hidden: true}));
    }
    return node;
  }

  function updateActive(node, condition, state, blocked) {
    setText(node.firstChild, text.conditionText(condition, (name) => labelOf(state.model, name)));
    const button = node.querySelector('button');
    if (!button) return;
    const own = standing(text, state, condition.undoType, condition.target);
    guard(button, blocked || own.bars, node.lastChild, own.words);
  }

  // ---- reset -------------------------------------------------------------

  const resetBlock = blockNote();
  const resetWhy = h('p', {class: 'note note--why', hidden: true});
  const resetHint = h('p', {class: 'note'});
  const reset = commandButton({
    class: 'btn btn--danger btn--block', 'data-testid': 'btn-reset', 'data-command-type': 'run.reset', text: UI.reset.button,
  }, async () => {
    if (await confirmEndOfRun((run) => ({title: UI.reset.dialogTitle, message: UI.reset.dialogText(run)}))) ctx.sendCommand('run.reset');
  });
  ctx.roots.reset.append(h('h2', {class: 'panel__title', text: UI.reset.title}), resetBlock, reset, resetWhy, resetHint);

  // ---- the group ---------------------------------------------------------

  const block = blockNote();
  root.append(
    h('h2', {class: 'panel__title', text: UI.conditions.title}),
    h('p', {class: 'panel__subtitle', text: UI.conditions.subtitle}),
    block, presetBox,
    ...rows.map((row) => row.node),
    h('div', {class: 'group__part'},
      h('h3', {class: 'group__sub', text: UI.conditions.active}), activeList, activeNone,
      h('p', {class: 'note', text: UI.conditions.undoNote})),
  );

  let followed = store.getState().ui.selected;
  let toFollow = followed;

  function render() {
    const state = store.getState();
    const {model} = state;
    const blocked = showBlock(block, text, state);

    const presets = presetsOf(state);
    reconcile(presetList, presets, (preset) => preset.id, createPreset, (node, preset) => updatePreset(node, preset, state, blocked));
    presetBox.hidden = presets.length === 0;

    // A newly selected object of the matching kind becomes the target; after that the user's own choice stays.
    if (state.ui.selected !== followed) toFollow = followed = state.ui.selected;
    const selected = model && toFollow ? model.things[toFollow] : null;
    if (model) toFollow = null;

    for (const {commands, select, button, why} of rows) {
      const things = model ? thingsOfKind(model, commands.targetKind) : [];
      reconcile(select, [null, ...things], (thing) => (thing ? thing.name : ''),
        (thing) => h('option', {value: thing ? thing.name : ''}),
        (option, thing) => setText(option, thing ? thing.label : UI.conditions.choose));
      if (selected && selected.kind === commands.targetKind) select.value = selected.name;
      const target = select.value;
      setAttrs(button, {'data-command-target': target || null});
      const own = standing(text, state, commands.set, target);
      // Without a target the select itself says what is missing: «выберите…».
      guard(button, blocked || !target || own.bars, why, own.words);
    }

    const active = model ? model.conditions : [];
    reconcile(activeList, active, (condition) => condition.raw, createActive,
      (node, condition) => updateActive(node, condition, state, blocked));
    activeNone.hidden = active.length > 0;

    showBlock(resetBlock, text, state);
    const ownReset = standing(text, state, 'run.reset', RESET_TARGET);
    guard(reset, blocked || ownReset.bars, resetWhy, ownReset.words);
    setText(resetHint, state.snapshot ? `${UI.reset.hint} · ${UI.status.run.toLowerCase()} ${state.snapshot.run}` : UI.reset.hint);
  }

  store.watch((state) => [state.model, state.pending, state.commandsBlocked, state.blockReason, state.ui.selected], render);
}
