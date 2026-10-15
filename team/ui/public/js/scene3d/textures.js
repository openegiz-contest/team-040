// Procedural textures of the model, drawn once on small 2D canvases with a
// seeded generator: the same picture on every load. Stone grain, strata of the
// cut faces with thin copper ore veins, the hatch patterns of the three hazard
// states, the barricade; and for the surroundings (environment.js) the rock of
// the massif, the chipped lips of the cuts and the vignette behind the model;
// the walls of the channels and the cut faces carry their own baked shadow at the
// foot and the underside, the pale floors two faint wheel ruts.

import * as THREE from 'three';
import {ENV, TOKEN, TONE} from './palette.js';

/** A small deterministic generator (mulberry32). */
export function random(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function canvas(width, height) {
  const element = document.createElement('canvas');
  element.width = width;
  element.height = height;
  return [element, element.getContext('2d')];
}

function texture(element, repeat = true) {
  const map = new THREE.CanvasTexture(element);
  map.colorSpace = THREE.SRGBColorSpace;
  if (repeat) {
    map.wrapS = THREE.RepeatWrapping;
    map.wrapT = THREE.RepeatWrapping;
  }
  map.anisotropy = 4;
  return map;
}

/**
 * The offsets at which a shape centred at (x, y) with half sizes (rx, ry) must be drawn on a tile of w × h that
 * repeats (0 for an axis that does not): itself, and once more across each edge it overlaps.
 */
function copies(x, y, rx, ry, w, h) {
  const along = (c, r, size) => (size ? [-size, 0, size].filter((d) => c + d + r > 0 && c + d - r < size) : [0]);
  const out = [];
  for (const dx of along(x, rx, w)) for (const dy of along(y, ry, h)) out.push([dx, dy]);
  return out;
}

/** A hex colour of the palette with an alpha, for the canvas. */
function rgba(hex, alpha) {
  const value = parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

/**
 * A thin jagged line (an ore vein, a crack) from a start point and a direction, wandering a little at every step;
 * drawn again one tile away across each edge of a repeating texture (`wrap` = [width, height], 0 for no repeat).
 */
function vein(g, rnd, start, {angle, steps, step, width, colour, wander = 0.55}, wrap = [0, 0]) {
  let [x, y] = start;
  let a = angle;
  const points = [[x, y]];
  for (let i = 0; i < steps; i += 1) {
    a += (rnd() - 0.5) * wander;
    const reach = step * (0.6 + rnd() * 0.8);
    x += Math.cos(a) * reach;
    y += Math.sin(a) * reach;
    points.push([x, y]);
  }
  g.strokeStyle = colour;
  g.lineWidth = width;
  g.lineJoin = 'round';
  g.lineCap = 'round';
  const [w, h] = wrap;
  for (const dx of w ? [-w, 0, w] : [0]) {
    for (const dy of h ? [-h, 0, h] : [0]) {
      g.beginPath();
      points.forEach(([px, py], index) => (index === 0 ? g.moveTo(px + dx, py + dy) : g.lineTo(px + dx, py + dy)));
      g.stroke();
    }
  }
  return points;
}

/**
 * Copper ore in a rock face, the way it shows on a sawn cut: a few small ore lenses, each a faint purple-bronze
 * bornite tarnish with disseminated chalcopyrite flecks (dull brass) and a handful of short veinlets, and short
 * green malachite smears near some of them. Subtle at every scale: rock with ore, never a sign; never on a floor.
 * `scale` is pixels per metre of the face relative to the massif's.
 */
function oreVeins(g, rnd, width, height, scale, wrap, lenses) {
  const [w, h] = wrap;
  const wrapped = (draw, x, y, rx, ry) => {
    for (const [dx, dy] of copies(x, y, rx, ry, w, h)) draw(dx, dy);
  };
  for (let c = 0; c < lenses; c += 1) {
    const cx = rnd() * width;
    const cy = height * (0.15 + rnd() * 0.7);
    const rx = (20 + rnd() * 26) * scale;
    const ry = rx * (0.35 + rnd() * 0.25);
    wrapped((dx, dy) => {
      const gradient = g.createRadialGradient(cx + dx, cy + dy, 0, cx + dx, cy + dy, rx);
      gradient.addColorStop(0, rgba(ENV.bornite, 0.3));
      gradient.addColorStop(1, rgba(ENV.bornite, 0));
      g.save();
      g.translate(cx + dx, cy + dy);
      g.scale(1, ry / rx);
      g.translate(-(cx + dx), -(cy + dy));
      g.fillStyle = gradient;
      g.fillRect(cx + dx - rx, cy + dy - rx, 2 * rx, 2 * rx);
      g.restore();
    }, cx, cy, rx, rx);
    const flecks = Math.round(40 + rnd() * 50);
    for (let i = 0; i < flecks; i += 1) {
      const a = rnd() * Math.PI * 2;
      const r = Math.sqrt(rnd());
      const x = cx + Math.cos(a) * rx * r;
      const y = cy + Math.sin(a) * ry * r;
      const size = (0.9 + rnd() * 1.6) * Math.max(scale, 0.7);
      g.fillStyle = rgba(ENV.chalcopyrite, 0.45 + rnd() * 0.4);
      wrapped((dx, dy) => g.fillRect(x + dx, y + dy, size, size), x, y, size, size);
    }
    const veinlets = 2 + Math.floor(rnd() * 4);
    for (let i = 0; i < veinlets; i += 1) {
      const start = [cx + (rnd() - 0.5) * rx * 1.4, cy + (rnd() - 0.5) * ry * 1.4];
      vein(g, rnd, start, {angle: -Math.PI / 2 + (rnd() - 0.5) * 1.6, steps: 3 + Math.floor(rnd() * 3), step: 5 * scale,
        width: Math.max(0.8, 0.7 * scale), colour: rgba(ENV.chalcopyrite, 0.55 + rnd() * 0.25), wander: 0.9}, wrap);
    }
    if (rnd() < 0.75) {
      const start = [cx + (rnd() - 0.5) * rx * 2, cy + (rnd() - 0.5) * ry * 2];
      vein(g, rnd, start, {angle: (rnd() - 0.5) * 0.6, steps: 2 + Math.floor(rnd() * 2), step: 4 * scale,
        width: Math.max(1.2, 1.6 * scale), colour: rgba(ENV.malachite, 0.3 + rnd() * 0.2), wander: 0.4}, wrap);
    }
  }
}

/**
 * Sawn stone: a mottled face with fine grain, faint parallel saw marks and a few thin veins. The tile is
 * 96 m of the plan; everything drawn near an edge is drawn again across it, so the tile repeats seamlessly.
 */
function stoneTop() {
  const size = 512;
  const [element, g] = canvas(size, size);
  const rnd = random(7);
  const wrapped = (draw) => {
    for (const dx of [-size, 0, size]) for (const dy of [-size, 0, size]) draw(dx, dy);
  };
  g.fillStyle = TONE.top;
  g.fillRect(0, 0, size, size);
  // Mottling: soft patches tens of metres across, lighter and darker, so a slab never reads as one flat card.
  for (let i = 0; i < 70; i += 1) {
    const x = rnd() * size;
    const y = rnd() * size;
    const r = 30 + rnd() * 110;
    const light = rnd() < 0.5;
    const alpha = 0.05 + rnd() * 0.08;
    wrapped((dx, dy) => {
      const gradient = g.createRadialGradient(x + dx, y + dy, 0, x + dx, y + dy, r);
      const colour = light ? '150, 146, 138' : '52, 50, 47';
      gradient.addColorStop(0, `rgba(${colour}, ${alpha})`);
      gradient.addColorStop(1, `rgba(${colour}, 0)`);
      g.fillStyle = gradient;
      g.fillRect(x + dx - r, y + dy - r, 2 * r, 2 * r);
    });
  }
  // Grain: many small flecks, darker and lighter.
  for (let i = 0; i < 16000; i += 1) {
    const light = rnd() < 0.45;
    g.fillStyle = light ? `rgba(160, 156, 147, ${0.07 + rnd() * 0.12})` : `rgba(38, 37, 35, ${0.08 + rnd() * 0.14})`;
    const w = 1 + rnd() * 2.2;
    g.fillRect(rnd() * size, rnd() * size, w, w * (0.4 + rnd() * 0.8));
  }
  // Saw marks: long faint parallel lines across the whole tile.
  g.lineWidth = 1;
  for (let y = 3; y < size; y += 5 + Math.floor(rnd() * 9)) {
    g.strokeStyle = rnd() < 0.5 ? 'rgba(40, 38, 36, 0.07)' : 'rgba(150, 146, 138, 0.06)';
    g.beginPath();
    g.moveTo(0, y);
    g.lineTo(size, y);
    g.stroke();
  }
  // Veins: a few thin pale cracks.
  for (let i = 0; i < 9; i += 1) {
    let x = rnd() * size;
    let y = rnd() * size;
    let angle = rnd() * Math.PI * 2;
    const points = [[x, y]];
    for (let step = 0; step < 14; step += 1) {
      angle += (rnd() - 0.5) * 0.9;
      x += Math.cos(angle) * 9;
      y += Math.sin(angle) * 9;
      points.push([x, y]);
    }
    g.strokeStyle = `rgba(158, 154, 145, ${0.12 + rnd() * 0.1})`;
    g.lineWidth = 0.8 + rnd() * 0.7;
    wrapped((dx, dy) => {
      g.beginPath();
      points.forEach(([px, py], index) => (index === 0 ? g.moveTo(px + dx, py + dy) : g.lineTo(px + dx, py + dy)));
      g.stroke();
    });
  }
  return texture(element);
}

/** Strata: horizontal bands of three stone tones with a slow irregular wobble; v = 0 at the bottom. */
function strata() {
  const [element, g] = canvas(512, 128);
  const rnd = random(19);
  const tones = [TONE.sideA, TONE.sideB, TONE.sideC, TONE.sideB, TONE.sideA, TONE.sideC, TONE.sideB, TONE.sideA];
  let y = 0;
  const bands = [];
  while (y < 128) {
    const h = 9 + Math.floor(rnd() * 16);
    bands.push({y, h, tone: tones[bands.length % tones.length], phase: rnd() * 6.28, amp: 1 + rnd() * 3});
    y += h;
  }
  // Each band covers from the bottom of the canvas up to its own top; painted from the highest down,
  // so every lower band overwrites what lies under its top and all bands stay visible.
  g.fillStyle = tones[0];
  g.fillRect(0, 0, 512, 128);
  for (const band of [...bands].reverse()) {
    g.fillStyle = band.tone;
    g.beginPath();
    g.moveTo(0, 128);
    for (let x = 0; x <= 512; x += 8) {
      // Integer multiples of the width keep the band continuous across the repeat.
      const wobble = Math.sin((x / 512) * Math.PI * 4 + band.phase) * band.amp + Math.sin((x / 512) * Math.PI * 10 + band.phase * 2) * band.amp * 0.4;
      g.lineTo(x, 128 - (band.y + band.h + wobble));
    }
    g.lineTo(512, 128);
    g.closePath();
    g.fill();
  }
  // Fine grain and a thin pale seam at a few band tops.
  for (let i = 0; i < 5200; i += 1) {
    g.fillStyle = rnd() < 0.5 ? 'rgba(0, 0, 0, 0.12)' : 'rgba(220, 214, 204, 0.06)';
    g.fillRect(rnd() * 512, rnd() * 128, 1 + rnd() * 3, 1);
  }
  g.lineWidth = 1.2;
  g.strokeStyle = `${TONE.sideHighlight}80`;
  for (const band of bands.filter((_, i) => i % 3 === 1)) {
    g.beginPath();
    for (let x = 0; x <= 512; x += 8) {
      const wobble = Math.sin((x / 512) * Math.PI * 4 + band.phase) * band.amp;
      g.lineTo(x, 128 - (band.y + band.h + wobble));
    }
    g.stroke();
  }
  // Copper ore in the cut face: a few veinlets across the bands (repeating along u only).
  oreVeins(g, random(23), 512, 128, 0.7, [512, 0], 2);
  // v = 0 is the underside of the slab: darker towards it (baked ambient occlusion; a ramp's side shows the lowest part).
  const under = g.createLinearGradient(0, 128, 0, 60);
  under.addColorStop(0, 'rgba(0, 0, 0, 0.5)');
  under.addColorStop(1, 'rgba(0, 0, 0, 0)');
  g.fillStyle = under;
  g.fillRect(0, 60, 512, 68);
  // The top of the texture is the sawn edge: a light line.
  g.fillStyle = 'rgba(186, 180, 168, 0.5)';
  g.fillRect(0, 0, 512, 2);
  return texture(element);
}

/**
 * Channel walls: dark rock broken by the drill and blast — blotches, a few cracks along the bedding and the
 * vertical half-barrels of the blast holes; v = 0 at the floor (the foot is darkened by the geometry's own AO).
 */
function wall() {
  const [element, g] = canvas(256, 48);
  const rnd = random(31);
  g.fillStyle = TONE.wall;
  g.fillRect(0, 0, 256, 48);
  for (let i = 0; i < 90; i += 1) {
    const x = rnd() * 256;
    const y = rnd() * 48;
    const r = 3 + rnd() * 10;
    for (const dx of [-256, 0, 256]) {
      g.fillStyle = rnd() < 0.5 ? 'rgba(0, 0, 0, 0.13)' : 'rgba(150, 144, 134, 0.07)';
      g.beginPath();
      g.ellipse(x + dx, y, r * 1.6, r * 0.7, 0, 0, Math.PI * 2);
      g.fill();
    }
  }
  // Half-barrels of the blast holes: faint vertical grooves at about a metre.
  for (let x = 4; x < 256; x += 30 + Math.floor(rnd() * 16)) {
    g.fillStyle = 'rgba(0, 0, 0, 0.16)';
    g.fillRect(x, 6, 2, 42);
    g.fillStyle = 'rgba(170, 164, 154, 0.08)';
    g.fillRect(x + 2, 6, 1, 42);
  }
  for (let i = 0; i < 6; i += 1) {
    vein(g, rnd, [rnd() * 256, 8 + rnd() * 32], {angle: (rnd() - 0.5) * 0.4, steps: 6, step: 9, width: 1, colour: 'rgba(0, 0, 0, 0.3)', wander: 0.6}, [256, 0]);
  }
  // v = 0 at the floor: the foot of the wall is in shadow (baked ambient occlusion).
  const foot = g.createLinearGradient(0, 48, 0, 0);
  foot.addColorStop(0, 'rgba(0, 0, 0, 0.45)');
  foot.addColorStop(0.6, 'rgba(0, 0, 0, 0.08)');
  foot.addColorStop(1, 'rgba(0, 0, 0, 0)');
  g.fillStyle = foot;
  g.fillRect(0, 0, 256, 48);
  // The top of the wall is the chipped lip: lighter, broken.
  for (let x = 0; x < 256; x += 2) {
    g.fillStyle = `rgba(150, 144, 134, ${0.08 + rnd() * 0.14})`;
    g.fillRect(x, 0, 2, 2 + rnd() * 4);
  }
  return texture(element);
}

/**
 * Floors of the hazard states: the same outlines as the scheme's hatches.
 * attention: sparse diagonal stripes; danger: dense crossed lines; unknown: fine fog hatch.
 * u runs along the working, v across it.
 */
function hazardFloor(state) {
  const [element, g] = canvas(64, 64);
  if (state === 'attention') {
    g.fillStyle = '#5C4824';
    g.fillRect(0, 0, 64, 64);
    g.strokeStyle = TOKEN.attention;
    g.lineWidth = 11;
    for (let k = -64; k <= 128; k += 32) {
      g.beginPath();
      g.moveTo(k, 64);
      g.lineTo(k + 64, 0);
      g.stroke();
    }
  } else if (state === 'danger') {
    g.fillStyle = TOKEN.danger;
    g.fillRect(0, 0, 64, 64);
    g.strokeStyle = '#3A1210';
    g.lineWidth = 4;
    for (let k = -64; k <= 128; k += 16) {
      g.beginPath(); g.moveTo(k, 64); g.lineTo(k + 64, 0); g.stroke();
      g.beginPath(); g.moveTo(k, 0); g.lineTo(k + 64, 64); g.stroke();
    }
  } else if (state === 'unknown') {
    g.fillStyle = '#8D9298';
    g.fillRect(0, 0, 64, 64);
    g.strokeStyle = '#5E636A';
    g.lineWidth = 3;
    for (let k = -64; k <= 128; k += 12) {
      g.beginPath(); g.moveTo(k, 0); g.lineTo(k + 64, 64); g.stroke();
    }
  } else if (state === 'zone') {
    g.fillStyle = TONE.floorZone;
    g.fillRect(0, 0, 64, 64);
    const rnd = random(43);
    for (let i = 0; i < 120; i += 1) {
      g.fillStyle = `rgba(90, 82, 70, ${0.05 + rnd() * 0.08})`;
      g.fillRect(rnd() * 64, rnd() * 64, 1 + rnd() * 2, 1 + rnd() * 2);
    }
    // Two faint wheel ruts along the working (u runs along it): the floor of a drift that machines use.
    for (const v of [19, 45]) {
      for (let x = 0; x < 64; x += 1) {
        g.fillStyle = `rgba(96, 88, 76, ${0.06 + rnd() * 0.05})`;
        g.fillRect(x, v - 2 + Math.round(rnd() - 0.5), 1, 4);
      }
    }
  } else {
    g.fillStyle = TONE.floor;
    g.fillRect(0, 0, 64, 64);
    const rnd = random(47);
    for (let i = 0; i < 220; i += 1) {
      g.fillStyle = rnd() < 0.5 ? 'rgba(30, 29, 27, 0.14)' : 'rgba(200, 196, 188, 0.07)';
      g.fillRect(rnd() * 64, rnd() * 64, 1 + rnd() * 2, 1 + rnd() * 2);
    }
  }
  return texture(element);
}

/** A barricade: graphite and white diagonal bands with a cross, never a hazard colour. */
function barricadeFace() {
  const [element, g] = canvas(64, 64);
  g.fillStyle = TONE.barricadeDark;
  g.fillRect(0, 0, 64, 64);
  g.strokeStyle = TONE.barricadeLight;
  g.lineWidth = 9;
  for (let k = -64; k <= 128; k += 26) {
    g.beginPath();
    g.moveTo(k, 64);
    g.lineTo(k + 64, 0);
    g.stroke();
  }
  return texture(element, false);
}

/** A soft dark spot under the stack: the model stands on the desk. */
function contactShadow() {
  const [element, g] = canvas(128, 128);
  const gradient = g.createRadialGradient(64, 64, 8, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(0, 0, 0, 0.55)');
  gradient.addColorStop(0.6, 'rgba(0, 0, 0, 0.25)');
  gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
  g.fillStyle = gradient;
  g.fillRect(0, 0, 128, 128);
  return texture(element, false);
}

/**
 * The rock of the massif: strata of four cool rock tones that wander slowly, thin bedding seams, grain, a few
 * steep cracks and the copper ore — clusters of brass veinlets with a bornite tarnish, malachite streaks. The tile
 * repeats both ways (MASSIF_TILE metres); the massif maps it with a slight dip, so the beds are not level.
 */
export const MASSIF_TILE = [240, 120];

function massif() {
  const w = 1024;
  const h = 512;
  // Drawn in the coordinates of a 1024 × 512 tile on a canvas of half that: the rock reads the same, and the
  // texture costs a quarter to make and to upload (the first frame on a software renderer).
  const [element, g] = canvas(w / 2, h / 2);
  g.scale(0.5, 0.5);
  const rnd = random(101);
  const tones = [ENV.rockA, ENV.rockB, ENV.rockC, ENV.rockD, ENV.rockE, ENV.rockF, ENV.rockA, ENV.rockC, ENV.rockB];
  const bands = [];
  for (let y = 0; y < h;) {
    // Thick beds with thin partings between some of them.
    const thin = rnd() < 0.18;
    const height = thin ? 3 + Math.floor(rnd() * 5) : 26 + Math.floor(rnd() * 80);
    bands.push({y, tone: thin ? ENV.rockParting : tones[Math.floor(rnd() * tones.length)], phase: rnd() * 6.28, amp: 1.5 + rnd() * 5,
      harmonics: [1, 3, 4, 7, 9].map((n) => [n, rnd() * 6.28, rnd()]), jag: Array.from({length: w / 16 + 1}, () => rnd() - 0.5)});
    y += height;
  }
  bands.forEach((band) => {
    // The last jag repeats the first, so the edge meets itself across the tile.
    band.jag[band.jag.length - 1] = band.jag[0];
  });
  // Every band is filled from its own top down to the bottom of the tile, the highest first: each lower band
  // covers what lies below its top, so every band keeps its own height.
  // Bed contacts are irregular: a slow swell, a few harmonics (whole periods across the tile) and a jagged step.
  const edge = (band, x) => band.y + Math.sin((x / w) * Math.PI * 2 * 2 + band.phase) * band.amp
    + band.harmonics.reduce((sum, [n, phase, amp]) => sum + Math.sin((x / w) * Math.PI * 2 * n + phase) * band.amp * 0.35 * amp, 0)
    + band.jag[Math.round(x / 16)] * 2.4;
  g.fillStyle = bands[0].tone;
  g.fillRect(0, 0, w, h);
  for (const band of bands.slice(1)) {
    g.fillStyle = band.tone;
    g.beginPath();
    g.moveTo(0, h);
    for (let x = 0; x <= w; x += 16) g.lineTo(x, edge(band, x));
    g.lineTo(w, h);
    g.closePath();
    g.fill();
  }
  // Lenses of other rock inside the beds: the beds pinch out and swell instead of running on like boards.
  for (let i = 0; i < 26; i += 1) {
    const x = rnd() * w;
    const y = rnd() * h;
    const rx = 30 + rnd() * 110;
    const ry = 3 + rnd() * 11;
    const tone = tones[Math.floor(rnd() * tones.length)];
    const tilt = (rnd() - 0.5) * 0.08;
    for (const [dx, dy] of copies(x, y, rx, rx * 0.1 + ry, w, h)) {
      g.fillStyle = rgba(tone, 0.55);
      g.beginPath();
      g.ellipse(x + dx, y + dy, rx, ry, tilt, 0, Math.PI * 2);
      g.fill();
    }
  }
  // Mottling inside the beds: soft patches, lighter and darker, wider than tall.
  for (let i = 0; i < 70; i += 1) {
    const x = rnd() * w;
    const y = rnd() * h;
    const r = 18 + rnd() * 60;
    const light = rnd() < 0.45;
    for (const [dx, dy] of copies(x, y, r, r, w, h)) {
      const gradient = g.createRadialGradient(x + dx, y + dy, 0, x + dx, y + dy, r);
      gradient.addColorStop(0, light ? 'rgba(140, 138, 132, 0.08)' : 'rgba(8, 8, 9, 0.1)');
      gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
      g.fillStyle = gradient;
      g.fillRect(x + dx - r, y + dy - r, 2 * r, 2 * r);
    }
  }
  // Grain: small specks, darker and lighter, a granular rock rather than a streaky one.
  for (let i = 0; i < 6000; i += 1) {
    const light = rnd() < 0.42;
    g.fillStyle = light ? `rgba(165, 160, 150, ${0.05 + rnd() * 0.08})` : `rgba(0, 0, 0, ${0.08 + rnd() * 0.14})`;
    const size = 1.6 + rnd() * 2;
    g.fillRect(rnd() * w, rnd() * h, size, size);
  }
  // A few joints of the rock: short, steep, dark.
  for (let i = 0; i < 14; i += 1) {
    vein(g, rnd, [rnd() * w, rnd() * h], {angle: -Math.PI / 2 + (rnd() - 0.5) * 0.5, steps: 3 + Math.floor(rnd() * 4), step: 8,
      width: 1.2, colour: 'rgba(0, 0, 0, 0.22)', wander: 0.5}, [w, h]);
  }
  oreVeins(g, random(103), w, h, 1.4, [w, h], 10);
  // The walls fill much of the stage behind the model: one mip level, no anisotropy (cheap on a software renderer).
  const map = texture(element);
  map.anisotropy = 1;
  map.minFilter = THREE.LinearMipmapNearestFilter;
  return map;
}

/**
 * The lip of a cut, drawn along a ribbon (u along it, v = 1 at the cut): a pale chipped edge fading into the stone
 * a metre or two in. Transparent; never much lighter than the sawn stone around it.
 */
function detail() {
  const w = 128;
  const h = 32;
  const [element, g] = canvas(w, h);
  const image = g.createImageData(w, h);
  const rnd = random(211);
  // Noise along u, smooth enough to read as chips and wear rather than as grain; repeats across the tile.
  const noise = (seed, scale) => {
    const r = random(seed);
    const knots = Array.from({length: Math.ceil(w / scale)}, () => r());
    return (x) => {
      const f = x / scale;
      const i = Math.floor(f);
      const t = f - i;
      const a = knots[i % knots.length];
      const b = knots[(i + 1) % knots.length];
      return a + (b - a) * (t * t * (3 - 2 * t));
    };
  };
  const chips = noise(5, 6);
  const wear = noise(9, 11);
  for (let x = 0; x < w; x += 1) {
    for (let y = 0; y < h; y += 1) {
      // Canvas row 0 is v = 1 (the texture is flipped on upload): the cut.
      const t = (y + 0.5) / h;
      const lip = Math.max(0, 1 - t / (0.35 + 0.35 * chips(x))) ** 1.5;
      const i = (y * w + x) * 4;
      image.data[i] = 222;
      image.data[i + 1] = 214;
      image.data[i + 2] = 200;
      image.data[i + 3] = Math.round(255 * Math.min(1, lip * (0.42 + 0.2 * wear(x)) + (rnd() < 0.04 && t < 0.5 ? 0.15 : 0)));
    }
  }
  g.putImageData(image, 0, 0);
  const map = texture(element);
  map.anisotropy = 1;
  map.wrapT = THREE.ClampToEdgeWrapping;
  map.generateMipmaps = false;
  map.minFilter = THREE.LinearFilter;
  return map;
}

/**
 * The scene's own background: a cool graphite, lighter behind the model and darker towards the corners (a soft
 * vignette), dithered so the dark gradient shows no bands when it is stretched over the stage.
 */
export function backdrop() {
  const size = 256;
  const [element, g] = canvas(size, size);
  const image = g.createImageData(size, size);
  const rnd = random(307);
  const c0 = parseInt(ENV.backCentre.slice(1), 16);
  const c1 = parseInt(ENV.backEdge.slice(1), 16);
  const channel = (c, shift) => (c >> shift) & 255;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const dx = (x + 0.5) / size - 0.5;
      const dy = (y + 0.5) / size - 0.44;
      const t = Math.min(1, Math.hypot(dx * 1.05, dy * 1.2) / 0.62) ** 1.7;
      const i = (y * size + x) * 4;
      for (const [k, shift] of [[0, 16], [1, 8], [2, 0]]) {
        image.data[i + k] = Math.round(channel(c0, shift) + (channel(c1, shift) - channel(c0, shift)) * t + (rnd() - 0.5) * 1.6);
      }
      image.data[i + 3] = 255;
    }
  }
  g.putImageData(image, 0, 0);
  const map = texture(element, false);
  map.generateMipmaps = false;
  map.minFilter = THREE.LinearFilter;
  return map;
}

/** Every texture of the model, made once per scene. */
export function makeTextures() {
  return {
    massif: massif(),
    detail: detail(),
    top: stoneTop(),
    strata: strata(),
    wall: wall(),
    floor: hazardFloor('plain'),
    zone: hazardFloor('zone'),
    attention: hazardFloor('attention'),
    danger: hazardFloor('danger'),
    unknown: hazardFloor('unknown'),
    barricade: barricadeFace(),
    shadow: contactShadow(),
  };
}
