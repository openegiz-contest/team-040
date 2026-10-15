// The situation headline (variant 3 «Глубина»): one line in poster type over
// the top left of the stage that says what is going on in the shift —
// «ШАХТА РАБОТАЕТ», «УЧАСТОК Г — ОПАСНО», «ВЫВОД ПЕРСОНАЛА · ВЫШЛИ 2»,
// «ИТОГ: ВЫШЛИ 4» — from situationOf (situation.js) and published values only.
// Under it, short lines of what must not be missed: zones that are not «норма»
// (an unknown state is never quiet), people in danger, people without a route.
//
// Contract: renders into ctx.roots.headline (#headline, a `.centre__bar` child of
// #centre, so the 3D stage keeps its labels and its framing clear of it).
// data-testid="situation-headline"; data-situation, data-tone and data-old on the
// root; every number of the title carries data-value.
//
// Motion (motion.js): when the words change, the old line leaves upward and the
// new words rise one after another out of their masks; when only a published
// number changes, that number slides from the old value to the new one. Once per
// change, at most 600 ms, never over old data, never under reduced motion. The
// first line of a page load is revealed once (the intro), in the 3D mode only.

import {h, reconcile, setAttrs, setText} from '../dom.js';
import {showsOldData} from '../link.js';
import {incidentOf, thingByName, thingsOfKind} from '../model.js';
import {motionAllowed, reducedMotion, slideValue, stagger} from '../motion.js';
import {situationOf} from '../situation.js';
import {decisionOf, headline as forecastLine, optionVerb} from './decision.js';
import {incidentSentence} from './progress.js';

const count = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const word = (text, tone = null) => ({kind: 'word', text, tone});
const number = (role, value, text, tone = null) => ({kind: 'num', role, value, text, tone});
const NBSP = ' ';
/** A separator («—», «·») stays at the end of the word before it, so that a line never starts with it. */
function joined(parts) {
  const out = [];
  let prefix = '';
  for (const part of parts) {
    const last = out[out.length - 1];
    if (part.kind === 'sep' && last && last.kind === 'word') out[out.length - 1] = {...last, text: `${last.text}${NBSP}${part.text}`};
    else if (part.kind === 'sep' && last && last.kind === 'num') out[out.length - 1] = {...last, after: part.text};
    else if (part.kind === 'sep') prefix = `${part.text}${NBSP}`;
    else if (prefix && part.kind === 'word') {
      out.push({...part, text: `${prefix}${part.text}`});
      prefix = '';
    } else out.push(part);
  }
  if (prefix) out.push(word(prefix.trim()));
  return out;
}
const sep = (text) => ({kind: 'sep', text});

/** The option the incident carries out or carried out (the same rule as the panel). */
function optionOf(model) {
  const decision = decisionOf(model);
  if (decision.executing) return decision.executing;
  const incident = incidentOf(model);
  const selected = incident ? thingByName(model, incident.values.selected_option) : null;
  if (selected && selected.kind === 'option') return selected;
  return decision.executed[decision.executed.length - 1] || null;
}

/**
 * What the headline says: kicker, title parts, tone, and the lines under it.
 * @returns {{kicker: string, title: Array, tone: (string|null), lines: Array<{key: string, text: string, tone: (string|null)}>}}
 */
