// The switches of the shell: the centre tabs «Схема / Список / Прогоны», and
// the two controls that exist only in the compact layout (DESIGN.md 2.3):
// the tabs of the right panel and the button that unfolds the journal.

import {h, setAttrs} from '../dom.js';
import {incidentOf} from '../model.js';

const VIEWS = ['scheme', 'list', 'runs'];
const RIGHT_PARTS = ['decision', 'card'];

export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;

  // Centre tabs.
  const buttons = VIEWS.map((view) => h('button', {
    class: 'tab', type: 'button', role: 'tab', id: `tab-${view}`, 'data-testid': `tab-${view}`,
    'aria-controls': `view-${view}`, text: UI.tabs[view],
    on: {click: () => ctx.setView(view)},
  }));
  setAttrs(root, {role: 'tablist', 'aria-label': UI.tabs.region});
  root.append(...buttons);
  const panels = VIEWS.map((view) => setAttrs(document.getElementById(`view-${view}`),
    {role: 'tabpanel', 'aria-labelledby': `tab-${view}`}));

  store.watch((state) => state.ui.view, (current) => {
    VIEWS.forEach((view, index) => {
      setAttrs(buttons[index], {'aria-selected': String(view === current), class: ['tab', view === current && 'is-current']});
      panels[index].hidden = view !== current;
    });
    ctx.roots.schemeControls.hidden = current !== 'scheme';
  });

  // Right panel: in the compact layout the decision panel and the card share the space.
  const rightButtons = RIGHT_PARTS.map((part) => h('button', {
    class: 'tab tab--small', type: 'button', 'data-testid': `right-tab-${part}`, text: UI.tabs[part],
    on: {click: () => showRight(part)},
  }));
  setAttrs(ctx.roots.rightTabs, {role: 'group', 'aria-label': UI.tabs.rightRegion});
  ctx.roots.rightTabs.append(...rightButtons);

  function showRight(part) {
    document.body.setAttribute('data-right', part);
    RIGHT_PARTS.forEach((name, index) => setAttrs(rightButtons[index],
      {'aria-pressed': String(name === part), class: ['tab', 'tab--small', name === part && 'is-current']}));
  }
  showRight('card');
  // A new selection brings up the card. An incident that asks for a decision brings up the decision
  // panel; so does one that is already being executed or is over when it is first seen (the page was
  // loaded in the middle of it) and nothing is selected. When the incident is gone, the card is back.
  let seenSelection = store.getState().ui.selected;
  store.watch((state) => state.ui.selected, (selected) => {
    if (selected && selected !== seenSelection) showRight('card');
    seenSelection = selected;
  });
  const isOpen = (incidentState) => typeof incidentState === 'string' && incidentState !== 'none';
  let seenIncident = null;
  store.watch((state) => {
    const incident = state.model ? incidentOf(state.model) : null;
    return incident && incident.hasState ? incident.values.state : null;
  }, (incidentState) => {
    if (incidentState === 'active' && seenIncident !== 'active') showRight('decision');
    else if (isOpen(incidentState) && !isOpen(seenIncident) && !store.getState().ui.selected) showRight('decision');
    else if (!isOpen(incidentState) && isOpen(seenIncident)) showRight('card');
    seenIncident = incidentState;
  });

  // Journal: its heading, and the unfold button of the compact layout.
  const toggle = h('button', {
    class: 'btn btn--small journal__toggle', type: 'button', 'data-testid': 'journal-toggle',
    'aria-controls': 'journal', 'aria-expanded': 'false', text: UI.tabs.journal,
  });
  toggle.addEventListener('click', () => {
    const open = document.body.getAttribute('data-journal') !== 'open';
    document.body.setAttribute('data-journal', open ? 'open' : 'collapsed');
    setAttrs(toggle, {'aria-expanded': String(open), title: open ? UI.tabs.journalClose : UI.tabs.journalOpen});
  });
  toggle.title = UI.tabs.journalOpen;
  ctx.roots.journalBar.append(
    h('h2', {class: 'panel__title journal__title', text: UI.journal.title}),
    h('span', {class: 'muted journal__order', text: UI.journal.order}),
    toggle,
  );
}
