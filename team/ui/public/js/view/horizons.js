// The horizon rail (variant 3 «Глубина»): the depth instrument of the shift at the right edge of the stage, drawn
// like a borehole log — a scale of metres with minor ticks every 10 m and labelled ticks every 50 m, one mark per
// horizon at its published elevation («−120», «−240»), and the people at the depth where they are.
//
// What it shows, from published data only:
//   - The horizons, each with the sign of the worst published hazard of its zones (danger, attention, or unknown —
//     an unknown state is never quiet); the words are in its title and accessible name. The horizon in view is
//     marked on the axis by the cursor, which slides to a new horizon with a spring (one motion per change).
//   - The people: a small marker per person (the marker of the stage: reachability, the danger ring, the fog ring of
//     an unknown place, a dashed outline for a position that is not fresh) at the depth of the place where the 3D
//     stage draws that person now (ctx.stage.people(): the same playback as the figures, so dot and figure agree),
//     or, without the 3D stage, at the published place. People at one depth sit side by side. Nothing moves by itself:
//     a dot is where the stage draws its person, so on a pause, old data or a new run nothing moves here either. The
//     people who came out are gone from the rail and counted at 0 m («вышли 3»).
//
// What it does:
//   - A press on a horizon frames it in the 3D stage (ctx.stage.focus(levelLocalName)); in the scheme mode it opens
//     the plan of that level. «Все» returns to the overview (3D) or the cutaway of all levels (scheme).
//   - The pointer over the gauge: a probe line with the depth under it («−173 м»), and the 3D stage draws a thin
//     glowing guide at that depth across the massif (ctx.stage.setDepthProbe). Ticks near the pointer magnify
//     smoothly (a lens on a critically damped spring); the frames of the lens are the rail's own, only while it moves.
//   - The pointer (or the keyboard focus) on a horizon: the stage glows the outlines of that level's workings
//     (ctx.stage.setLevelHighlight) and a chip shows the level's published summary: the people on it, its zones with
//     their state.
//   - Keyboard: the horizons are one tab stop; ↑ ↓ move between them (and show their highlight), Enter frames,
//     Esc returns to the overview.
//   - Scroll through depth (ctx.stage.depthView / scrollDepth): a window on the rail spans the depths the stage shows
//     now (the top and the bottom of its free part), following every move of the camera in the same frame. The
//     wheel over the rail scrolls the camera through depth (the wheel over the stage stays zoom) and, once it rests,
//     settles on a horizon within SNAP_M of the middle; at the overview the first tick down zooms to a depth
//     reading at the pointer's depth, and scrolling up past the top returns to the overview. The window can be
//     dragged (1:1 in depth; a finger anywhere on the rail), a press on the track elsewhere glides it there;
//     PageUp/PageDown move by one horizon spacing, Home/End to the upper and the lower horizon. The stage's pan
//     clamp holds: the scroll stops where the art ends.
// Reduced motion: the cursor jumps, there is no lens, scrolls and snaps are instant; the probe and the highlight
// follow the pointer at once and never blink (a change is drawn in one frame). Nothing runs while nothing moves.
//
// Contract: renders into ctx.roots.horizons (#horizons, a `.centre__bar` child of #centre: the 3D stage keeps its
// labels and its framing clear of it). Test ids: horizon-rail (root), horizon-all, horizon-<level local name>,
// horizon-gauge, horizon-probe (its readout horizon-probe-value), horizon-people (dots horizon-dot-<person>),
// horizon-out, horizon-chip, horizon-cursor.

import {h, reconcile, s, setAttrs, setText} from '../dom.js';
import * as geo from '../geometry.js';
import {thingsOfKind} from '../model.js';
import {workerMarker} from '../icons.js';
import {createSpring, EASE_POSTER, motionAllowed, reducedMotion, springEasing, SPRING_MS, stagger} from '../motion.js';
import {setSign} from './signs.js';

const WORST = ['danger', 'attention', 'unknown'];
/** People: the pitch of the dots side by side (px), and how many sit side by side before the last one counts the rest. */
const DOT_PX = 17;
const SLOTS = 4;
/** The lens over the ticks: its reach (px, gaussian); how much a tick grows is poster.css's (--lens). */
const LENS = {sigma: 34};
/** Scrolling: a wheel tick moves this share of the window; the snap after the wheel rests (ms) and its reach (m). */
const SCROLL = {tick: 0.18, settle: 360, read: 520, jump: 600, snapAfter: 260, snapMs: 320};
const SNAP_M = 12;

