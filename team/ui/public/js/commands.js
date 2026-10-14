// Commands of team/CONTRACT.md, section 3: one identifier per intent, the same
// body on every retry, and no change of any object until the snapshot shows it.
// The pending list is a pure reducer; createCommands() is the thin sender.

import {ACK_TIMEOUT_MS, APPLIED_LINGER_MS} from './config.js';
import {isOutcome} from './model.js';

/** @typedef {import('./store.js').PendingCommand} PendingCommand */
/** @typedef {import('./store.js').State} State */

export const COMMAND_TYPES = [
  'condition.close_working', 'condition.open_working', 'condition.sensor_lost', 'condition.sensor_restored',
  'condition.instability_on', 'condition.instability_off',
  'action.stop_zone', 'action.withdraw_zone', 'action.resume_zone', 'action.execute_option',
  'run.reset', 'run.start_preset',
];

/** `run.reset` has no meaningful target; the contract still wants the field. */
export const RESET_TARGET = 'run';

const UNRESOLVED = new Set(['sending', 'sent', 'no_ack', 'delivery_unknown']);
const RETRYABLE = new Set(['no_ack', 'delivery_unknown', 'not_sent']);
const STARTS_RUN = new Set(['run.reset', 'run.start_preset']);

/** A command whose outcome is not known yet: the same type and target is not sent again. */
export function isUnresolved(phase) {
  return UNRESOLVED.has(phase);
}

/** The user may send the same identifier and body again. */
export function canRetry(phase) {
  return RETRYABLE.has(phase);
}

/**
 * @param {PendingCommand[]} pending
 * @param {string} type
 * @param {string} target
 * @returns {PendingCommand|null} the unresolved command of this type for this target
 */
export function findUnresolved(pending, type, target) {
  return pending.find((entry) => entry.type === type && entry.target === target && isUnresolved(entry.phase)) || null;
}

/**
 * @param {PendingCommand[]} pending
 * @param {string} target local name
 * @returns {PendingCommand[]} unresolved commands aimed at the twin (for the "sent, not confirmed" mark)
 */
export function unresolvedFor(pending, target) {
  return pending.filter((entry) => entry.target === target && isUnresolved(entry.phase));
}

/** A reset or preset start of this page that the platform accepted or may still accept. */
export function hasOwnResetPending(pending) {
  return pending.some((entry) => STARTS_RUN.has(entry.type) && (entry.phase === 'sending' || entry.phase === 'sent'));
}

/**
 * "c-" and 32 hexadecimal digits from the browser's cryptographic generator.
 * @param {(bytes: Uint8Array) => Uint8Array} [fill]
 */
export function newCommandId(fill = (bytes) => crypto.getRandomValues(bytes)) {
  const bytes = fill(new Uint8Array(16));
  let hex = '';
  for (const byte of bytes) hex += byte.toString(16).padStart(2, '0');
  return `c-${hex}`;
}

/**
 * The request body. `decisionId` is added for action.execute_option only.
 * @param {{id: string, type: string, target: string, run: string, decisionId: (string|undefined)}} command
 */
export function buildBody({id, type, target, run, decisionId}) {
  const body = {command_id: id, type, target, run};
  if (type === 'action.execute_option') body.decision_id = decisionId;
  return body;
}

/** A refusal by the platform itself: this POST was certainly not passed on. */
function isRefusal(failure) {
  return Boolean(failure) && failure.kind === 'http' && failure.status >= 400 && failure.status < 500;
}

/**
 * How an HTTP outcome of the POST moves a command.
 * 2xx: accepted by the platform, not confirmed. 4xx: this POST was certainly
 * not delivered, which settles the command only if no earlier POST of it may
 * have arrived. Timeout, network error, 5xx: unknown, the command may have
 * been passed on.
 * @param {{ok: boolean, kind: (string|undefined), status: (number|null|undefined)}} result
 * @param {boolean} [maybeDelivered] an earlier POST of the command was accepted or had an unknown outcome
 * @returns {'sent'|'not_sent'|'delivery_unknown'}
 */
