// Commands of this page that still need attention: what was sent, to what,
// and what is known about it. Nothing here changes an object: the entry is
// the only trace of a command until the snapshot shows its effect.
// The helpers every command button of the panels shares live here as well.

import {canRetry, isUnresolved} from '../commands.js';
import {h, reconcile, setAttrs, setGlyph, setText} from '../dom.js';
import {labelOf} from '../model.js';

const PHASE_GLYPH = {
  sending: 'clock', sent: 'clock', applied: 'ok', rejected: 'blocked', no_ack: 'attention',
  delivery_unknown: 'unknown', not_sent: 'danger',
};

/** @returns {Array<{id: string, label: string, expect: *, schedule: Object[]}>} the presets the mine twin publishes */
export function presetsOf(state) {
  const presets = state.attributes ? state.attributes.mine.presets : null;
  const seen = new Set();
  return (Array.isArray(presets) ? presets : [])
    // An id that comes twice names one preset (the command carries the id): the first entry is kept.
    .filter((preset) => preset && typeof preset.id === 'string' && preset.id !== '' && !seen.has(preset.id) && seen.add(preset.id))
    .map((preset) => ({
      id: preset.id,
      label: typeof preset.label === 'string' && preset.label ? preset.label : preset.id,
      expect: preset.expect,
      schedule: Array.isArray(preset.schedule) ? preset.schedule.filter((step) => step && typeof step === 'object') : [],
    }));
}

/** What a command is aimed at, as written on the screen: the code of a twin, the label of a preset. */
export function targetLabel(state, type, target) {
  if (type === 'run.reset' || typeof target !== 'string') return '';
  if (type === 'run.start_preset') {
    const preset = presetsOf(state).find((item) => item.id === target);
    return preset ? preset.label : String(target);
  }
  return state.model ? labelOf(state.model, target) : String(target);
}

/** "Остановить участок: Участок Б"; a preset is named by its label. */
export function commandTitle(text, state, type, target) {
  return text.commandText(type, target, (name) => targetLabel(state, type, name));
}

/**
 * A button that sends a command. It is switched off with `aria-disabled`, not
 * `disabled`: it stays in the Tab order and keeps the focus while its own
 * command is waiting, and a press while it is off does nothing.
 * @param {Object<string, *>} attrs
 * @param {(button: HTMLButtonElement) => void} onPress
 */
export function commandButton(attrs, onPress) {
  const button = h('button', {type: 'button', ...attrs});
  button.addEventListener('click', () => {
    if (button.getAttribute('aria-disabled') !== 'true') onPress(button);
  });
  return button;
}

/**
 * Switch a command button on or off. The reason is always on the screen: the
 * note next to the button says `why`; a block of all commands is said once
 * per group by `showBlock`.
 * @param {Element} button
 * @param {boolean} off
 * @param {Element|null} [note]
 * @param {string} [why]
 */
export function guard(button, off, note = null, why = '') {
  setAttrs(button, {'aria-disabled': off ? 'true' : null});
  if (note) {
    setText(note, why);
    note.hidden = !why;
  }
}

/**
 * The latest command of this page for a type and target, as the message next to its button:
 * the words of its phase, and whether it bars a second press (its outcome is not known yet).
 * @returns {{words: string, bars: boolean}}
 */
export function standing(text, state, type, target) {
  const entry = [...state.pending].reverse().find((item) => item.type === type && item.target === target);
  return entry ? {words: text.pendingText(entry), bars: isUnresolved(entry.phase)} : {words: '', bars: false};
}

export function blockNote() {
  return h('p', {class: 'block-note', hidden: true});
}

/** Say in the group why none of its commands can be sent. @returns {boolean} commands are blocked */
export function showBlock(note, text, state) {
  setText(note, state.commandsBlocked ? text.blockText(state.blockReason) : '');
  note.hidden = !state.commandsBlocked;
  return state.commandsBlocked;
}

/**
 * @param {HTMLElement} root the element of index.html this view owns
 * @param {Object} ctx store, text, roots and the action functions
 */
