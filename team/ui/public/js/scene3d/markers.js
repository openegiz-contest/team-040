// Markers of people, sensors, exits and signs: screen-facing sprites of a
// constant size in pixels, all in one draw call (THREE.Points with a sprite
// atlas), plus a faint "ghost" pass where stone stands in front of them, so
// that rock never hides a person, a barrier sign or a sensor.
//
// The pictures repeat the outlines of the scheme and its legend (icons.js):
// a person with a route is a round mark, without a route a crossed square,
// unknown a dashed circle with "?"; a sensor is a diamond, with a clock when
// its data are stale and struck through when lost; an exit is a portal with an
// upward chevron. Every one stands on a dark plate so it reads on pale stone.

import * as THREE from 'three';
import {TOKEN} from './palette.js';

const CELL = 64;
const COLUMNS = 8;
const ROWS = 4;

const CELLS = [
  'worker:ok', 'worker:none', 'worker:unknown', 'ring:danger', 'ring:selected', 'ring:hover',
  'sensor:fresh', 'sensor:stale', 'sensor:lost', 'sensor:unknown', 'exit:available', 'exit:unavailable', 'exit:unknown',
  'sign:attention', 'sign:danger', 'sign:unknown', 'sign:lastDanger', 'sign:pending', 'sign:blocked', 'sign:stopped',
  'sign:leaving', 'sign:question', 'ring:pending',
];

export const CELL_INDEX = Object.fromEntries(CELLS.map((name, index) => [name, index]));

// Outlines of icons.js, in a 16 px box centred on the origin.
const PATH = {
  octagon: 'M-2.8 -6.5h5.6l3.7 3.7v5.6l-3.7 3.7h-5.6l-3.7 -3.7v-5.6z',
  bang: 'M0 -3.6v4.4M0 2.9v.6',
  triangle: 'M0 -6.2l6.6 12h-13.2z',
  triangleBang: 'M0 -1.8v3.6M0 3.6v.5',
  question: 'M-2 -1.6a2 2 0 1 1 2.9 1.8c-.6.3-.9.7-.9 1.4M0 3.6v.5',
  clock: 'M0 -3.8V0l2.6 1.6',
  leaving: 'M-6.5 0h8.5M-1.5 -3.5l3.5 3.5l-3.5 3.5M6 -6v12',
  portal: 'M0 -10L8.5 -3.5V9h-17V-3.5z',
  chevron: 'M0 5.5v-9M-3.5 -1l3.5 -3.5l3.5 3.5',
  diamond: 'M0 -7L7 0L0 7L-7 0z',
};

function plate(g, radius) {
  g.fillStyle = 'rgba(17, 19, 22, 0.9)';
  g.strokeStyle = 'rgba(232, 227, 218, 0.6)';
  g.lineWidth = 1.5;
  g.beginPath();
  g.arc(0, 0, radius, 0, Math.PI * 2);
  g.fill();
  g.stroke();
}

function ring(g, radius, colour, width, dash = null) {
  g.save();
  g.strokeStyle = colour;
  g.lineWidth = width;
  if (dash) g.setLineDash(dash);
  g.beginPath();
  g.arc(0, 0, radius, 0, Math.PI * 2);
  g.stroke();
  g.restore();
}

/** Stroke (and fill) an icons.js outline scaled from its 16 px box; `width` in pixels of the cell. */
function outline(g, d, scale, {stroke = TOKEN.dust1, fill = null, width = 3, dash = null} = {}) {
  g.save();
  g.scale(scale, scale);
  const path = new Path2D(d);
  if (fill) {
    g.fillStyle = fill;
    g.fill(path);
  }
  g.strokeStyle = stroke;
  g.lineWidth = width / scale;
  g.lineJoin = 'round';
  g.lineCap = 'round';
  if (dash) g.setLineDash(dash.map((v) => v / scale));
  g.stroke(path);
  g.restore();
}

function line(g, x1, y1, x2, y2, colour, width) {
  g.strokeStyle = colour;
  g.lineWidth = width;
  g.lineCap = 'round';
  g.beginPath();
  g.moveTo(x1, y1);
  g.lineTo(x2, y2);
  g.stroke();
}