export function phaseAfterPost(result, maybeDelivered = false) {
  if (result.ok) return 'sent';
  if (isRefusal(result) && !maybeDelivered) return 'not_sent';
  return 'delivery_unknown';
}

/**
 * @typedef {Object} PendingEvent
 * @property {'created'|'blocked'|'posted'|'acks'|'tick'|'retry'|'dismiss'} type
 * @property {number} [at]
 * @property {PendingCommand} [entry]        created, blocked
 * @property {string} [id]                   posted, retry, dismiss
 * @property {Object} [result]               posted: the api result
 * @property {Object<string, Object>} [acks] acks: latest record by command id, from a full snapshot
 */

/**
 * A pending command after the acknowledgement record with its id was read.
 * Only `applied` and `rejected` settle it. A record with another status is
 * kept for the screen and the command goes on waiting; a conflict over the id
 * never takes back an outcome that was already read.
 */
function acknowledged(entry, record, at) {
  if (entry.ack === record || entry.oddAck === record) return entry;
  if (!isOutcome(record)) {
    if (entry.ack || (entry.oddAck && entry.oddAck.status === record.status)) return entry;
    return {...entry, oddAck: record};
  }
  if (entry.ack && (record.reason === 'command_id_conflict'
    || (entry.ack.status === record.status && entry.ack.reason === record.reason))) return entry;
  return {...entry, phase: record.status, phaseAt: at, ack: record, oddAck: null, failure: null};
}

/**
 * @param {PendingCommand[]} pending
 * @param {PendingEvent} event
 * @returns {PendingCommand[]} the same array when nothing changed
 */
export function reducePending(pending, event) {
  const mapEntry = (id, change) => {
    let changed = false;
    const next = pending.map((entry) => {
      if (entry.id !== id) return entry;
      const updated = change(entry);
      if (updated !== entry) changed = true;
      return updated;
    });
    return changed ? next : pending;
  };

  switch (event.type) {
    case 'created':
    case 'blocked': {
      // A new command for the same type and target replaces the message of the previous, finished one.
      const kept = pending.filter((entry) => entry.type !== event.entry.type || entry.target !== event.entry.target
        || isUnresolved(entry.phase));
      const added = event.type === 'created'
        ? {...event.entry, phase: 'sending', attempts: 1, failure: null}
        : {...event.entry, phase: 'not_sent', attempts: 0};
      return [...kept, {...added, createdAt: event.at, phaseAt: event.at, maybeDelivered: false, ack: null, oddAck: null}];
    }
    case 'posted':
      return mapEntry(event.id, (entry) => {
        // An answer that arrives after the acknowledgement, or after a newer attempt was resolved, changes nothing.
        if (entry.phase !== 'sending') return entry;
        const phase = phaseAfterPost(event.result, entry.maybeDelivered);
        const failure = event.result.ok ? null
          : {kind: event.result.kind, status: typeof event.result.status === 'number' ? event.result.status : null};
        return {...entry, phase, phaseAt: event.at, failure, maybeDelivered: phase !== 'not_sent'};
      });
    case 'acks': {
      let changed = false;
      const next = pending.map((entry) => {
        const record = event.acks[entry.id];
        const updated = record ? acknowledged(entry, record, event.at) : entry;
        if (updated !== entry) changed = true;
        return updated;
      });
      return changed ? next : pending;
    }
    case 'tick': {
      let changed = false;
      const next = [];
      for (const entry of pending) {
        if (entry.phase === 'applied' && event.at - entry.phaseAt >= APPLIED_LINGER_MS) {
          changed = true;
        } else if (entry.phase === 'sent' && event.at - entry.phaseAt >= ACK_TIMEOUT_MS) {
          changed = true;
          next.push({...entry, phase: 'no_ack', phaseAt: event.at});
        } else {
          next.push(entry);
        }
      }
      return changed ? next : pending;
    }
    case 'retry':
      return mapEntry(event.id, (entry) => (canRetry(entry.phase)
        ? {...entry, phase: 'sending', phaseAt: event.at, attempts: entry.attempts + 1, failure: null}
        : entry));
    case 'dismiss':
      return pending.some((entry) => entry.id === event.id) ? pending.filter((entry) => entry.id !== event.id) : pending;
    default:
      return pending;
  }
}

