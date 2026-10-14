// Composition of the interface: store, platform reader, commands, routes, views.
//
// THE VIEW-MODULE CONTRACT
//
// Every file in view/ exports `mount(root, ctx)`. It is called once, after the
// document is parsed; `root` is the view's own element of index.html and the
// view owns everything inside it (and nothing outside, except the extra roots
// named below).
//
// ctx:
//   store       the observable store; the state shape is documented in store.js.
//               `store.getState()`, `store.subscribe(fn)`, `store.watch(selector, fn)`.
//   text        the module text.js: every user-visible string, label and formatter.
//   roots       every mount point by name (see ROOTS): a view that also fills a
//               secondary root reads it here, e.g. `ctx.roots.schemeControls`
//               (projection and level controls in the centre bar, owned by
//               view/scheme.js) and `ctx.roots.reset` (the reset block of the
//               left panel, owned by view/conditions.js).
//   select(thingId | null)                    select an object (full thingId) or clear the selection
//   setView('scheme' | 'list' | 'runs')
//   setProjection('axo' | 'plan')
//   setLevel(localName | null)                the level of the plan
//   setListType(kind | 'all')
//   sendCommand(type, target, options?)       -> {ok, id?, reason?}; see commands.js `send`
//   retryCommand(id)                          -> {ok, id?, reason?}; the same id and body again
//   dismissCommand(id)                        stop waiting; removes the entry from state.pending
//   confirm({title, message, confirmLabel, cancelLabel?, danger?}) -> Promise<boolean>
//               the modal dialog of view/dialog.js
//
// A view subscribes itself (prefer `store.watch` with a selector of the slice
// it shows), re-renders only when that slice changed, and updates existing
// nodes in place (dom.js `setAttrs`, `setText`, `reconcile`). A poll arrives
// every second: it must never move keyboard focus, reset a <select> or close
// a dialog. A view never changes an object optimistically: what is drawn is
// `state.model`, and a command of this page shows up only in `state.pending`.

import {createApi} from './api.js';
import {createCommands, deriveBlock, hasOwnResetPending} from './commands.js';
import {DERIVE_INTERVAL_MS} from './config.js';
import {setAttrs} from './dom.js';
import {showsOldData} from './link.js';
import {createPoller} from './poller.js';
import {startRouter} from './router.js';
import {createStore, initialState} from './store.js';
import * as text from './text.js';

import * as actions from './view/actions.js';
import * as card from './view/card.js';
import * as conditions from './view/conditions.js';
import * as decision from './view/decision.js';
import * as dialog from './view/dialog.js';
import * as incident from './view/incident.js';
import * as journal from './view/journal.js';
import * as legend from './view/legend.js';
import * as list from './view/list.js';
import * as overlay from './view/overlay.js';
import * as pending from './view/pending.js';
import * as runs from './view/runs.js';
import * as scheme from './view/scheme.js';
import * as statusbar from './view/statusbar.js';
import * as tabs from './view/tabs.js';

/** Mount points of index.html: name in ctx.roots -> element id. */
const ROOTS = {
  statusbar: 'statusbar', incident: 'incident', banners: 'banners', oldData: 'old-data',
  tabs: 'tabs', schemeControls: 'scheme-controls', rightTabs: 'right-tabs', journalBar: 'journal-bar',
  scheme: 'scheme', legend: 'legend', list: 'view-list', runs: 'view-runs',
  conditions: 'conditions', actions: 'actions', pending: 'pending', reset: 'reset',
  decision: 'decision', card: 'card', journal: 'journal', dialog: 'dialog-root',
};

/** Views in mount order, each with the name of its root. */
const VIEWS = [
  ['statusbar', statusbar], ['incident', incident], ['banners', overlay], ['tabs', tabs], ['list', list],
  ['scheme', scheme], ['legend', legend], ['card', card],
  ['conditions', conditions], ['actions', actions], ['pending', pending],
  ['decision', decision], ['journal', journal], ['runs', runs], ['dialog', dialog],
];

function mirrorOnBody(state) {
  const {snapshot, link} = state;
  setAttrs(document.body, {
    'data-boot': state.boot,
    'data-link': link.link,
    'data-publications': link.publications,
    'data-snapshot': link.snapshot,
    'data-snapshot-reason': link.invalid ? link.invalid.code : null,
    'data-commands': state.commandsBlocked ? 'blocked' : 'enabled',
    'data-block-reason': state.blockReason,
    'data-run': snapshot ? snapshot.run : null,
    'data-tick': snapshot ? snapshot.tick : null,
    'data-seq': snapshot ? snapshot.seq : null,
    'data-run-state': snapshot ? snapshot.runState : null,
    'data-view': state.ui.view,
    'data-old-data': showsOldData(link) ? 'true' : null,
    'data-own-reset': hasOwnResetPending(state.pending) ? 'pending' : null,
  });
}

function start() {
  const now = () => performance.now();
  const store = createStore(initialState(), deriveBlock);
  const api = createApi();
  const poller = createPoller({store, api, now});
  const commands = createCommands({store, api, now});

  const roots = {};
  for (const [name, id] of Object.entries(ROOTS)) roots[name] = document.getElementById(id);

  const setUi = (change) => store.update((state) => {
    const ui = {...state.ui, ...change};
    return Object.keys(change).some((key) => ui[key] !== state.ui[key]) ? {ui} : null;
  });

  const ctx = {
    store, text, roots,
    select: (thingId) => setUi({selected: thingId || null}),
    setView: (view) => setUi({view}),
    setProjection: (projection) => setUi({projection}),
    setLevel: (level) => setUi({level: level || null}),
    setListType: (listType) => setUi({listType}),
    sendCommand: commands.send,
    retryCommand: commands.retry,
    dismissCommand: commands.dismiss,
    confirm: (options) => dialog.confirm(options),
  };

  store.subscribe(mirrorOnBody);
  mirrorOnBody(store.getState());
  startRouter(store);

  for (const [name, view] of VIEWS) {
    try {
      view.mount(roots[name], ctx);
    } catch (error) {
      // One broken view must not take the status bar and the banners with it.
      console.error(`view ${name} failed to mount`, error);
    }
  }

  // A selection that points at a twin the platform no longer lists is dropped.
  store.watch((state) => [state.attributes, state.ui.selected], ([attributes, selected]) => {
    if (attributes && selected && !attributes.things[selected]) ctx.select(null);
  });

  // Thresholds are wall-clock: they must fire while a fetch is still pending.
  setInterval(() => {
    poller.tick();
    commands.tick();
  }, DERIVE_INTERVAL_MS);

  poller.start();
  return {store, ctx};
}

/** The running application: `app.store`, `app.ctx`. */
export const app = start();
