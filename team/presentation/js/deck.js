// The deck: one 1920×1080 stage, slides that descend like into the mine.
// Navigation: arrows, PageUp/PageDown, space, Home/End, the wheel, swipes,
// the rail's dots and #N in the address. `?print` gives the print mode used by
// tools/render_pdf.py: no motion, and window.deck.prepare(i) puts slide i in
// its final state with a still of the mine instead of the live canvas.

const stage = document.getElementById('stage');
const slides = [...document.querySelectorAll('.slide')];
const params = new URLSearchParams(location.search);
const PRINT = params.has('print');
const media = window.matchMedia('(prefers-reduced-motion: reduce)');
let reduced = media.matches || PRINT;
const RAIL_TOP = 180;
const RAIL_H = 750;
const RAIL_M = 240;
const STRATA_PX = 22;   // strata pixels per metre of deck depth

let current = -1;
let mine = null;
let lock = 0;
const counters = new WeakMap();

if (PRINT) document.body.classList.add('print', 'instant');

// ---- fit the stage to the window --------------------------------------------------------------------------
function fit() {
  const s = PRINT ? 1 : Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  stage.style.setProperty('--fit', String(s));
  if (mine) mine.resize(1920, 1080, Math.min(1.5, Math.max(0.5, s * (window.devicePixelRatio || 1))));
}

// ---- type: words in masks, staged parts -------------------------------------------------------------------
function splitWords(element) {
  const parts = [];
  for (const node of [...element.childNodes]) {
    if (node.nodeType === Node.TEXT_NODE) parts.push({text: node.textContent, cls: ''});
    else parts.push({text: node.textContent, cls: node.className || ''});
  }
  element.textContent = '';
  let i = 0;
  for (const {text, cls} of parts) {
    // keep non-breaking spaces inside a word group
    for (const word of text.split(/ +/)) {
      if (!word) continue;
      const mask = document.createElement('span');
      mask.className = 'm';
      const w = document.createElement('span');
      w.className = cls ? `w ${cls}` : 'w';
      w.style.setProperty('--i', String(i));
      w.textContent = word;
      mask.append(w);
      element.append(mask, ' ');
      i += 1;
    }
  }
  element.setAttribute('aria-label', parts.map((p) => p.text).join('').replace(/ /g, ' '));
}
document.querySelectorAll('[data-split]').forEach(splitWords);
document.querySelectorAll('[data-in]').forEach((el) => el.style.setProperty('--d', el.dataset.in));

// people bars of the what-if grid: out (mint), no route (crossed), the rest under ground
document.querySelectorAll('.g__c').forEach((cell) => {
  const out = Number(cell.dataset.out || 0);
  const stuck = Number(cell.dataset.stuck || 0);
  const bar = document.createElement('i');
  bar.className = 'ppl';
  bar.setAttribute('aria-hidden', 'true');
  for (let n = 0; n < 8; n += 1) {
    const p = document.createElement('i');
    p.className = n < out ? 'p p--out' : (n >= 8 - stuck ? 'p p--stuck' : 'p p--in');
    bar.append(p);
  }
  cell.append(bar);
});

// ---- the rail and the strata ------------------------------------------------------------------------------
const railTrack = document.getElementById('rail-track');
const probe = document.getElementById('rail-probe');
const readout = document.getElementById('rail-readout');
const yOf = (m) => (Math.abs(m) / RAIL_M) * RAIL_H;
for (let m = 0; m <= RAIL_M; m += 10) {
  const tick = document.createElement('i');
  tick.className = m % 50 === 0 ? 'r-tick r-tick--50' : 'r-tick';
  tick.style.top = `${yOf(m)}px`;
  railTrack.append(tick);
  if (m % 50 === 0 && m % 120 !== 0) {
    const num = document.createElement('span');
    num.className = 'r-num';
    num.style.top = `${yOf(m)}px`;
    num.textContent = `−${m}`;
    railTrack.append(num);
  }
}
const horizons = [0, 120, 240].map((m) => {
  const hz = document.createElement('p');
  hz.className = 'r-hz';
  hz.style.top = `${yOf(m)}px`;
  hz.innerHTML = `<b>${m ? `−${m}` : '0'}</b><span>горизонт ${m ? `−${m}` : '0'} м</span>`;
  hz.dataset.m = String(m);
  railTrack.append(hz);
  return hz;
});
const dots = slides.map((slide, i) => {
  const dot = document.createElement('button');
  dot.className = 'r-dot';
  dot.type = 'button';
  dot.style.top = `${yOf(Number(slide.dataset.depth))}px`;
  const label = `${String(i + 1).padStart(2, '0')} · ${slide.dataset.label}`;
  dot.setAttribute('aria-label', label);
  dot.innerHTML = `<span class="r-dot__tip">${label}</span>`;
  dot.addEventListener('click', () => go(i));
  railTrack.append(dot);
  return dot;
});

