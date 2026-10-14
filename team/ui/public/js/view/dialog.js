// The one modal confirmation dialog. It exists in the document only while a
// question is open: the page behind is inert, focus stays inside, Esc and the
// cancel button answer "no", and focus returns to the control that asked.

import {h} from '../dom.js';

let ask = () => Promise.resolve(false);

/**
 * @param {HTMLElement} root the element of index.html this view owns
 * @param {Object} ctx store, text, roots and the action functions
 */
export function mount(root, ctx) {
  const {UI} = ctx.text;
  const page = document.getElementById('app');
  let open = false;

  ask = (options) => {
    // One question at a time: a second one is not asked, so it is not confirmed.
    if (open) return Promise.resolve(false);
    open = true;
    return new Promise((resolve) => {
      const invoker = document.activeElement;
      const cancel = h('button', {
        class: 'btn', type: 'button', 'data-testid': 'dialog-cancel', text: options.cancelLabel || UI.dialog.cancel,
      });
      const confirm = h('button', {
        class: ['btn', options.danger ? 'btn--danger' : 'btn--primary'], type: 'button', 'data-testid': 'dialog-confirm',
        text: options.confirmLabel || UI.dialog.confirm,
      });
      const backdrop = h('div', {class: 'dialog-backdrop'},
        h('div', {
          class: 'dialog', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'dialog-title',
          'aria-describedby': 'dialog-message', 'data-testid': 'dialog',
        },
        h('h2', {class: 'dialog__title', id: 'dialog-title', text: options.title}),
        h('p', {class: 'dialog__message', id: 'dialog-message', text: options.message}),
        h('div', {class: 'dialog__buttons'}, cancel, confirm)));

      function finish(answer) {
        document.removeEventListener('keydown', onKey, true);
        backdrop.remove();
        page.inert = false;
        open = false;
        if (invoker && invoker.isConnected && typeof invoker.focus === 'function') invoker.focus();
        resolve(answer);
      }

      function onKey(event) {
        if (event.key === 'Escape') {
          event.preventDefault();
          finish(false);
        } else if (event.key === 'Tab') {
          // The two buttons are the whole Tab order while the dialog is open.
          event.preventDefault();
          (document.activeElement === cancel ? confirm : cancel).focus();
        }
      }

      cancel.addEventListener('click', () => finish(false));
      confirm.addEventListener('click', () => finish(true));
      document.addEventListener('keydown', onKey, true);
      page.inert = true;
      root.append(backdrop);
      // The safe answer has the focus: Enter pressed twice by habit confirms nothing.
      cancel.focus();
    });
  };
}

/**
 * Ask the user to confirm an action. Reached by views as `ctx.confirm(options)`.
 * @param {{title: string, message: string, confirmLabel: (string|undefined), cancelLabel: (string|undefined),
 *          danger: (boolean|undefined)}} options
 * @returns {Promise<boolean>} true only when the user pressed the confirming button
 */
export function confirm(options) {
  return ask(options);
}
