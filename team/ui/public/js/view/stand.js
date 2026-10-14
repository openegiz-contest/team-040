// The stand drawer: the experiment's conditions, presets and the full reset,
// over the left edge of the stage. It is chalk mark-up, set apart from the
// dispatcher's actions in the right column. Closed by default; the «Стенд»
// button of the top bar opens it, Esc or «Закрыть» closes it and the focus
// goes back to that button. While closed it is inert: out of the Tab order.
// Its content belongs to view/conditions.js (roots.conditions, roots.reset).

import {h, setAttrs} from '../dom.js';

export function mount(root, ctx) {
  const {text, shell} = ctx;
  const {UI} = text;

  const close = h('button', {class: 'btn btn--quiet btn--small stand__close', type: 'button', 'data-testid': 'stand-close', text: UI.stand.close});
  ctx.roots.standHead.append(
    h('div', {class: 'stand__titles'},
      h('h2', {class: 'stand__title', id: 'stand-title'}, h('span', {class: 'stand-tag', text: UI.stand.tag}), ' ', UI.stand.title),
      h('p', {class: 'stand__subtitle', text: UI.stand.subtitle})),
    close);
  setAttrs(root, {role: 'region', 'aria-labelledby': 'stand-title'});

  const toggle = () => document.querySelector('[data-testid="stand-toggle"]');
  close.addEventListener('click', () => shell.set({stand: 'closed'}));

  document.addEventListener('keydown', (event) => {
    // A key the confirmation dialog already answered, or any key while it is open, is not ours.
    if (event.key !== 'Escape' || event.defaultPrevented || shell.get().stand !== 'open') return;
    if (document.getElementById('app').inert) return;
    // Esc belongs to the drawer when the focus is in it, on its button, or nowhere; on the stage it is the stage's.
    const focused = document.activeElement;
    if (focused && focused !== document.body && !root.contains(focused) && focused !== toggle()) return;
    event.preventDefault();
    shell.set({stand: 'closed'});
    const button = toggle();
    if (button) button.focus();
  });

  let wasOpen = false;
  shell.watch((frame) => {
    const open = frame.stand === 'open';
    const focusInside = root.contains(document.activeElement);
    root.inert = !open;
    setAttrs(root, {'data-open': String(open), 'aria-hidden': open ? null : 'true'});
    if (open && !wasOpen) close.focus();
    if (!open && wasOpen && focusInside) {
      const button = toggle();
      if (button) button.focus();
    }
    wasOpen = open;
  });
}