export function headlineOf(text, state) {
  const H = text.HEADLINE;
  const P = text.PANEL;
  const situation = situationOf(state);
  const {model} = state;
  const lines = [];
  if (situation === 'none' || !model) {
    return {situation, kicker: H.kicker.none, title: H.waiting.map((item) => word(item)), tone: 'unknown', lines};
  }
  const shift = model.shift ? model.shift.values : {};
  const inDanger = count(shift.workers_in_danger);
  const noRoute = count(shift.workers_no_route);
  const unknown = count(shift.workers_unknown);
  const peopleLines = () => {
    if (inDanger > 0) lines.push({key: 'in-danger', text: H.inDanger(inDanger), tone: 'danger'});
    if (unknown > 0) lines.push({key: 'unknown', text: H.unknown(unknown), tone: 'unknown'});
    if (noRoute > 0) lines.push({key: 'no-route', text: H.noRoute(noRoute), tone: 'noroute'});
  };
  const zones = thingsOfKind(model, 'zone');
  let title;
  let tone = null;

  if (situation === 'norm') {
    const working = zones.filter((zone) => zone.values.work_state === 'working');
    const stopped = zones.length > 0 && zones.every((zone) => zone.values.work_state === 'stopped');
    title = (working.length > 0 ? H.working : (stopped ? H.stopped : H.noState)).map((item) => word(item));
    if (working.length === 0 && !stopped) tone = 'unknown';
    // A zone that is not «норма» is named; an unknown state is never silent.
    for (const zone of zones) {
      const state = zone.hasState && zone.hazard ? zone.hazard.state : 'unknown';
      if (state === 'normal') continue;
      const words = zone.hasState && zone.hazard ? text.hazardText(zone.hazard) : text.UI.rail.noState;
      lines.push({key: zone.name, text: H.zoneState(zone.label, words), tone: state});
    }
    peopleLines();
    if (lines.length === 0 && zones.length > 0) lines.push({key: 'all-normal', text: H.allNormal, tone: null});
  } else if (situation === 'decision') {
    const said = incidentSentence(text, model);
    const incident = incidentOf(model);
    const zone = incident ? thingByName(model, incident.values.zone) : null;
    const split = said.line.indexOf(' — ');
    if (zone && split > 0) {
      title = [...said.line.slice(0, split).split(' ').map((item) => word(item)), sep('—'),
        ...said.line.slice(split + 3).split(' ').map((item) => word(item, said.hazard))];
    } else {
      title = said.line.split(' ').map((item) => word(item, said.hazard));
    }
    tone = said.hazard;
    peopleLines();
    const {snapshot} = state;
    if (snapshot && snapshot.runState === 'paused' && snapshot.pauseReason === 'decision') {
      lines.push({key: 'paused', text: H.paused, tone: 'accent'});
    }
  } else if (situation === 'executing') {
    const option = optionOf(model);
    const observe = option && (option.attrs.option_kind === 'observe'
      || !(Array.isArray(option.values.scope) && option.values.scope.length > 0));
    if (observe) {
      title = [...H.observe.map((item) => word(item)), sep('·'),
        ...H.inDangerWord.split(' ').map((item) => word(item)),
        number('in-danger', inDanger, inDanger === null ? text.DASH : text.num(inDanger), inDanger > 0 ? 'danger' : null)];
    } else {
      const out = count(shift.workers_out);
      title = [...H.withdrawal.map((item) => word(item)), sep('·'), word(H.outWord),
        number('out', out, out === null ? text.DASH : text.num(out), 'accent')];
    }
    if (option) lines.push({key: 'option', text: optionVerb(text, model, option), tone: null});
    if (option && !observe) {
      const values = option.values;
      let expected = '';
      if (values.forecast_all_out === true) expected = P.expectAllOut(values.forecast_last_out_s);
      else if (typeof values.forecast_out === 'number') expected = P.expectOut(values.forecast_out);
      if (expected) lines.push({key: 'expect', text: expected, tone: 'forecast'});
    }
    // The people stay in the rail and the panel; an unknown state is still said here, never silenced.
    if (unknown > 0) lines.push({key: 'unknown', text: H.unknown(unknown), tone: 'unknown'});
  } else {
    // done: the fact of the run, by the same fixed rules as the panel; no success that was not published.
    const option = optionOf(model);
    const values = option ? option.values : {};
    const fact = option ? forecastLine(text, values, 'actual_') : null;
    const out = count(values.actual_out);
    const danger = count(values.actual_in_danger);
    if (!fact) {
      title = H.resultUnknown.map((item) => word(item));
      tone = 'unknown';
    } else if (values.actual_all_out === true) {
      title = [word(H.result), ...H.allOut.map((item) => word(item, 'accent'))];
    } else if (danger > 0) {
      title = [word(H.result), number('in-danger', danger, text.num(danger), 'danger'),
        ...H.resultInDanger.split(' ').map((item) => word(item, 'danger'))];
      tone = 'danger';
    } else {
      title = [word(H.result), word(H.outWord), number('out', out, out === null ? text.DASH : text.num(out), 'accent')];
      if (values.actual_all_out === false) title.push(sep('·'), word(H.notAll.replace(/ /g, NBSP), 'noroute'));
    }
    if (fact) lines.push({key: 'fact', text: fact.text, tone: fact.rule === 'in_danger' ? 'danger' : (fact.rule === 'no_route' ? 'noroute' : null)});
    for (const zone of zones.filter((item) => item.values.withdrawal_state === 'incomplete')) {
      lines.push({key: `incomplete-${zone.name}`, text: P.incomplete(zone.label), tone: 'noroute'});
    }
  }
  return {situation, kicker: H.kicker[situation], title: joined(title), tone, lines};
}

