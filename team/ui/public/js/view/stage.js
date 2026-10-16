// The central stage: the 3D cutaway model (js/scene3d/) or the SVG scheme
// (view/scheme.js), switched from the stage HUD and by the hash (mode=3d|scheme).
//
// The scene module is loaded only when 3D is shown, so the scheme mode never
// downloads three.js. Automatic choices: no WebGL 2 -> the scheme with a calm
// notice; a software renderer -> the light quality; frames still slower than
// SLOW_FRAME_MS -> the scheme with a notice and a way back to 3D. A lost
// graphics context shows the scheme until the browser restores it. The user's
// own choices (mode, quality, spread of the slabs) persist in localStorage.
//
// Mirrored on the stage element for tests, read-only: data-stage-mode,
// data-quality, data-renderer, data-explode, data-rendering (active while the camera, a transition or a refit
// runs; people walking between publications draw frames of their own, counted by data-tweens), data-levels,
// data-workings, data-workers-drawn, data-camera, data-fallback, data-frames, data-hud-fold (the HUD folded to
// icons beside the gizmo), data-loaders (the loaders of
// the zones drawn), data-choreo (the last camera move that followed the situation of the shift), data-art (art mode:
// one orthographic view, pan and zoom only; forced with `?art=ortho` in the address for development and tests).

import {h, s, setAttrs, setText} from '../dom.js';
import {STAGE} from '../text3d.js';

const PREFS_KEY = 'mine-ui.stage';
/** Median frame time of the first frames above which 3D gives way to the scheme. */
export const SLOW_FRAME_MS = 200;
const SOFTWARE = /swiftshader|llvmpipe|softpipe|software|basic render/i;
const EXPLODE_DEFAULT = 0.8;
const MIRRORED = ['data-rendering', 'data-levels', 'data-workings', 'data-workers-drawn', 'data-camera', 'data-frames',
  'data-tweens', 'data-routes', 'data-first-frame-ms', 'data-decor', 'data-loaders', 'data-choreo', 'data-intro', 'data-art'];

/**
 * Art mode asked for in the address: `?art=ortho` starts the scene with the orthographic camera of the art (the
 * procedural scene); `?art=off` never shows the art of the mine (for comparisons). Else: the art when it matches.
 */
function artRequested() {
  try {
    return new URLSearchParams(window.location.search).get('art');
  } catch (error) {
    return null;
  }
}

/** Icons of the HUD (16 px, stroked): the row folds to them while the dock is unfolded over a small stage. */
const ICONS = {
  overview: 'M2.5 8.2L8 3l5.5 5.2M4.2 6.8V13h7.6V6.8',
  levels: 'M8 2.2l5.8 2.6L8 7.4 2.2 4.8zM2.2 8.2L8 10.8l5.8-2.6M2.2 11.4L8 14l5.8-2.6',
  explode: 'M8 1.6v3.6M6.2 3.2L8 1.4l1.8 1.8M8 14.4v-3.6M6.2 12.8L8 14.6l1.8-1.8M2.5 8h11',
  settings: 'M2.5 4.5h11M2.5 8h11M2.5 11.5h11M5.5 3v3M10.5 6.5v3M7 10v3',
};

function icon(name) {
  return s('svg', {class: 'hud__icon', viewBox: '0 0 16 16', width: 16, height: 16, 'aria-hidden': 'true', focusable: 'false'},
    s('path', {d: ICONS[name]}));
}

function readPrefs() {
  try {
    const value = JSON.parse(window.localStorage.getItem(PREFS_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch (error) {
    return {};
  }
}

function writePrefs(change) {
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({...readPrefs(), ...change}));
  } catch (error) {
    // Storage may be unavailable (private mode, a policy): the choice lasts for this page only.
  }
}

/** Whether WebGL 2 can be had, and from which renderer. The probe context is released at once. */
function probeWebgl() {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2', {failIfMajorPerformanceCaveat: false});
    if (!gl) return {ok: false, renderer: '', software: false};
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = String(gl.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : gl.RENDERER) || '');
    const lose = gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
    return {ok: true, renderer, software: SOFTWARE.test(renderer)};
  } catch (error) {
    return {ok: false, renderer: '', software: false};
  }
}