export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;
  const title = h('h2', {class: 'panel__title', text: UI.pending.title});
  const block = blockNote();
  const list = h('ul', {class: 'pending-list'});
  let timer = null;

  function leave(entry) {
    ctx.dismissCommand(entry.id);
    // Focus goes to the next entry, or back to the control the command came from.
    const source = [...document.querySelectorAll(`button[data-command-type="${entry.type}"]:not([data-testid="btn-retry"])`)]
      .find((button) => !button.dataset.commandTarget || button.dataset.commandTarget === entry.target);
    const next = list.querySelector('[data-testid="pending"]') || source;
    if (next) next.focus();
  }

  function create(entry) {
    const retry = commandButton({class: 'btn btn--small', 'data-testid': 'btn-retry', text: UI.pending.retry},
      () => ctx.retryCommand(entry.id));
    const dismiss = h('button', {class: 'btn btn--small', type: 'button', 'data-testid': 'btn-dismiss', on: {click: () => leave(entry)}});
    return h('li', {class: 'pending', 'data-testid': 'pending', tabindex: -1},
      h('p', {class: 'pending__head'},
        h('strong', {class: 'pending__what'}), ' ',
        h('span', {class: 'pending__id mono', title: entry.id, text: text.shortCommandId(entry.id)})),
      h('p', {class: 'pending__state'}, h('span', {class: 'pending__glyph'}), h('span', {class: 'pending__text'})),
      h('p', {class: 'pending__buttons'}, retry, dismiss));
  }

  function update(node, entry, state) {
    const [retry, dismiss] = node.querySelectorAll('button');
    const waited = entry.phase === 'sent' ? Math.floor((performance.now() - entry.phaseAt) / 1000) : undefined;
    let words = text.pendingText(entry, waited);
    if (entry.attempts > 1) words += ` · ${UI.pending.attempts(entry.attempts)}`;
    setAttrs(node, {
      'data-command-id': entry.id, 'data-command-type': entry.type, 'data-command-target': entry.target,
      'data-phase': entry.phase,
    });
    setText(node.querySelector('.pending__what'), commandTitle(text, state, entry.type, entry.target));
    setText(node.querySelector('.pending__text'), words);
    setGlyph(node.querySelector('.pending__glyph'), PHASE_GLYPH[entry.phase] || 'unknown');
    const focused = document.activeElement;
    retry.hidden = !canRetry(entry.phase);
    setAttrs(retry, {'data-command-type': entry.type, 'data-command-target': entry.target});
    guard(retry, state.commandsBlocked);
    dismiss.hidden = entry.phase === 'sending';
    setText(dismiss, isUnresolved(entry.phase) ? UI.pending.dismiss : UI.pending.close);
    // A pressed button that goes away leaves the focus on its entry, not at the top of the page.
    if (focused && focused.hidden && node.contains(focused)) node.focus();
  }

  function render() {
    const state = store.getState();
    const {pending} = state;
    if (pending.length === 0) {
      // No child nodes: the stylesheet hides an empty group.
      if (root.firstChild) root.replaceChildren();
    } else if (!root.firstChild) {
      root.append(title, block, list);
    }
    // Newest first: the group has a limited height and scrolls inside, and the command that was just
    // sent must be in sight without scrolling, right under the heading.
    reconcile(list, [...pending].reverse(), (entry) => entry.id, create, (node, entry) => update(node, entry, state));
    block.hidden = !(state.commandsBlocked && pending.some((entry) => canRetry(entry.phase)));
    setText(block, block.hidden ? '' : text.blockText(state.blockReason));

    // The seconds of a waiting command need a clock; it runs only while something waits.
    const waiting = pending.some((entry) => entry.phase === 'sent');
    if (waiting && timer === null) {
      timer = setInterval(render, 500);
    } else if (!waiting && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  store.watch((state) => [state.pending, state.commandsBlocked, state.blockReason, state.attributes], render);
}
