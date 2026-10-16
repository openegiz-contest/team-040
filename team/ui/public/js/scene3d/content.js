// The words of the scene's labels and its tooltip, from the published state
// (text.js and text3d.js). Pure apart from the label anchors, which are
// functions of the vertical factor given by the scene.
//
// Few words by default (variant 2, «Пульт смены»): the horizons, one line per
// zone («Участок Г · опасно · 3 чел.»), the exits («Восстающий · вышли 0») and
// the objects in a problem state (a closed passage, people in danger or without
// a computed route, data that are not fresh, a stopped zone's loader). Codes of
// workings, sensors and ordinary people appear on hover, on selection or close
// up; the details of a zone on its selection, in its tooltip and accessible name.

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
export function labelItems({model, view, layout, groups, anchors, arriving = new Set(), loaders = [], orePasses = []}) {
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
    const lines = [{text: `${thing.label} · ${text.hazardText(thing.hazard)}${people}`, bold: true}];
    const more = [];
    if (zone.workState === 'stopped') more.push(text.label('workState', zone.workState));
    if (zone.withdrawal && zone.withdrawal !== 'none') more.push(text.label('withdrawal', zone.withdrawal));
    if (zone.quality === 'stale') more.push(UI.scheme.byStaleData);
    else if (zone.quality && zone.quality !== 'fresh') more.push(text.label('quality', zone.quality));
    const lastKnown = text.lastKnownText(thing.values, nowS);
    if (lastKnown) lines.push({text: lastKnown, bold: zone.lastKnown === 'danger'});
    if (zone.restriction && zone.restriction !== 'allowed') more.push(text.label('restriction', zone.restriction));
    if (zone.pending) more.push(UI.scheme.pending);
    // The details stay in the tooltip and the accessible name; the tag shows them while its zone is selected.
    const full = [...lines, ...more.map((word) => ({text: word}))];
    if (thing.thingId === selected) for (const word of more) lines.push({text: word});
    const signs = [hazardSign(thing.hazard.state)];
    if (thing.hazard.state === 'unknown' && zone.lastKnown === 'danger') signs.push('lastDanger');
    if (zone.pending) signs.push('pending');
    // The signs of the details go with their words: on the selected tag only.
    if (thing.thingId === selected) {
      if (zone.workState === 'stopped') signs.push('stopped');
      if (zone.withdrawal === 'in_progress' || zone.withdrawal === 'incomplete') signs.push('leaving');
      if (zone.restriction === 'blocked') signs.push('blocked');
    }
    items.push({
      key: thing.thingId, thingId: thing.thingId,
      attrs: attrsOf(thing, zone.pending, full.map((line) => line.text).join('; ')),
      // A zone in danger (the incident's, as a rule) is placed before its people's labels: it names what happens.
      lines, tip: full, signs: signs.filter(Boolean), rank: thing.hazard.state === 'danger' ? 1.7 : 2, always: true,
      cls: ['s3-label--zone', `s3-label--${thing.hazard.state}`, thing.thingId === selected && 'is-selected',
        scopeZones.has(local) && 'is-scope'].filter(Boolean),
      anchor: () => anchors.zone(local), place: 'centre',
    });
  }

  // Exits: always.
  for (const [local, exit] of Object.entries(view.exits)) {
    const thing = thingByName(model, local);
    const first = exit.out !== null ? `${thing.label} · ${SCENE.exitOut(exit.out)}` : thing.label;
    const stateLine = {text: text.label('exitState', exit.state), muted: exit.state === 'available'};
    // One line while the exit is available; its state is said when it is not.
    const lines = exit.state === 'available' && thing.thingId !== selected ? [{text: first, bold: true}] : [{text: first, bold: true}, stateLine];
    const full = [{text: first, bold: true}, stateLine];
    items.push({
      key: thing.thingId, thingId: thing.thingId, attrs: attrsOf(thing, false, full.map((line) => line.text).join('; ')),
      lines, tip: full, signs: [], rank: 3, always: true,
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
      // A closed passage is placed before the zone tags: it is usually what the incident is about. The shafts, ramps
      // and raises are named close up, as the other codes.
      rank: closed ? 1.5 : (problem ? 2 : (line.between ? 5 : 8)), always: problem,
      cls: ['s3-label--working', problem && 's3-label--problem', closed && 's3-label--closed', working.pending && 's3-label--pending',
        isSelected && 'is-selected', arriving.has(thing.thingId) && 'is-arriving'].filter(Boolean),
      anchor: () => anchors.working(local, closed), place: 'around', minScale: problem ? 0 : (line.between ? 3 : 4.5),
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
      anchor: () => anchors.group(group), place: 'around', minScale: problem ? 0 : 4,
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
      anchor: () => anchors.sensor(local), place: 'around', minScale: problem ? 0 : 5,
    });
  }

  // Loaders: the symbol of a zone's published work state. A working zone's loader needs no word (its lamps are lit);
  // a stopped one carries «остановлен», one without a published work state «?». The sign selects the zone.
  for (const {zone, look, lines: said} of loaders) {
    const thing = thingByName(model, zone);
    if (thing && thing.kind === 'equipment') {
      items.push(machineItem(thing, look, said, selected, anchors, view, name));
      continue;
    }
    if (!thing || look === 'working') continue;
    const word = look === 'stopped' ? text.label('workState', 'stopped') : SCENE.loaderQuestion;
    items.push({
      key: `loader:${zone}`, thingId: null,
      attrs: {'data-kind': 'loader', 'data-zone': thing.thingId, 'data-select': thing.thingId, 'data-work-state': look,
        'aria-label': said.join('. '), 'aria-pressed': String(thing.thingId === selected)},
      lines: [{text: word, bold: look === 'stopped'}], tip: said.map((line, index) => ({text: line, bold: index === 0})),
      signs: look === 'stopped' ? ['stopped'] : [], rank: 2.5, always: true,
      cls: ['s3-label--loader', `s3-label--loader-${look}`],
      anchor: () => anchors.loader(zone), place: 'around',
    });
  }

  // Ore passes (mine.attributes.dump_points, CONTRACT.md §9): named close up; a press selects their working.
  for (const entry of orePasses) {
    const working = thingByName(model, entry.working);
    const words = SCENE.orePass(entry.label, working ? working.label : entry.working);
    items.push({
      key: `orepass:${entry.id}`, thingId: null,
      attrs: {'data-kind': 'orepass', 'data-orepass': entry.id, 'data-select': working ? working.thingId : null, 'aria-label': words},
      lines: [{text: entry.label}], tip: [{text: words, bold: true}, {text: SCENE.orePassNote}],
      signs: [], rank: 8, always: false, cls: ['s3-label--orepass'],
      anchor: () => anchors.orePass(entry.id), place: 'around', minScale: 3,
    });
  }

  return items;
}