const strata = document.getElementById('strata');
for (let m = 0; m <= 260; m += 10) {
  const mark = document.createElement('span');
  const isHz = m % 120 === 0;
  mark.className = isHz ? 'strata__m strata__m--h' : 'strata__m';
  mark.style.top = `${540 + m * STRATA_PX}px`;
  mark.textContent = m ? `−${m} м` : '0 м';
  strata.append(mark);
  if (isHz) {
    const line = document.createElement('i');
    line.className = 'strata__h';
    line.style.top = `${540 + m * STRATA_PX}px`;
    const lab = document.createElement('span');
    lab.className = 'strata__hl';
    lab.style.top = `${540 + m * STRATA_PX}px`;
    lab.textContent = m ? `горизонт −${m} м` : 'поверхность · 0 м';
    strata.append(line, lab);
  }
}

// ---- numbers that slide up to their value -----------------------------------------------------------------
const fmt = (n) => Math.round(n).toLocaleString('ru-RU');
function settle(el) {
  const anim = counters.get(el);
  if (anim) cancelAnimationFrame(anim);
  el.textContent = fmt(Number(el.dataset.count));
}
function countUp(el, delayMs) {
  const target = Number(el.dataset.count);
  if (reduced || !Number.isFinite(target) || target === 0) { settle(el); return; }
  const start = performance.now() + delayMs;
  const ms = target > 99 ? 1300 : 900;
  el.textContent = fmt(0);
  const step = (now) => {
    const t = Math.min(1, Math.max(0, (now - start) / ms));
    const e = 1 - Math.pow(1 - t, 4);
    el.textContent = fmt(target * e);
    if (t < 1) counters.set(el, requestAnimationFrame(step));
    else counters.delete(el);
  };
  counters.set(el, requestAnimationFrame(step));
}

// ---- show a slide -----------------------------------------------------------------------------------------
function show(index, {instant = false} = {}) {
  index = Math.max(0, Math.min(slides.length - 1, index));
  if (index === current) return;
  const previous = current;
  current = index;
  const quick = instant || reduced;
  document.body.classList.toggle('instant', quick || PRINT);
  stage.dataset.dir = previous > index ? 'up' : 'down';
  slides.forEach((slide, i) => {
    slide.classList.toggle('is-current', i === index);
    slide.classList.toggle('is-leaving', !quick && i === previous);
    slide.setAttribute('aria-hidden', i === index ? 'false' : 'true');
    if (i !== index) slide.inert = true; else slide.inert = false;
  });
  if (!quick && previous >= 0) {
    const leaving = slides[previous];
    setTimeout(() => leaving.classList.remove('is-leaving'), 950);
  }
  if (quick) {
    // the instant class must hold until the browser has applied the new state
    requestAnimationFrame(() => requestAnimationFrame(() => { if (!PRINT && !reduced) document.body.classList.remove('instant'); }));
  }

  const slide = slides[index];
  const depth = Number(slide.dataset.depth);
  const y = yOf(depth);
  probe.style.setProperty('--probe', `${y}px`);
  railTrack.style.setProperty('--fill', `${y}px`);
  readout.textContent = `${depth ? '−' + Math.abs(depth) : '0'} м`;
  horizons.forEach((hz) => hz.classList.toggle('is-passed', Number(hz.dataset.m) <= Math.abs(depth)));
  dots.forEach((dot, i) => {
    dot.classList.toggle('is-now', i === index);
    dot.classList.toggle('is-done', i < index);
    if (i === index) dot.setAttribute('aria-current', 'step'); else dot.removeAttribute('aria-current');
  });
  strata.style.setProperty('--depth-px', `${Math.abs(depth) * STRATA_PX}px`);
  document.getElementById('count-now').textContent = String(index + 1).padStart(2, '0');
  document.getElementById('foot-label').textContent = slide.dataset.label;
  document.querySelector('.foot__bar').style.setProperty('--progress', `${((index + 1) / slides.length) * 100}%`);

  const hero = slide.hasAttribute('data-hero');
  if (hero) document.body.dataset.hero = slide.dataset.view; else delete document.body.dataset.hero;
  if (mine && !PRINT) {
    mine.setVisible(hero);
    if (hero) mine.go(slide.dataset.view, {instant: quick});
  }

  slide.querySelectorAll('[data-count]').forEach((el) => {
    const host = el.closest('[data-in]');
    const d = host ? Number(host.dataset.in) : 0;
    if (quick) settle(el); else countUp(el, d * 85 + 260);
  });

  if (!PRINT) {
    const hash = `#${index + 1}`;
    if (location.hash !== hash) history.replaceState(null, '', hash);
  }
}

