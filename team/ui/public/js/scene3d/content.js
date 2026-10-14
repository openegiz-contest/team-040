// The words of the scene's labels and its tooltip, from the published state
// (text.js and text3d.js). Pure apart from the label anchors, which are
// functions of the vertical factor given by the scene.

import {labelOf, stateAttributes, thingByName} from '../model.js';
import * as text from '../text.js';
import {SCENE} from '../text3d.js';
import {hazardSign} from '../icons.js';

const {UI} = text;

/**
 * Label requests of every object worth a label, in order of importance.
 * @param {Object} args
 * @param {import('../store.js').Model} args.model
 * @param {Object} args.view           describe().view
 * @param {Object} args.layout
 * @param {Array} args.groups          groupWorkers()
 * @param {Object} args.anchors        functions returning scene points: level(level), working(name), zone(name),
 *                                     group(group), sensor(name), exit(name)
 * @returns {import('./labels.js').LabelItem[]}
 */
export function labelItems({model, view, layout, groups, anchors, arriving = new Set()}) {
  const items = [];
  const name = (local) => labelOf(model, local);
  const selected = view.selected;
  const scopeZones = new Set(view.scope ? view.scope.zones : []);
  const scopeWorkers = new Set(view.scope ? view.scope.workers : []);
  // The model time now, for the age of a last known state (text.js may use it; ticks stay in the titles).
  const nowS = model.shift && Number.isFinite(model.shift.values.sim_time_s) ? model.shift.values.sim_time_s : null;
  const attrsOf = (thing, pending, aria) => ({...stateAttributes(thing, pending), 'aria-label': aria, 'aria-pressed': String(thing.thingId === selected)});

  // Levels: always, at the left edge of their slab.
  for (const level of layout.levels) {
    const thing = level.name ? thingByName(model, level.name) : null;
    const caption = (thing && thing.label) || level.label || text.quantity(level.elevation, 'm');
    items.push({
      key: `level:${level.name || level.elevation}`, thingId: thing ? thing.thingId : null,
      attrs: thing ? attrsOf(thing, false, caption) : {'data-kind': 'level', 'aria-label': caption, tabindex: '-1'},
      lines: [{text: caption, bold: true}],
      signs: [], rank: 1, always: true, cls: ['s3-label--level'], anchor: () => anchors.level(level), place: 'left',
    });
  }

  // Zones: a tag with the state, always.
  for (const [local, zone] of Object.entries(view.zones)) {
    const thing = thingByName(model, local);
    if (!thing || zone.workings.length === 0) continue;
    // The published number of people in the zone follows its state (clarity spec A10).
    const people = zone.workers !== null ? ` · ${SCENE.people(zone.workers)}` : '';
    const lines = [{text: `${thing.label}: ${text.hazardText(thing.hazard)}${people}`, bold: true}];
    const more = [];
    if (zone.workState === 'stopped') more.push(text.label('workState', zone.workState));
    if (zone.withdrawal && zone.withdrawal !== 'none') more.push(text.label('withdrawal', zone.withdrawal));
    if (zone.quality === 'stale') more.push(UI.scheme.byStaleData);
    else if (zone.quality && zone.quality !== 'fresh') more.push(text.label('quality', zone.quality));
    const lastKnown = text.lastKnownText(thing.values, nowS);
    if (lastKnown) lines.push({text: lastKnown, bold: zone.lastKnown === 'danger'});
    if (zone.restriction && zone.restriction !== 'allowed') more.push(text.label('restriction', zone.restriction));
    if (zone.pending) more.push(UI.scheme.pending);
    for (const word of more) lines.push({text: word});
    const signs = [hazardSign(thing.hazard.state)];
    if (thing.hazard.state === 'unknown' && zone.lastKnown === 'danger') signs.push('lastDanger');
    if (zone.workState === 'stopped') signs.push('stopped');
    if (zone.withdrawal === 'in_progress' || zone.withdrawal === 'incomplete') signs.push('leaving');
    if (zone.restriction === 'blocked') signs.push('blocked');
    if (zone.pending) signs.push('pending');
    items.push({
      key: thing.thingId, thingId: thing.thingId,
      attrs: attrsOf(thing, zone.pending, lines.map((line) => line.text).join('; ')),
      lines, signs: signs.filter(Boolean), rank: 2, always: true,
      cls: ['s3-label--zone', `s3-label--${thing.hazard.state}`, thing.thingId === selected && 'is-selected',
        scopeZones.has(local) && 'is-scope'].filter(Boolean),
      anchor: () => anchors.zone(local), place: 'centre',
    });
  }

  // Exits: always.
  for (const [local, exit] of Object.entries(view.exits)) {
    const thing = thingByName(model, local);
    const first = exit.out !== null ? `${thing.label} · ${UI.scheme.out(exit.out)}` : thing.label;
    const lines = [{text: first, bold: true}, {text: text.label('exitState', exit.state), muted: exit.state === 'available'}];
    items.push({
      key: thing.thingId, thingId: thing.thingId, attrs: attrsOf(thing, false, lines.map((line) => line.text).join('; ')),
      lines, signs: [], rank: 3, always: true,
      cls: ['s3-label--exit', exit.state !== 'available' && 's3-label--problem', thing.thingId === selected && 'is-selected'].filter(Boolean),
      anchor: () => anchors.exit(local), place: 'around',
    });
  }

  // Workings: closed, unknown with a last danger, restricted alone, pending, inter-level ones; codes when close.
  for (const [local, working] of Object.entries(view.workings)) {
    const thing = thingByName(model, local);
    const line = layout.workings.get(local);
    const zone = working.zone ? view.zones[working.zone] : null;
    const closed = working.passability === 'closed';
    const unknownPass = view.hasSnapshot && !closed && working.passability !== 'open';
    const bare = working.quality === 'none' && working.hazard === 'unknown';
    const likeZone = Boolean(zone) && zone.hazard === working.hazard && zone.lastKnown === working.lastKnown;
    const words = [];
    if (closed) words.push(text.label('passability', 'closed'), text.label('closedBy', working.closedBy));
    if (unknownPass) words.push(`${text.fieldLabel('passability')}: ${text.label('passability', working.passability)}`);
    const marked = view.hasSnapshot && !bare && (working.hazard === 'danger' || working.hazard === 'unknown');
    if (marked && !likeZone) {
      words.push(text.hazardText(thing.hazard));
      if (working.hazard === 'unknown' && working.lastKnown === 'danger') words.push(text.lastKnownText(thing.values, nowS));
    }
    const restrictedAlone = working.restriction === 'blocked' && !(zone && zone.restriction === 'blocked');
    if (restrictedAlone) words.push(text.label('restriction', 'blocked'));
    if (working.pending) words.push(UI.scheme.pending);
    const shown = words.filter((word) => word && word !== text.DASH);
    const isSelected = thing.thingId === selected;
    const problem = shown.length > 0;
    let code = thing.label;
    if (line.between) code = SCENE.between(text.codeLabel('workingKind', thing.attrs.working_kind), thing.label);
    const lines = [{text: code, bold: problem || line.between}];
    for (const word of shown) lines.push({text: word});
    if (isSelected && !problem) lines.push({text: bare ? SCENE.noSensors : text.hazardText(thing.hazard)});
    const said = [text.hazardText(thing.hazard), text.label('quality', working.quality), text.passabilityText(thing.values)];
    if (working.restriction === 'blocked') said.push(text.label('restriction', 'blocked'));
    if (working.pending) said.push(UI.scheme.pending);
    const signs = [];
    if (closed) signs.push('blocked');
    if (marked && !likeZone) signs.push(working.lastKnown === 'danger' && working.hazard === 'unknown' ? 'lastDanger' : hazardSign(working.hazard));
    if (working.pending) signs.push('pending');
    items.push({
      key: thing.thingId, thingId: thing.thingId, attrs: attrsOf(thing, working.pending, `${thing.label}: ${said.join('; ')}`),
      lines, signs: signs.filter(Boolean),
      // A closed passage is placed before the zone tags: it is usually what the incident is about.
      rank: closed ? 1.5 : (problem ? 2 : (line.between ? 5 : 8)), always: problem || line.between,
      cls: ['s3-label--working', problem && 's3-label--problem', closed && 's3-label--closed', working.pending && 's3-label--pending',
        isSelected && 'is-selected', arriving.has(thing.thingId) && 'is-arriving'].filter(Boolean),
      anchor: () => anchors.working(local, closed), place: 'around', minScale: problem || line.between ? 0 : 1.6,
    });
  }

  // Workers: one label per group; problem states always, codes when close.
  for (const group of groups) {
    const front = view.workers[group.front];
    const thing = thingByName(model, group.front);
    const chosen = group.members.find((member) => thingByName(model, member).thingId === selected);
    const lead = chosen ? thingByName(model, chosen) : thing;
    const status = front.egress;
    const reach = status === 'ok' ? '' : text.label('egress', status);
    const inDanger = group.members.some((member) => view.workers[member].locationHazard === 'danger');
    const lines = [];
    if (group.members.length === 1) {
      lines.push({text: lead.label, bold: true});
      if (reach) lines.push({text: reach});
      if (inDanger) lines.push({text: SCENE.inDangerZone});
      if (front.posQuality && front.posQuality !== 'fresh') lines.push({text: text.label('posQuality', front.posQuality)});
    } else {
      lines.push({text: `${chosen ? `${lead.label} ` : `${thing.label} `}${SCENE.grouped(group.members.length)}`, bold: true});
      if (reach) lines.push({text: `${text.num(group.members.filter((member) => view.workers[member].egress === status).length)} · ${reach}`});
      if (inDanger) lines.push({text: SCENE.inDangerZone});
    }
    const leadView = view.workers[lead.name];
    const where = [text.egressText(lead.values, name), `${UI.incident.zone}: ${text.hazardCodeText(lead.values.location_hazard)}`,
      text.label('workerStatus', lead.values.status)];
    if (group.members.length > 1) where.push(UI.scheme.inGroup(group.members.length));
    const problem = Boolean(reach) || inDanger;
    // Without a computed route: the crossed square first, every line bold, never left out by the decluttering
    // (clarity spec A5). No new colour: the white border of the marker.
    const noRoute = status === 'none';
    if (noRoute) for (const entry of lines) entry.bold = true;
    const signs = [];
    if (noRoute) signs.push('worker:none');
    if (inDanger) signs.push('danger');
    items.push({
      key: `worker:${group.key}`, thingId: lead.thingId,
      attrs: {...attrsOf(lead, leadView.pending, `${lead.label}: ${where.join('; ')}`), 'data-group': group.members.length > 1 ? group.members.length : null},
      // People in a danger zone or without a route are placed before the zone tags: they are what the screen is about.
      lines, signs, rank: noRoute ? 1.6 : (problem ? 1.8 : 7), always: problem, keep: noRoute,
      cls: ['s3-label--worker', noRoute && 's3-label--noroute', status !== 'ok' && status !== 'none' && 's3-label--unknown',
        inDanger && 's3-label--indanger', lead.thingId === selected && 'is-selected',
        group.members.some((member) => scopeWorkers.has(member)) && 'is-scope'].filter(Boolean),
      anchor: () => anchors.group(group), place: 'around', minScale: problem ? 0 : 1.1,
    });
  }

  // Sensors whose data are not current: always; the others when close.
  for (const [local, sensor] of Object.entries(view.sensors)) {
    const thing = thingByName(model, local);
    const fresh = sensor.quality === 'fresh' || !view.hasSnapshot;
    const lines = [{text: fresh ? thing.label : `${thing.label} · ${text.label('quality', sensor.quality)}`, bold: !fresh}];
    if (sensor.pending) lines.push({text: UI.scheme.pending});
    const problem = !fresh || sensor.pending;
    items.push({
      key: thing.thingId, thingId: thing.thingId,
      attrs: attrsOf(thing, sensor.pending, `${thing.label}: ${text.label('quality', sensor.quality)}; ${text.label('linkState', sensor.link)}`),
      lines, signs: sensor.pending ? ['pending'] : [], rank: problem ? 4 : 9, always: problem,
      cls: ['s3-label--sensor', problem && 's3-label--problem', thing.thingId === selected && 'is-selected'].filter(Boolean),
      anchor: () => anchors.sensor(local), place: 'around', minScale: problem ? 0 : 2.2,
    });
  }

  return items;
}

/** The text of the tooltip of a hovered object: its label lines, or the decor note. */
export function tooltipLines(items, key) {
  const item = items.find((entry) => entry.thingId === key || entry.key === key);
  return item ? item.lines.map((line) => line.text) : [];
}
