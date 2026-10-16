// The view model: attributes and one full snapshot joined into what views
// read. Pure. Nothing is computed that the platform did not publish; the only
// display rule lives in displayedHazard(). No drawing and no geometry here.

import {MINE_ID, NAMESPACE, SHIFT_ID} from './config.js';
import {localName, normalizeCause} from './validate.js';

/** @typedef {import('./store.js').Attributes} Attributes */
/** @typedef {import('./store.js').Snapshot} Snapshot */
/** @typedef {import('./store.js').Model} Model */
/** @typedef {import('./store.js').Thing} Thing */
/** @typedef {import('./store.js').DisplayedHazard} DisplayedHazard */
/** @typedef {import('./store.js').Condition} Condition */

export {localName};

/** @param {string} name local name @returns {string} full thingId */
export function fullId(name) {
  return `${NAMESPACE}:${name}`;
}

const HAZARD_STATES = new Set(['normal', 'attention', 'danger', 'unknown']);

/**
 * The hazard that is drawn. Published `normal` counts only with fresh data;
 * a code outside the vocabulary and an absent value are unknown, never normal.
 * @param {Object<string, *>} values features of a working or a zone
 * @returns {DisplayedHazard}
 */
export function displayedHazard(values) {
  const raw = typeof values.hazard_state === 'string' ? values.hazard_state : null;
  if (raw === null || !HAZARD_STATES.has(raw)) {
    return {state: 'unknown', raw, known: raw === null, defensive: false};
  }
  if (raw === 'normal' && values.data_quality !== 'fresh') {
    return {state: 'unknown', raw, known: true, defensive: true};
  }
  return {state: raw, raw, known: true, defensive: false};
}

/**
 * A hazard code that is not paired with a data quality (worker.location_hazard, egress_crosses).
 * @param {*} code
 * @returns {'normal'|'attention'|'danger'|'unknown'}
 */
export function knownHazard(code) {
  return HAZARD_STATES.has(code) ? code : 'unknown';
}

/** Commands that set and cancel each scenario condition, and the kind of their target. */
export const CONDITION_COMMANDS = {
  working_closed: {set: 'condition.close_working', undo: 'condition.open_working', targetKind: 'working'},
  sensor_lost: {set: 'condition.sensor_lost', undo: 'condition.sensor_restored', targetKind: 'sensor'},
  instability: {set: 'condition.instability_on', undo: 'condition.instability_off', targetKind: 'zone'},
};

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

/**
 * One entry of shift.conditions to its parts. Total: the text "working_closed:w-07"
 * and an object with `kind` (or `type`) and `target` give the same condition;
 * anything else is kept as an entry of an unknown form, named by its JSON text.
 * @param {*} raw
 * @returns {Condition}
 */
export function parseCondition(raw) {
  let kind = null;
  let target = '';
  if (typeof raw === 'string') {
    const at = raw.indexOf(':');
    kind = at < 0 ? raw : raw.slice(0, at);
    target = at < 0 ? '' : raw.slice(at + 1);
  } else if (isObject(raw) && typeof raw.target === 'string') {
    if (typeof raw.kind === 'string') kind = raw.kind;
    else if (typeof raw.type === 'string') kind = raw.type;
    target = raw.target;
  }
  if (kind === null) return {raw: String(JSON.stringify(raw)), kind: '', target: '', undoType: null};
  const commands = Object.prototype.hasOwnProperty.call(CONDITION_COMMANDS, kind) ? CONDITION_COMMANDS[kind] : null;
  // The text form is kept as it came; the object form gets the same key.
  const key = typeof raw === 'string' ? raw : `${kind}:${target}`;
  return {raw: key, kind, target, undoType: commands && target ? commands.undo : null};
}

/**
 * The conditions of shift, each once: a repeated entry (or the same condition
 * in both forms) is one condition, so `raw` is a key no view sees twice.
 * @param {*} conditions value of shift.conditions
 * @returns {Condition[]}
 */
export function parseConditions(conditions) {
  const byKey = new Map();
  for (const entry of Array.isArray(conditions) ? conditions : []) {
    const condition = parseCondition(entry);
    if (!byKey.has(condition.raw)) byKey.set(condition.raw, condition);
  }
  return [...byKey.values()];
}

