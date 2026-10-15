// The menu of the top bar and its overlays. «Меню» opens a short list —
// «Список», «Прогоны», «Журнал» — and each of them opens over the whole frame
// under the top bar (rail, stage and panel), with «Назад к шахте» in its bar.
// The list and the archive are routes (ui.view: #/list, #/runs); the journal is
// a state of the frame (shell.journal). The open overlay is mirrored on <body>
// as data-menu = none | list | runs | journal. Esc closes the open menu list,
// then the overlay.

import {h, s, setAttrs} from '../dom.js';

const ITEMS = ['list', 'runs', 'journal'];

export function mount(root, ctx) {
  const {store, shell, text} = ctx;
  const M = text.UI.menu;

  // ---- the menu button and its list ----------------------------------------------
  const button = h('button', {
    class: 'btn btn--quiet menu-button', type: 'button', 'data-testid': 'menu-toggle',
    'aria-haspopup': 'true', 'aria-expanded': 'false', 'aria-controls': 'menu-list', title: text.UI.top.menuTitle,
  }, s('svg', {class: 'menu-button__icon', viewBox: '0 0 16 16', width: 16, height: 16, 'aria-hidden': 'true', focusable: 'false'},
    s('path', {d: 'M2.5 4h11M2.5 8h11M2.5 12h11'})), h('span', {text: text.UI.top.menu}));
  const items = ITEMS.map((item) => h('button', {
    class: 'menu-list__item', type: 'button', 'data-testid': `tab-${item}`, 'data-menu-item': item,
  }, h('span', {class: 'menu-list__name', text: M[item]}), h('span', {class: 'menu-list__hint', text: M[`${item}Hint`]})));
  const list = h('div', {class: 'menu-list', id: 'menu-list', role: 'group', 'aria-label': M.region, hidden: true}, items);
  const slot = ctx.roots.menuSlot || root;
  slot.append(button, list);

  const showList = (open) => {
    list.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
  };
  button.addEventListener('click', () => {
    showList(list.hidden);
    if (!list.hidden) items[0].focus();
  });
  items.forEach((node, index) => node.addEventListener('click', () => {
    showList(false);
    if (ITEMS[index] === 'journal') ctx.openJournal();
    else ctx.setView(ITEMS[index]);
    back.focus();
  }));
  document.addEventListener('pointerdown', (event) => {
    if (!list.hidden && !list.contains(event.target) && !button.contains(event.target)) showList(false);
  });

  // ---- the bar of the overlay ----------------------------------------------------------
  const back = h('button', {class: 'btn menu-view__back', type: 'button', 'data-testid': 'tab-scheme'},
    s('svg', {class: 'menu-view__arrow', viewBox: '0 0 12 12', width: 12, height: 12, 'aria-hidden': 'true', focusable: 'false'},
      s('path', {d: 'M7.5 2.5L4 6l3.5 3.5'})), h('span', {text: M.back}));
  back.addEventListener('click', () => {
    ctx.setView('scheme');
    button.focus();
  });
  const title = h('h2', {class: 'menu-view__title', id: 'menu-view-title'});
  root.append(back, title);
  setAttrs(ctx.roots.menu, {role: 'region', 'aria-labelledby': 'menu-view-title'});

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || event.defaultPrevented || document.getElementById('app').inert) return;
    if (!list.hidden) {
      event.preventDefault();
      showList(false);
      button.focus();
    } else if (document.body.getAttribute('data-menu') !== 'none' && ctx.roots.menu.contains(document.activeElement)) {
      event.preventDefault();
      back.click();
    }
  });

  const update = () => {
    const view = store.getState().ui.view;
    const current = view === 'scheme' ? (shell.get().journal === 'open' ? 'journal' : 'none') : view;
    ctx.roots.menu.hidden = current === 'none';
    ctx.roots.viewScheme.hidden = current !== 'none';
    ctx.roots.list.hidden = current !== 'list';
    ctx.roots.runs.hidden = current !== 'runs';
    ctx.roots.journalView.hidden = current !== 'journal';
    // The overlay names its view once; the heading of the view itself is not repeated (layout.css).
    const titles = {list: text.UI.list.title, runs: text.UI.runs.title, journal: text.UI.journal.title};
    setAttrs(title, {text: current === 'none' ? '' : (titles[current] || current)});
    items.forEach((node, index) => setAttrs(node, {'aria-current': ITEMS[index] === current ? 'page' : null}));
    setAttrs(document.body, {'data-menu': current});
  };
  store.watch((state) => state.ui.view, update);
  shell.watch(update);
}