function drawCell(g, name) {
  const [kind, state] = name.split(':');
  if (kind === 'ring') {
    if (state === 'danger') {
      ring(g, 26, 'rgba(17, 19, 22, 0.95)', 9);
      ring(g, 26, TOKEN.danger, 5);
    } else if (state === 'selected') {
      ring(g, 27, TOKEN.copper, 5);
    } else if (state === 'hover') {
      ring(g, 27, 'rgba(232, 227, 218, 0.9)', 3);
    } else {
      ring(g, 27, TOKEN.copper, 4, [7, 5]);
    }
    return;
  }
  if (kind === 'worker') {
    plate(g, 19);
    if (state === 'ok') {
      g.fillStyle = TOKEN.dust1;
      g.beginPath();
      g.arc(0, 0, 10.5, 0, Math.PI * 2);
      g.fill();
    } else if (state === 'none') {
      g.fillStyle = TOKEN.ink0;
      g.strokeStyle = TOKEN.noroute;
      g.lineWidth = 3.4;
      g.beginPath();
      g.rect(-10, -10, 20, 20);
      g.fill();
      g.stroke();
      line(g, -10, -10, 10, 10, TOKEN.noroute, 3.4);
      line(g, -10, 10, 10, -10, TOKEN.noroute, 3.4);
    } else {
      ring(g, 11, TOKEN.unknown, 3, [4, 3]);
      outline(g, PATH.question, 2.4, {stroke: TOKEN.unknown, width: 3});
    }
    return;
  }
  if (kind === 'sensor') {
    plate(g, 15);
    outline(g, PATH.diamond, 1.35, {stroke: TOKEN.dust1, fill: state === 'fresh' ? TOKEN.steel : TOKEN.ink2, width: 2.4});
    if (state === 'stale') {
      g.save();
      g.translate(8, -8);
      g.fillStyle = TOKEN.ink0;
      g.beginPath();
      g.arc(0, 0, 7, 0, Math.PI * 2);
      g.fill();
      ring(g, 6.5, TOKEN.dust1, 1.6);
      outline(g, PATH.clock, 1.3, {stroke: TOKEN.dust1, width: 1.6});
      g.restore();
    }
    if (state === 'lost' || state === 'unknown') line(g, -12, 12, 12, -12, TOKEN.dust1, 3);
    if (state === 'unknown') outline(g, PATH.question, 1.6, {stroke: TOKEN.unknown, width: 2});
    return;
  }
  if (kind === 'exit') {
    plate(g, 21);
    const available = state === 'available';
    outline(g, PATH.portal, 1.75, {stroke: available ? TOKEN.verdigris : TOKEN.dust2, fill: available ? '#1F3A36' : TOKEN.ink2, width: 2.8});
    if (state !== 'unknown') outline(g, PATH.chevron, 1.75, {stroke: available ? '#CDEDE7' : TOKEN.dust3, width: 2.8});
    if (state === 'unavailable') line(g, -16, 16, 16, -16, TOKEN.dust1, 3);
    if (state === 'unknown') outline(g, PATH.question, 1.9, {stroke: TOKEN.dust1, width: 2.6});
    return;
  }
  // Signs.
  plate(g, 18);
  if (state === 'attention') {
    outline(g, PATH.triangle, 2, {stroke: TOKEN.attention, fill: '#3A2C12', width: 3});
    outline(g, PATH.triangleBang, 2, {stroke: TOKEN.attention, width: 3});
  } else if (state === 'danger' || state === 'lastDanger') {
    outline(g, PATH.octagon, 2, {stroke: TOKEN.danger, fill: state === 'danger' ? '#3F1714' : null, width: 3.2,
      dash: state === 'lastDanger' ? [4.4, 3.2] : null});
    outline(g, PATH.bang, 2, {stroke: TOKEN.danger, width: 3.2});
  } else if (state === 'unknown' || state === 'question') {
    if (state === 'unknown') ring(g, 12.5, TOKEN.unknown, 2.6, [4, 3]);
    outline(g, PATH.question, 2.2, {stroke: TOKEN.unknown, width: 3});
  } else if (state === 'pending') {
    ring(g, 13, TOKEN.copper, 2.6, [5, 4]);
    outline(g, PATH.clock, 2.4, {stroke: TOKEN.copper, width: 3});
  } else if (state === 'blocked') {
    ring(g, 12, TOKEN.dust1, 3);
    line(g, -7, 0, 7, 0, TOKEN.dust1, 4.5);
  } else if (state === 'stopped') {
    g.strokeStyle = TOKEN.dust1;
    g.lineWidth = 2.4;
    g.strokeRect(-11, -11, 22, 22);
    line(g, -4, -6, -4, 6, TOKEN.dust1, 2.4);
    line(g, 4, -6, 4, 6, TOKEN.dust1, 2.4);
  } else {
    outline(g, PATH.leaving, 2, {stroke: TOKEN.dust1, width: 3});
  }
}