/**
 * The label of a loader of the model (CONTRACT.md §9). A working one is named by its code close up, on hover or
 * selected; a held one says why («стоит: вход в участок запрещён»), a stopped one «остановлена», one without a
 * published state «?» — those always. A loader in a danger zone carries the danger sign of a person, always; an
 * unknown place carries «?» unless the working has no sensors by design (as people). The operator riding it is a
 * second line («оператор Р-A4 на борту»): the person is part of the machine, no figure of its own. The label is the
 * loader's twin: Enter or a click selects it, the card shows its fields.
 */
function machineItem(thing, look, said, selected, anchors, view, name) {
  const isSelected = thing.thingId === selected;
  const machine = view && view.equipment ? view.equipment[thing.name] : null;
  const working = machine && machine.at && view.workings ? view.workings[machine.at] : null;
  const hazard = machine ? machine.locationHazard : null;
  const danger = hazard === 'danger';
  const unknownPlace = hazard === 'unknown' && !(working && working.quality === 'none');
  const held = look === 'parked' && machine && machine.holdReason && machine.holdReason !== 'none'
    ? SCENE.machineHeld(text.label('holdReason', machine.holdReason)) : null;
  const sign = SCENE.machineSign[look] || held;
  const lines = sign && !isSelected ? [{text: `${thing.label} · ${sign}`, bold: look === 'stopped' || danger}]
    : [{text: isSelected ? said[0] : thing.label, bold: true}];
  if (machine && machine.operatorAboard === true && machine.operator && view.workers && view.workers[machine.operator]) {
    lines.push({text: SCENE.machineRider(name(machine.operator)), muted: true});
  }
  const signs = [];
  if (danger) signs.push('danger');
  else if (unknownPlace) signs.push('unknown');
  if (look === 'stopped') signs.push('stopped');
  const always = Boolean(sign) || danger || unknownPlace || isSelected;
  return {
    key: `loader:${thing.name}`, thingId: thing.thingId,
    // The state attributes of the list (model.js stateAttributes), then the look drawn and the rest of the machine.
    attrs: {...stateAttributes(thing), 'data-look': look, 'aria-label': said.join('. '), 'aria-pressed': String(isSelected),
      'data-hold-reason': machine && machine.holdReason ? machine.holdReason : null, 'data-aboard': machine && machine.operatorAboard ? 'true' : null},
    lines, tip: said.map((line, index) => ({text: line, bold: index === 0})),
    signs, rank: danger ? 2 : (always ? 2.5 : 6), always,
    cls: ['s3-label--loader', 's3-label--machine', `s3-label--loader-${look}`, danger && 's3-label--problem', isSelected && 'is-selected']
      .filter(Boolean),
    anchor: () => anchors.loader(thing.name), place: 'around', minScale: always ? 0 : 4,
  };
}