/** The range of the gauge: the horizons with a margin, rounded out to 10 m. */
function rangeOf(levels) {
  const top = Math.max(...levels.map((level) => level.elevation));
  const bottom = Math.min(...levels.map((level) => level.elevation));
  const pad = Math.max(20, (top - bottom) * 0.18);
  return {top: Math.ceil((top + pad) / 10) * 10, bottom: Math.floor((bottom - pad) / 10) * 10};
}

/** The elevation of a published place: the polyline of its working (attributes) at its offset of length_m. */
function publishedDepth(model, nodes, workingName, offsetM) {
  const working = model.byName[workingName];
  if (!working || working.kind !== 'working' || !Number.isFinite(offsetM)) return null;
  const points = geo.polyline3(working.attrs, nodes);
  if (!points) return null;
  const cum = geo.cumulative(points);
  const total = cum[cum.length - 1];
  const lengthM = Number.isFinite(working.attrs.length_m) && working.attrs.length_m > 0 ? working.attrs.length_m : total;
  return geo.pointAt(points, cum, geo.offsetLength(offsetM, lengthM, total)).point[2];
}

/** The level a working lies on: its published `level`, else the level both its ends lie at. Null for a ramp. */
function levelOfWorking(model, nodes, working, levels) {
  if (typeof working.attrs.level === 'string') return working.attrs.level;
  const points = geo.polyline3(working.attrs, nodes);
  if (!points || !points.every((point) => Math.abs(point[2] - points[0][2]) < 0.01)) return null;
  const level = levels.find((entry) => Math.abs(entry.elevation - points[0][2]) < 0.01);
  return level ? level.name : null;
}

