// «Действия диспетчера»: what the dispatcher decides for one zone. A button is
// switched off only by one published field of the zone (DESIGN.md 2.6), by the
// block of all commands, by its own unconfirmed command, or because no zone is
// chosen; every other refusal comes back from the model and is shown with the
// command.
//
// The zone (clarity pass, A1): the user's own choice (the select, or a zone
// selected on the stage, in the list or by «показать» of the strip) wins; without
// one, an open incident's zone; without either, nothing, and the buttons say
// «Выберите участок». A choice other than the incident's zone is said above the
// buttons. While the model waits for a decision between its options (A2), these
// buttons are drawn as secondary: the launch of an option is the decision asked for.

import {h, reconcile, setAttrs, setText} from '../dom.js';
import {incidentOf, labelOf, thingsOfKind} from '../model.js';
import {blockNote, commandButton, guard, showBlock, standing} from './pending.js';

const OPEN = new Set(['active', 'executing']);

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
  const other = h('p', {class: 'note note--other', 'data-testid': 'actions-other-zone', hidden: true});
  const waits = h('p', {class: 'note note--waits', 'data-testid': 'actions-waits', hidden: true, text: UI.actions.waitsForOption});
  const buttons = ACTIONS.map((action) => {
    const button = commandButton({class: 'btn btn--dispatch btn--block', 'data-command-type': action.type, text: action.label},
      () => ctx.sendCommand(action.type, select.value));
    const why = h('p', {class: 'note note--why', hidden: true});
    return {action, button, why, node: h('div', {class: 'act'}, button, why, action.standing ? h('p', {class: 'note', text: action.standing}) : null)};
  });
  root.append(
    h('h2', {class: 'panel__title', text: UI.actions.title}),
    h('p', {class: 'panel__subtitle', text: UI.actions.subtitle}),
    block,
    h('div', {class: 'pick'}, h('label', {class: 'field', for: 'action-zone', text: UI.actions.zone}), select),
    zoneState,
    other,
    waits,
    h('div', {class: 'acts'}, buttons.map((item) => item.node)),
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

  // The user's own choice of a zone (local name), or null: then the zone follows the incident.
  let choice = null;
  // The selection last read with a model: a selection made before the twins are read (from the route) counts too.
  let followed = null;
  let incidentKey = null;
  select.addEventListener('change', () => {
    choice = select.value || null;
    render();
  });

  function render() {
    const state = store.getState();
    const {model, snapshot} = state;
    const zones = model ? thingsOfKind(model, 'zone') : [];
    reconcile(select, [null, ...zones], (zone) => (zone ? zone.name : ''), (zone) => h('option', {value: zone ? zone.name : ''}),
      (option, zone) => setText(option, zone ? zone.label : UI.actions.chooseOption));

    // A zone selected anywhere on the screen is the user's choice.
    if (model && state.ui.selected !== followed) {
      followed = state.ui.selected;
      const selected = model && followed ? model.things[followed] : null;
      if (selected && selected.kind === 'zone') choice = selected.name;
    }
    // A new incident (another zone or another opening) is followed again.
    const incident = model ? incidentOf(model) : null;
    const open = Boolean(incident && incident.hasState && OPEN.has(incident.values.state) && typeof incident.values.zone === 'string');
    const key = open ? `${incident.values.zone}@${incident.values.opened_at_tick}` : null;
    if (key !== incidentKey) {
      if (key !== null && incidentKey !== null) choice = null;
      incidentKey = key;
    }
    if (choice && !zones.some((zone) => zone.name === choice)) choice = null;
    const incidentZone = open && zones.some((zone) => zone.name === incident.values.zone) ? incident.values.zone : null;
    const target = choice || incidentZone || '';
    if (select.value !== target) select.value = target;

    const zone = zones.find((item) => item.name === target) || null;
    reconcile(zoneState, stateRows(zone), ([field]) => field,
      // The spaces keep the list readable as plain text; the columns on the screen are CSS.
      ([field]) => h('div', {class: 'kv__row'}, h('dt', {text: text.fieldLabel(field, 'zone')}), ' ', h('dd'), ' '),
      (row, [, words]) => setText(row.children[1], words));
    setAttrs(zoneState, {
      'data-zone': zone ? zone.name : null,
      'data-work-state': zone ? zone.values.work_state : null,
      'data-withdrawal': zone ? zone.values.withdrawal_state : null,
    });
    setAttrs(root, {'data-zone-from': zone ? (choice ? 'choice' : 'incident') : null});

    other.hidden = !(incidentZone && zone && zone.name !== incidentZone);
    setText(other, other.hidden ? '' : UI.actions.otherZone(labelOf(model, incidentZone), zone.label));

    // The decision the model waits for is the launch of an option; these buttons stay, as secondary commands.
    const options = model ? thingsOfKind(model, 'option') : [];
    const asked = Boolean(snapshot && snapshot.runState === 'paused' && snapshot.pauseReason === 'decision'
      && options.some((option) => option.values.state === 'offered'));
    waits.hidden = !asked;
    setAttrs(root, {'data-secondary': asked ? 'true' : null});

    const blocked = showBlock(block, text, state);
    for (const {action, button, why} of buttons) {
      setAttrs(button, {'data-command-target': zone ? zone.name : null,
        class: ['btn', 'btn--dispatch', 'btn--block', asked && 'btn--secondary']});
      const off = zone && zone.hasState ? action.off(zone.values) : '';
      const own = standing(text, state, action.type, zone ? zone.name : '');
      // A switched-off button always says why, next to it.
      let words = own.words;
      if (!zone) words = UI.actions.chooseZone;
      else if (off) words = `${UI.actions.unavailable}: ${off}`;
      guard(button, blocked || !zone || !zone.hasState || off !== '' || own.bars, why, words);
    }
  }

  store.watch((state) => [state.model, state.snapshot && state.snapshot.runState, state.pending, state.commandsBlocked,
    state.blockReason, state.ui.selected], render);
}
