// What the scene shows, derived from the store state only: one plain object
// per drawn twin with the published codes the scene encodes, plus a signature
// that changes exactly when something visible changes. Pure: no three.js and
// no DOM. Nothing is computed that the platform did not publish; routes are
// the published ones, laid on the workings as the scheme lays them.

import {unresolvedFor} from '../commands.js';
import * as geo from '../geometry.js';
import {showsOldData} from '../link.js';
import {incidentOf, isUnderground, routeOf, thingByName, thingsOfKind, workersInZone, zoneOfWorking} from '../model.js';

const str = (value) => (typeof value === 'string' && value !== '' ? value : null);

/**
 * @param {import('../store.js').State} state
 * @param {ReturnType<typeof import('./layout.js').buildLayout>} layout
 */
export function describe(state, layout) {
  const {model, link, ui} = state;
  const pendingOf = (thing) => unresolvedFor(state.pending, thing.name).length > 0;
  const view = {
    run: state.snapshot ? state.snapshot.run : null,
    runState: state.snapshot ? state.snapshot.runState : null,
    hasSnapshot: Boolean(model && model.hasSnapshot),
    old: showsOldData(link),
    linkOk: link.link === 'ok',
    selected: ui.selected || null,
    workings: {},
    zones: {},
    sensors: {},
    workers: {},
    exits: {},
    equipment: {},
    routes: [],
    routeReason: 'selection',
    // The published scope of the decision option under the pointer or chosen (ui.hoverOption): its zones and
    // the people whose published position is inside them now. Empty without such an option.
    scope: {option: null, zones: [], workers: []},
  };
  if (!model || !layout) return {view, signature: JSON.stringify(view)};

  for (const working of thingsOfKind(model, 'working')) {
    if (!layout.workings.has(working.name)) continue;
    const {values} = working;
    const zone = zoneOfWorking(model, working.name);
    view.workings[working.name] = {
      thingId: working.thingId,
      hazard: working.hazard.state,
      quality: str(values.data_quality),
      lastKnown: str(values.last_known_hazard_state),
      lastKnownTick: Number.isFinite(values.last_known_hazard_tick) ? values.last_known_hazard_tick : null,
      passability: str(values.passability),
      closedBy: str(values.closed_by),
      restriction: str(values.routing_restriction),
      pending: pendingOf(working),
      zone: zone ? zone.name : null,
    };
  }
  for (const zone of thingsOfKind(model, 'zone')) {
    const {values} = zone;
    view.zones[zone.name] = {
      thingId: zone.thingId,
      workings: (Array.isArray(zone.attrs.workings) ? zone.attrs.workings : []).filter((name) => layout.workings.has(name)),
      hazard: zone.hazard.state,
      known: zone.hazard.known,
      quality: str(values.data_quality),
      lastKnown: str(values.last_known_hazard_state),
      lastKnownTick: Number.isFinite(values.last_known_hazard_tick) ? values.last_known_hazard_tick : null,
      workState: str(values.work_state),
      withdrawal: str(values.withdrawal_state),
      restriction: str(values.routing_restriction),
      workers: Number.isFinite(values.workers_count) ? values.workers_count : null,
      pending: pendingOf(zone),
    };
  }
  for (const sensor of thingsOfKind(model, 'sensor')) {
    if (typeof sensor.attrs.working !== 'string' || !layout.workings.has(sensor.attrs.working)) continue;
    view.sensors[sensor.name] = {
      thingId: sensor.thingId,
      quality: str(sensor.values.quality),
      link: str(sensor.values.link_state),
      pending: pendingOf(sensor),
    };
  }
  for (const worker of thingsOfKind(model, 'worker')) {
    const {values} = worker;
    const placed = isUnderground(worker) && typeof values.at_working === 'string' && Number.isFinite(values.offset_m)
      && layout.workings.has(values.at_working);
    view.workers[worker.name] = {
      thingId: worker.thingId,
      status: str(values.status),
      egress: str(values.egress_status),
      locationHazard: str(values.location_hazard),
      posQuality: str(values.pos_quality),
      underground: isUnderground(worker),
      at: placed ? values.at_working : null,
      offsetM: placed ? values.offset_m : null,
      hasState: worker.hasState,
      pending: pendingOf(worker),
    };
  }
  // Equipment twins (contract question 18): a loader drawn where the model publishes it. Without a published
  // position on a known working it has no place (`at` null) and is not drawn.
  for (const machine of thingsOfKind(model, 'equipment')) {
    if (machine.attrs.equipment_kind !== 'lhd') continue;
    const {values} = machine;
    const placed = typeof values.at_working === 'string' && Number.isFinite(values.offset_m) && layout.workings.has(values.at_working);
    view.equipment[machine.name] = {
      thingId: machine.thingId,
      zone: str(machine.attrs.zone),
      state: str(values.state),
      activity: str(values.activity),
      at: placed ? values.at_working : null,
      offsetM: placed ? values.offset_m : null,
      toward: str(values.toward_node),
      loaded: typeof values.loaded === 'boolean' ? values.loaded : null,
      hasState: machine.hasState,
    };
  }
  for (const exit of thingsOfKind(model, 'exit')) {
    if (!layout.nodes.has(exit.attrs.node)) continue;
    view.exits[exit.name] = {
      thingId: exit.thingId,
      node: exit.attrs.node,
      state: str(exit.values.state),
      out: Number.isFinite(exit.values.workers_out) ? exit.values.workers_out : null,
    };
  }

  // Routes: of the selected worker, or of every worker of the selected zone; with nothing selected and an
  // open incident, of the workers of its zone (the same rule as the scheme).
  const selected = ui.selected && model.things[ui.selected] ? model.things[ui.selected] : null;
  const incident = incidentOf(model);
  let walkers = [];
  if (selected && selected.kind === 'worker') walkers = isUnderground(selected) ? [selected] : [];
  else if (selected && selected.kind === 'zone') walkers = workersInZone(model, selected.name);
  else if (!selected && incident && ['active', 'executing'].includes(incident.values.state)) {
    walkers = workersInZone(model, incident.values.zone);
    view.routeReason = 'incident';
  }
  for (const worker of walkers) {
    const pieces = geo.routePieces(routeOf(model, worker), {working: worker.values.at_working, offsetM: worker.values.offset_m},
      (name) => {
        const line = layout.workings.get(name);
        return line ? {from: line.from, to: line.to, lengthM: line.lengthM, total: line.total} : null;
      });
    if (pieces.length > 0) view.routes.push({worker: worker.name, thingId: worker.thingId, pieces});
  }
  view.scope = scopeOf(model, ui, view);
  return {view, signature: JSON.stringify(view)};
}

