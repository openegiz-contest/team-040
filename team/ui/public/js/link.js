// The link state machine of team/CONTRACT.md, section 4. A pure reducer over
// poll events plus a derivation for a given moment. Time is always passed in
// (monotonic milliseconds), so thresholds can be re-derived while a fetch is
// still pending and the whole machine can be tested with scripted times.

import {
  POLL_INTERVAL_MS, PUBLICATIONS_STOPPED_AFTER_MS, REQUEST_TIMEOUT_MS, STALE_AFTER_MS, UNAVAILABLE_AFTER_FAILURES,
} from './config.js';

/** @typedef {import('./store.js').LinkStatus} LinkStatus */

/**
 * @typedef {Object} LinkState
 * @property {number|null} pollingSince  when polling of shift began; the "no snapshot" clock starts here
 * @property {number} failures           failed reads in a row
 * @property {{kind: string, status: (number|null)}|null} failure
 * @property {number|null} lastOkAt      the last read the platform answered
 * @property {number|null} lastFullAt    the last full snapshot
 * @property {number|null} seq           the last publication_seq read
 * @property {number|null} seqSeenAt     when that value was first read
 * @property {number|null} seqReadAt     when that value was read last
 * @property {number} seqBaseAgeMs       how old the publication already was when it was first read
 * @property {'ok'|'invalid'|'none'} snapshot
 * @property {Object|null} invalid       the rejection of the last answered read
 * @property {string|null} runState      run_state of the last full snapshot
 */

/**
 * @typedef {Object} LinkEvent
 * @property {'polling_started'|'poll_failed'|'poll_ok'|'answered'|'restart'} type
 * @property {number} at
 * @property {string} [kind]             poll_failed: timeout | network | http | body | incomplete
 * @property {number|null} [status]      poll_failed: HTTP status
 * @property {number|null} [seq]         poll_ok: publication_seq if it could be read
 * @property {number|null} [dateMs]      poll_ok: HTTP Date
 * @property {number|null} [modifiedMs]  poll_ok: _modified of shift
 * @property {boolean} [full]            poll_ok: the read is a full snapshot
 * @property {Object|null} [rejection]   poll_ok and not full: {code, params, detail}
 * @property {string|null} [runState]    poll_ok and full
 */

/** @returns {LinkState} */
export function initialLink() {
  return {
    pollingSince: null, failures: 0, failure: null, lastOkAt: null, lastFullAt: null,
    seq: null, seqSeenAt: null, seqReadAt: null, seqBaseAgeMs: 0, snapshot: 'none', invalid: null, runState: null,
  };
}

/**
 * Age of a publication at the moment it is first read: HTTP Date minus
 * _modified, never negative. Both values are the platform's own clock. The
 * header is cut to the whole second, so the difference never overstates the
 * age; nothing more is taken off.
 */
export function initialAgeMs(dateMs, modifiedMs) {
  if (typeof dateMs !== 'number' || typeof modifiedMs !== 'number') return 0;
  return Math.max(0, dateMs - modifiedMs);
}

/**
 * @param {LinkState} state
 * @param {LinkEvent} event
 * @returns {LinkState}
 */
export function reduceLink(state, event) {
  switch (event.type) {
    case 'restart':
      return initialLink();
    case 'polling_started':
      return {...state, pollingSince: event.at};
    case 'answered':
      // The platform answered a read that is not a poll of shift (boot reads, an empty stand).
      return {...state, failures: 0, failure: null, lastOkAt: event.at};
    case 'poll_failed':
      return {
        ...state,
        failures: state.failures + 1,
        failure: {kind: event.kind, status: typeof event.status === 'number' ? event.status : null},
      };
    case 'poll_ok': {
      const next = {...state, failures: 0, failure: null, lastOkAt: event.at};
      if (typeof event.seq === 'number') {
        // A number that is new to this page is not a new publication: after an outage the platform may
        // return a state it kept for a minute. Its age comes from the two clocks of the answer, every time.
        if (event.seq !== state.seq) {
          next.seq = event.seq;
          next.seqSeenAt = event.at;
          next.seqBaseAgeMs = initialAgeMs(event.dateMs, event.modifiedMs);
        }
        next.seqReadAt = event.at;
      }
      if (event.full) {
        next.lastFullAt = event.at;
        next.snapshot = 'ok';
        next.invalid = null;
        next.runState = event.runState || null;
      } else {
        next.snapshot = 'invalid';
        next.invalid = event.rejection || null;
      }
      return next;
    }
    default:
      return state;
  }
}

