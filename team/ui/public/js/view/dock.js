// The decision dock under the stage: present only while an incident is open,
// unfolded or folded to its bar. The bar is this view's: the title, a slot for
// the one-line summary (ctx.roots.decisionSummary, filled by view/decision.js)
// and the fold button. The options themselves are view/decision.js's (#decision).
//
// When it unfolds by itself: an incident that asks for a decision (a new
// `active` state), and an incident already executing or done when it is first
// seen with nothing selected (the page was loaded in the middle of it).
// Otherwise the user's choice stays. In the compact layout the dock lies over
// the stage, so there it only shows its bar by itself and unfolds on request.
// While it lies over the stage, its height is published as --dock-cover on the
// centre column (the legend chip stays above it), and the height of its bar as
// --dock-bar-cover (the 3D picture and the scheme are fitted above the bar).
// Unfolding and folding take 200 ms (the height of the body); never under
// reduced motion or with old data, never when the dock comes or goes with
// the incident.

import {h, setAttrs} from '../dom.js';
import {incidentOf} from '../model.js';
import {EASE, MS, motionAllowed, play} from '../motion.js';

const OPEN = new Set(['active', 'executing', 'done']);
/** The compact layout of layout.css. */
const COMPACT = '(max-width: 1599px), (max-height: 899px)';

export function mount(root, ctx) {
  const {store, text, shell} = ctx;
  const {UI} = text;

  const summary = h('div', {class: 'dock__summary', id: 'decision-summary', 'data-testid': 'decision-summary'});
  ctx.roots.decisionSummary = summary;
  const toggle = h('button', {
    class: 'btn btn--quiet btn--small dock__toggle', type: 'button', 'data-testid': 'dock-toggle',
    'aria-controls': 'decision', 'aria-expanded': 'false',
  });
  toggle.addEventListener('click', () => shell.set({dock: shell.get().dock === 'open' ? 'collapsed' : 'open'}));
  ctx.roots.dockBar.append(h('h2', {class: 'dock__title', id: 'dock-title', text: UI.dock.title}), summary, toggle);
  setAttrs(root, {role: 'region', 'aria-labelledby': 'dock-title'});

  const body = ctx.roots.decision;
  let folding = null;
  let shown = shell.get().dock;
  /** The body of the dock opens from no height to its own, or closes to none; it stays drawn while it closes. */
  function move(from, to) {
    if (!body || !motionAllowed(store.getState())) return;
    if (from === 'collapsed' && to === 'open') {
      const height = body.getBoundingClientRect().height;
      if (height > 0) play(body, [{height: '0px', overflow: 'hidden'}, {height: `${height}px`, overflow: 'hidden'}], {duration: MS.dock, easing: EASE});
    } else if (from === 'open' && to === 'collapsed') {
      root.setAttribute('data-folding', 'true');
      const height = body.getBoundingClientRect().height;
      const motion = height > 0
        ? play(body, [{height: `${height}px`, overflow: 'hidden'}, {height: '0px', overflow: 'hidden'}], {duration: MS.dock, easing: EASE}) : null;
      if (!motion) {
        root.removeAttribute('data-folding');
        return;
      }
      folding = motion;
      const end = () => {
        if (folding !== motion) return;
        folding = null;
        root.removeAttribute('data-folding');
      };
      motion.finished.then(end, end);
    }
  }
  shell.watch((frame) => {
    const open = frame.dock === 'open';
    setAttrs(toggle, {'aria-expanded': String(open), text: open ? UI.dock.collapse : UI.dock.expand});
    root.hidden = frame.dock === 'none';
    setAttrs(root, {'data-dock': frame.dock});
    if (folding) {
      folding.cancel();
      folding = null;
      root.removeAttribute('data-folding');
    }
    move(shown, frame.dock);
    shown = frame.dock;
  });

  const unfolded = () => (window.matchMedia && window.matchMedia(COMPACT).matches ? 'collapsed' : 'open');

  const centre = root.parentElement;
  const bar = ctx.roots.dockBar;
  const cover = () => {
    const over = !root.hidden && getComputedStyle(root).position === 'absolute';
    centre.style.setProperty('--dock-cover', `${over ? Math.round(root.getBoundingClientRect().height) : 0}px`);
    centre.style.setProperty('--dock-bar-cover', `${over ? Math.round(bar.getBoundingClientRect().height) : 0}px`);
  };
  if (typeof ResizeObserver === 'function') new ResizeObserver(cover).observe(root);
  shell.watch(cover);
  // The dock lies over the stage only in the view of the mine.
  store.watch((state) => state.ui.view, () => cover());

  let seen = null;
  store.watch((state) => {
    const incident = state.model ? incidentOf(state.model) : null;
    return incident && incident.hasState && state.snapshot ? incident.values.state : null;
  }, (incidentState) => {
    const current = shell.get().dock;
    if (!OPEN.has(incidentState)) {
      shell.set({dock: 'none'});
    } else if (incidentState === 'active' && seen !== 'active') {
      shell.set({dock: unfolded()});
    } else if (current === 'none') {
      shell.set({dock: OPEN.has(seen) || store.getState().ui.selected ? 'collapsed' : unfolded()});
    }
    seen = incidentState;
  });
}