/** The zones of the hovered or chosen option's published `scope`, and the people now in them. */
function scopeOf(model, ui, view) {
  const id = ui && typeof ui.hoverOption === 'string' ? ui.hoverOption : null;
  const option = id ? (model.things[id] || thingByName(model, id)) : null;
  if (!option || option.kind !== 'option') return {option: null, zones: [], workers: []};
  const zones = (Array.isArray(option.values.scope) ? option.values.scope : []).filter((name) => typeof name === 'string' && view.zones[name]);
  const inside = new Set(zones.flatMap((name) => view.zones[name].workings));
  const workers = Object.keys(view.workers).filter((name) => view.workers[name].at && inside.has(view.workers[name].at)).sort();
  return {option: option.thingId, zones, workers};
}

/**
 * What changed between two published states that the scene explains with a short transition (clarity spec B):
 * the displayed hazard of a zone or a working (M6; a change to «unknown» is a loss of knowledge, M9), a passage
 * that became closed (M8), a sensor whose data stopped being fresh (M9). Both views must hold a full snapshot of
 * the same run; the caller decides whether motion is allowed at all.
 * @returns {{zones: Map<string, 'hazard'|'knowledge'>, workings: Map<string, 'hazard'|'knowledge'>, closed: Set<string>,
 *            sensors: Map<string, string>}} sensors: name -> the quality shown before
 */
export function changesBetween(before, after) {
  const out = {zones: new Map(), workings: new Map(), closed: new Set(), sensors: new Map()};
  if (!before || !after || !before.hasSnapshot || !after.hasSnapshot || before.run !== after.run) return out;
  const kindOf = (a, b) => (b.hazard === 'unknown' && a.hazard !== 'unknown' ? 'knowledge' : 'hazard');
  for (const [name, zone] of Object.entries(after.zones)) {
    const was = before.zones[name];
    if (was && (was.hazard !== zone.hazard || was.lastKnown !== zone.lastKnown)) out.zones.set(name, kindOf(was, zone));
  }
  for (const [name, working] of Object.entries(after.workings)) {
    const was = before.workings[name];
    if (!was) continue;
    if (was.hazard !== working.hazard || was.lastKnown !== working.lastKnown) out.workings.set(name, kindOf(was, working));
    if (working.passability === 'closed' && was.passability !== 'closed') out.closed.add(name);
  }
  for (const [name, sensor] of Object.entries(after.sensors)) {
    const was = before.sensors[name];
    if (was && was.quality === 'fresh' && (sensor.quality === 'stale' || sensor.quality === 'lost')) out.sensors.set(name, was.quality);
  }
  return out;
}

/**
 * Workers grouped as the scheme groups them: same working, same stretch of BIN metres.
 * The group shows its worst reachability in front.
 * @returns {Array<{key: string, working: string, members: string[], front: string}>}
 */
export function groupWorkers(workers, bin = 25) {
  const rank = (worker) => ({ok: 0, none: 2}[worker.egress] ?? 1);
  const groups = new Map();
  for (const [name, worker] of Object.entries(workers)) {
    if (!worker.at) continue;
    const key = `${worker.at}|${Math.floor(worker.offsetM / bin)}`;
    if (!groups.has(key)) groups.set(key, {key, working: worker.at, members: []});
    groups.get(key).members.push(name);
  }
  for (const group of groups.values()) {
    group.members.sort();
    const worst = Math.max(...group.members.map((name) => rank(workers[name])));
    group.front = group.members.find((name) => rank(workers[name]) === worst);
  }
  return [...groups.values()];
}