/** The structure of a title: its words and the roles of its numbers (a changed number alone does not rebuild it). */
const shapeOf = (title) => title.map((part) => (part.kind === 'num' ? `#${part.role}:${part.tone || ''}:${part.after || ''}`
  : `${part.text}:${part.tone || ''}`)).join('|');

export function mount(root, ctx) {
  const {store, text} = ctx;
  const H = text.HEADLINE;

  const kicker = h('p', {class: 'hl__kicker'}, h('span', {class: 'hl__tick', 'aria-hidden': 'true'}), h('span', {class: 'hl__kicker-words'}));
  const title = h('h1', {class: 'hl__title', 'aria-live': 'polite'});
  const lines = h('ul', {class: 'hl__lines'});
  root.append(kicker, title, lines);
  setAttrs(root, {role: 'region', 'aria-label': H.region, 'data-testid': 'situation-headline'});

  let shape = null;
  let introDone = false;

  /** The words of the title, each in its mask; a separator after a number stays on its line (.hl__g). */
  function buildTitle(parts) {
    const masks = [];
    const groups = parts.map((part) => {
      const mask = h('span', {class: ['hl__m', part.kind === 'num' && 'hl__m--num'], 'data-tone': part.tone,
        'data-role': part.kind === 'num' ? part.role : null, 'data-value': part.kind === 'num' ? part.value : null},
      h('span', {class: 'hl__w', text: part.text}));
      masks.push(mask);
      if (!part.after) return mask;
      const after = h('span', {class: 'hl__m'}, h('span', {class: 'hl__w', text: part.after}));
      masks.push(after);
      return h('span', {class: 'hl__g'}, mask, NBSP, after);
    });
    const spaced = [];
    groups.forEach((node, index) => {
      if (index > 0) spaced.push(' ');
      spaced.push(node);
    });
    title.replaceChildren(...spaced);
    return masks;
  }

  function render() {
    const state = store.getState();
    const said = headlineOf(text, state);
    const old = showsOldData(state.link) && Boolean(state.snapshot);
    setText(kicker.lastChild, old ? H.old : said.kicker);
    // A long title is set smaller, so that it keeps to two lines.
    const length = said.title.reduce((sum, part) => sum + part.text.length + (part.after ? part.after.length + 1 : 0) + 1, 0);
    setAttrs(root, {'data-situation': said.situation, 'data-tone': said.tone, 'data-old': old ? 'true' : null,
      'data-length': length > 26 ? 'long' : (length > 18 ? 'mid' : null)});
    const animate = motionAllowed(state);
    const nextShape = shapeOf(said.title);

    const seen = new Set([...lines.children].map((node) => node.getAttribute('data-line')));
    reconcile(lines, said.lines, (line) => line.key, () => h('li', {class: 'hl__line'}, h('span', {class: 'hl__sign', 'aria-hidden': 'true'}),
      h('span', {class: 'hl__words'})), (node, line) => {
      setText(node.lastChild, line.text);
      setAttrs(node, {'data-tone': line.tone, 'data-line': line.key});
    });
    const fresh = [...lines.children].filter((node) => !seen.has(node.getAttribute('data-line')));
    const titleChanged = nextShape !== shape;
    if (titleChanged) {
      const before = title.firstChild ? title.cloneNode(true) : null;
      if (before) for (const ghost of before.querySelectorAll('.hl__title--ghost')) ghost.remove();
      const first = shape === null || shape === shapeOf(headlineOf(text, {model: null}).title);
      const nodes = buildTitle(said.title);
      shape = nextShape;
      const stage = document.getElementById('stage');
      const intro = first && !introDone && said.situation !== 'none'
        && !(stage && stage.getAttribute('data-stage-mode') === 'scheme');
      if (said.situation !== 'none') introDone = true;
      if (animate && (intro || !first)) {
        let start = 0;
        if (before && !first) {
          // The old line leaves upward, word by word, as a ghost over the new one.
          before.classList.add('hl__title--ghost');
          before.removeAttribute('aria-live');
          before.setAttribute('aria-hidden', 'true');
          title.append(before);
          const gone = stagger([...before.querySelectorAll('.hl__w')], [{transform: 'translateY(0)'}, {transform: 'translateY(-105%)'}],
            {duration: 220, step: 20});
          const drop = () => before.remove();
          if (gone.length > 0) Promise.all(gone.map((motion) => motion.finished)).then(drop, drop);
          else drop();
          start = 140;
        }
        stagger(nodes.map((node) => node.firstChild), [{transform: 'translateY(108%)'}, {transform: 'translateY(0)'}],
          {duration: 440, start, step: 55});
        stagger([...lines.children], [{opacity: 0, transform: 'translateY(10px)'}, {opacity: 1, transform: 'none'}],
          {duration: 320, start: start + 180, step: 40});
      }
    } else {
      // A line that appears under the same title rises in once.
      if (animate && fresh.length > 0 && seen.size > 0) {
        stagger(fresh, [{opacity: 0, transform: 'translateY(10px)'}, {opacity: 1, transform: 'none'}], {duration: 320, step: 40});
      }
      // Same words: a published number that changed slides from its old value to the new one.
      for (const part of said.title) {
        if (part.kind !== 'num') continue;
        const holder = title.querySelector(`.hl__m--num[data-role="${part.role}"]`);
        if (!holder) continue;
        const inner = holder.firstChild;
        const before = inner.textContent;
        if (before === part.text) continue;
        setText(inner, part.text);
        setAttrs(holder, {'data-value': part.value});
        if (animate) slideValue(holder, inner, before, 380);
      }
    }
  }

  // The band of notices (rare states) pushes the stage down: what floats over the stage follows it (--notices-h).
  const notices = ctx.roots.banners ? ctx.roots.banners.parentElement : null;
  const centre = ctx.roots.centre;
  if (notices && centre && typeof ResizeObserver === 'function') {
    new ResizeObserver(() => centre.style.setProperty('--notices-h', `${Math.round(notices.getBoundingClientRect().height)}px`)).observe(notices);
  }

  // The HUD of the stage (view/stage.js) lies over the top of the stage too. The headline keeps beside it when
  // there is room for a line of the title, and else starts under it (--hl-top, --hl-room on #centre).
  const MIN_ROOM = 560;
  function placeBesideHud() {
    if (!centre) return;
    const row = document.querySelector('#stage-hud .hud__row');
    const box = centre.getBoundingClientRect();
    const left = root.getBoundingClientRect().left;
    let top = null;
    let room = null;
    const hud = row && row.getClientRects().length > 0 ? row.getBoundingClientRect() : null;
    // Only a HUD along the top of the stage is in the way of the headline.
    if (hud && hud.top < box.top + 200) {
      if (hud.left - left >= MIN_ROOM || hud.right < left) room = hud.right < left ? null : Math.round(hud.left - left - 32);
      else top = Math.round(hud.bottom - box.top + 14);
    }
    centre.style.setProperty('--hl-top', top === null ? '' : `${top}px`);
    centre.style.setProperty('--hl-room', room === null ? '' : `${room}px`);
    if (top === null) centre.style.removeProperty('--hl-top');
    if (room === null) centre.style.removeProperty('--hl-room');
    // The scheme (an SVG that fits its box) starts under the headline: the bottom of the headline over the stage.
    const stage = document.getElementById('stage');
    const own = root.getBoundingClientRect();
    if (stage && own.height > 0) {
      centre.style.setProperty('--hl-bottom', `${Math.max(0, Math.round(own.bottom - stage.getBoundingClientRect().top + 8))}px`);
    }
  }
  // Resize observers already run after layout and before paint: place at once, coalesced in one microtask,
  // so that a banner appearing (e.g. on a failed read) never asks for an animation frame.
  let placing = false;
  const place = () => {
    if (placing) return;
    placing = true;
    queueMicrotask(() => { placing = false; placeBesideHud(); });
  };
  if (typeof ResizeObserver === 'function' && centre) {
    const watcher = new ResizeObserver(place);
    watcher.observe(centre);
    watcher.observe(root);
    const hud = ctx.roots.stageHud;
    if (hud) {
      watcher.observe(hud);
      new MutationObserver(place).observe(hud, {subtree: true, childList: true, attributes: true, attributeFilter: ['hidden', 'class']});
    }
    new MutationObserver(place).observe(document.body, {attributes: true, attributeFilter: ['data-panel', 'data-stand', 'data-rail']});
    const stage = document.getElementById('stage');
    if (stage) new MutationObserver(place).observe(stage, {attributes: true, attributeFilter: ['data-hud-fold', 'data-stage-mode']});
  }

  store.watch((state) => [state.model, state.snapshot, state.link, state.boot], render);
  if (reducedMotion()) introDone = true;
}

