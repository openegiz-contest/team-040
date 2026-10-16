// Validation of what the platform returned (team/CONTRACT.md, section 2). Pure:
// no DOM, no network, no clock. A rejection carries a code, the parameters a
// text can be built from (text.js) and an English `detail` for diagnostics.

import {CONTRACT_VERSION, ID_PATTERN, LOCAL_NAME_PATTERN, MINE_ID} from './config.js';

/** @typedef {import('./store.js').Attributes} Attributes */
/** @typedef {import('./store.js').Snapshot} Snapshot */
/** @typedef {import('./store.js').Features} Features */

/**
 * @typedef {Object} Rejection
 * @property {false} ok
 * @property {'no_metadata'|'contract_version'|'topology_mismatch'|'scene_missing_id'|'scene_extra_id'|
 *            'scene_duplicate_id'|'scene_mixed_tick'|'scene_mixed_run'|'missing_field'|'malformed'|
 *            'manifest_incomplete'} code
 * @property {Object} params   thing, field, ids, expected, actual: whatever the code needs
 * @property {string} detail
 */

/**
 * What can be read from a shift response even when it is not a full snapshot.
 * @typedef {Object} ShiftInfo
 * @property {number|null} seq
 * @property {string|null} run
 * @property {number|null} tick
 * @property {string|null} runState
 * @property {string|null} topologyVersion
 * @property {number|null} modifiedMs
 */

const SHIFT_REQUIRED = {
  contract_version: 'number', publication_seq: 'number', tick: 'number', sim_time_s: 'number',
  idSimulationRun: 'string', run_state: 'string', pause_reason: 'string', speedup: 'number', seed: 'number',
  topology_version: 'string', conditions: 'array', workers_total: 'number', workers_out: 'number',
  workers_in_danger: 'number', workers_no_route: 'number', workers_unknown: 'number',
  commands: 'array', runs: 'array', scene: 'array',
};

const SCENE_COMMON = {tick: 'number', sim_time_s: 'number', idSimulationRun: 'string'};

const KIND_REQUIRED = {
  working: {passability: 'string', hazard_state: 'string', data_quality: 'string'},
  zone: {work_state: 'string', withdrawal_state: 'string', hazard_state: 'string', data_quality: 'string'},
  sensor: {quality: 'string', link_state: 'string', measured_at_tick: 'number'},
  worker: {status: 'string', egress_status: 'string'},
  exit: {state: 'string'},
  incident: {state: 'string'},
  option: {state: 'string'},
  journal: {last_seq: 'number', events: 'array'},
  // Equipment twins (CONTRACT.md §9): a machine always has a state and a place on a working (it never leaves the mine).
  equipment: {state: 'string', at_working: 'string', offset_m: 'number'},
};

/** A worker with one of these statuses has no position on a working. */
const WORKER_WITHOUT_POSITION = new Set(['out', 'unknown']);
const WORKER_POSITION = {at_working: 'string', offset_m: 'number'};