export function mount(root, ctx) {
  const {store} = ctx;
  const stage3d = ctx.roots.stage3d;
  const hud = ctx.roots.stageHud;
  const motionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  const reducedMotion = () => Boolean(motionQuery && motionQuery.matches);

  let probe = null;
  let instance = null;
  let loading = null;
  let fallback = null;          // null | 'no-webgl' | 'slow' | 'context-lost' | 'load-failed'
  let forced3d = false;         // the user went back to 3D after the slow notice
  let measured = new Set();     // qualities whose first frames were measured in this page
  let pending = null;           // {kind: 'focus'|'overview', id}
  let mode = null;
  let builtQuality = null;
  // The intro of the 3D stage plays once per page load, and only when the page opens on the 3D stage.
  let introAllowed = true;
  // The depth rail (view/horizons.js) hears when the people drawn by the 3D stage moved (ctx.stage.onPeople).
  const peopleListeners = new Set();
  const tellPeople = () => {
    for (const listener of peopleListeners) listener();
  };

  const setUi = (change) => store.update((state) => {
    const ui = {...state.ui, ...change};
    return Object.keys(change).some((key) => ui[key] !== state.ui[key]) ? {ui} : null;
  });

  // ---- HUD -------------------------------------------------------------------------------
  const modeButtons = {};
  for (const name of ['3d', 'scheme']) {
    modeButtons[name] = h('button', {
      type: 'button', class: 'seg__item', 'data-testid': `stage-mode-${name}`, 'data-mode': name,
      title: STAGE.modeHint[name], text: STAGE.mode[name],
      on: {click: () => chooseMode(name)},
    });
  }
  const modeGroup = h('div', {class: 'seg', role: 'group', 'aria-label': STAGE.modeGroup}, modeButtons['3d'], modeButtons.scheme);
  const overviewButton = h('button', {type: 'button', class: 'hud__btn', 'data-testid': 'stage-overview', title: STAGE.overview,
    'aria-label': STAGE.overview, on: {click: () => (instance ? instance.overview(true) : null)}},
  icon('overview'), h('span', {class: 'hud__text', text: STAGE.overview}));
  const explodeInput = h('input', {type: 'range', min: 0, max: 100, step: 1, class: 'hud__range', id: 'stage-explode',
    'data-testid': 'stage-explode', title: STAGE.explodeHint});
  explodeInput.addEventListener('input', () => applyExplode(Number(explodeInput.value) / 100, false));
  const explodeField = h('label', {class: 'hud__field hud__field--explode', for: 'stage-explode', title: STAGE.explodeHint},
    h('span', {class: 'hud__caption', text: STAGE.explode}), explodeInput);
  // Folded HUD: the spread of the slabs as one button, as the key E.
  const explodeToggle = h('button', {type: 'button', class: 'hud__btn hud__btn--fold', 'data-testid': 'stage-explode-toggle',
    title: STAGE.explodeHint, 'aria-label': STAGE.explodeToggle, on: {click: () => toggleExplode()}}, icon('explode'));
  const qualitySelect = h('select', {class: 'hud__select', id: 'stage-quality', 'data-testid': 'stage-quality', title: STAGE.qualityHint},
    h('option', {value: 'high'}), h('option', {value: 'low'}));
  qualitySelect.addEventListener('change', () => {
    const value = qualitySelect.value === 'high' ? 'high' : 'low';
    writePrefs({quality: value});
    setUi({quality: value});
  });
  const qualityField = h('label', {class: 'hud__field', for: 'stage-quality'}, h('span', {class: 'hud__caption', text: STAGE.quality}), qualitySelect);
  const keyTerms = (list) => list.map(([keyName, what]) => [h('dt', {text: keyName}), h('dd', {text: what})]).flat();
  const keyListEl = h('dl', null, keyTerms(STAGE.keyList));
  let keysArt = false;
  const keys = h('details', {class: 'hud__keys', 'data-testid': 'stage-settings'},
    h('summary', {class: 'hud__btn', title: STAGE.settings, 'aria-label': STAGE.settings}, icon('settings'),
      h('span', {class: 'hud__text', text: STAGE.settings})),
    h('div', {class: 'hud__keys-body'}, qualityField, explodeField, h('p', {class: 'hud__keys-title', text: STAGE.keysTitle}),
      keyListEl));
  // Variant 3: the horizons are chosen on the rail of the stage (view/horizons.js); the HUD keeps 3D/Схема, the overview
  // and the settings (quality, the spread of the slabs, the keys).
  const tools = h('div', {class: 'hud__tools'}, explodeToggle, overviewButton, keys);
  const rowMain = h('div', {class: 'hud__row'}, modeGroup, tools);
  const status = h('p', {class: 'hud__status', 'data-testid': 'stage-status', hidden: true});
  hud.append(rowMain, status);
  setAttrs(hud, {role: 'toolbar', 'aria-label': STAGE.region, 'data-testid': 'stage-hud'});

  const notice = h('div', {class: 'stage-notice', 'data-testid': 'stage-notice', role: 'status', hidden: true});
  const noticeText = h('span', {class: 'stage-notice__text'});
  const noticeButton = h('button', {type: 'button', class: 'hud__btn stage-notice__btn', 'data-testid': 'stage-back-3d',
    on: {click: () => backTo3d()}});
  notice.append(noticeText, noticeButton);
  root.append(notice);

  // ---- choices -----------------------------------------------------------------------------

  function requestedMode() {
    const {ui} = store.getState();
    if (ui.stageMode === '3d' || ui.stageMode === 'scheme') return ui.stageMode;
    const prefs = readPrefs();
    return prefs.mode === 'scheme' ? 'scheme' : '3d';
  }

  function quality() {
    const {ui} = store.getState();
    if (ui.quality === 'high' || ui.quality === 'low') return {value: ui.quality, auto: false};
    const prefs = readPrefs();
    if (prefs.quality === 'high' || prefs.quality === 'low') return {value: prefs.quality, auto: false};
    return {value: probe && probe.software ? 'low' : 'high', auto: true};
  }

  function explodeValue() {
    const {ui} = store.getState();
    if (Number.isFinite(ui.explode)) return ui.explode;
    const prefs = readPrefs();
    return Number.isFinite(prefs.explode) ? prefs.explode : EXPLODE_DEFAULT;
  }

  function chooseMode(name) {
    writePrefs({mode: name});
    if (name === '3d') {
      forced3d = forced3d || fallback === 'slow';
      if (fallback !== 'no-webgl') fallback = null;
    }
    setUi({stageMode: name});
    apply();
  }

  function backTo3d() {
    forced3d = true;
    fallback = null;
    setUi({stageMode: '3d'});
    apply();
  }

  let lastSpread = EXPLODE_DEFAULT;
  function applyExplode(value, animate) {
    if (value > 0.05) lastSpread = value;
    writePrefs({explode: value});
    setUi({explode: value});
    if (instance) instance.setExplode(value, animate);
  }

  function toggleExplode() {
    const current = instance ? instance.explode : explodeValue();
    applyExplode(current > 0.05 ? 0 : (lastSpread > 0.05 ? lastSpread : EXPLODE_DEFAULT), true);
  }

  // ---- 3D life cycle ---------------------------------------------------------------------

  function destroy() {
    if (instance) {
      instance.dispose();
      instance = null;
      tellPeople();
    }
    builtQuality = null;
  }

  /** The first frames with the model drawn: slower than SLOW_FRAME_MS gives way to the scheme. */
  async function measureOnce() {
    const wanted = builtQuality;
    if (!instance || forced3d || measured.has(wanted)) return;
    measured.add(wanted);
    const subject = instance;
    const ms = await subject.measure(6);
    setAttrs(root, {'data-measured-ms': Math.round(ms)});
    if (instance === subject && ms > SLOW_FRAME_MS && !forced3d) {
      fallback = 'slow';
      apply();
    }
  }

  function onEvent(type) {
    if (type === 'frame') mirror();
    else if (type === 'people') tellPeople();
    else if (type === 'ready') measureOnce();
    else if (type === 'explode-key') {
      if (!(instance && instance.art)) toggleExplode();
    }
    else if (type === 'context-lost') {
      fallback = 'context-lost';
      apply();
    } else if (type === 'context-restored') {
      destroy();
      fallback = null;
      apply();
    }
  }

  async function build() {
    const wanted = quality().value;
    const token = {};
    loading = token;
    try {
      const module = await import('../scene3d/scene.js');
      if (loading !== token || mode !== '3d') return;
      instance = module.createScene(stage3d, {
        ctx, quality: wanted, explode: explodeValue(), reducedMotion, onEvent, intro: introAllowed,
        art: artRequested() === 'ortho' ? {} : null, artEnv: artRequested() !== 'off',
      });
      introAllowed = false;
      builtQuality = wanted;
      instance.update(store.getState());
      loading = null;
      apply();
      if (pending) {
        const request = pending;
        pending = null;
        if (request.kind === 'focus') instance.focus(request.id);
        else instance.overview(false);
      }
      mirror();
    } catch (error) {
      if (loading === token) loading = null;
      destroy();
      fallback = 'load-failed';
      apply();
    }
  }

  /** Bring the stage to what is requested and possible. */
  function apply() {
    const requested = requestedMode();
    if (requested === '3d' && !probe) probe = probeWebgl();
    if (requested === '3d' && probe && !probe.ok) fallback = 'no-webgl';
    const next = requested === '3d' && !fallback ? '3d' : 'scheme';
    if (next === 'scheme') introAllowed = false;
    const q = quality();
    if (mode !== next) {
      mode = next;
      if (mode === 'scheme') {
        loading = null;
        // A lost context is kept, hidden: its canvas tells when the browser restores it.
        if (fallback !== 'context-lost') destroy();
      }
    }
    if (mode === '3d' && instance && builtQuality !== q.value) destroy();
    if (mode === '3d' && !instance && !loading) build();

    // HUD and notice.
    for (const [name, button] of Object.entries(modeButtons)) {
      const on = name === mode;
      setAttrs(button, {'aria-pressed': String(on), class: ['seg__item', on && 'is-current']});
    }
    tools.hidden = mode !== '3d';
    const names = {high: STAGE.qualityName.high, low: STAGE.qualityName.low};
    for (const option of qualitySelect.options) {
      setText(option, q.auto && option.value === q.value ? STAGE.qualityAuto(names[option.value]) : names[option.value]);
    }
    if (qualitySelect.value !== q.value) qualitySelect.value = q.value;
    const explode = Math.round(explodeValue() * 100);
    if (Number(explodeInput.value) !== explode && document.activeElement !== explodeInput) explodeInput.value = String(explode);
    status.hidden = !(mode === '3d' && loading);
    setText(status, mode === '3d' && loading ? STAGE.loading : '');
    const shown = fallback && requested === '3d';
    notice.hidden = !shown;
    setText(noticeText, shown ? STAGE.notice[fallback] : '');
    noticeButton.hidden = !shown || fallback === 'no-webgl';
    setText(noticeButton, fallback === 'slow' ? STAGE.backTo3d : STAGE.retry3d);
    setAttrs(root, {
      'data-stage-mode': mode,
      'data-quality': q.value,
      'data-quality-auto': q.auto ? 'true' : null,
      'data-renderer': probe ? (probe.ok ? (probe.software ? 'software' : 'hardware') : 'none') : null,
      'data-fallback': fallback,
      'data-explode': explodeValue().toFixed(2),
    });
    mirror();
    fitHud();
  }

  function mirror() {
    const source = instance ? instance.root : null;
    const attrs = {};
    for (const name of MIRRORED) attrs[name] = source ? (source.hasAttribute(name) ? source.getAttribute(name) : null) : null;
    if (source) attrs['data-explode'] = source.getAttribute('data-explode');
    setAttrs(root, attrs);
    // Art mode: the vertical factor is the art's (no spread of the slabs) and the keys pan instead of turning.
    const art = Boolean(instance && instance.art);
    explodeField.hidden = art;
    explodeToggle.hidden = art;
    if (art !== keysArt) {
      keysArt = art;
      keyListEl.replaceChildren(...keyTerms(art ? STAGE.keyListArt : STAGE.keyList));
    }
  }

  // ---- requests of other views -------------------------------------------------------------

  ctx.stage.focus = (id) => {
    if (mode !== '3d') return false;
    if (instance) return instance.focus(id);
    pending = {kind: 'focus', id};
    return true;
  };
  ctx.stage.overview = () => {
    if (mode !== '3d') return false;
    if (instance) return instance.overview(true);
    pending = {kind: 'overview'};
    return true;
  };
  /** Where an object is drawn, in viewport pixels ({x, y, visible}); null when not in 3D or not drawn. Read-only. */
  ctx.stage.screenOf = (thingId) => {
    if (mode !== '3d' || !instance) return null;
    const point = instance.screenOf(thingId);
    if (!point) return null;
    const rect = instance.root.getBoundingClientRect();
    return {x: rect.left + point.x, y: rect.top + point.y, visible: point.visible, world: point.world};
  };
  /** Renderer figures of the 3D stage (triangles, draw calls, frames); null when not in 3D. Read-only. */
  ctx.stage.info = () => (mode === '3d' && instance ? instance.info() : null);
  /**
   * The depth rail. people(): the people as the 3D stage draws them now ([{name, thingId, z, working, moving}], z the
   * mine elevation of the drawn place), null when not in 3D; onPeople(listener): told whenever a drawn depth changed
   * (and when the 3D stage goes); setDepthProbe(z|null) and setLevelHighlight(level|null): drawn by the 3D stage,
   * false when there is none.
   */
  ctx.stage.people = () => (mode === '3d' && instance ? instance.people() : null);
  ctx.stage.onPeople = (listener) => {
    peopleListeners.add(listener);
    return () => peopleListeners.delete(listener);
  };
  ctx.stage.setDepthProbe = (z) => (mode === '3d' && instance ? instance.setDepthProbe(z) : false);
  ctx.stage.setLevelHighlight = (name) => (mode === '3d' && instance ? instance.setLevelHighlight(name) : false);

  // ---- the HUD beside the gizmo ------------------------------------------------------------

  /**
   * Fold the HUD row to icons (and the gizmo to its compass) when, in full, it would run over the gizmo or wrap:
   * the panel or the stand drawer over a narrow stage leaves it little room. Measured unfolded, then decided.
   */
  function fitHud() {
    const was = root.hasAttribute('data-hud-fold');
    root.removeAttribute('data-hud-fold');
    let fold = false;
    const gizmo = mode === '3d' ? stage3d.querySelector('.s3__gizmo') : null;
    const row = rowMain.getBoundingClientRect();
    if (row.width > 0) {
      fold = row.height > 48;
      if (gizmo) {
        const g = gizmo.getBoundingClientRect();
        fold = fold || (row.left < g.right + 8 && row.top < g.bottom + 4 && row.bottom > g.top - 4);
      }
    }
    if (fold) root.setAttribute('data-hud-fold', '');
    if (fold !== was && instance) instance.invalidate();
  }
  const hudObserver = new ResizeObserver(() => fitHud());
  hudObserver.observe(root);
  new MutationObserver(() => fitHud()).observe(document.body, {attributes: true, attributeFilter: ['data-stand', 'data-panel']});

  // ---- store ---------------------------------------------------------------------------

  store.watch((state) => [state.ui.stageMode, state.ui.quality, state.ui.explode], () => apply());
  store.watch((state) => [state.model, state.attributes, state.pending, state.ui.selected, state.ui.hoverOption, state.link, state.boot], (_, state) => {
    if (instance) instance.update(state);
  });
  if (motionQuery && motionQuery.addEventListener) motionQuery.addEventListener('change', () => instance && instance.invalidate());
}
