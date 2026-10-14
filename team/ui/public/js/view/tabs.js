// The view tabs of the centre column: «Шахта / Список / Прогоны». A tab is a
// real button; switching keeps the focus on it.

import {h, setAttrs} from '../dom.js';

const VIEWS = ['scheme', 'list', 'runs'];

export function mount(root, ctx) {
  const {store, text} = ctx;
  const {UI} = text;

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
}