function reject(code, params, detail) {
  return {ok: false, code, params, detail};
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasType(value, type) {
  if (type === 'array') return Array.isArray(value);
  if (type === 'number') return typeof value === 'number' && Number.isFinite(value);
  return typeof value === type;
}

/** The published value of a feature, or undefined when the feature is absent. */
function valueOf(features, name) {
  const feature = features[name];
  return isObject(feature) && isObject(feature.properties) ? feature.properties.value : undefined;
}

/**
 * @param {Object} features
 * @param {Object<string, string>} required
 * @param {string} thing local name, for the message
 * @returns {Rejection|null}
 */
function checkFields(features, required, thing) {
  for (const [field, type] of Object.entries(required)) {
    const value = valueOf(features, field);
    if (value === undefined) {
      return reject('missing_field', {thing, field}, `${thing}: required feature ${field} is absent`);
    }
    if (!hasType(value, type)) {
      return reject('malformed', {thing, field, expected: type},
        `${thing}: feature ${field} is not a ${type}`);
    }
  }
  return null;
}

/**
 * Ditto features to plain values and units. A feature without a value is skipped.
 * @param {Object} features
 * @param {string} [skip] a feature name left out
 * @returns {Features}
 */
export function plainFeatures(features, skip) {
  const values = {};
  const units = {};
  for (const [name, feature] of Object.entries(features || {})) {
    if (name === skip || !isObject(feature) || !isObject(feature.properties)) continue;
    const {value, unit} = feature.properties;
    if (value === undefined || value === null) continue;
    values[name] = value;
    if (typeof unit === 'string') units[name] = unit;
  }
  return {values, units};
}

/**
 * One cause of an incident as {trigger, subject}. The contract draft lists records
 * {trigger, subject, tick}; the simulation publishes a text "trigger:subject" ("hazard:zone-a",
 * "passage_closed:w-04"). Both are read; a text without a colon and anything else is returned as it
 * came (the readers skip what is not an object).
 * @param {*} cause
 */
export function normalizeCause(cause) {
  if (typeof cause !== 'string') return cause;
  const at = cause.indexOf(':');
  return at < 0 ? cause : {trigger: cause.slice(0, at), subject: cause.slice(at + 1)};
}

/** @param {string} thingId */
export function localName(thingId) {
  const at = thingId.indexOf(':');
  return at < 0 ? thingId : thingId.slice(at + 1);
}

function isIdList(value) {
  return Array.isArray(value) && value.every((id) => typeof id === 'string' && ID_PATTERN.test(id))
    && new Set(value).size === value.length;
}

/**
 * Check the mine twin before anything else is read.
 * @param {*} thing the body of the mine read
 * @returns {{ok: true, attrs: Object, manifest: string[], dynamicIds: string[], topologyVersion: string}|Rejection}
 */
export function validateMine(thing) {
  if (!isObject(thing) || !isObject(thing.attributes)) {
    return reject('malformed', {thing: 'mine', field: 'attributes'}, 'mine: no attributes object');
  }
  const attrs = thing.attributes;
  if (attrs.contract_version === undefined) {
    return reject('missing_field', {thing: 'mine', field: 'contract_version'}, 'mine: attribute contract_version is absent');
  }
  if (attrs.contract_version !== CONTRACT_VERSION) {
    return reject('contract_version', {expected: CONTRACT_VERSION, actual: attrs.contract_version, where: 'mine'},
      `mine: contract_version ${JSON.stringify(attrs.contract_version)}, supported ${CONTRACT_VERSION}`);
  }
  for (const field of ['manifest', 'dynamic_ids']) {
    if (attrs[field] === undefined) {
      return reject('missing_field', {thing: 'mine', field}, `mine: attribute ${field} is absent`);
    }
    if (!isIdList(attrs[field])) {
      return reject('malformed', {thing: 'mine', field, expected: 'array'},
        `mine: attribute ${field} is not a list of distinct thingIds`);
    }
  }
  if (typeof attrs.topology_version !== 'string') {
    return reject(attrs.topology_version === undefined ? 'missing_field' : 'malformed',
      {thing: 'mine', field: 'topology_version', expected: 'string'}, 'mine: attribute topology_version is not a string');
  }
  if (!isObject(attrs.nodes)) {
    return reject(attrs.nodes === undefined ? 'missing_field' : 'malformed',
      {thing: 'mine', field: 'nodes', expected: 'object'}, 'mine: attribute nodes is not an object');
  }
  const outside = attrs.dynamic_ids.filter((id) => !attrs.manifest.includes(id));
  if (outside.length > 0) {
    return reject('malformed', {thing: 'mine', field: 'dynamic_ids', ids: outside},
      `mine: dynamic_ids not in manifest: ${outside.join(', ')}`);
  }
  return {
    ok: true, attrs, manifest: attrs.manifest, dynamicIds: attrs.dynamic_ids,
    topologyVersion: attrs.topology_version,
  };
}

/**
 * Join the mine attributes and the batch results into the Attributes of the store.
 * @param {{attrs: Object, manifest: string[], dynamicIds: string[], topologyVersion: string}} mine a validateMine result
 * @param {Array<{thingId: string, attributes: Object}>} things every manifest twin, any order
 * @returns {{ok: true, attributes: Attributes}|Rejection}
 */
export function buildAttributes(mine, things) {
  const byId = {};
  for (const thing of things) {
    if (isObject(thing) && typeof thing.thingId === 'string') byId[thing.thingId] = thing.attributes;
  }
  byId[MINE_ID] = mine.attrs;
  const missing = mine.manifest.filter((id) => !(id in byId));
  if (missing.length > 0) {
    return reject('manifest_incomplete', {ids: missing, total: mine.manifest.length},
      `attributes of ${missing.length} manifest twins were not returned: ${missing.join(', ')}`);
  }
  const ordered = {};
  for (const id of mine.manifest) {
    if (!isObject(byId[id]) || typeof byId[id].kind !== 'string') {
      return reject('malformed', {thing: localName(id), field: 'kind', expected: 'string'},
        `${localName(id)}: attributes have no kind`);
    }
    ordered[id] = byId[id];
  }
  ordered[MINE_ID] = mine.attrs;
  return {
    ok: true,
    attributes: {
      mine: mine.attrs, things: ordered, topologyVersion: mine.topologyVersion,
      manifest: mine.manifest, dynamicIds: mine.dynamicIds,
    },
  };
}

function parseTime(text) {
  if (typeof text !== 'string') return null;
  const ms = Date.parse(text);
  return Number.isFinite(ms) ? ms : null;
}

/**
 * Read what is readable from a shift body without judging it.
 * @param {*} body
 * @returns {ShiftInfo}
 */
export function peekShift(body) {
  const features = isObject(body) && isObject(body.features) ? body.features : {};
  const pick = (name, type) => {
    const value = valueOf(features, name);
    return hasType(value, type) ? value : null;
  };
  return {
    seq: pick('publication_seq', 'number'),
    run: pick('idSimulationRun', 'string'),
    tick: pick('tick', 'number'),
    runState: pick('run_state', 'string'),
    topologyVersion: pick('topology_version', 'string'),
    modifiedMs: isObject(body) ? parseTime(body._modified) : null,
  };
}

/**
 * Decide whether a poll result is a full snapshot.
 * @param {{body: *, dateMs: (number|null)}} response a successful read of shift
 * @param {Attributes} attributes
 * @returns {({ok: true, snapshot: Snapshot}|Rejection) & {info: ShiftInfo}}
 */
export function validateShift(response, attributes) {
  const info = peekShift(response.body);
  const result = checkShift(response, attributes, info);
  return {...result, info};
}

function checkShift(response, attributes, info) {
  const body = response.body;
  if (!isObject(body) || !isObject(body.features)) {
    return reject('malformed', {thing: 'shift', field: 'features', expected: 'object'}, 'shift: no features object');
  }
  if (typeof response.dateMs !== 'number' || !Number.isFinite(response.dateMs)) {
    return reject('no_metadata', {field: 'Date'}, 'shift: the response has no parsable Date header');
  }
  if (info.modifiedMs === null) {
    return reject('no_metadata', {field: '_modified'}, 'shift: _modified is absent or not a time');
  }
  if (!hasType(body._revision, 'number')) {
    return reject('no_metadata', {field: '_revision'}, 'shift: _revision is absent or not a number');
  }
  const features = body.features;

  // The version first: the other rules describe version 1 only.
  const version = valueOf(features, 'contract_version');
  if (version === undefined) {
    return reject('missing_field', {thing: 'shift', field: 'contract_version'}, 'shift: required feature contract_version is absent');
  }
  if (version !== CONTRACT_VERSION) {
    return reject('contract_version', {expected: CONTRACT_VERSION, actual: version, where: 'shift'},
      `shift: contract_version ${JSON.stringify(version)}, supported ${CONTRACT_VERSION}`);
  }
  const broken = checkFields(features, SHIFT_REQUIRED, 'shift');
  if (broken) return broken;

  const run = valueOf(features, 'idSimulationRun');
  if (!LOCAL_NAME_PATTERN.test(run)) {
    return reject('malformed', {thing: 'shift', field: 'idSimulationRun', expected: 'string'}, 'shift: idSimulationRun is not a local name');
  }
  const topologyVersion = valueOf(features, 'topology_version');
  if (topologyVersion !== attributes.topologyVersion) {
    return reject('topology_mismatch', {attributes: attributes.topologyVersion, shift: topologyVersion},
      `topology_version: attributes ${attributes.topologyVersion}, shift ${topologyVersion}`);
  }

  const tick = valueOf(features, 'tick');
  const simTimeS = valueOf(features, 'sim_time_s');
  const elements = valueOf(features, 'scene');
  const expected = new Set(attributes.dynamicIds);
  const seen = new Map();
  for (const element of elements) {
    if (!isObject(element) || typeof element.thingId !== 'string' || !isObject(element.features)) {
      return reject('malformed', {thing: 'shift', field: 'scene', expected: 'array'},
        'shift: a scene element is not {thingId, features}');
    }
    if (seen.has(element.thingId)) {
      return reject('scene_duplicate_id', {ids: [element.thingId]}, `scene holds ${element.thingId} more than once`);
    }
    seen.set(element.thingId, element.features);
  }
  const missing = attributes.dynamicIds.filter((id) => !seen.has(id));
  if (missing.length > 0) {
    return reject('scene_missing_id', {ids: missing}, `scene lacks ${missing.join(', ')}`);
  }
  const extra = [...seen.keys()].filter((id) => !expected.has(id));
  if (extra.length > 0) {
    return reject('scene_extra_id', {ids: extra}, `scene holds ids outside dynamic_ids: ${extra.join(', ')}`);
  }

  const scene = {};
  for (const id of attributes.dynamicIds) {
    const elementFeatures = seen.get(id);
    const name = localName(id);
    const common = checkFields(elementFeatures, SCENE_COMMON, name);
    if (common) return common;
    const elementRun = valueOf(elementFeatures, 'idSimulationRun');
    if (elementRun !== run) {
      return reject('scene_mixed_run', {thing: name, expected: run, actual: elementRun},
        `${name}: idSimulationRun ${elementRun}, shift ${run}`);
    }
    const elementTick = valueOf(elementFeatures, 'tick');
    if (elementTick !== tick) {
      return reject('scene_mixed_tick', {thing: name, field: 'tick', expected: tick, actual: elementTick},
        `${name}: tick ${elementTick}, shift ${tick}`);
    }
    const elementTime = valueOf(elementFeatures, 'sim_time_s');
    if (elementTime !== simTimeS) {
      return reject('scene_mixed_tick', {thing: name, field: 'sim_time_s', expected: simTimeS, actual: elementTime},
        `${name}: sim_time_s ${elementTime}, shift ${simTimeS}`);
    }
    const kind = attributes.things[id] ? attributes.things[id].kind : null;
    const fields = checkFields(elementFeatures, KIND_REQUIRED[kind] || {}, name);
    if (fields) return fields;
    if (kind === 'worker' && !WORKER_WITHOUT_POSITION.has(valueOf(elementFeatures, 'status'))) {
      const position = checkFields(elementFeatures, WORKER_POSITION, name);
      if (position) return position;
    }
    scene[id] = plainFeatures(elementFeatures);
    if (kind === 'incident' && Array.isArray(scene[id].values.causes)) {
      scene[id].values.causes = scene[id].values.causes.map(normalizeCause);
    }
  }

  return {
    ok: true,
    snapshot: {
      run, tick, simTimeS,
      seq: valueOf(features, 'publication_seq'),
      runState: valueOf(features, 'run_state'),
      pauseReason: valueOf(features, 'pause_reason'),
      topologyVersion,
      modified: body._modified,
      modifiedMs: info.modifiedMs,
      revision: body._revision,
      dateMs: response.dateMs,
      shift: plainFeatures(features, 'scene'),
      scene,
    },
  };
}

/**
 * The runs of the archive as local names, oldest first, each once. The
 * contract does not say whether shift.runs holds local names or full
 * thingIds: both are accepted.
 * @param {*} runs value of shift.runs
 * @returns {string[]}
 */
export function runNames(runs) {
  const names = (Array.isArray(runs) ? runs : []).filter((name) => typeof name === 'string').map(localName);
  return [...new Set(names)];
}

/**
 * A run twin of the archive in plain form: a named value is taken from features first, then attributes.
 * @param {{thingId: string, attributes: (Object|undefined), features: (Object|undefined)}} thing
 * @returns {import('./store.js').ArchiveRun}
 */
export function plainRun(thing) {
  const attributes = isObject(thing.attributes) ? thing.attributes : {};
  const {values, units} = plainFeatures(thing.features);
  const name = localName(thing.thingId);
  return {
    thingId: thing.thingId,
    name,
    label: typeof attributes.label === 'string' ? attributes.label : name,
    values: {...attributes, ...values},
    units,
  };
}
