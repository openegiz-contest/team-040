// The scheme of the mine: one inline SVG built from twin attributes and the
// last full snapshot. Two projections (geometry.js): the axonometric stack of
// levels and the plan of one level. Elements are keyed by twin and updated in
// place, so a poll never moves keyboard focus; nothing is animated except the
// glide of a marker between two published positions (.move-transition).
//
// The three axes stay apart: hazard is the band of a working and the frame of
// a zone, knowledge is the sensor mark and the dashed or bare line, and
// reachability is the shape of a worker marker, the barrier and the exit.
//
// Selection is a chalk-white double outline. A worker without a computed route
// is labelled unmistakably: the crossed-square sign first, bold words, a 2 px
// frame, and his label is never left out. The option the user points at in the
// decision dock (ui.hoverOption) lights the zones of its published scope and the
// people now in them; the light fades in and out (150 ms, scheme.css).

import {unresolvedFor} from '../commands.js';
import {h, onActivate, reconcile, s, setAttrs, setText} from '../dom.js';
import * as geo from '../geometry.js';
import {drawWorking, exitMarker, focusFrame, hazardSign, patterns, sensorMarker, sign, workerMarker} from '../icons.js';
import {
  incidentOf, isUnderground, labelOf, placeOf, routeOf, stateAttributes, thingsOfKind, workersInZone, zoneOfWorking,
} from '../model.js';

// Bottom to top. A route lies on the workings and under every tag and marker: words are never crossed by a line.
const LAYERS = ['planes', 'halos', 'workings', 'nodes', 'route', 'zones', 'sensors', 'exits', 'workers', 'labels'];
const PAD = {top: 50, right: 16, bottom: 58, left: 16};
const BAND_PX = {shaft: 11, drift: 9};
const STUB_PX = 34;
/** Workers of one working whose offsets fall into the same stretch of this length share a marker. */
const BIN_M = 25;
const LINE_H = 13;
const PAD_X = 4;
const PAD_Y = 2;
/** How far the focus frame of a zone tag stands off its box. */
const FOCUS_GAP = 7;
const PATTERNS = 'sch';
/** Thickness of a slab in the axonometric view, px: its sawn front and side faces. Not to scale. */
const SLAB_PX = 10;
const RULER_M = [10, 20, 50, 100, 200, 500, 1000, 2000];
// Orders of the candidates of geo.around. A label of a working never lies along it.
const OFF_LINE = [2, 8, 9, 3, 10, 11, 4, 5, 6, 7];
const ABOVE_FIRST = [2, 8, 9, 4, 5, 3, 10, 11, 0, 1, 6, 7];
const BELOW_ONLY = [6, 7, 4, 5];
const pick = (order, point, gap) => (w, h) => {
  const boxes = geo.around(point, w, h, gap);
  return order.map((index) => boxes[index]);
};

const reachRank = (worker) => ({ok: 0, none: 2}[worker.values.egress_status] ?? 1);