/**
 * The words of a loader of the model, from its published fields only: «ПДМ-Г · везёт руду · участок Г (данные
 * модели)», then its place and its load, then what is drawn larger.
 * @param {import('../store.js').Model} model
 * @param {Object} machine describe().view.equipment[name]
 * @param {string} look    the look drawn: working, parked, stopped or unknown
 * @param {number} factor  how many times larger the machine is drawn
 */
export function machineLines(model, name, machine, look, factor) {
  const thing = thingByName(model, name);
  if (!thing || !machine) return [];
  let words = SCENE.machineUnknown;
  const doing = machine.activity === 'yielding' && machine.yieldingTo ? SCENE.machineYields(labelOf(model, machine.yieldingTo))
    : (machine.activity ? text.label('equipmentActivity', machine.activity) : null);
  if (look === 'working') words = doing || SCENE.machineWorking;
  else if (look === 'parked') {
    words = machine.holdReason && machine.holdReason !== 'none' ? SCENE.machineHeld(text.label('holdReason', machine.holdReason)) : SCENE.machineStill.parked;
    if (doing && machine.activity !== 'idle') words = `${words} · ${doing}`;
  } else if (look === 'stopped') words = doing && machine.activity !== 'idle' ? `${SCENE.machineStill.stopped} · ${doing}` : SCENE.machineStill.stopped;
  const zone = machine.zone ? thingByName(model, machine.zone) : null;
  const lines = [SCENE.machineTitle(thing.label, words, zone ? zone.label : null)];
  const where = [];
  if (machine.at) where.push(`${labelOf(model, machine.at)}, ${text.quantity(machine.offsetM, 'm')}`);
  if (machine.loaded !== null) where.push(SCENE.machineLoad(machine.loaded));
  if (machine.locationHazard) where.push(`${UI.incident.zone}: ${text.hazardCodeText(machine.locationHazard)}`);
  if (where.length > 0) lines.push(where.join(' · '));
  if (machine.operatorAboard === true && machine.operator) lines.push(SCENE.machineRider(labelOf(model, machine.operator)));
  else if (machine.operatorAboard === false) lines.push(SCENE.machineNoRider);
  lines.push(SCENE.machineNote(factor));
  return lines;
}

/** The text of the tooltip of a hovered object: all its words (the label may show fewer). */
export function tooltipLines(items, key) {
  const item = items.find((entry) => entry.thingId === key || entry.key === key);
  return item ? (item.tip || item.lines).map((line) => line.text) : [];
}
