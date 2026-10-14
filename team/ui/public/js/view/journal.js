// The event journal of the model, newest first, one line per event. The
// sentence is put together from the code, its subject and its argument; a
// code this interface does not know is shown as it came. A jump of `seq` is
// said in its own line: missing events are never passed over in silence.
// Condensed by default: the latest three lines; the button of its bar unfolds
// the whole journal (body[data-journal="open"]). A line starts with its moment
// by the model clock and its age («00:13:30 · 7 мин назад»); the tick is in its title.

import {h, reconcile, setAttrs, setText} from '../dom.js';
import {labelOf, thingsOfKind} from '../model.js';
import {presetsOf} from './pending.js';

/**
 * The words of one event.
 * @param {Object} text the module text.js
 * @param {import('../store.js').State} state
 * @param {{code: *, subject: *, arg: *}} event
 */
export function eventText(text, state, event) {
  const {VOCAB} = text;
  const name = (local) => labelOf(state.model, local);
  const code = text.codeLabel('journalCode', event.code);
  const subject = typeof event.subject === 'string' ? name(event.subject) : '';
  const arg = typeof event.arg === 'string' ? event.arg : null;
  if ((event.code === 'condition.set' || event.code === 'condition.cancelled') && text.isKnown('conditionKind', arg)) {
    return `${code}: «${subject} ${VOCAB.conditionKind[arg]}»`;
  }
  // The outcome of a withdrawal is its argument: «вывод не завершён» must not follow the word «завершён».
  if (event.code === 'withdrawal.finished' && text.isKnown('withdrawal', arg)) return `${subject}: ${VOCAB.withdrawal[arg]}`;
  let detail = arg === null ? (event.arg === undefined || event.arg === null ? '' : String(event.arg)) : arg;
  if (arg !== null) {
    if (arg.startsWith('preset:')) {
      // A run or a condition that came from a preset names it by its label.
      const preset = presetsOf(state).find((item) => item.id === arg.slice(7));
      detail = `${text.UI.journal.preset} «${preset ? preset.label : arg.slice(7)}»`;
    } else if (event.code === 'hazard.changed') detail = text.label('hazard', arg);
    else if (event.code === 'quality.changed') detail = text.label('quality', arg);
    else if (event.code === 'command.applied') detail = text.codeLabel('commandType', arg);
    else if (event.code === 'command.rejected' && text.isKnown('ackReason', arg)) detail = `${VOCAB.ackReason[arg]} (${arg})`;
    else if (event.code === 'worker.route_changed' || event.code === 'worker.out') detail = `${VOCAB.kind.exit} ${name(arg)}`;
  }
  return [subject ? `${subject}: ${code}` : code, detail].filter(Boolean).join(' — ');
}

/**
 * Events newest first, with a line wherever `seq` jumps (also between the newest event and `last_seq`).
 * @returns {Array<{key: string, gap: ([number, number]|undefined), event: (Object|undefined)}>}
 */
export function journalLines(events, lastSeq) {
  const sorted = events.map((event, index) => ({event, index}))
    .filter(({event}) => event && typeof event === 'object')
    .sort((a, b) => (typeof a.event.seq === 'number' && typeof b.event.seq === 'number' ? b.event.seq - a.event.seq : b.index - a.index));
  const lines = [];
  const keys = new Set();
  let above = typeof lastSeq === 'number' ? lastSeq + 1 : null;
  for (const {event, index} of sorted) {
    const numbered = typeof event.seq === 'number';
    if (numbered) {
      if (above !== null && above - event.seq > 1) lines.push({key: `gap-${event.seq}`, gap: [event.seq + 1, above - 1]});
      above = event.seq;
    }
    // A repeated or missing number must not merge two events into one line.
    const key = numbered && !keys.has(`e-${event.seq}`) ? `e-${event.seq}` : `x-${index}`;
    keys.add(key);
    lines.push({key, event});
  }
  return lines;
}

/**
 * @param {HTMLElement} root the element of index.html this view owns
 * @param {Object} ctx store, text, roots and the action functions
 */
