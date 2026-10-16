// Hash routes, both ways. A route only opens a view and selects an object:
// nothing in a URL can send a command, so a reload never repeats an incident.
//
//   #/scheme?sel=<thingId>&view=axo|plan&level=<local id>&mode=3d|scheme
//   #/list?type=<kind>&sel=<thingId>
//   #/runs
//
// `mode` chooses the stage (3D model or SVG scheme). It is read in every view
// and kept when a route does not carry it; it is written only in the scheme view.

import {ID_PATTERN, LOCAL_NAME_PATTERN} from './config.js';

/** @typedef {import('./store.js').State['ui']} UiState */

const VIEWS = ['scheme', 'list', 'runs'];
const PROJECTIONS = ['axo', 'plan'];
const STAGE_MODES = ['3d', 'scheme'];
export const LIST_TYPES = ['all', 'level', 'working', 'zone', 'sensor', 'worker', 'equipment', 'exit', 'incident', 'option', 'journal'];

/**
 * The UI state a hash asks for. Anything unreadable falls back to the default
 * of its field; fields the route does not carry keep their current value.
 * @param {string} hash location.hash
 * @param {UiState} current
 * @returns {UiState}
 */
export function parseHash(hash, current) {
  const text = hash.replace(/^#\/?/, '');
  const mark = text.indexOf('?');
  const path = mark < 0 ? text : text.slice(0, mark);
  const params = new URLSearchParams(mark < 0 ? '' : text.slice(mark + 1));
  const view = VIEWS.includes(path) ? path : 'scheme';
  const sel = params.get('sel');
  const next = {...current, view, selected: sel !== null && ID_PATTERN.test(sel) ? sel : null};
  const mode = params.get('mode');
  if (STAGE_MODES.includes(mode)) next.stageMode = mode;
  if (view === 'scheme') {
    const projection = params.get('view');
    const level = params.get('level');
    next.projection = PROJECTIONS.includes(projection) ? projection : 'axo';
    next.level = level !== null && LOCAL_NAME_PATTERN.test(level) ? level : null;
  } else if (view === 'list') {
    const type = params.get('type');
    next.listType = LIST_TYPES.includes(type) ? type : 'all';
  }
  return next;
}

/**
 * The canonical hash of a UI state; defaults are left out.
 * @param {UiState} ui
 * @returns {string}
 */
export function formatHash(ui) {
  const params = [];
  if (ui.view === 'scheme') {
    if (ui.selected) params.push(`sel=${ui.selected}`);
    if (ui.projection !== 'axo') params.push(`view=${ui.projection}`);
    if (ui.level) params.push(`level=${ui.level}`);
    if (ui.stageMode) params.push(`mode=${ui.stageMode}`);
  } else if (ui.view === 'list') {
    if (ui.listType !== 'all') params.push(`type=${ui.listType}`);
    if (ui.selected) params.push(`sel=${ui.selected}`);
  }
  return `#/${ui.view}${params.length > 0 ? `?${params.join('&')}` : ''}`;
}

function sameUi(a, b) {
  return a.view === b.view && a.projection === b.projection && a.level === b.level
    && a.selected === b.selected && a.listType === b.listType && a.stageMode === b.stageMode;
}

/**
 * Keep the hash and `state.ui` in step.
 * @param {import('./store.js').Store} store
 */
export function startRouter(store) {
  function fromHash() {
    const current = store.getState().ui;
    const next = parseHash(window.location.hash, current);
    if (!sameUi(next, current)) store.update({ui: next});
  }

  fromHash();
  window.addEventListener('hashchange', fromHash);
  store.watch((state) => state.ui, (ui) => {
    const hash = formatHash(ui);
    // replaceState: selecting objects must not fill the browser history, and it raises no hashchange.
    if (window.location.hash !== hash) window.history.replaceState(null, '', hash);
  });
}
