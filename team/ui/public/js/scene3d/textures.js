// Procedural textures of the model, drawn once on small 2D canvases with a
// seeded generator: the same picture on every load. Stone grain, strata of the
// cut faces, the hatch patterns of the three hazard states, the barricade.

import * as THREE from 'three';
import {TOKEN, TONE} from './palette.js';

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
  // The top of the texture is the sawn edge: a light line.
  g.fillStyle = 'rgba(186, 180, 168, 0.5)';
  g.fillRect(0, 0, 512, 2);
  return texture(element);
}

/** Channel walls: dark stone with vertical tool marks. */
function wall() {
  const [element, g] = canvas(128, 32);
  const rnd = random(31);
  g.fillStyle = TONE.wall;
  g.fillRect(0, 0, 128, 32);
  for (let i = 0; i < 120; i += 1) {
    g.fillStyle = rnd() < 0.5 ? 'rgba(0, 0, 0, 0.12)' : 'rgba(200, 194, 184, 0.05)';
    g.fillRect(rnd() * 128, 0, 1 + rnd() * 2, 32);
  }
  // v = 0 at the floor: the foot of the wall is in shadow.
  const foot = g.createLinearGradient(0, 32, 0, 0);
  foot.addColorStop(0, 'rgba(0, 0, 0, 0.35)');
  foot.addColorStop(1, 'rgba(0, 0, 0, 0)');
  g.fillStyle = foot;
  g.fillRect(0, 0, 128, 32);
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

/** Every texture of the model, made once per scene. */
export function makeTextures() {
  return {
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