/**
 * The store fields that follow from the others: are commands blocked, and why.
 * @param {State} state
 * @returns {{commandsBlocked: boolean, blockReason: (string|null)}}
 */
export function deriveBlock(state) {
  let blockReason = null;
  if (state.boot !== 'ready') blockReason = 'not_ready';
  else if (state.link.blocked) blockReason = state.link.blockReason;
  else if (hasOwnResetPending(state.pending)) blockReason = 'own_reset_pending';
  return {commandsBlocked: blockReason !== null, blockReason};
}

/**
 * @typedef {Object} SendResult
 * @property {boolean} ok        true: the POST was started
 * @property {string} [id]       the command id (also of the command that stands in the way)
 * @property {'blocked'|'duplicate'|'no_run'|'no_decision_id'|'not_retryable'|'unknown_command'} [reason]
 */

/**
 * @param {{store: import('./store.js').Store,
 *          api: {postCommand: (bodyText: string) => Promise<Object>},
 *          now: () => number}} deps
 */
export function createCommands({store, api, now}) {
  function dispatch(event) {
    const pending = reducePending(store.getState().pending, event);
    store.update({pending});
  }

  async function post(id, bodyText) {
    const result = await api.postCommand(bodyText);
    dispatch({type: 'posted', id, result, at: now()});
  }

  /**
   * Send a command for the run on the screen.
   * @param {string} type one of COMMAND_TYPES
   * @param {string} [target] local name; omitted for run.reset
   * @param {{decisionId: (string|undefined)}} [options] decision_id of the chosen option; by default the
   *        one the option twin publishes in the last full snapshot
   * @returns {SendResult}
   */
  function send(type, target = RESET_TARGET, options = {}) {
    const state = store.getState();
    const standing = findUnresolved(state.pending, type, target);
    if (standing) return {ok: false, reason: 'duplicate', id: standing.id};
    if (!state.snapshot) return {ok: false, reason: 'no_run'};

    let decisionId;
    if (type === 'action.execute_option') {
      const option = state.model ? state.model.byName[target] : null;
      decisionId = options.decisionId || (option ? option.values.decision_id : undefined);
      if (typeof decisionId !== 'string' || decisionId === '') return {ok: false, reason: 'no_decision_id'};
    }

    const id = newCommandId();
    const run = state.snapshot.run;
    const bodyText = JSON.stringify(buildBody({id, type, target, run, decisionId}));
    const entry = {id, type, target, run, bodyText};
    if (state.commandsBlocked) {
      dispatch({type: 'blocked', entry: {...entry, failure: {kind: 'blocked', status: null, reason: state.blockReason}}, at: now()});
      return {ok: false, reason: 'blocked', id};
    }
    dispatch({type: 'created', entry, at: now()});
    post(id, bodyText);
    return {ok: true, id};
  }

  /**
   * Send the same identifier and the same body again.
   * @param {string} id
   * @returns {SendResult}
   */
  function retry(id) {
    const state = store.getState();
    const entry = state.pending.find((item) => item.id === id);
    if (!entry) return {ok: false, reason: 'unknown_command'};
    if (!canRetry(entry.phase)) return {ok: false, reason: 'not_retryable', id};
    if (state.commandsBlocked) return {ok: false, reason: 'blocked', id};
    dispatch({type: 'retry', id, at: now()});
    post(id, entry.bodyText);
    return {ok: true, id};
  }

  /** Stop waiting for a command; nothing is sent and nothing is undone. */
  function dismiss(id) {
    dispatch({type: 'dismiss', id});
  }

  /** Called by the shared timer: the no-acknowledgement threshold and the departure of applied commands. */
  function tick() {
    if (store.getState().pending.length > 0) dispatch({type: 'tick', at: now()});
  }

  // Acknowledgements are matched on every new full snapshot, also after a run change:
  // the record of a reset appears only in the commands of the new run.
  store.watch((state) => state.model, (model) => {
    if (model && model.hasSnapshot && store.getState().pending.length > 0) {
      dispatch({type: 'acks', acks: model.acks, at: now()});
    }
  });

  return {send, retry, dismiss, tick};
}
