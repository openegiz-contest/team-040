// «Действия диспетчера» for one zone: the block that unfolds under a zone row of
// the people rail (view/people.js). A button is switched off only by one
// published field of the zone (DESIGN.md 2.6), by the block of all commands, or
// by its own unconfirmed command; every other refusal comes back from the model
// and is shown with the command (view/pending.js).
//
// While the model waits for a decision between its options (clarity A2), these
// buttons are drawn as secondary with a note: the launch of an option in the
// panel «Решение» is the decision asked for.

import {h, setAttrs} from '../dom.js';
import {thingsOfKind} from '../model.js';
import {blockNote, commandButton, guard, showBlock, standing} from './pending.js';

/** True while the model is paused for a choice between offered options. */
export function waitsForOption(state) {
  const {model, snapshot} = state;
  return Boolean(model && snapshot && snapshot.runState === 'paused' && snapshot.pauseReason === 'decision'
    && thingsOfKind(model, 'option').some((option) => option.values.state === 'offered'));
}

/**
 * The action block of one zone.
 * @param {Object} ctx
 * @param {string} zoneName local name of the zone
 * @returns {{node: HTMLElement, render: (state: Object) => void}}
 */
export function zoneActions(ctx, zoneName) {
  const {text} = ctx;
  const {UI, VOCAB} = text;
  const workState = (values) => (text.isKnown('workState', values.work_state)
    ? `${VOCAB.kind.zone} ${VOCAB.workState[values.work_state]}`
    : `${text.fieldLabel('work_state')} — ${text.label('workState', values.work_state)}`);
  /** Each action with its single-field precondition: the text says why the button is off, '' when it is on. */
  const ACTIONS = [
    {type: 'action.stop_zone', label: UI.actions.stop, off: (values) => (values.work_state === 'working' ? '' : workState(values))},
    {
      type: 'action.withdraw_zone', label: UI.actions.withdraw,
      off: (values) => (values.withdrawal_state === 'in_progress' ? VOCAB.withdrawal.in_progress : ''),
    },
    {
      type: 'action.resume_zone', label: UI.actions.resume, standing: UI.actions.resumeNote,
      off: (values) => (values.work_state === 'stopped' ? '' : workState(values)),
    },
  ];

  const block = blockNote();
  const waits = h('p', {class: 'note note--waits', 'data-testid': 'actions-waits', hidden: true, text: UI.actions.waitsForOption});
  const buttons = ACTIONS.map((action) => {
    const button = commandButton({
      class: 'btn btn--dispatch btn--block', 'data-command-type': action.type, 'data-command-target': zoneName, text: action.label,
    }, () => ctx.sendCommand(action.type, zoneName));
    const why = h('p', {class: 'note note--why', hidden: true});
    return {action, button, why, node: h('div', {class: 'act'}, button, why, action.standing ? h('p', {class: 'note', text: action.standing}) : null)};
  });
  const node = h('div', {class: 'zone-actions', 'data-testid': 'actions-panel', 'data-zone': zoneName},
    block, waits, h('div', {class: 'acts'}, buttons.map((item) => item.node)));

  function render(state) {
    const zone = state.model ? thingsOfKind(state.model, 'zone').find((item) => item.name === zoneName) : null;
    const asked = waitsForOption(state);
    waits.hidden = !asked;
    setAttrs(node, {'data-secondary': asked ? 'true' : null});
    const blocked = showBlock(block, text, state);
    for (const {action, button, why} of buttons) {
      setAttrs(button, {class: ['btn', 'btn--dispatch', 'btn--block', asked && 'btn--secondary']});
      const off = zone && zone.hasState ? action.off(zone.values) : '';
      const own = standing(text, state, action.type, zoneName);
      // A switched-off button always says why, next to it.
      let words = own.words;
      if (!zone || !zone.hasState) words = UI.rail.noState;
      else if (off) words = `${UI.actions.unavailable}: ${off}`;
      guard(button, blocked || !zone || !zone.hasState || off !== '' || own.bars, why, words);
    }
  }

  return {node, render};
}