/** True for a record that settles a command: the model applied it or refused it. */
export function isOutcome(record) {
  return record.status === 'applied' || record.status === 'rejected';
}

/**
 * The acknowledgement record that counts for every command id. The window may
 * hold several records with one id. A later record replaces an earlier one,
 * with two exceptions that keep a settled outcome: a `command_id_conflict`
 * (somebody reused the id with another body; the first command stays applied
 * or rejected as it was) and a record whose status is outside the contract.
 * @param {*} commands value of shift.commands
 * @returns {Object<string, Object>}
 */
export function latestAcks(commands) {
  const acks = {};
  if (!Array.isArray(commands)) return acks;
  for (const record of commands) {
    if (!isObject(record) || typeof record.id !== 'string') continue;
    const kept = Object.prototype.hasOwnProperty.call(acks, record.id) ? acks[record.id] : null;
    if (kept && isOutcome(kept) && (record.reason === 'command_id_conflict' || !isOutcome(record))) continue;
    acks[record.id] = record;
  }
  return acks;
}

/**
 * The causes of an incident that can be read: records {trigger, subject, tick} and the texts
 * "trigger:subject" of the simulation (the snapshot already holds them as records; see
 * normalizeCause). A cause of another form is skipped, never dereferenced.
 * @param {Object<string, *>} values features of the incident
 * @returns {Array<{trigger: *, subject: *, tick: *}>}
 */
export function causesOf(values) {
  return Array.isArray(values.causes) ? values.causes.map(normalizeCause).filter(isObject) : [];
}

/**
 * A published route as oriented segments. Both forms of the contract are
 * accepted: local names of workings (the first is the current one, walked
 * towards `nextNode`) and objects {working, from, to}. For the name form the
 * direction of each working follows from the node it shares with the one
 * before; `from`/`to` are null where the attributes do not tell.
 * @param {*} route value of worker.route
 * @param {string|null} nextNode value of worker.route_next_node
 * @param {(name: string) => ({from: string, to: string}|null)} endsOf ends of a working from its attributes
 * @returns {Array<{working: string, from: (string|null), to: (string|null)}>}
 */
export function normalizeRoute(route, nextNode, endsOf) {
  if (!Array.isArray(route)) return [];
  const segments = [];
  let towards = typeof nextNode === 'string' ? nextNode : null;
  for (const item of route) {
    if (item && typeof item === 'object' && typeof item.working === 'string') {
      const from = typeof item.from === 'string' ? item.from : null;
      const to = typeof item.to === 'string' ? item.to : null;
      segments.push({working: item.working, from, to});
      towards = null;
      continue;
    }
    if (typeof item !== 'string') continue;
    const ends = endsOf(item);
    let from = null;
    let to = null;
    if (ends && segments.length === 0 && towards !== null) {
      if (ends.to === towards) [from, to] = [ends.from, ends.to];
      else if (ends.from === towards) [from, to] = [ends.to, ends.from];
    } else if (ends && segments.length > 0) {
      const entered = segments[segments.length - 1].to;
      if (ends.from === entered) [from, to] = [ends.from, ends.to];
      else if (ends.to === entered) [from, to] = [ends.to, ends.from];
    }
    segments.push({working: item, from, to});
  }
  return segments;
}

/**
 * @param {Attributes} attributes
 * @param {Snapshot|null} snapshot the last full snapshot; null gives twins without state
 * @returns {Model}
 */
export function buildModel(attributes, snapshot) {
  const things = {};
  const byKind = {};
  const byName = {};
  const none = {values: {}, units: {}};
  for (const thingId of attributes.manifest) {
    const attrs = attributes.things[thingId];
    let features = null;
    if (snapshot) features = thingId === SHIFT_ID ? snapshot.shift : (snapshot.scene[thingId] || null);
    const name = localName(thingId);
    /** @type {Thing} */
    const thing = {
      thingId, name,
      kind: attrs.kind,
      label: typeof attrs.label === 'string' && attrs.label ? attrs.label : name,
      attrs,
      values: (features || none).values,
      units: (features || none).units,
      hasState: features !== null,
    };
    if (thing.kind === 'working' || thing.kind === 'zone') thing.hazard = displayedHazard(thing.values);
    things[thingId] = thing;
    byName[name] = thing;
    (byKind[thing.kind] = byKind[thing.kind] || []).push(thing);
  }
  const shift = things[SHIFT_ID] || null;
  const shiftValues = snapshot ? snapshot.shift.values : {};
  return {
    things, byKind, byName, shift,
    conditions: parseConditions(shiftValues.conditions),
    acks: latestAcks(shiftValues.commands),
    hasSnapshot: snapshot !== null,
  };
}