/**
 * Draw the atlas.
 * @returns {HTMLCanvasElement}
 */
export function drawAtlas() {
  const canvas = document.createElement('canvas');
  canvas.width = CELL * COLUMNS;
  canvas.height = CELL * ROWS;
  const g = canvas.getContext('2d');
  CELLS.forEach((name, index) => {
    g.save();
    g.translate((index % COLUMNS) * CELL + CELL / 2, Math.floor(index / COLUMNS) * CELL + CELL / 2);
    drawCell(g, name);
    g.restore();
  });
  return canvas;
}

const VERTEX = `
attribute float aCell;
attribute float aSize;
attribute float aAlpha;
uniform float uPixelRatio;
varying float vCell;
varying float vAlpha;
void main() {
  vCell = aCell;
  vAlpha = aAlpha;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * uPixelRatio;
}`;

const FRAGMENT = `
uniform sampler2D uAtlas;
uniform vec2 uGrid;
uniform float uOpacity;
varying float vCell;
varying float vAlpha;
void main() {
  vec2 cell = vec2(mod(vCell, uGrid.x), floor(vCell / uGrid.x));
  vec4 colour = texture2D(uAtlas, (cell + gl_PointCoord) / uGrid);
  if (colour.a * vAlpha < 0.04) discard;
  gl_FragColor = vec4(colour.rgb, colour.a * uOpacity * vAlpha);
}`;

/**
 * The two passes of the sprites: in front (depth tested) and behind stone (faint).
 * @param {THREE.Texture} atlas
 */
export function spriteMaterials(atlas, pixelRatio) {
  const make = (opacity, depthFunc) => new THREE.ShaderMaterial({
    uniforms: {
      uAtlas: {value: atlas}, uGrid: {value: new THREE.Vector2(COLUMNS, ROWS)},
      uOpacity: {value: opacity}, uPixelRatio: {value: pixelRatio},
    },
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    depthFunc,
  });
  return {front: make(1, THREE.LessEqualDepth), behind: make(0.38, THREE.GreaterDepth)};
}

/** A Points geometry with room for `capacity` sprites. */
export function spriteGeometry(capacity) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(capacity * 3), 3).setUsage(THREE.DynamicDrawUsage));
  geometry.setAttribute('aCell', new THREE.BufferAttribute(new Float32Array(capacity), 1).setUsage(THREE.DynamicDrawUsage));
  geometry.setAttribute('aSize', new THREE.BufferAttribute(new Float32Array(capacity), 1).setUsage(THREE.DynamicDrawUsage));
  geometry.setAttribute('aAlpha', new THREE.BufferAttribute(new Float32Array(capacity), 1).setUsage(THREE.DynamicDrawUsage));
  geometry.setDrawRange(0, 0);
  return geometry;
}

/**
 * Write sprites into a geometry made by spriteGeometry: [{position, cell, size, alpha?}].
 * Grows the buffers when needed; returns the geometry to use.
 */
export function writeSprites(geometry, sprites) {
  let target = geometry;
  if (sprites.length > target.attributes.aCell.count) {
    target.dispose();
    target = spriteGeometry(Math.max(sprites.length, target.attributes.aCell.count * 2));
  }
  const pos = target.attributes.position;
  const cell = target.attributes.aCell;
  const size = target.attributes.aSize;
  const alpha = target.attributes.aAlpha;
  sprites.forEach((sprite, i) => {
    pos.setXYZ(i, sprite.position[0], sprite.position[1], sprite.position[2]);
    cell.setX(i, CELL_INDEX[sprite.cell] ?? 0);
    size.setX(i, sprite.size);
    alpha.setX(i, sprite.alpha ?? 1);
  });
  for (const attribute of [pos, cell, size, alpha]) attribute.needsUpdate = true;
  target.setDrawRange(0, sprites.length);
  // Sprites are not culled by the bounding sphere of an earlier set of positions.
  target.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e7);
  return target;
}