/**
 * The status at the moment `now`.
 * @param {LinkState} state
 * @param {number} now
 * @returns {LinkStatus}
 */
export function deriveLink(state, now) {
  const fullAgeMs = state.lastFullAt === null ? null : now - state.lastFullAt;
  const seqAgeMs = state.seq === null ? null : state.seqBaseAgeMs + (now - state.seqSeenAt);

  let withoutFullMs = 0;
  if (fullAgeMs !== null) withoutFullMs = fullAgeMs;
  else if (state.pollingSince !== null) withoutFullMs = now - state.pollingSince;

  let link = 'ok';
  if (state.failures >= UNAVAILABLE_AFTER_FAILURES) link = 'unavailable';
  else if (withoutFullMs >= STALE_AFTER_MS) link = 'stale';
  else if (state.failures >= 1) link = 'degraded';

  // Whether publications go on is known only while reads are answered. A stop that the last answered
  // read had already shown stays a stop through failed and pending reads: only a new number ends it.
  const answeredRecently = state.failures === 0 && state.lastOkAt !== null
    && now - state.lastOkAt <= REQUEST_TIMEOUT_MS + POLL_INTERVAL_MS;
  const stoppedWhenLastRead = state.seq !== null
    && state.seqBaseAgeMs + (state.seqReadAt - state.seqSeenAt) >= PUBLICATIONS_STOPPED_AFTER_MS;
  let publications = 'unknown';
  if (stoppedWhenLastRead) publications = 'stopped';
  else if (answeredRecently && seqAgeMs !== null) {
    publications = seqAgeMs >= PUBLICATIONS_STOPPED_AFTER_MS ? 'stopped' : 'alive';
  }

  let blockReason = null;
  if (link === 'unavailable') blockReason = 'platform_unavailable';
  else if (state.snapshot === 'none') blockReason = 'no_snapshot';
  else if (state.snapshot === 'invalid') blockReason = 'snapshot_invalid';
  else if (link === 'stale') blockReason = 'stale';
  else if (publications === 'stopped') blockReason = 'publications_stopped';
  else if (state.runState === 'resetting') blockReason = 'resetting';

  // The shown state is as old as the older of: the last full read, the last new publication.
  let dataAgeS = null;
  if (fullAgeMs !== null) dataAgeS = Math.floor(Math.max(fullAgeMs, seqAgeMs === null ? 0 : seqAgeMs) / 1000);

  return {
    link, publications,
    snapshot: state.snapshot,
    failure: link === 'ok' ? null : state.failure,
    invalid: state.invalid,
    dataAgeS,
    blocked: blockReason !== null,
    blockReason,
  };
}

/**
 * True when two statuses would look the same on the screen.
 * @param {LinkStatus} a
 * @param {LinkStatus} b
 */
export function sameLinkStatus(a, b) {
  return a.link === b.link && a.publications === b.publications && a.snapshot === b.snapshot
    && a.dataAgeS === b.dataAgeS && a.blocked === b.blocked && a.blockReason === b.blockReason
    && (a.invalid === b.invalid || (a.invalid !== null && b.invalid !== null
      && a.invalid.code === b.invalid.code && a.invalid.detail === b.invalid.detail))
    && (a.failure === b.failure || (a.failure !== null && b.failure !== null
      && a.failure.kind === b.failure.kind && a.failure.status === b.failure.status));
}

/**
 * True when the screen shows a state that is known not to be current: the
 * centre is marked with the time of the last full snapshot and nothing moves.
 * @param {LinkStatus} status
 */
export function showsOldData(status) {
  return status.link === 'stale' || status.link === 'unavailable' || status.snapshot === 'invalid'
    || status.publications === 'stopped';
}
