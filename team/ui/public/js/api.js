// The only network code of the interface: the four reads and the command POST
// of team/CONTRACT.md, sections 2 and 3, on the page's own origin.

import {
  ATTR_BATCH, COMMAND_PATH, FIELDS_ATTRIBUTES, FIELDS_RUN, FIELDS_SHIFT, ID_PATTERN, LOCAL_NAME_PATTERN,
  MINE_ID, NAMESPACE, REQUEST_TIMEOUT_MS, SHIFT_ID, THINGS_PATH,
} from './config.js';

/**
 * @typedef {Object} ApiOk
 * @property {true} ok
 * @property {number} status
 * @property {*} body            parsed JSON; null for an empty body
 * @property {number|null} dateMs  the HTTP Date header as epoch milliseconds; null when absent or unparsable
 */

/**
 * @typedef {Object} ApiFailure
 * @property {false} ok
 * @property {'timeout'|'network'|'http'|'body'|'incomplete'} kind
 *           timeout: no complete answer in REQUEST_TIMEOUT_MS; network: the request failed;
 *           http: a status outside 2xx; body: 2xx with a body that is not the expected JSON;
 *           incomplete: a batch did not return every requested id exactly once
 * @property {number|null} status
 * @property {*} [body]          http: the parsed error body when there is one
 * @property {string[]} [missing]    incomplete
 * @property {string[]} [duplicate]  incomplete
 * @property {string[]} [extra]      incomplete
 */

/** @typedef {ApiOk|ApiFailure} ApiResult */

function parseJson(text) {
  if (text.trim() === '') return {ok: true, value: null};
  try {
    return {ok: true, value: JSON.parse(text)};
  } catch {
    return {ok: false};
  }
}

/**
 * @param {string} url same-origin path
 * @param {{method: (string|undefined), bodyText: (string|undefined), timeoutMs: (number|undefined)}} [options]
 * @returns {Promise<ApiResult>}
 */
async function request(url, {method = 'GET', bodyText, timeoutMs = REQUEST_TIMEOUT_MS} = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = {Accept: 'application/json'};
    if (bodyText !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(url, {
      method, headers, body: bodyText, signal: controller.signal, cache: 'no-store', credentials: 'same-origin',
    });
    // The body is read under the same timeout: headers alone are not an answer.
    const parsed = parseJson(await response.text());
    const date = Date.parse(response.headers.get('Date') || '');
    if (!response.ok) {
      return {ok: false, kind: 'http', status: response.status, body: parsed.ok ? parsed.value : null};
    }
    if (!parsed.ok) return {ok: false, kind: 'body', status: response.status};
    return {ok: true, status: response.status, body: parsed.value, dateMs: Number.isFinite(date) ? date : null};
  } catch {
    return {ok: false, kind: controller.signal.aborted ? 'timeout' : 'network', status: null};
  } finally {
    clearTimeout(timer);
  }
}

function chunks(items, size) {
  const parts = [];
  for (let start = 0; start < items.length; start += size) parts.push(items.slice(start, start + size));
  return parts;
}

/**
 * Read twins by id in batches of at most ATTR_BATCH. The answer of a batch may
 * come in any order; it is accepted only if every requested id is there once.
 * @param {string[]} ids full thingIds
 * @param {string} fields
 * @returns {Promise<ApiOk|ApiFailure>} body: the twins in the order of `ids`
 */
async function readThings(ids, fields) {
  const unsafe = ids.filter((id) => !ID_PATTERN.test(id));
  if (unsafe.length > 0) return {ok: false, kind: 'incomplete', status: null, missing: unsafe, duplicate: [], extra: []};
  const byId = new Map();
  let dateMs = null;
  for (const batch of chunks(ids, ATTR_BATCH)) {
    const result = await request(`${THINGS_PATH}?ids=${batch.join(',')}&fields=${fields}`);
    if (!result.ok) return result;
    if (!Array.isArray(result.body)) return {ok: false, kind: 'body', status: result.status};
    const asked = new Set(batch);
    const seen = new Set();
    const duplicate = [];
    const extra = [];
    for (const thing of result.body) {
      const id = thing && typeof thing === 'object' ? thing.thingId : undefined;
      if (!asked.has(id)) extra.push(String(id));
      else if (seen.has(id)) duplicate.push(id);
      else {
        seen.add(id);
        byId.set(id, thing);
      }
    }
    const missing = batch.filter((id) => !seen.has(id));
    if (missing.length > 0 || duplicate.length > 0 || extra.length > 0) {
      return {ok: false, kind: 'incomplete', status: result.status, missing, duplicate, extra};
    }
    dateMs = result.dateMs;
  }
  return {ok: true, status: 200, body: ids.map((id) => byId.get(id)), dateMs};
}

/** @typedef {ReturnType<typeof createApi>} Api */

export function createApi() {
  return {
    /** Attributes of the mine twin. HTTP 404 means the stand has no twins of the team. */
    readMine: () => request(`${THINGS_PATH}/${MINE_ID}?fields=${FIELDS_ATTRIBUTES}`),

    /** Attributes of the manifest twins. @param {string[]} ids full thingIds */
    readAttributes: (ids) => readThings(ids, FIELDS_ATTRIBUTES),

    /** One poll of shift: features with the consistent scene, and the Ditto metadata. */
    readShift: () => request(`${THINGS_PATH}/${SHIFT_ID}?fields=${FIELDS_SHIFT}`),

    /** Archived run twins. @param {string[]} names local names from shift.runs */
    readRuns: (names) => {
      const unsafe = names.filter((name) => typeof name !== 'string' || !LOCAL_NAME_PATTERN.test(name));
      if (unsafe.length > 0) {
        return Promise.resolve({ok: false, kind: 'incomplete', status: null, missing: unsafe.map(String), duplicate: [], extra: []});
      }
      return readThings(names.map((name) => `${NAMESPACE}:${name}`), FIELDS_RUN);
    },

    /** Send a command. @param {string} bodyText the JSON body, sent as is */
    postCommand: (bodyText) => request(COMMAND_PATH, {method: 'POST', bodyText}),
  };
}