function go(index) { show(index); }
function step(delta) {
  const now = performance.now();
  if (now < lock) return;
  lock = now + (reduced ? 120 : 650);
  show(current + delta);
}

// ---- input --------------------------------------------------------------------------------------------------
if (!PRINT) {
  window.addEventListener('keydown', (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const next = ['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter'];
    const prev = ['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'];
    if (next.includes(event.key)) { event.preventDefault(); step(event.shiftKey && event.key === ' ' ? -1 : 1); }
    else if (prev.includes(event.key)) { event.preventDefault(); step(-1); }
    else if (event.key === 'Home') { event.preventDefault(); show(0); }
    else if (event.key === 'End') { event.preventDefault(); show(slides.length - 1); }
    else if (event.key === 'f' || event.key === 'F') {
      if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen?.();
    }
  });
  let wheel = 0;
  let wheelTimer = 0;
  window.addEventListener('wheel', (event) => {
    event.preventDefault();
    wheel += event.deltaY;
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(() => { wheel = 0; }, 180);
    if (Math.abs(wheel) > 70) { step(wheel > 0 ? 1 : -1); wheel = 0; }
  }, {passive: false});
  let touch = null;
  window.addEventListener('touchstart', (e) => { touch = {x: e.touches[0].clientX, y: e.touches[0].clientY}; }, {passive: true});
  window.addEventListener('touchend', (e) => {
    if (!touch) return;
    const dx = e.changedTouches[0].clientX - touch.x;
    const dy = e.changedTouches[0].clientY - touch.y;
    touch = null;
    const d = Math.abs(dy) > Math.abs(dx) ? dy : dx;
    if (Math.abs(d) > 50) step(d < 0 ? 1 : -1);
  });
  window.addEventListener('hashchange', () => {
    const n = Number(location.hash.slice(1));
    if (Number.isInteger(n) && n >= 1) show(n - 1);
  });
  media.addEventListener('change', () => { reduced = media.matches; });
}
window.addEventListener('resize', fit);

// ---- the mine -----------------------------------------------------------------------------------------------
async function startMine() {
  const canvas = document.getElementById('mine');
  try {
    const probeGl = document.createElement('canvas').getContext('webgl2');
    if (!probeGl) throw new Error('WebGL2 unavailable');
    const {createMine} = await import('./mine3d.js');
    mine = await createMine(canvas, {reduced});
    document.body.dataset.mine = 'ready';
    fit();
    if (!PRINT && current >= 0) {
      const slide = slides[current];
      const hero = slide.hasAttribute('data-hero');
      mine.setVisible(hero);
      if (hero) {
        // the opening: from the surface down to the whole mine
        if (current === 0 && !reduced) { mine.go('surface', {instant: true}); mine.go('overview', {ms: 2600}); }
        else mine.go(slide.dataset.view, {instant: true});
      } else mine.go('overview', {instant: true});
    }
  } catch (error) {
    document.body.dataset.mine = 'failed';
    console.warn('The live mine is not shown:', error.message);
  }
}

// ---- print API (tools/render_pdf.py) -------------------------------------------------------------------------
const still = document.getElementById('mine-still');
window.deck = {
  count: slides.length,
  async prepare(index) {
    show(index, {instant: true});
    const slide = slides[index];
    slide.querySelectorAll('[data-count]').forEach(settle);
    if (slide.hasAttribute('data-hero') && mine) {
      still.src = mine.still(slide.dataset.view, 1920, 1080);
      await still.decode();
    }
    await document.fonts.ready;
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    return {index, label: slide.dataset.label, hero: slide.hasAttribute('data-hero'), mine: document.body.dataset.mine};
  },
  still(view) { return mine ? mine.still(view, 1920, 1080) : null; },
};

// ---- boot ---------------------------------------------------------------------------------------------------
fit();
const start = Number(location.hash.slice(1));
const first = PRINT ? 0 : (Number.isInteger(start) && start >= 1 ? start - 1 : 0);
if (PRINT || reduced) show(first, {instant: true});
else requestAnimationFrame(() => requestAnimationFrame(() => show(first)));
startMine().finally(() => { document.body.dataset.boot = 'ready'; });
