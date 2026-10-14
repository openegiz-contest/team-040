// Banners of the states in which the screen cannot be taken at face value
// (DESIGN.md section 4, as amended by CONTRACT.md section 4), and the mark on
// the centre that says how old the shown data are.

import {hasOwnResetPending} from '../commands.js';
import {h, reconcile, setAttrs, setGlyph, setText} from '../dom.js';
import {showsOldData} from '../link.js';
import {labelOf} from '../model.js';

const SEVERITY_GLYPH = {danger: 'danger', attention: 'attention', info: 'info'};
const CODE_GLYPH = {paused_decision: 'pause', stale: 'clock', publications_stopped: 'clock', resetting: 'clock'};
/** Banners that report a rejection; they carry its code in `data-reason`. */
const REJECTION_BANNERS = new Set(['snapshot_invalid', 'topology_mismatch', 'contract_version', 'manifest_incomplete']);

/**
 * Which banners the state calls for, most severe first.
 * @param {import('../store.js').State} state
 * @param {string[]} order
 * @returns {string[]}
 */
export function bannerCodes(state, order) {
  const {link, snapshot, boot, bootError} = state;
  const codes = new Set();
  if (boot === 'empty') return ['empty_stand'];
  if (bootError) codes.add(bootError.code === 'contract_version' ? 'contract_version' : 'manifest_incomplete');

  const invalid = link.snapshot === 'invalid' && link.invalid ? link.invalid.code : null;
  if (link.link === 'unavailable') {
    codes.add('platform_unavailable');
  } else if (invalid === 'topology_mismatch' || invalid === 'manifest_incomplete') {
    codes.add(invalid);
  } else if (invalid) {
    codes.add('snapshot_invalid');
  } else if (link.link === 'stale' && boot === 'ready') {
    codes.add('stale');
  } else if (link.link === 'degraded') {
    codes.add('link_degraded');
  }
  if (link.publications === 'stopped' && link.link !== 'unavailable') codes.add('publications_stopped');

  // What the model says about itself is repeated only while it is current.
  const current = snapshot && link.snapshot === 'ok' && link.publications !== 'stopped'
    && (link.link === 'ok' || link.link === 'degraded');
  if ((current && snapshot.runState === 'resetting') || hasOwnResetPending(state.pending)) codes.add('resetting');
  if (current && snapshot.runState === 'paused' && snapshot.pauseReason === 'decision') codes.add('paused_decision');
  return order.filter((code) => codes.has(code));
}

export function mount(root, ctx) {
  const {store, text} = ctx;
  const oldData = ctx.roots.oldData;
  const oldGlyph = h('span', {class: 'old-data__glyph'});
  const oldText = h('span');
  setGlyph(oldGlyph, 'clock');
  oldData.append(oldGlyph, oldText);

  store.watch((state) => [state.link, state.snapshot, state.boot, state.bootError, state.pending], () => {
    const state = store.getState();
    const name = state.model ? (local) => labelOf(state.model, local) : null;
    const codes = bannerCodes(state, text.BANNER_ORDER);
    reconcile(root, codes, (code) => code,
      (code) => {
        const severity = text.BANNER_SEVERITY[code] || 'attention';
        const glyphHolder = h('span', {class: 'banner__glyph'});
        setGlyph(glyphHolder, CODE_GLYPH[code] || SEVERITY_GLYPH[severity]);
        return h('div', {
          class: `banner banner--${severity}`, 'data-testid': 'overlay-banner', 'data-code': code,
          'data-severity': severity, role: 'status',
        }, glyphHolder, h('p', {class: 'banner__words'}, h('strong', {class: 'banner__title'}), ' ', h('span', {class: 'banner__text'})));
      },
      (node, code) => {
        const words = text.bannerText(code, state, name);
        setText(node.querySelector('.banner__title'), words.title);
        setText(node.querySelector('.banner__text'), words.text);
        const reason = REJECTION_BANNERS.has(code) ? (state.bootError || state.link.invalid) : null;
        setAttrs(node, {'data-reason': reason ? reason.code : null});
      });

    const old = showsOldData(state.link) && state.boot === 'ready';
    oldData.hidden = !old;
    setText(oldText, old ? text.UI.oldData(state.snapshot) : '');
  });
}