export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;
  const list = h('ol', {class: 'journal-list'});
  const note = h('p', {class: 'journal-line muted'});
  root.append(list, note);

  // The bar: heading, order, and the button that unfolds the whole journal.
  const toggle = h('button', {
    class: 'btn btn--quiet btn--small journal__toggle', type: 'button', 'data-testid': 'journal-toggle',
    'aria-controls': 'journal', 'aria-expanded': 'false',
  });
  const isOpen = () => document.body.getAttribute('data-journal') === 'open';
  const showToggle = () => {
    const count = list.querySelectorAll('[data-testid="journal-entry"]').length;
    setAttrs(toggle, {'aria-expanded': String(isOpen()), text: isOpen() ? UI.journal.less : UI.journal.more(count)});
  };
  toggle.addEventListener('click', () => {
    document.body.setAttribute('data-journal', isOpen() ? 'collapsed' : 'open');
    showToggle();
  });
  ctx.roots.journalBar.append(
    h('h2', {class: 'panel__title journal__title', text: UI.journal.title}),
    h('span', {class: 'journal__order', text: UI.journal.order}),
    toggle,
  );
  let shown = null;
  let shownFor = null;

  function create(line) {
    if (line.gap) return h('li', {class: 'journal-line journal-line--gap', 'data-testid': 'journal-gap'});
    return h('li', {class: 'journal-line', 'data-testid': 'journal-entry'},
      h('span', {class: 'mono journal-line__time'}), ' ', h('span', {class: 'journal-line__text'}), ' ',
      h('span', {class: 'mono muted', hidden: true}), ' ', h('span', {class: 'badge badge--unknown', hidden: true}));
  }

  function update(node, line, state) {
    if (line.gap) {
      const [from, to] = line.gap;
      setText(node, UI.journal.gap(from, to));
      node.setAttribute('data-gap', to - from + 1);
      return;
    }
    const {event} = line;
    const [time, words, command, run] = node.children;
    setAttrs(node, {'data-seq': event.seq, 'data-code': event.code, 'data-run': event.run});
    // The age is counted in the run of the event only: a moment of another run has no age here.
    const sameRun = typeof event.run !== 'string' || !state.snapshot || event.run === state.snapshot.run;
    const now = state.snapshot && sameRun ? state.snapshot.simTimeS : undefined;
    setText(time, typeof event.sim_time_s === 'number' ? text.clockAgoLine(event.sim_time_s, now) : text.tickTime(null, event.tick));
    setAttrs(time, {title: text.tickWords(event.tick) || null});
    setText(words, eventText(text, state, event));
    command.hidden = typeof event.command_id !== 'string';
    setText(command, command.hidden ? '' : `${UI.journal.command} ${text.shortCommandId(event.command_id)}`);
    setAttrs(command, {title: command.hidden ? null : event.command_id});
    run.hidden = typeof event.run !== 'string' || !state.snapshot || event.run === state.snapshot.run;
    setText(run, run.hidden ? '' : `${UI.journal.otherRun}: ${event.run}`);
  }

  store.watch((state) => state.model, () => {
    const state = store.getState();
    const journal = state.model ? thingsOfKind(state.model, 'journal')[0] : null;
    const events = journal && Array.isArray(journal.values.events) ? journal.values.events : [];
    const lastSeq = journal ? journal.values.last_seq : undefined;
    // The journal changes far less often than the snapshot: the same events are not written again.
    // The age of the lines follows the model clock: a new model time is a new picture too.
    const signature = journal && journal.hasState
      ? [state.snapshot.run, state.snapshot.simTimeS, lastSeq, ...events.map((event) => (event ? event.seq : ''))].join() : null;
    if (signature !== null && signature === shown && shownFor === state.attributes) return;
    shown = signature;
    shownFor = state.attributes;
    reconcile(list, journalLines(events, lastSeq), (line) => line.key, create, (node, line) => update(node, line, state));
    note.hidden = events.length > 0;
    setText(note, journal && journal.hasState ? UI.journal.empty : UI.list.noState);
    showToggle();
  });
}
