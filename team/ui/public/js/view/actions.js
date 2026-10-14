// «Действия диспетчера»: what the dispatcher decides for one zone. A button is
// switched off only by one published field of the zone (DESIGN.md 2.6), by the
// block of all commands, or by its own unconfirmed command; every other
// refusal comes back from the model and is shown with the command.

import {h, reconcile, setAttrs, setText} from '../dom.js';
import {thingsOfKind} from '../model.js';
import {blockNote, commandButton, guard, showBlock, standing} from './pending.js';

/**
 * @param {HTMLElement} root the element of index.html this view owns
 * @param {Object} ctx store, text, roots and the action functions
 */
export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;

  const workState = (values) => (text.isKnown('workState', values.work_state)
    ? `${text.VOCAB.kind.zone} ${text.VOCAB.workState[values.work_state]}`
    : `${text.fieldLabel('work_state')} — ${text.label('workState', values.work_state)}`);
  /** Each action with its single-field precondition: the text says why the button is off, '' when it is on. */
  const ACTIONS = [
    {type: 'action.stop_zone', label: UI.actions.stop, off: (values) => (values.work_state === 'working' ? '' : workState(values))},
    {
      type: 'action.withdraw_zone', label: UI.actions.withdraw,
      off: (values) => (values.withdrawal_state === 'in_progress' ? text.VOCAB.withdrawal.in_progress : ''),
    },
    {
      type: 'action.resume_zone', label: UI.actions.resume, standing: UI.actions.resumeNote,
      off: (values) => (values.work_state === 'stopped' ? '' : workState(values)),
    },
  ];

  const select = h('select', {class: 'select', id: 'action-zone'});
  const zoneState = h('dl', {class: 'kv', 'data-testid': 'actions-zone-state'});
  const block = blockNote();
  const buttons = ACTIONS.map((action) => {
    const button = commandButton({class: 'btn btn--dispatch btn--block', 'data-command-type': action.type, text: action.label},
      () => ctx.sendCommand(action.type, select.value));
    const why = h('p', {class: 'note note--why', hidden: true});
    return {action, button, why, node: h('div', {class: 'act'}, button, why, action.standing ? h('p', {class: 'note', text: action.standing}) : null)};
  });
  select.addEventListener('change', render);
  root.append(
    h('h2', {class: 'panel__title', text: UI.actions.title}),
    h('p', {class: 'panel__subtitle', text: UI.actions.subtitle}),
    block,
    h('div', {class: 'pick'}, h('label', {class: 'field', for: 'action-zone', text: UI.actions.zone}), select),
    zoneState,
    ...buttons.map((item) => item.node),
  );

  /** The published state of the chosen zone as caption and words. */
  function stateRows(zone) {
    if (!zone) return [];
    if (!zone.hasState) return [['state', UI.list.noState]];
    const {values} = zone;
    return [
      ['work_state', text.label('workState', values.work_state)],
      ['withdrawal_state', text.label('withdrawal', values.withdrawal_state)],
      ['hazard_state', `${text.hazardText(zone.hazard)} · ${text.label('quality', values.data_quality)}`],
      ['workers_count', typeof values.workers_count === 'number' ? text.num(values.workers_count) : text.DASH],
    ];
  }

  let followed = store.getState().ui.selected;
  let toFollow = followed;

  function render() {
    const state = store.getState();
    const {model} = state;
    const zones = model ? thingsOfKind(model, 'zone') : [];
    reconcile(select, zones, (zone) => zone.name, (zone) => h('option', {value: zone.name}), (option, zone) => setText(option, zone.label));

    // A newly selected zone becomes the target; after that the user's own choice stays.
    if (state.ui.selected !== followed) toFollow = followed = state.ui.selected;
    const selected = model && toFollow ? model.things[toFollow] : null;
    if (model) toFollow = null;
    if (selected && selected.kind === 'zone') select.value = selected.name;

    const zone = zones.find((item) => item.name === select.value) || null;
    reconcile(zoneState, stateRows(zone), ([field]) => field,
      // The spaces keep the list readable as plain text; the columns on the screen are CSS.
      ([field]) => h('div', {class: 'kv__row'}, h('dt', {text: text.fieldLabel(field, 'zone')}), ' ', h('dd'), ' '),
      (row, [, words]) => setText(row.children[1], words));
    setAttrs(zoneState, {
      'data-zone': zone ? zone.name : null,
      'data-work-state': zone ? zone.values.work_state : null,
      'data-withdrawal': zone ? zone.values.withdrawal_state : null,
    });

    const blocked = showBlock(block, text, state);
    for (const {action, button, why} of buttons) {
      setAttrs(button, {'data-command-target': zone ? zone.name : null});
      const off = zone && zone.hasState ? action.off(zone.values) : '';
      const own = standing(text, state, action.type, zone ? zone.name : '');
      guard(button, blocked || !zone || !zone.hasState || off !== '' || own.bars, why, off ? `${UI.actions.unavailable}: ${off}` : own.words);
    }
  }

  store.watch((state) => [state.model, state.pending, state.commandsBlocked, state.blockReason, state.ui.selected], render);
}
