// The horizon rail (variant 3 «Глубина»): a vertical depth gauge at the right
// edge of the stage, drawn like a borehole log — a scale of metres with minor
// ticks every 10 m and labelled ticks every 50 m, and one mark per horizon at
// its published elevation («−260», «−320», «−380»). It is the depth legend of
// the stage and its way between horizons: a press on a horizon flies the 3D
// camera to it (ctx.stage.focus(levelLocalName)); in the scheme mode it opens
// the plan of that level. «Все» returns to the overview (3D) or the cutaway of
// all levels (scheme). The horizon in view is highlighted.
//
// A horizon also shows the sign of the worst published hazard of its zones
// (danger, attention, or unknown — an unknown state is never quiet); the words
// are in its title and accessible name. Nothing is counted.
//
// Contract: renders into ctx.roots.horizons (#horizons, a `.centre__bar` child of
// #centre: the 3D stage keeps its labels and its framing clear of it).
// Test ids: horizon-rail (root), horizon-all, horizon-<level local name>.

import {h, reconcile, setAttrs, setText} from '../dom.js';
import {sortLevels} from '../geometry.js';
import {thingsOfKind} from '../model.js';
import {EASE_POSTER, motionAllowed, stagger} from '../motion.js';
import {setSign} from './signs.js';

const WORST = ['danger', 'attention', 'unknown'];

/** The range of the gauge: the horizons with a margin, rounded out to 10 m. */
function rangeOf(levels) {
  const top = Math.max(...levels.map((level) => level.elevation));
  const bottom = Math.min(...levels.map((level) => level.elevation));
  const pad = Math.max(20, (top - bottom) * 0.18);
  return {top: Math.ceil((top + pad) / 10) * 10, bottom: Math.floor((bottom - pad) / 10) * 10};
}

export function mount(root, ctx) {
  const {store, text} = ctx;
  const Z = text.HORIZON;

  const all = h('button', {type: 'button', class: 'hz__all', 'data-testid': 'horizon-all', title: Z.allTitle, text: Z.all});
  const head = h('div', {class: 'hz__head'}, h('span', {class: 'hz__title', text: `${Z.title}, ${Z.unit}`}), all);
  const ticks = h('div', {class: 'hz__ticks', 'aria-hidden': 'true'});
  const marks = h('ol', {class: 'hz__levels'});
  const gauge = h('div', {class: 'hz__gauge'}, h('span', {class: 'hz__axis', 'aria-hidden': 'true'}), ticks, marks);
  root.append(head, gauge);
  setAttrs(root, {role: 'navigation', 'aria-label': Z.region, 'data-testid': 'horizon-rail'});

  let current = null;     // the level the user went to; null: all levels
  let drawnKey = null;

  const stageMode = () => {
    const stage = document.getElementById('stage');
    return stage ? stage.getAttribute('data-stage-mode') : null;
  };

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
    }
    return current;
  }

  function hazardOf(model, levelName) {
    const zones = thingsOfKind(model, 'zone').filter((zone) => zone.attrs.level === levelName);
    const states = zones.map((zone) => (zone.hasState && zone.hazard ? zone.hazard.state : 'unknown'));
    const worst = WORST.find((state) => states.includes(state)) || null;
    const words = zones.filter((zone) => (zone.hasState && zone.hazard ? zone.hazard.state : 'unknown') === worst)
      .map((zone) => `${zone.label} — ${zone.hasState && zone.hazard ? text.hazardText(zone.hazard) : text.UI.rail.noState}`);
    return {worst, words: words.join('; ')};
  }

  function paint() {
    const state = store.getState();
    const levels = state.model ? sortLevels(thingsOfKind(state.model, 'level')) : [];
    // The gauge appears with the first full snapshot (and draws itself in then); it stays for the rest of the page.
    const ready = levels.length > 0 && (drawnKey !== null || Boolean(state.model && state.model.hasSnapshot));
    root.hidden = !ready;
    if (!ready) return;
    const range = rangeOf(levels);
    const at = (elevation) => `${((range.top - elevation) / (range.top - range.bottom)) * 100}%`;

    const key = `${range.top}:${range.bottom}`;
    if (key !== drawnKey) {
      const items = [];
      for (let metres = range.top; metres >= range.bottom; metres -= 10) items.push(metres);
      reconcile(ticks, items, (metres) => String(metres), (metres) => {
        const major = metres % 50 === 0;
        return h('span', {class: ['hz__tick', major && 'hz__tick--major']}, major ? h('span', {class: 'hz__tick-label', text: Z.elevation(metres)}) : null);
      }, (node, metres) => {
        node.style.top = at(metres);
      });
    }

    const view = inView(levels);
    reconcile(marks, levels, (level) => level.name, (level) => {
      const button = h('button', {type: 'button', class: 'hz__level', 'data-testid': `horizon-${level.name}`},
        h('span', {class: 'hz__elev'}), h('span', {class: 'hz__sign', 'aria-hidden': 'true'}), h('span', {class: 'hz__bar', 'aria-hidden': 'true'}),
        h('span', {class: 'hz__name'}));
      button.addEventListener('click', () => go(level.name));
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
        'data-elevation': level.elevation});
      item.style.top = at(level.elevation);
    });
    setAttrs(all, {'aria-current': view === null ? 'true' : null});

    if (key !== drawnKey) {
      const first = drawnKey === null;
      drawnKey = key;
      // The gauge draws itself once when the mine is first shown: the axis grows, the horizons come in from the edge.
      const stage = document.getElementById('stage');
      if (first && motionAllowed(state) && !(stage && stage.getAttribute('data-stage-mode') === 'scheme')) {
        stagger([gauge.firstChild], [{transform: 'scaleY(0)'}, {transform: 'scaleY(1)'}], {duration: 520});
        stagger([...marks.children].map((node) => node.firstChild), [{opacity: 0, transform: 'translateX(24px)'}, {opacity: 1, transform: 'none'}],
          {duration: 380, start: 120, step: 70, easing: EASE_POSTER});
      }
    }
  }

  store.watch((state) => [state.model, state.attributes, state.ui.projection, state.ui.level, state.boot], paint);
  // The camera of the 3D stage moved or the mode changed: the stage mirrors it on its own attributes.
  const stage = document.getElementById('stage');
  if (stage) {
    let timer = null;
    const later = () => {
      if (timer === null) timer = setTimeout(() => { timer = null; paint(); }, 150);
    };
    new MutationObserver(later).observe(stage, {attributes: true, attributeFilter: ['data-stage-mode', 'data-camera', 'data-choreo']});
  }
}