/** @param {Model} model @param {string} kind @returns {Thing[]} */
export function thingsOfKind(model, kind) {
  return model.byKind[kind] || [];
}

/** @param {Model} model @param {*} name local name @returns {Thing|null} */
export function thingByName(model, name) {
  return typeof name === 'string' && Object.prototype.hasOwnProperty.call(model.byName, name) ? model.byName[name] : null;
}

/** The code for the screen of a local name; the name itself when the twin is not known. */
export function labelOf(model, name) {
  const thing = thingByName(model, name);
  return thing ? thing.label : String(name);
}

/** @returns {Thing|null} the zone a working belongs to */
export function zoneOfWorking(model, workingName) {
  const working = thingByName(model, workingName);
  if (working && typeof working.attrs.zone === 'string') return thingByName(model, working.attrs.zone);
  return thingsOfKind(model, 'zone').find((zone) => Array.isArray(zone.attrs.workings)
    && zone.attrs.workings.includes(workingName)) || null;
}

/** @returns {Thing[]} workings of a zone, in the order of its attribute */
export function workingsOfZone(model, zoneName) {
  const zone = thingByName(model, zoneName);
  const names = zone && Array.isArray(zone.attrs.workings) ? zone.attrs.workings : [];
  return names.map((name) => thingByName(model, name)).filter(Boolean);
}

/** @returns {Thing[]} sensors that control a zone */
export function sensorsOfZone(model, zoneName) {
  const zone = thingByName(model, zoneName);
  const listed = zone && Array.isArray(zone.attrs.sensors) ? zone.attrs.sensors : [];
  return thingsOfKind(model, 'sensor').filter((sensor) => listed.includes(sensor.name) || sensor.attrs.zone === zoneName);
}

/** @returns {Thing[]} sensors installed in a working */
export function sensorsOfWorking(model, workingName) {
  return thingsOfKind(model, 'sensor').filter((sensor) => sensor.attrs.working === workingName);
}

/**
 * True when a worker is under ground as far as the model says. A worker who
 * is out may still carry the working and offset of an earlier publication:
 * that position is not where the worker is.
 * @param {Thing} worker
 */
export function isUnderground(worker) {
  return worker.values.status !== 'out';
}

/** @returns {Thing[]} workers whose published position is in the working */
export function workersAtWorking(model, workingName) {
  return thingsOfKind(model, 'worker').filter((worker) => isUnderground(worker) && worker.values.at_working === workingName);
}

/** @returns {Thing[]} workers the model reports as out through the exit */
export function workersAtExit(model, exitName) {
  return thingsOfKind(model, 'worker').filter((worker) => worker.values.at_exit === exitName);
}

/** @returns {Thing[]} workers whose position is in one of the zone's workings */
export function workersInZone(model, zoneName) {
  const names = new Set(workingsOfZone(model, zoneName).map((working) => working.name));
  return thingsOfKind(model, 'worker').filter((worker) => isUnderground(worker) && names.has(worker.values.at_working));
}

/** @returns {Thing|null} the exit twin attached to a node */
export function exitAtNode(model, nodeName) {
  return thingsOfKind(model, 'exit').find((exit) => exit.attrs.node === nodeName) || null;
}

/** @returns {Thing|null} */
export function incidentOf(model) {
  return thingsOfKind(model, 'incident')[0] || null;
}

/**
 * The route of a worker as oriented segments (see normalizeRoute).
 * @param {Model} model
 * @param {Thing} worker
 */
export function routeOf(model, worker) {
  return normalizeRoute(worker.values.route, worker.values.route_next_node || null, (name) => {
    const working = thingByName(model, name);
    return working && typeof working.attrs.from === 'string' && typeof working.attrs.to === 'string'
      ? {from: working.attrs.from, to: working.attrs.to} : null;
  });
}

/**
 * Where a twin is, as references to other twins. Every part may be null.
 * @param {Model} model
 * @param {Thing} thing
 * @returns {{level: (Thing|null), zone: (Thing|null), working: (Thing|null), offsetM: (number|null),
 *            fromNode: (string|null), exit: (Thing|null), node: (string|null)}}
 */