export function mount(root, ctx) {
  const {store, text} = ctx;
  const Z = text.HORIZON;

  const all = h('button', {type: 'button', class: 'hz__all', 'data-testid': 'horizon-all', title: Z.allTitle, text: Z.all});
  const head = h('div', {class: 'hz__head'}, h('span', {class: 'hz__title', text: `${Z.title}, ${Z.unit}`}), all);
  const ticks = h('div', {class: 'hz__ticks', 'aria-hidden': 'true'});
  const marks = h('ol', {class: 'hz__levels'});
  const cursor = h('span', {class: 'hz__cursor', 'data-testid': 'horizon-cursor', 'aria-hidden': 'true'});
  const win = h('div', {class: 'hz__window', 'data-testid': 'horizon-window', 'aria-hidden': 'true', hidden: true},
    h('span', {class: 'hz__window-end hz__window-end--top'}), h('span', {class: 'hz__window-end hz__window-end--bottom'}));
  const lane = h('div', {class: 'hz__people', 'data-testid': 'horizon-people', 'aria-hidden': 'true'});
  const out = h('span', {class: 'hz__out', 'data-testid': 'horizon-out', 'aria-hidden': 'true', hidden: true});
  const probeValue = h('span', {class: 'hz__probe-value', 'data-testid': 'horizon-probe-value'});
  const probe = h('div', {class: 'hz__probe', 'data-testid': 'horizon-probe', 'aria-hidden': 'true', hidden: true},
    h('span', {class: 'hz__probe-line'}), probeValue);
  const chip = h('div', {class: 'hz__chip', 'data-testid': 'horizon-chip', role: 'status', hidden: true});
  const gauge = h('div', {class: 'hz__gauge', 'data-testid': 'horizon-gauge'},
    h('span', {class: 'hz__axis', 'aria-hidden': 'true'}), ticks, win, cursor, lane, out, marks, probe, chip);
  root.append(head, gauge);
  setAttrs(root, {role: 'navigation', 'aria-label': Z.region, 'data-testid': 'horizon-rail'});

  let current = null;     // the level the user went to; null: all levels
  let drawnKey = null;
  let range = null;
  let levelsNow = [];
  let cursorAt = null;    // {top, height} of the cursor in px of the gauge, as drawn
  let keyLevel = null;    // the horizon that holds the tab stop of the rail
  let hoverLevel = null;  // the horizon under the pointer
  let focusLevel = null;  // the horizon with the keyboard focus
  let litLevel;           // the horizon highlighted now (undefined: not yet told to the stage)
  const slots = new Map();

  const stageMode = () => {
    const stage = document.getElementById('stage');
    return stage ? stage.getAttribute('data-stage-mode') : null;
  };
  /** The pixel offset of an elevation from the top of the gauge, and back. */
  const share = (elevation) => (range.top - elevation) / (range.top - range.bottom);
  const at = (elevation) => `${share(elevation) * 100}%`;

  function go(name) {
    current = name;
    if (name === null) {
      if (!ctx.stage.overview()) {
        ctx.setProjection('axo');
        ctx.setLevel(null);
      }
    } else if (!ctx.stage.focus(name)) {
      // Not in 3D: the plan of the level.
      ctx.setProjection('plan');
      ctx.setLevel(name);
    }
    paint();
  }
  all.addEventListener('click', () => go(null));

  /** Which horizon is in view: in 3D the focus of the camera, in the scheme the level of the plan. */
  function inView(levels) {
    const state = store.getState();
    if (stageMode() === 'scheme') return state.ui.projection === 'plan' ? state.ui.level : null;
    const info = ctx.stage.info ? ctx.stage.info() : null;
    if (info) {
      if (info.overview) return null;
      const focus = typeof info.focus === 'string' ? info.focus.split(':').pop() : null;
      if (focus && levels.some((level) => level.name === focus)) return focus;
      if (focus) return current;
      // Moved by the user (a scroll, a pan): no horizon is the one in view; the window says what is.
      return null;
    }
    return current;
  }

  /** True when the 3D stage shows its overview (or there is no 3D stage). */
  function overviewNow() {
    const info = ctx.stage.info ? ctx.stage.info() : null;
    return !info || Boolean(info.overview);
  }

  const zoneState = (zone) => (zone.hasState && zone.hazard ? zone.hazard.state : 'unknown');

  function hazardOf(model, levelName) {
    const zones = thingsOfKind(model, 'zone').filter((zone) => zone.attrs.level === levelName);
    const states = zones.map(zoneState);
    const worst = WORST.find((state) => states.includes(state)) || null;
    const words = zones.filter((zone) => zoneState(zone) === worst)
      .map((zone) => `${zone.label} — ${zone.hasState && zone.hazard ? text.hazardText(zone.hazard) : text.UI.rail.noState}`);
    return {worst, words: words.join('; ')};
  }

  // ---- the gauge: ticks, horizons, the cursor ----------------------------------------------------------------------

  function paint() {
    const state = store.getState();
    const levels = state.model ? geo.sortLevels(thingsOfKind(state.model, 'level')) : [];
    // The gauge appears with the first full snapshot (and draws itself in then); it stays for the rest of the page.
    const ready = levels.length > 0 && (drawnKey !== null || Boolean(state.model && state.model.hasSnapshot));
    root.hidden = !ready;
    if (!ready) return;
    levelsNow = levels;
    range = rangeOf(levels);

    const key = `${range.top}:${range.bottom}`;
    if (key !== drawnKey) {
      const items = [];
      for (let metres = range.top; metres >= range.bottom; metres -= 10) items.push(metres);
      reconcile(ticks, items, (metres) => String(metres), (metres) => {
        const major = metres % 50 === 0;
        return h('span', {class: ['hz__tick', major && 'hz__tick--major'], 'data-metres': metres},
          h('span', {class: 'hz__tick-line'}), major ? h('span', {class: 'hz__tick-label', text: Z.elevation(metres)}) : null);
      }, (node, metres) => {
        node.style.top = at(metres);
      });
    }

    const view = inView(levels);
    if (keyLevel === null || !levels.some((level) => level.name === keyLevel)) keyLevel = view || levels[0].name;
    reconcile(marks, levels, (level) => level.name, (level) => {
      const button = h('button', {type: 'button', class: 'hz__level', 'data-testid': `horizon-${level.name}`, 'aria-description': Z.keys},
        h('span', {class: 'hz__elev'}), h('span', {class: 'hz__sign', 'aria-hidden': 'true'}), h('span', {class: 'hz__bar', 'aria-hidden': 'true'}),
        h('span', {class: 'hz__name'}));
      button.addEventListener('click', () => {
        keyLevel = level.name;
        go(level.name);
      });
      button.addEventListener('pointerenter', () => setHover(level.name));
      button.addEventListener('pointerleave', () => setHover(null));
      button.addEventListener('focus', () => {
        focusLevel = level.name;
        keyLevel = level.name;
        showLevel();
      });
      button.addEventListener('blur', () => {
        if (focusLevel === level.name) focusLevel = null;
        // The focus moves to the next horizon within the same task: no frame without a highlight in between.
        queueMicrotask(showLevel);
      });
      return h('li', {class: 'hz__item'}, button);
    }, (item, level) => {
      const button = item.firstChild;
      const [elev, signHolder, , name] = button.children;
      setText(elev, Z.elevation(level.elevation));
      setText(name, level.label);
      const hazard = state.model ? hazardOf(state.model, level.name) : {worst: null, words: ''};
      signHolder.hidden = !hazard.worst;
      if (hazard.worst) setSign(signHolder, hazard.worst);
      const label = stageMode() === 'scheme' ? Z.plan(level.label) : Z.go(level.label);
      setAttrs(button, {title: hazard.words ? `${label}; ${Z.hazard(hazard.words)}` : label,
        'aria-label': hazard.words ? `${label}; ${Z.hazard(hazard.words)}` : label,
        'aria-current': view === level.name ? 'true' : null, 'data-hazard': hazard.worst, 'data-level': level.name,
        'data-elevation': level.elevation, tabindex: level.name === keyLevel ? '0' : '-1'});
      item.style.top = at(level.elevation);
    });
    setAttrs(all, {'aria-current': view === null ? 'true' : null});
    root.setAttribute('data-view', view || 'all');

    const first = drawnKey === null;
    if (key !== drawnKey) {
      drawnKey = key;
      // The gauge draws itself once when the mine is first shown: the axis grows, the horizons come in from the edge.
      const stage = document.getElementById('stage');
      if (first && motionAllowed(state) && !(stage && stage.getAttribute('data-stage-mode') === 'scheme')) {
        stagger([gauge.firstChild], [{transform: 'scaleY(0)'}, {transform: 'scaleY(1)'}], {duration: 520});
        stagger([...marks.children].map((node) => node.firstChild), [{opacity: 0, transform: 'translateX(24px)'}, {opacity: 1, transform: 'none'}],
          {duration: 380, start: 120, step: 70, easing: EASE_POSTER});
      }
    }
    placeCursor(view, !first, view === null && !overviewNow());
    placeWindow();
    paintPeople();
    if (chipLevel()) paintChip();
  }

  /** The cursor on the axis: a short bar at the horizon in view, or a bracket over all of them; it slides on a change. */
  function placeCursor(view, animate, hidden = false) {
    const height = gauge.clientHeight;
    if (!height || !range) return;
    cursor.hidden = hidden;
    if (hidden) {
      cursor.setAttribute('data-at', 'none');
      cursorAt = null;
      return;
    }
    const level = view ? levelsNow.find((entry) => entry.name === view) : null;
    const tops = levelsNow.map((entry) => share(entry.elevation) * height);
    const next = level ? {top: share(level.elevation) * height - 15, height: 30}
      : {top: Math.min(...tops) - 6, height: Math.max(...tops) - Math.min(...tops) + 12};
    const before = cursorAt;
    cursorAt = next;
    cursor.style.transform = `translateY(${next.top}px) scaleY(${next.height})`;
    cursor.setAttribute('data-at', view || 'all');
    if (animate && before && (Math.abs(before.top - next.top) > 0.5 || Math.abs(before.height - next.height) > 0.5) && !reducedMotion()
      && typeof cursor.animate === 'function') {
      cursor.animate([{transform: `translateY(${before.top}px) scaleY(${before.height})`}, {transform: cursor.style.transform}],
        {duration: SPRING_MS, easing: springEasing(), iterations: 1, fill: 'none'});
    }
  }

  // ---- the people ----------------------------------------------------------------------------------------------

  /** The people as the stage draws them now, or at their published places without the 3D stage: [{name, z}]. */
  function peopleNow(state) {
    const drawn = ctx.stage.people ? ctx.stage.people() : null;
    if (drawn) return drawn.map((person) => ({name: person.name, z: person.z}));
    if (!state.model || !state.model.hasSnapshot || !state.attributes || !state.attributes.mine) return [];
    const nodes = state.attributes.mine.nodes || {};
    const list = [];
    for (const worker of thingsOfKind(state.model, 'worker')) {
      const {values} = worker;
      if (values.status === 'out' || typeof values.at_working !== 'string') continue;
      const z = publishedDepth(state.model, nodes, values.at_working, values.offset_m);
      if (Number.isFinite(z)) list.push({name: worker.name, z});
    }
    return list;
  }

  function paintPeople() {
    const state = store.getState();
    if (!range || !state.model) return;
    const height = gauge.clientHeight || 1;
    const model = state.model;
    const people = peopleNow(state).filter((person) => model.byName[person.name])
      .map((person) => ({...person, y: share(person.z) * height}))
      .sort((p, q) => p.y - q.y || (p.name < q.name ? -1 : 1));
    // Side by side: each dot takes the slot nearest the axis that is free at its depth; the last slot counts the rest.
    const last = new Array(SLOTS).fill(-Infinity);
    const holder = new Array(SLOTS).fill(null);
    const more = new Map();          // the dot of the last slot -> how many it stands for
    slots.clear();
    for (const person of people) {
      let slot = last.findIndex((y) => person.y - y >= DOT_PX - 1);
      if (slot < 0) {
        slot = SLOTS - 1;
        more.set(holder[slot], (more.get(holder[slot]) || 1) + 1);
        person.hidden = true;
      } else {
        last[slot] = person.y;
        holder[slot] = person.name;
      }
      person.slot = slot;
      slots.set(person.name, slot);
    }
    reconcile(lane, people, (person) => person.name, (person) => h('span', {class: 'hz__dot', 'data-testid': `horizon-dot-${person.name}`,
      'data-person': person.name}, s('svg', {class: 'hz__dot-pic', viewBox: '-12 -12 24 24', width: 22, height: 22, 'aria-hidden': 'true',
      focusable: 'false'}, s('g', {class: 'worker'}, workerMarker())), h('span', {class: 'hz__more'})), (node, person) => {
      const worker = model.byName[person.name];
      const values = worker.values;
      const working = typeof values.at_working === 'string' ? model.byName[values.at_working] : null;
      // As the people rail: a working without sensors by design is no unknown monitored zone (no fog ring there).
      const unmonitored = values.location_hazard === 'unknown' && working && working.values.data_quality === 'none';
      setAttrs(node.querySelector('.worker'), {
        'data-egress': values.egress_status === undefined ? null : String(values.egress_status),
        'data-location-hazard': values.location_hazard === undefined || unmonitored ? null : String(values.location_hazard),
        'data-pos-quality': values.pos_quality === undefined ? null : String(values.pos_quality),
        class: ['worker', values.status === 'moving_to_exit' && 'is-going'],
      });
      const extra = person.hidden ? 0 : (more.get(person.name) || 0);
      node.hidden = Boolean(person.hidden);
      setText(node.lastChild, extra > 1 ? `+${extra - 1}` : '');
      setAttrs(node, {'data-z': Math.round(person.z * 100) / 100, 'data-slot': person.slot, title: Z.person(worker.label || person.name, Z.depth(Math.round(person.z)))});
      node.style.top = `${(person.y / height) * 100}%`;
      node.style.setProperty('--slot', String(person.slot));
    });
    const gone = thingsOfKind(model, 'worker').filter((worker) => worker.values.status === 'out').length;
    out.hidden = gone === 0;
    setText(out, gone > 0 ? Z.out(gone) : '');
    out.style.top = `${Math.min(Math.max(share(0), 0), 1) * 100}%`;
    root.setAttribute('data-people', String(people.length));
  }

  // ---- the probe, the lens -------------------------------------------------------------------------------------

  let probeY = null;                         // the pointer over the gauge (px from its top), or null
  const lensY = createSpring(0, 22);
  const lensOn = createSpring(0, 16);
  let lensFrame = 0;
  let lensLast = null;

  /** The depth under a pointer at `y` px of the gauge, whole metres, within the scale. */
  function depthAt(y, height) {
    const z = range.top - (y / height) * (range.top - range.bottom);
    return Math.round(Math.min(Math.max(z, range.bottom), range.top));
  }

  function onProbe(event) {
    if (!range || dragging) return;
    const box = gauge.getBoundingClientRect();
    const y = event.clientY - box.top;
    if (y < 0 || y > box.height) return endProbe();
    // Over a horizon the horizon speaks (its highlight and chip): the probe gives way, the lens keeps following.
    if (event.target && event.target.closest && event.target.closest('.hz__level')) {
      hideProbe();
      followLens(y);
      return;
    }
    const z = depthAt(y, box.height);
    probeY = y;
    probe.hidden = false;
    probe.style.top = `${share(z) * 100}%`;
    setText(probeValue, Z.depth(z));
    probe.setAttribute('data-z', String(z));
    root.setAttribute('data-probe', String(z));
    if (ctx.stage.setDepthProbe) ctx.stage.setDepthProbe(z);
    followLens(y);
  }

  /** The lens follows the pointer on a spring; it opens where the pointer came in (no slide from elsewhere). */
  function followLens(y) {
    if (reducedMotion()) return;
    lensY.set(y, lensOn.value < 0.02 && lensOn.goal === 0);
    lensOn.set(1);
    startLens();
  }

  function hideProbe() {
    if (probeY === null) return;
    probeY = null;
    probe.hidden = true;
    root.removeAttribute('data-probe');
    if (ctx.stage.setDepthProbe) ctx.stage.setDepthProbe(null);
  }

  function endProbe() {
    hideProbe();
    lensOn.set(0);
    if (reducedMotion()) lensOn.set(0, true);
    startLens();
  }

  function startLens() {
    if (lensFrame) return;
    lensLast = null;
    lensFrame = requestAnimationFrame(stepLens);
  }

  function stepLens(now) {
    lensFrame = 0;
    const dt = lensLast === null ? 16 : now - lensLast;
    lensLast = now;
    const moving = [lensY.step(dt), lensOn.step(dt)].some(Boolean);
    applyLens();
    if (moving) lensFrame = requestAnimationFrame(stepLens);
    else root.setAttribute('data-lens', lensOn.value > 0 ? 'open' : 'closed');
  }

  /**
   * Every tick grows by its nearness to the lens (a gaussian, --lens 0…1 on the tick): its line wider, its label
   * larger and brighter (poster.css draws it; a short stage keeps the labels within the rail). Nothing when closed.
   */
  function applyLens() {
    const height = gauge.clientHeight || 1;
    const amount = reducedMotion() ? 0 : lensOn.value;
    root.setAttribute('data-lens', amount > 0 ? 'moving' : 'closed');
    for (const tick of ticks.children) {
      const y = share(Number(tick.getAttribute('data-metres'))) * height;
      const near = amount > 0 ? amount * Math.exp(-(((y - lensY.value) / LENS.sigma) ** 2)) : 0;
      if (near > 0.002) tick.style.setProperty('--lens', near.toFixed(3));
      else tick.style.removeProperty('--lens');
      tick.toggleAttribute('data-near', near > 0.5);
    }
  }

  gauge.addEventListener('pointermove', onProbe);
  gauge.addEventListener('pointerdown', onProbe);
  gauge.addEventListener('pointerleave', endProbe);

  // ---- a horizon under the pointer or the focus: the highlight in the stage and the chip ---------------------------

  const chipLevel = () => hoverLevel || focusLevel;

  function setHover(name) {
    hoverLevel = name;
    showLevel();
  }

  function showLevel() {
    const name = chipLevel();
    if (name !== litLevel) {
      litLevel = name;
      if (ctx.stage.setLevelHighlight) ctx.stage.setLevelHighlight(name);
    }
    root.setAttribute('data-lit', name || '');
    paintChip();
  }

  /** The published summary of a horizon: the people whose published place is on it, its zones with their state. */
  function paintChip() {
    const name = chipLevel();
    const state = store.getState();
    const level = name ? levelsNow.find((entry) => entry.name === name) : null;
    if (!level || !state.model || !range) {
      chip.hidden = true;
      chip.removeAttribute('data-level');
      return;
    }
    const model = state.model;
    const nodes = state.attributes && state.attributes.mine ? state.attributes.mine.nodes || {} : {};
    const onLevel = new Set(thingsOfKind(model, 'working').filter((working) => levelOfWorking(model, nodes, working, levelsNow) === level.name)
      .map((working) => working.name));
    const people = model.hasSnapshot ? thingsOfKind(model, 'worker').filter((worker) => worker.values.status !== 'out'
      && onLevel.has(worker.values.at_working)).length : null;
    const zones = thingsOfKind(model, 'zone').filter((zone) => zone.attrs.level === level.name);
    const rows = zones.map((zone) => ({key: zone.name, state: zoneState(zone),
      words: Z.chipZone(zone.label, zone.hasState && zone.hazard ? text.UI.rail.hazardShort[zone.hazard.state] || text.hazardText(zone.hazard)
        : text.UI.rail.noState)}));
    chip.replaceChildren(
      h('span', {class: 'hz__chip-title', text: level.label}),
      h('span', {class: 'hz__chip-line', 'data-chip': 'people', text: people === null ? text.UI.rail.noState : Z.chipPeople(people)}),
      ...(rows.length ? rows.map((row) => {
        const holder = h('span', {class: 'hz__chip-sign', 'aria-hidden': 'true'});
        if (row.state !== 'normal') setSign(holder, row.state);
        return h('span', {class: 'hz__chip-line', 'data-chip': 'zone', 'data-zone': row.key, 'data-state': row.state}, holder, h('span', {text: row.words}));
      }) : [h('span', {class: 'hz__chip-line hz__chip-line--quiet', text: Z.chipNoZones})]),
    );
    chip.style.top = at(level.elevation);
    chip.setAttribute('data-level', level.name);
    chip.hidden = false;
  }

  // ---- the window and scrolling through depth -------------------------------------------------------------------

  const depthView = () => (ctx.stage.depthView ? ctx.stage.depthView() : null);
  const canScroll = () => Boolean(ctx.stage.scrollDepth && depthView());
  let dragging = null;     // {id, y0, centre0, pxPerM} while the window is dragged
  let pressing = null;     // {id, x0, y0} a press on the track that may be a click
  let snapTimer = 0;

  /** The window: the depths the stage shows now, from the frame that moved the camera (ctx.stage.onView). */
  function placeWindow() {
    const view = range ? depthView() : null;
    win.hidden = !view;
    if (!view) return;
    const top = Math.min(Math.max(share(view.top), 0), 1);
    const bottom = Math.min(Math.max(share(view.bottom), 0), 1);
    win.style.top = `${top * 100}%`;
    win.style.height = `${Math.max(bottom - top, 0) * 100}%`;
    setAttrs(win, {'data-top': Math.round(view.top * 10) / 10, 'data-bottom': Math.round(view.bottom * 10) / 10,
      'data-centre': Math.round(view.centre * 10) / 10, 'data-overview': view.overview ? '' : null,
      'data-scroll': ctx.stage.scrollDepth ? '' : null});
    if (dragging) showProbeAt(view.centre);
  }

  /** The probe at a depth (while dragging: the middle of the window). */
  function showProbeAt(z) {
    const value = Math.round(z);
    probe.hidden = false;
    probe.style.top = `${Math.min(Math.max(share(value), 0), 1) * 100}%`;
    setText(probeValue, Z.depth(value));
    probe.setAttribute('data-z', String(value));
    root.setAttribute('data-probe', String(value));
  }

  /** The upper and the lower horizon, and the usual spacing of the horizons (m). */
  function spacing() {
    const zs = levelsNow.map((level) => level.elevation);
    const gaps = zs.slice(1).map((z, i) => Math.abs(zs[i] - z)).sort((p, q) => p - q);
    return gaps.length ? gaps[Math.floor(gaps.length / 2)] : 100;
  }

  /** Scroll the stage; leaves the horizon chosen on the rail (the camera is the user's now). */
  function scroll(spec) {
    current = null;
    return ctx.stage.scrollDepth(spec);
  }

  /** After the wheel rests: a horizon within SNAP_M of the middle of the window takes the middle (a soft snap). */
  function snapSoon() {
    clearTimeout(snapTimer);
    snapTimer = setTimeout(() => {
      snapTimer = 0;
      const view = depthView();
      if (!view || view.overview || dragging) return;
      const near = levelsNow.reduce((best, level) => (!best || Math.abs(level.elevation - view.goalCentre) < Math.abs(best.elevation - view.goalCentre)
        ? level : best), null);
      if (near && Math.abs(near.elevation - view.goalCentre) <= SNAP_M && Math.abs(near.elevation - view.goalCentre) > 0.05) {
        scroll({to: near.elevation, ms: SCROLL.snapMs});
        root.setAttribute('data-snapped', near.name);
      }
    }, SCROLL.snapAfter);
  }

  /** Scroll by `steps` wheel ticks (down positive); at the overview the first tick down reads the depth `at`. */
  function wheelBy(steps, at) {
    const view = depthView();
    if (!view) return;
    if (view.overview) {
      if (steps > 0) scroll({to: at, read: true, ms: SCROLL.read});
      return;
    }
    const span = Math.max(view.goalTop - view.goalBottom, 1);
    const before = view.goalCentre;
    const after = scroll({by: -steps * span * SCROLL.tick, ms: SCROLL.settle});
    // Up against the top of what can be shown: back to the overview.
    if (steps < 0 && after !== null && after - before < 0.5) {
      clearTimeout(snapTimer);
      ctx.stage.overview();
      return;
    }
    snapSoon();
  }

  root.addEventListener('wheel', (event) => {
    if (!canScroll() || !range) return;
    event.preventDefault();
    const unit = event.deltaMode === 1 ? 33 : (event.deltaMode === 2 ? 400 : 1);
    const steps = Math.max(-3, Math.min(3, (event.deltaY * unit) / 100));
    if (Math.abs(steps) < 0.01) return;
    const box = gauge.getBoundingClientRect();
    const y = event.clientY - box.top;
    const view = depthView();
    const at = y >= 0 && y <= box.height ? depthAt(y, box.height) : (view ? view.centre : levelsNow[0].elevation);
    wheelBy(steps, at);
  }, {passive: false});

  gauge.addEventListener('pointerdown', (event) => {
    if (!canScroll() || !range || event.button > 0) return;
    if (event.target.closest && event.target.closest('.hz__level')) return;
    const box = gauge.getBoundingClientRect();
    const onWindow = event.target === win || win.contains(event.target);
    if (onWindow || event.pointerType === 'touch') {
      // Drag the window (a finger anywhere on the rail): the middle of the window follows the pointer 1:1 in depth.
      let view = depthView();
      if (view.overview) {
        scroll({to: depthAt(event.clientY - box.top, box.height), read: true, ms: 0});
        view = depthView();
      }
      dragging = {id: event.pointerId, y0: event.clientY, centre0: view.goalCentre, pxPerM: box.height / (range.top - range.bottom)};
      gauge.setPointerCapture(event.pointerId);
      win.classList.add('is-dragging');
      root.setAttribute('data-dragging', '');
      clearTimeout(snapTimer);
      if (ctx.stage.setDepthProbe) ctx.stage.setDepthProbe(null);
      showProbeAt(view.centre);
      event.preventDefault();
      return;
    }
    pressing = {id: event.pointerId, x0: event.clientX, y0: event.clientY};
  });

  gauge.addEventListener('pointermove', (event) => {
    if (!dragging || event.pointerId !== dragging.id) return;
    const dz = -(event.clientY - dragging.y0) / dragging.pxPerM;
    scroll({to: dragging.centre0 + dz, ms: 0});
  });

  const endDrag = (event) => {
    if (dragging && event.pointerId === dragging.id) {
      dragging = null;
      win.classList.remove('is-dragging');
      root.removeAttribute('data-dragging');
      if (gauge.hasPointerCapture && gauge.hasPointerCapture(event.pointerId)) gauge.releasePointerCapture(event.pointerId);
      onProbe(event);
      return;
    }
    if (pressing && event.pointerId === pressing.id && event.type === 'pointerup') {
      const moved = Math.hypot(event.clientX - pressing.x0, event.clientY - pressing.y0);
      pressing = null;
      if (moved > 5) return;
      // A press on the track: the window glides there (from the overview: a depth reading there).
      const box = gauge.getBoundingClientRect();
      const z = depthAt(event.clientY - box.top, box.height);
      const view = depthView();
      if (view && view.overview) scroll({to: z, read: true, ms: SCROLL.read});
      else if (view && (z > view.top || z < view.bottom)) scroll({to: z, ms: SCROLL.jump});
    }
    pressing = null;
  };
  gauge.addEventListener('pointerup', endDrag);
  gauge.addEventListener('pointercancel', endDrag);

  // ---- keyboard ------------------------------------------------------------------------------------------------

  root.addEventListener('keydown', (event) => {
    if (!levelsNow.length) return;
    const buttons = [...marks.querySelectorAll('.hz__level')];
    const index = buttons.indexOf(document.activeElement);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      const step = event.key === 'ArrowDown' ? 1 : -1;
      const nextIndex = index < 0 ? (step > 0 ? 0 : buttons.length - 1) : Math.min(Math.max(index + step, 0), buttons.length - 1);
      const next = buttons[nextIndex];
      if (!next) return;
      event.preventDefault();
      keyLevel = next.getAttribute('data-level');
      for (const button of buttons) button.setAttribute('tabindex', button === next ? '0' : '-1');
      next.focus();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      go(null);
    } else if (['PageUp', 'PageDown', 'Home', 'End'].includes(event.key) && canScroll()) {
      // Through depth: a horizon spacing, or the upper and the lower horizon.
      event.preventDefault();
      const view = depthView();
      const first = levelsNow[0].elevation;
      const last = levelsNow[levelsNow.length - 1].elevation;
      if (event.key === 'Home' || event.key === 'End') {
        scroll({to: event.key === 'Home' ? first : last, read: view.overview, ms: view.overview ? SCROLL.read : SCROLL.jump});
      } else if (view.overview) {
        if (event.key === 'PageDown') scroll({to: first, read: true, ms: SCROLL.read});
      } else {
        const before = view.goalCentre;
        const after = scroll({by: event.key === 'PageDown' ? -spacing() : spacing(), ms: SCROLL.jump});
        if (event.key === 'PageUp' && after !== null && after - before < 0.5) ctx.stage.overview();
      }
    }
  });

  // ---- what makes it paint -------------------------------------------------------------------------------------

  store.watch((state) => [state.model, state.attributes, state.ui.projection, state.ui.level, state.boot], paint);
  // The people as the 3D stage draws them: the frame of the stage that moved one tells it (ctx.stage.onPeople), and
  // the dots are placed in that same frame, so a dot and its figure are never a frame apart.
  let listening = false;
  const listen = () => {
    if (listening || !ctx.stage.onPeople) return;
    listening = true;
    ctx.stage.onPeople(paintPeople);
    // The window follows the camera in the frame that moved it; the cursor and the hidden state follow later.
    if (ctx.stage.onView) ctx.stage.onView(placeWindow);
  };
  listen();
  queueMicrotask(listen);
  // The camera of the 3D stage moved or the mode changed: the stage mirrors it on its own attributes.
  const stage = document.getElementById('stage');
  if (stage) {
    let timer = null;
    const later = () => {
      listen();
      if (timer === null) timer = setTimeout(() => { timer = null; paint(); }, 150);
    };
    new MutationObserver(later).observe(stage, {attributes: true, attributeFilter: ['data-stage-mode', 'data-camera', 'data-choreo']});
  }
  // A new size of the gauge: the cursor and the dots are placed again (at once).
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => {
      if (!range) return;
      placeCursor(inView(levelsNow), false);
      paintPeople();
    }).observe(gauge);
  }
}