export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;

  // ---- controls -------------------------------------------------------------
  const projectionButton = (name) => h('button', {
    class: 'tab tab--small', type: 'button', 'data-testid': `projection-${name}`, text: UI.scheme[name],
  });
  const buttons = {axo: projectionButton('axo'), plan: projectionButton('plan')};
  const select = h('select', {class: 'select', id: 'level-select', 'data-testid': 'level-select'});
  ctx.roots.schemeControls.append(
    h('span', {class: 'field', id: 'projection-label', text: UI.scheme.projection}),
    h('div', {class: 'tabs', role: 'group', 'aria-labelledby': 'projection-label'}, buttons.axo, buttons.plan),
    h('label', {class: 'visually-hidden', for: 'level-select', text: UI.scheme.level}),
    select,
  );

  // ---- the picture ----------------------------------------------------------
  const svg = s('svg', {class: 'scheme-svg', 'data-testid': 'scheme-svg', role: 'group', 'aria-label': UI.scheme.title},
    s('defs', null, patterns(PATTERNS)));
  const layer = {};
  for (const name of LAYERS) layer[name] = svg.appendChild(s('g', {class: `layer layer--${name}`}));
  layer.labels.setAttribute('aria-hidden', 'true');
  const ruler = svg.appendChild(s('text', {class: 'tag__text', visibility: 'hidden', 'aria-hidden': 'true'}));
  const bar = h('span', {class: 'scheme__bar'});
  const barText = h('span', {class: 'mono'});
  const noteText = h('span', {text: UI.scheme.note});
  const lostText = h('span', {class: 'scheme__lost', hidden: true});
  const empty = h('p', {class: 'scheme__empty', hidden: true});
  const note = h('p', {class: 'scheme__note'}, bar, barText, noteText, lostText);
  root.append(svg, note, empty);

  let size = {w: 0, h: 0};
  let scene = null;
  let sceneKey = [];
  let lastRun = null;
  const kept = new Map();
  const widths = new Map();
  const goArrows = new WeakMap();

  /** Width of a label line in px, measured once per string. */
  function measure(value, bold) {
    const key = (bold ? 'b' : 'n') + value;
    let width = widths.get(key);
    if (width === undefined) {
      setAttrs(ruler, {class: ['tag__text', bold && 'is-bold']});
      ruler.textContent = value;
      width = ruler.getComputedTextLength();
      if (width > 0) {
        if (widths.size > 800) widths.clear();
        widths.set(key, width);
      } else {
        width = value.length * 6.5;
      }
    }
    return width;
  }

  function levelNames(state) {
    return state.model ? geo.sortLevels(thingsOfKind(state.model, 'level')) : [];
  }

  /** The level of the plan: the chosen one, else the level of the selected object, else the upper one. */
  function planLevel(state) {
    const levels = levelNames(state);
    const chosen = levels.find((level) => level.name === state.ui.level);
    if (chosen) return chosen.name;
    const selected = state.model && state.ui.selected ? state.model.things[state.ui.selected] : null;
    const place = selected ? placeOf(state.model, selected) : null;
    const own = selected && selected.kind === 'level' ? selected : (place ? place.level : null);
    return own && levels.some((level) => level.name === own.name) ? own.name : (levels[0] ? levels[0].name : null);
  }

  buttons.axo.addEventListener('click', () => ctx.setProjection('axo'));
  buttons.plan.addEventListener('click', () => {
    ctx.setLevel(planLevel(store.getState()));
    ctx.setProjection('plan');
  });
  select.addEventListener('change', () => {
    // Read once: the first update re-renders and sets the control to the state.
    const level = select.value || null;
    ctx.setProjection(level ? 'plan' : 'axo');
    ctx.setLevel(level);
  });
  svg.addEventListener('click', (event) => {
    if (!event.target.closest('[data-thing-id], .halo')) ctx.select(null);
  });

  // ---- static geometry: attributes, projection and size ----------------------

  function buildScene(model, mine, plan, width, height) {
    const nodes = mine.nodes && typeof mine.nodes === 'object' ? mine.nodes : {};
    const nodePoints = Object.keys(nodes).map((name) => ({name, node: nodes[name], point: geo.nodePoint(nodes, name)}))
      .filter((entry) => entry.point);
    let levels = geo.sortLevels(thingsOfKind(model, 'level'));
    // A mine without level twins still gets its planes: one per elevation of its nodes.
    if (levels.length === 0) {
      levels = [...new Set(nodePoints.map((entry) => entry.point[2]))].sort((a, b) => b - a)
        .map((elevation) => ({name: null, label: text.quantity(elevation, 'm'), elevation}));
    }
    const elevations = levels.map((level) => level.elevation);
    const levelOf = (nodeName) => (geo.nodePoint(nodes, nodeName) ? nodes[nodeName].level : null);
    const levelLabel = (name) => (levels.find((level) => level.name === name) || {label: String(name)}).label;

    const lines = new Map();
    const all = nodePoints.map((entry) => entry.point);
    for (const working of thingsOfKind(model, 'working')) {
      const raw = geo.polyline3(working.attrs, nodes);
      if (!raw) continue;
      const points = geo.splitAtElevations(raw, elevations);
      const cum = geo.cumulative(points);
      all.push(...points);
      lines.set(working.name, {
        points, cum, total: cum[cum.length - 1], from: working.attrs.from, to: working.attrs.to,
        lengthM: working.attrs.length_m, ends: [levelOf(working.attrs.from), levelOf(working.attrs.to)],
        width: BAND_PX[working.attrs.working_kind] || 8,
      });
    }
    if (all.length === 0) return null;
    const box = geo.padded(geo.bounds(all));
    const view = plan ? geo.planProjector(box, width, height, PAD) : geo.axoProjector(box, elevations, width, height, PAD);

    /** Screen polyline of every working that is drawn; `cum` maps a length of the mine polyline to it. */
    const drawn = new Map();
    for (const [name, line] of lines) {
      const [a, b] = line.ends;
      let item = null;
      if (!plan || (a === plan && b === plan)) {
        item = {pts: line.points.map(view.project), cum: line.cum, stub: false, between: a !== b};
      } else if (a === plan || b === plan) {
        // The working leaves the level: a stub from its node, towards its next vertex in plan;
        // a vertical one leans up-left when it rises and down-left when it descends.
        const out = a === plan ? line.points : [...line.points].reverse();
        const origin = view.project(out[0]);
        const next = out.find((point) => Math.hypot(point[0] - out[0][0], point[1] - out[0][1]) > 0.5);
        let dir = out[out.length - 1][2] > out[0][2] ? [-0.6, -0.8] : [-0.6, 0.8];
        if (next) {
          const towards = view.project(next);
          const d = geo.dist(origin, towards) || 1;
          dir = [(towards[0] - origin[0]) / d, (towards[1] - origin[1]) / d];
        }
        const tip = [origin[0] + dir[0] * STUB_PX, origin[1] + dir[1] * STUB_PX];
        item = {pts: a === plan ? [origin, tip] : [tip, origin], cum: [0, line.total], stub: true, between: true,
          leads: levelLabel(a === plan ? b : a)};
      }
      if (item) {
        item.shape = geo.workingShape(item.pts, line.width, 16);
        drawn.set(name, item);
      }
    }
    const samples = [];
    for (const item of drawn.values()) samples.push(...geo.sample(item.pts, 7));
    const planes = view.planes.map((corners, index) => {
      const level = plan ? levels.find((entry) => entry.name === plan) : levels[index];
      const label = level ? (plan ? UI.scheme.planOf(level.label) : level.label) : '';
      const at = plan ? [corners[3][0] + 8, corners[3][1] + 16] : [corners[0][0] + 10, corners[0][1] - 8];
      return {key: `plane-${index}`, corners, label, at, edges: plan ? null : slabEdges(corners)};
    });
    const dots = nodePoints.filter((entry) => !plan || entry.node.level === plan)
      .map((entry) => ({name: entry.name, at: view.project(entry.point)}));
    const barM = RULER_M.find((metres) => metres * view.scale >= 56) || RULER_M[RULER_M.length - 1];
    return {lines, drawn, samples, planes, dots, plan, nodes, project: view.project, barM, barPx: barM * view.scale};
  }

  /**
   * The sawn faces of a slab under its top face (front and right side) and two strata lines on the front.
   * Drawn from the projected corners only: front-left, front-right, back-right, back-left.
   */
  function slabEdges([a, b, c]) {
    const down = (point, by = SLAB_PX) => [point[0], point[1] + by];
    const strata = [0.36, 0.7].map((share) => geo.linePath([down(a, SLAB_PX * share), down(b, SLAB_PX * share)])).join('');
    return {
      front: `${geo.linePath([a, b, down(b), down(a)])}Z`,
      side: `${geo.linePath([b, c, down(c), down(b)])}Z`,
      strata,
    };
  }

  /** A worker under ground whose published position can be drawn on this picture. */
  function placed(worker) {
    const {values} = worker;
    return typeof values.at_working === 'string' && typeof values.offset_m === 'number' && scene.lines.has(values.at_working);
  }

  /** Codes of the workers under ground whose position is not published (or names no known working). */
  function unplacedCodes(model) {
    return thingsOfKind(model, 'worker').filter((worker) => isUnderground(worker) && worker.hasState && !placed(worker))
      .map((worker) => worker.label);
  }

  /**
   * Boxes in picture coordinates of what lies over the picture: the legend chip and the controls of the
   * stage. A box larger than a quarter of the picture is a container, not a control, and is left out.
   */
  function overlays() {
    const frame = root.getBoundingClientRect();
    const nodes = [ctx.roots.legend && ctx.roots.legend.querySelector('.legend__chip'), note,
      ...(ctx.roots.stageHud ? ctx.roots.stageHud.children : [])];
    const boxes = [];
    for (const node of nodes) {
      if (!node) continue;
      for (const rect of node.getClientRects()) {
        const x = Math.max(rect.left, frame.left);
        const y = Math.max(rect.top, frame.top);
        const w = Math.min(rect.right, frame.right) - x;
        const h = Math.min(rect.bottom, frame.bottom) - y;
        if (w > 0 && h > 0 && w * h < frame.width * frame.height / 4) {
          boxes.push({x: x - frame.left - 4, y: y - frame.top - 4, w: w + 8, h: h + 8});
        }
      }
    }
    return boxes;
  }

  /** Where a published offset of a working is on the screen, with the direction of the working there. */
  function spot(name, offsetM) {
    const item = scene.drawn.get(name);
    const line = scene.lines.get(name);
    if (!item || !line) return null;
    const last = item.cum[item.cum.length - 1];
    return geo.pointAt(item.pts, item.cum, geo.offsetLength(offsetM, line.lengthM, last));
  }

  // ---- labels ---------------------------------------------------------------

  function tagSize(lines, signs) {
    const width = Math.max(...lines.map((line, index) => measure(line.text, line.bold) + (index === 0 ? signs.length * 14 : 0)));
    return {w: Math.ceil(width) + PAD_X * 2, h: lines.length * LINE_H + PAD_Y * 2};
  }

  const createTag = () => s('g', null, s('rect', {class: 'tag__box', rx: 2}), s('g', {class: 'tag__signs'}), s('text', {class: 'tag__text'}));

  function updateTag(g, spec) {
    const [rect, signs, words] = g.children;
    setAttrs(rect, {width: spec.box.w, height: spec.box.h});
    reconcile(signs, spec.signs, (name, index) => `${index}-${name}`, (name) => sign(name),
      (node, name, index) => setAttrs(node, {transform: `translate(${PAD_X + 6 + index * 14} ${PAD_Y + 6.5}) scale(.75)`}));
    reconcile(words, spec.lines, (line, index) => index, () => s('tspan'), (tspan, line, index) => setAttrs(tspan, {
      x: PAD_X + (index === 0 ? spec.signs.length * 14 : 0), y: PAD_Y + 10 + index * LINE_H,
      class: [line.bold && 'is-bold', line.muted && 'is-muted'], text: line.text,
    }));
    g.style.transform = `translate(${Math.round(spec.box.x)}px, ${Math.round(spec.box.y)}px)`;
  }

  // ---- one frame -------------------------------------------------------------

  function createObject(thing, children) {
    const g = s('g', {tabindex: 0, role: 'button'}, children);
    onActivate(g, () => ctx.select(thing.thingId));
    return g;
  }

  function clearAll() {
    for (const name of LAYERS) reconcile(layer[name], [], () => '', () => null);
  }

  function render() {
    const state = store.getState();
    const {model, attributes, ui, link} = state;
    const levels = levelNames(state);
    const plan = ui.projection === 'plan' ? planLevel(state) : null;

    for (const name of ['axo', 'plan']) {
      const on = (name === 'plan') === Boolean(plan);
      setAttrs(buttons[name], {'aria-pressed': String(on), class: ['tab', 'tab--small', on && 'is-current']});
    }
    reconcile(select, [{name: '', label: UI.scheme.allLevels}, ...levels], (level) => level.name || '-',
      (level) => h('option', {value: level.name}), (option, level) => setText(option, level.label));
    if (select.value !== (plan || '')) select.value = plan || '';

    const mismatch = link.snapshot === 'invalid' && link.invalid && link.invalid.code === 'topology_mismatch';
    if (!model || !attributes || mismatch) {
      clearAll();
      scene = null;
      sceneKey = [];
      setAttrs(svg, {'data-drawn': 'false', 'data-tick': null});
      setText(empty, mismatch ? UI.scheme.notDrawn : (state.boot === 'loading' ? UI.list.noAttributes : ''));
      empty.hidden = empty.textContent === '';
      note.hidden = true;
      return;
    }
    if (size.w < 40 || size.h < 40) return;

    const key = [attributes, plan, size.w, size.h];
    const refit = key.some((value, index) => value !== sceneKey[index]);
    if (refit) {
      scene = buildScene(model, attributes.mine, plan, size.w, size.h);
      sceneKey = key;
      kept.clear();
      setAttrs(svg, {viewBox: `0 0 ${size.w} ${size.h}`});
    }
    const run = state.snapshot ? state.snapshot.run : null;
    // A new picture or a new run is shown at once: markers glide only between two positions of one run.
    const jump = refit || run !== lastRun;
    lastRun = run;
    empty.hidden = scene !== null;
    setText(empty, scene ? '' : UI.scheme.notDrawn);
    note.hidden = scene === null;
    setAttrs(svg, {
      'data-drawn': String(scene !== null), 'data-projection': plan ? 'plan' : 'axo', 'data-level': plan,
      // The tick this view shows: a view that stopped following the state is told apart from the others.
      'data-tick': state.snapshot && model.hasSnapshot ? state.snapshot.tick : null,
    });
    if (!scene) {
      clearAll();
      return;
    }
    if (jump) svg.classList.add('is-jump');

    const name = (local) => labelOf(model, local);
    const isPending = (thing) => unresolvedFor(state.pending, thing.name).length > 0;
    const isSelected = (thing) => thing.thingId === ui.selected;
    const now = state.snapshot ? state.snapshot.simTimeS : undefined;
    // The zones of the option pointed at in the decision dock: its published scope, nothing derived.
    const option = ui.hoverOption ? model.things[ui.hoverOption] : null;
    const scope = new Set(option && option.kind === 'option' && Array.isArray(option.values.scope)
      ? option.values.scope.filter((zone) => typeof zone === 'string') : []);
    const inScope = (worker) => scope.size > 0 && typeof worker.values.at_working === 'string'
      && Boolean(zoneOfWorking(model, worker.values.at_working)) && scope.has(zoneOfWorking(model, worker.values.at_working).name);
    const placer = geo.createPlacer(size.w, size.h, scene.samples);
    /** Label requests in order of importance: {key, lines, signs, cls, candidates(w, h), zone?, glide?}. */
    const specs = [];

    // Planes and their captions.
    reconcile(layer.planes, scene.planes, (plane) => plane.key,
      () => s('g', {class: 'plane'}, s('path', {class: 'plane__side'}), s('path', {class: 'plane__front'}),
        s('path', {class: 'plane__strata'}), s('path', {class: 'plane__face'}), s('text', {class: 'plane__label'})),
      (g, plane) => {
        const [side, front, strata, face, label] = g.children;
        setAttrs(side, {d: plane.edges ? plane.edges.side : null});
        setAttrs(front, {d: plane.edges ? plane.edges.front : null});
        setAttrs(strata, {d: plane.edges ? plane.edges.strata : null});
        setAttrs(face, {d: `${geo.linePath(plane.corners)}Z`});
        setAttrs(label, {x: plane.at[0], y: plane.at[1], text: plane.label});
        placer.block({x: plane.at[0] - 2, y: plane.at[1] - 13, w: measure(plane.label, true) * 1.15 + 4, h: 17}, 200);
      });
    // The scale with its note, and whatever lies over the picture (the legend chip, the controls of the
    // stage): labels keep off them.
    bar.style.width = `${Math.round(scene.barPx)}px`;
    setText(barText, text.quantity(scene.barM, 'm'));
    setText(lostText, model.hasSnapshot ? (unplacedCodes(model).length > 0 ? UI.scheme.noPosition(unplacedCodes(model).join(', ')) : '') : UI.list.noState);
    lostText.hidden = lostText.textContent === '';
    for (const box of overlays()) placer.block(box, 400);

    // Workings.
    const workings = thingsOfKind(model, 'working').filter((working) => scene.drawn.has(working.name));
    reconcile(layer.workings, workings, (working) => working.thingId, (working) => createObject(working), (g, working) => {
      const {values, hazard} = working;
      const item = scene.drawn.get(working.name);
      const pending = isPending(working);
      const selected = isSelected(working);
      const closed = values.passability === 'closed';
      const unknownPass = model.hasSnapshot && !closed && values.passability !== 'open';
      // What the tag of the zone already says is not repeated on each of its workings.
      const zone = zoneOfWorking(model, working.name);
      const likeZone = Boolean(zone) && zone.hazard.state === hazard.state
        && zone.values.last_known_hazard_state === values.last_known_hazard_state;
      const look = {
        hazard: hazard.state,
        bare: values.data_quality === 'none' && hazard.state === 'unknown',
        closed, unknownPass, pending,
        lastDanger: hazard.state === 'unknown' && values.last_known_hazard_state === 'danger',
        restricted: values.routing_restriction === 'blocked' && !(zone && zone.values.routing_restriction === 'blocked'),
      };
      drawWorking(g, item.shape, look, PATTERNS);
      const words = [];
      if (closed) words.push(text.label('passability', 'closed'), text.label('closedBy', values.closed_by));
      if (unknownPass) words.push(`${text.fieldLabel('passability')}: ${text.label('passability', values.passability)}`);
      const marked = model.hasSnapshot && !look.bare && (hazard.state === 'danger' || hazard.state === 'unknown');
      if (marked && !likeZone) {
        words.push(text.hazardText(hazard));
        if (look.lastDanger) words.push(text.lastKnownText(values, now));
      }
      if (look.restricted) words.push(text.label('restriction', 'blocked'));
      if (pending) words.push(UI.scheme.pending);
      const said = [text.hazardText(hazard), text.label('quality', values.data_quality), text.passabilityText(values)];
      if (values.routing_restriction === 'blocked') said.push(text.label('restriction', 'blocked'));
      if (pending) said.push(UI.scheme.pending);
      setAttrs(g, {
        ...stateAttributes(working, pending),
        class: ['obj', 'working', selected && 'is-selected', item.between && 'working--between', look.lastDanger && 'working--last-danger'],
        'aria-label': `${working.label}: ${said.join('; ')}`,
      });
      if (selected && words.length === 0) words.push(look.bare ? UI.scheme.noSensors : text.hazardText(hazard));
      const shown = words.filter((word) => word && word !== text.DASH);
      const always = shown.length > 0 || marked || item.between || plan;
      if (!always) return;
      let code = working.label;
      if (item.between) code = `${text.codeLabel('workingKind', working.attrs.working_kind)} ${working.label}`;
      // A short first statement shares the line with the code; a long one gets its own.
      const joined = shown.length > 0 && shown[0].length <= 16;
      const lines = [{text: joined ? `${code} · ${shown[0]}` : code, bold: shown.length > 0}];
      if (item.stub) lines.push({text: UI.scheme.leadsTo(item.leads), muted: true});
      for (const word of shown.slice(joined ? 1 : 0)) lines.push({text: word});
      const slot = item.shape.slots[closed || look.pending ? 1 : 0];
      const boxed = shown.length > 0;
      specs.push({
        key: `${working.thingId}:label`, lines, signs: [], rank: boxed ? 0 : (item.between ? 5 : 7),
        cls: boxed ? ['tag--box', closed && 'tag--closed', pending && 'tag--pending', selected && 'tag--selected'] : 'tag--plain',
        candidates: pick(OFF_LINE, [slot.x, slot.y], boxed ? 14 : 8),
      });
    });

    // Junctions.
    reconcile(layer.nodes, scene.dots, (dot) => dot.name, () => s('circle', {class: 'node', r: 2}),
      (circle, dot) => setAttrs(circle, {cx: dot.at[0], cy: dot.at[1]}));

    // Sensors, exits and workers come before the labels: a label keeps off every marker.
    const sensors = [];
    for (const sensor of thingsOfKind(model, 'sensor')) {
      const at = typeof sensor.attrs.working === 'string' ? spot(sensor.attrs.working, sensor.attrs.offset_m) : null;
      if (!at) continue;
      // Beside the working, on its upper side, so that it hides neither the band nor a worker on it.
      const side = at.dir[0] >= 0 ? -1 : 1;
      const point = [at.point[0] - at.dir[1] * 14 * side, at.point[1] + at.dir[0] * 14 * side];
      sensors.push({thing: sensor, point});
      placer.block({x: point[0] - 7, y: point[1] - 7, w: 14, h: 14}, 60);
    }
    const exits = [];
    for (const exit of thingsOfKind(model, 'exit')) {
      const point3 = geo.nodePoint(scene.nodes, exit.attrs.node);
      if (!point3 || (plan && scene.nodes[exit.attrs.node].level !== plan)) continue;
      const [x, y] = scene.project(point3);
      exits.push({thing: exit, point: [x, y - 13]});
      placer.block({x: x - 10, y: y - 25, w: 20, h: 24}, 400);
    }

    // Workers: grouped by the data (working and stretch of offset), never by distance on the screen.
    const groups = new Map();
    for (const worker of thingsOfKind(model, 'worker')) {
      const {values} = worker;
      // A worker who is out is not drawn under ground, whatever position is still published for them.
      if (!isUnderground(worker) || !placed(worker) || !scene.drawn.has(values.at_working)) continue;
      const groupKey = `${values.at_working}|${Math.floor(values.offset_m / BIN_M)}`;
      if (!groups.has(groupKey)) groups.set(groupKey, []);
      groups.get(groupKey).push(worker);
    }
    const workers = [];
    for (const members of groups.values()) {
      const working = members[0].values.at_working;
      const mean = members.reduce((sum, worker) => sum + worker.values.offset_m, 0) / members.length;
      const at = spot(working, mean);
      const worst = Math.max(...members.map(reachRank));
      const front = members.find((worker) => reachRank(worker) === worst);
      const chosen = members.find(isSelected);
      placer.block({x: at.point[0] - 9, y: at.point[1] - 9, w: 18, h: 18}, 400);
      for (const worker of members) workers.push({thing: worker, at, front: worker === front, count: members.length});
      const lines = [];
      const code = (chosen || front).label;
      const status = front.values.egress_status;
      const reach = status === 'ok' ? '' : text.label('egress', status);
      const stranded = status === 'none';
      if (members.length === 1) {
        lines.push({text: code, bold: true});
        if (reach) lines.push({text: reach, bold: stranded});
        if (front.values.pos_quality !== undefined && front.values.pos_quality !== 'fresh') {
          lines.push({text: text.label('posQuality', front.values.pos_quality)});
        }
      } else {
        lines.push({text: chosen ? `${code} ${UI.scheme.grouped(members.length)}` : UI.scheme.grouped(members.length), bold: true});
        if (reach) {
          lines.push({text: `${text.num(members.filter((worker) => reachRank(worker) === worst).length)} · ${reach}`, bold: stranded});
        }
      }
      const boxed = Boolean(reach) || lines.length > 1;
      // No computed route: the crossed square first and the most important label of the picture (rank 0, placed first;
      // every label is placed, none is ever dropped).
      specs.push({
        key: `${front.thingId}:label`, lines, signs: stranded ? ['noroute'] : [], rank: stranded ? 0 : (boxed ? 2 : 6), glide: true,
        cls: boxed ? ['tag--box', stranded && 'tag--closed tag--noroute', !stranded && 'tag--unknown'] : 'tag--plain',
        candidates: (w, h) => geo.around(at.point, w, h, boxed ? 15 : 10),
      });
    }

    // Zones: a frame around their workings and a tag with the state in words.
    const zones = thingsOfKind(model, 'zone').map((zone) => {
      const items = (Array.isArray(zone.attrs.workings) ? zone.attrs.workings : []).map((local) => scene.drawn.get(local))
        .filter((item) => item && !item.stub);
      return {thing: zone, items};
    }).filter((entry) => entry.items.length > 0);
    reconcile(layer.halos, zones, (entry) => entry.thing.thingId, (entry) => {
      // Under the rim of its hazard, a wider rim lit only for the option pointed at: the hazard rim stays in sight.
      const g = s('g', null, s('path', {class: 'halo__scope'}), s('path', {class: 'halo__rim'}), s('path', {class: 'halo__pad'}));
      g.addEventListener('click', () => ctx.select(entry.thing.thingId));
      return g;
    }, (g, entry) => {
      const zone = entry.thing;
      const d = entry.items.map((item) => item.shape.line).join('');
      for (const path of g.children) setAttrs(path, {d});
      setAttrs(g, {class: ['halo', `halo--${zone.hazard.state}`, isSelected(zone) && 'is-selected', scope.has(zone.name) && 'is-in-scope',
        zone.hazard.state === 'unknown' && zone.values.last_known_hazard_state === 'danger' && 'halo--last-danger'],
      'data-in-scope': scope.has(zone.name) ? 'true' : null});
    });
    for (const {thing: zone, items} of zones) {
      const {values, hazard} = zone;
      const pending = isPending(zone);
      const lines = [{text: `${zone.label}: ${text.hazardText(hazard)}`, bold: true}];
      const work = [];
      if (values.work_state !== undefined) work.push(text.label('workState', values.work_state));
      if (typeof values.workers_count === 'number') work.push(text.counted(values.workers_count, text.FORMS.worker));
      if (work.length > 0) lines.push({text: work.join(' · ')});
      if (values.withdrawal_state !== undefined && values.withdrawal_state !== 'none') lines.push({text: text.label('withdrawal', values.withdrawal_state)});
      if (values.data_quality === 'stale') lines.push({text: UI.scheme.byStaleData});
      else if (values.data_quality !== undefined && values.data_quality !== 'fresh') lines.push({text: text.label('quality', values.data_quality)});
      const lastKnown = text.lastKnownText(values, now);
      if (lastKnown) lines.push({text: lastKnown, bold: values.last_known_hazard_state === 'danger'});
      if (values.routing_restriction !== undefined && values.routing_restriction !== 'allowed') {
        lines.push({text: text.label('restriction', values.routing_restriction)});
      }
      if (pending) lines.push({text: UI.scheme.pending});
      const signs = [hazardSign(hazard.state)];
      if (hazard.state === 'unknown' && values.last_known_hazard_state === 'danger') signs.push('lastDanger');
      if (values.work_state === 'stopped') signs.push('stopped');
      if (values.withdrawal_state === 'in_progress' || values.withdrawal_state === 'incomplete') signs.push('leaving');
      if (values.routing_restriction === 'blocked') signs.push('blocked');
      if (pending) signs.push('pending');
      const frame = geo.boxOf(items.flatMap((item) => item.pts));
      specs.push({
        key: zone.thingId, zone, lines, signs: signs.filter(Boolean), rank: 1, pending,
        cls: ['tag--box', `tag--${hazard.state}`, isSelected(zone) && 'tag--selected'],
        // Inside the frame where the workings leave room, otherwise right next to it.
        candidates: (w, h) => {
          const inside = [];
          for (const fy of [0.5, 0.3, 0.7]) {
            for (const fx of [0.5, 0.3, 0.7, 0.15, 0.85]) inside.push({x: frame.x + frame.w * fx - w / 2, y: frame.y + frame.h * fy - h / 2, w, h, clear: 9});
          }
          const gap = 18;
          const outside = [];
          for (const fx of [0, 1, 0.5]) {
            const x = frame.x + (frame.w - w) * fx;
            outside.push({x, y: frame.y - gap - h, w, h, clear: 9}, {x, y: frame.y + frame.h + gap, w, h, clear: 9});
          }
          // Beside the frame: level with its middle, then with its lower and its upper edge (a tall tag
          // of a zone at the very bottom or top of the picture has no room for the middle).
          const beside = [];
          for (const y of [frame.y + frame.h / 2 - h / 2, frame.y + frame.h - h, frame.y]) {
            beside.push({x: frame.x + frame.w + gap, y, w, h, clear: 9}, {x: frame.x - gap - w, y, w, h, clear: 9});
          }
          return [...inside, ...outside, ...beside];
        },
      });
    }

    for (const {thing: exit, point} of exits) {
      const {values} = exit;
      const lines = [{text: exit.label, bold: true}, {text: text.label('exitState', values.state)}];
      if (typeof values.workers_out === 'number') lines[0].text += ` · ${UI.scheme.out(values.workers_out)}`;
      specs.push({
        key: `${exit.thingId}:label`, lines, signs: [], rank: 3,
        cls: values.state === 'available' ? 'tag--plain' : ['tag--box', values.state === 'unavailable' ? 'tag--closed' : 'tag--unknown'],
        candidates: pick(ABOVE_FIRST, point, 13),
      });
    }
    for (const {thing: sensor, point} of sensors) {
      // A sensor whose data are not current is named on the scheme; the others in the plan and when selected.
      const fresh = sensor.values.quality === 'fresh' || !model.hasSnapshot;
      const pending = isPending(sensor);
      if (!plan && !isSelected(sensor) && fresh && !pending) continue;
      const lines = [{text: fresh ? sensor.label : `${sensor.label} · ${text.label('quality', sensor.values.quality)}`, bold: !fresh}];
      if (pending) lines.push({text: UI.scheme.pending});
      specs.push({
        key: `${sensor.thingId}:label`, lines, signs: [], rank: fresh && !pending ? 7 : 4,
        cls: pending ? ['tag--box', 'tag--pending'] : (fresh ? 'tag--plain' : ['tag--box', 'tag--unknown']),
        candidates: pick(ABOVE_FIRST, point, 10),
      });
    }
    if (plan) {
      for (const dot of scene.dots) {
        specs.push({
          key: `node:${dot.name}`, lines: [{text: dot.name, muted: true}], signs: [], rank: 8, cls: 'tag--plain',
          candidates: pick(BELOW_ONLY, dot.at, 7),
        });
      }
    }

    // Place the labels: the most important first, each keeping its previous side when it can.
    specs.sort((a, b) => a.rank - b.rank);
    for (const spec of specs) {
      const {w, h} = tagSize(spec.lines, spec.signs);
      const boxes = spec.candidates(w, h);
      const index = placer.place(boxes, kept.has(spec.key) ? kept.get(spec.key) : -1);
      kept.set(spec.key, index);
      spec.box = boxes[index];
    }

    reconcile(layer.zones, specs.filter((spec) => spec.zone), (spec) => spec.key,
      (spec) => createObject(spec.zone, [...createTag().children, s('rect', {class: 'tag__sel', rx: 3}), focusFrame(0, 0, 0, 0)]), (g, spec) => {
        const zone = spec.zone;
        setAttrs(g, {
          ...stateAttributes(zone, spec.pending),
          class: ['obj', 'zone', 'tag', ...spec.cls],
          'aria-label': spec.lines.map((line) => line.text).join('; '),
        });
        updateTag(g, spec);
        // The outer line of the double selection outline, inside the focus frame.
        setAttrs(g.lastChild.previousSibling, {x: -3, y: -3, width: spec.box.w + 6, height: spec.box.h + 6});
        setAttrs(g.lastChild, {x: -FOCUS_GAP, y: -FOCUS_GAP, width: spec.box.w + 2 * FOCUS_GAP, height: spec.box.h + 2 * FOCUS_GAP});
      });

    reconcile(layer.sensors, sensors, (entry) => entry.thing.thingId, (entry) => createObject(entry.thing, sensorMarker()), (g, {thing, point}) => {
      const {values} = thing;
      setAttrs(g, {
        ...stateAttributes(thing, isPending(thing)),
        class: ['obj', 'sensor', isSelected(thing) && 'is-selected'],
        transform: `translate(${Math.round(point[0])} ${Math.round(point[1])})`,
        'aria-label': `${thing.label}: ${text.label('quality', values.quality)}; ${text.label('linkState', values.link_state)}`,
      });
    });

    reconcile(layer.exits, exits, (entry) => entry.thing.thingId, (entry) => createObject(entry.thing, exitMarker()), (g, {thing, point}) => {
      const out = typeof thing.values.workers_out === 'number' ? `; ${UI.scheme.out(thing.values.workers_out)}` : '';
      setAttrs(g, {
        ...stateAttributes(thing),
        class: ['obj', 'exit', isSelected(thing) && 'is-selected'],
        transform: `translate(${Math.round(point[0])} ${Math.round(point[1])})`,
        'aria-label': `${thing.label}: ${text.label('exitState', thing.values.state)}${out}`,
      });
    });

    reconcile(layer.workers, workers, (entry) => entry.thing.thingId, (entry) => {
      const g = createObject(entry.thing, workerMarker());
      goArrows.set(g, g.querySelector('.worker__go'));
      return g;
    }, (g, {thing, at, front, count}) => {
      const {values} = thing;
      const moving = values.status === 'moving_to_exit';
      const first = moving ? routeOf(model, thing)[0] : null;
      const line = scene.lines.get(values.at_working);
      // The arrow of a walking worker points along the working towards the end its published route names.
      const heading = first && first.to === line.to ? 1 : (first && first.to === line.from ? -1 : 0);
      setAttrs(goArrows.get(g), {
        transform: `rotate(${Math.round(Math.atan2(at.dir[1] * heading, at.dir[0] * heading) * 180 / Math.PI)})`,
      });
      const where = [text.egressText(values, name), `${UI.incident.zone}: ${text.hazardCodeText(values.location_hazard)}`,
        text.label('workerStatus', values.status)];
      if (count > 1) where.push(UI.scheme.inGroup(count));
      setAttrs(g, {
        ...stateAttributes(thing, isPending(thing)),
        class: ['obj', 'worker', 'move-transition', isSelected(thing) && 'is-selected', !front && 'is-merged',
          moving && heading !== 0 && 'is-going', !text.isKnown('workerStatus', values.status) && 'is-odd', inScope(thing) && 'is-in-scope'],
        'data-group': count > 1 ? count : null,
        'data-in-scope': inScope(thing) ? 'true' : null,
        'aria-label': `${thing.label}: ${where.join('; ')}`,
      });
      g.style.transform = `translate(${Math.round(at.point[0])}px, ${Math.round(at.point[1])}px)`;
    });

    // The published route of the selected worker, or of every worker of the selected zone. With nothing
    // selected and an open incident: of the workers of its zone, so that the consequence shows without a click.
    const selected = ui.selected ? model.things[ui.selected] : null;
    const incident = incidentOf(model);
    let walkers = [];
    let reason = 'selection';
    if (selected && selected.kind === 'worker') walkers = isUnderground(selected) ? [selected] : [];
    else if (selected && selected.kind === 'zone') walkers = workersInZone(model, selected.name);
    else if (!selected && incident && ['active', 'executing'].includes(incident.values.state)) {
      walkers = workersInZone(model, incident.values.zone);
      reason = 'incident';
    }
    const routes = [];
    for (const worker of walkers) {
      const pieces = geo.routePieces(routeOf(model, worker), {working: worker.values.at_working, offsetM: worker.values.offset_m},
        (local) => scene.lines.get(local) || null);
      const runs = [];
      const through = [];
      let arrows = '';
      for (const piece of pieces) {
        const item = scene.drawn.get(piece.working);
        if (!item) continue;
        const points = geo.cut(item.pts, item.cum, piece.start, piece.end);
        const previous = runs[runs.length - 1];
        if (previous && geo.dist(previous[previous.length - 1], points[0]) < 1.5) previous.push(...points.slice(1));
        else runs.push(points);
        through.push(piece.working);
        // Arrows are set per working, so that routes sharing a working draw the same arrows.
        arrows += geo.chevrons(points, 46, 6);
      }
      if (runs.length > 0) routes.push({worker, runs, through, arrows});
    }
    reconcile(layer.route, routes, (route) => route.worker.thingId,
      () => s('g', {class: 'route'}, s('path', {class: 'route__casing'}), s('path', {class: 'route__line'}), s('path', {class: 'route__arrows'})),
      (g, route) => {
        const d = route.runs.map(geo.linePath).join('');
        setAttrs(g, {'data-worker': route.worker.thingId, 'data-workings': route.through.join(' '), 'data-reason': reason});
        setAttrs(g.children[0], {d});
        setAttrs(g.children[1], {d});
        setAttrs(g.children[2], {d: route.arrows});
      });

    reconcile(layer.labels, specs.filter((spec) => !spec.zone), (spec) => spec.key, createTag, (g, spec) => {
      setAttrs(g, {class: ['tag', spec.glide && 'move-transition', ...[].concat(spec.cls)]});
      updateTag(g, spec);
    });

    if (jump) {
      // The new positions are laid out with the glide switched off; no frame callback is needed for that.
      svg.getBoundingClientRect();
      svg.classList.remove('is-jump');
    }
  }

  new ResizeObserver((entries) => {
    const {width, height} = entries[entries.length - 1].contentRect;
    const next = {w: Math.round(width), h: Math.round(height)};
    if (next.w === size.w && next.h === size.h) return;
    size = next;
    render();
  }).observe(root);

  store.watch((state) => [state.model, state.attributes, state.pending, state.ui.selected, state.ui.projection,
    state.ui.level, state.ui.hoverOption, state.link.snapshot, state.link.invalid && state.link.invalid.code, state.boot], render);
}