export function placeOf(model, thing) {
  const place = {level: null, zone: null, working: null, offsetM: null, fromNode: null, exit: null, node: null};
  const {attrs, values} = thing;
  const onWorking = (name, offset) => {
    place.working = thingByName(model, name);
    place.offsetM = typeof offset === 'number' ? offset : null;
    if (place.working) {
      place.fromNode = typeof place.working.attrs.from === 'string' ? place.working.attrs.from : null;
      place.level = thingByName(model, place.working.attrs.level);
      place.zone = zoneOfWorking(model, place.working.name);
    }
  };
  if (thing.kind === 'working') {
    place.level = thingByName(model, attrs.level);
    place.zone = zoneOfWorking(model, thing.name);
  } else if (thing.kind === 'zone') {
    place.level = thingByName(model, attrs.level);
  } else if (thing.kind === 'sensor') {
    onWorking(attrs.working, attrs.offset_m);
    if (typeof attrs.zone === 'string') place.zone = thingByName(model, attrs.zone) || place.zone;
  } else if (thing.kind === 'worker') {
    if (typeof values.at_exit === 'string') place.exit = thingByName(model, values.at_exit);
    else if (isUnderground(thing) && typeof values.at_working === 'string') onWorking(values.at_working, values.offset_m);
  } else if (thing.kind === 'equipment') {
    if (typeof values.at_working === 'string') onWorking(values.at_working, values.offset_m);
  } else if (thing.kind === 'exit') {
    place.node = typeof attrs.node === 'string' ? attrs.node : null;
    const nodes = model.things[MINE_ID] ? model.things[MINE_ID].attrs.nodes : null;
    const node = place.node && nodes ? nodes[place.node] : null;
    if (node) place.level = thingByName(model, node.level);
  } else if (thing.kind === 'option') {
    const scope = Array.isArray(values.scope) ? values.scope : [];
    if (scope.length === 1) place.zone = thingByName(model, scope[0]);
  } else if (thing.kind === 'incident') {
    place.zone = thingByName(model, values.zone);
  }
  return place;
}

const text = (value) => (typeof value === 'string' && value !== '' ? value : null);

/**
 * The `data-*` attributes of a drawn twin (implementation spec, section 5),
 * the same for the scheme and for the list. Pass the result to dom.setAttrs:
 * a null value removes the attribute.
 * @param {Thing} thing
 * @param {boolean} [pending] an unconfirmed command of this page targets the twin
 * @returns {Object<string, (string|boolean|null)>}
 */
export function stateAttributes(thing, pending = false) {
  const {values} = thing;
  const attrs = {
    'data-thing-id': thing.thingId,
    'data-kind': thing.kind,
    'data-pending': pending ? true : null,
  };
  if (thing.kind === 'working' || thing.kind === 'zone') {
    attrs['data-hazard'] = thing.hazard.state;
    attrs['data-quality'] = text(values.data_quality);
    attrs['data-last-known-hazard'] = text(values.last_known_hazard_state);
  }
  if (thing.kind === 'working') {
    attrs['data-passability'] = text(values.passability);
    attrs['data-restriction'] = text(values.routing_restriction);
  } else if (thing.kind === 'zone') {
    attrs['data-work-state'] = text(values.work_state);
    attrs['data-withdrawal'] = text(values.withdrawal_state);
  } else if (thing.kind === 'sensor') {
    attrs['data-quality'] = text(values.quality);
    attrs['data-link'] = text(values.link_state);
  } else if (thing.kind === 'worker') {
    attrs['data-status'] = text(values.status);
    attrs['data-egress'] = text(values.egress_status);
    attrs['data-location-hazard'] = text(values.location_hazard);
    attrs['data-pos-quality'] = text(values.pos_quality);
  } else if (thing.kind === 'exit' || thing.kind === 'incident' || thing.kind === 'option') {
    attrs['data-state'] = text(values.state);
  } else if (thing.kind === 'equipment') {
    // A loader (CONTRACT.md §9): its published state and the hazard of its place, as a person's.
    attrs['data-state'] = text(values.state);
    attrs['data-location-hazard'] = text(values.location_hazard);
  }
  return attrs;
}
