// The 3D stage: the mine as a cutaway stone model on a graphite desk. One
// slab per horizon with its workings carved into the top face, the inter-level
// workings stretched between the slabs, people, sensors, exits, barricades and
// published routes on and above the floors, and HTML labels over the canvas.
//
// Everything placed comes from twin attributes and the last full snapshot
// (layout.js, describe.js); nothing is invented. Rendering is on demand: a
// frame is drawn when the camera moves, a transition runs or the visible state
// changes, and no animation frame is requested while nothing changes.
//
// Transitions explain a published change once (clarity spec B: hazard and knowledge of a zone, a closed
// passage, a route, the selection, the scope of a hovered option) and are skipped under reduced motion, on the
// first picture and while the data are old. The camera frames a zone with its people, the ends of their routes
// and its horizon («показать», an incident that opens); panels over the stage refit it only when they would hide
// the incident or leave the stage mostly empty, at once.
//
// Variant 2 («Пульт смены»): each zone with workings has a loader (lhd.glb, loaders.js), the symbol of the zone's
// published work state — lit while it works, dark and signed «остановлен» when stopped, grey with «?» without a
// published state; a change fades its lights once (400 ms). It never moves: its place is chosen once per run on a
// free floor. The camera follows the situation of the shift (situation.js) once per change: the decision frames the
// incident, the execution the walk, the result and the norm the overview (choreograph).
//
// Read-only mirrors on the scene root (.s3) for tests: data-fx (the changes now explained), data-fx-count,
// data-auto-framed (the incident framed by itself), data-refits (refits after a panel or a size change),
// data-framing (how the last zone framing was chosen), data-scope (zones of the hovered option), data-loaders
// (loaders placed), data-loader-fx-count (fades of their lights), data-choreo and data-choreo-count (the camera
// moves that followed the situation).

import * as THREE from 'three';
import {showsOldData} from '../link.js';
import {incidentOf, isUnderground, routeOf, thingByName, thingsOfKind} from '../model.js';
import {situationOf} from '../situation.js';
import * as geo from '../geometry.js';
import {SCENE} from '../text3d.js';
import * as text from '../text.js';
import {createOrbit} from './camera.js';
import {labelItems, tooltipLines} from './content.js';
import {changesBetween, describe, groupWorkers} from './describe.js';
import {createLabels} from './labels.js';
import {
  alongStep, buildLayout, DIMS, levelY, LOADER_SCALE, loaderPlaces as placesForLoaders, pointOnWorking, sceneBounds, sceneLine, silhouette, stepBetween,
  stepLength, toScene, verticalFactor, zoneEntrances,
} from './layout.js';
import {createLoaders} from './loaders.js';
import {drawAtlas, spriteGeometry, spriteMaterials, writeSprites} from './markers.js';
import {TOKEN, TONE} from './palette.js';
import {
  arrowHead, barricade, carveSlab, casing, dashes, disc, frameLoops, merge, plane, portal, rampBand, ribbon, slabGeometry, tube,
} from './shapes.js';
import {makeTextures} from './textures.js';

const DEG = Math.PI / 180;
export const DEFAULT_VIEW = {az: 26 * DEG, el: 25 * DEG};
const TWEEN_MS = 900;
const DRAW_IN_MS = 550;
const EXPLODE_MS = 600;
const MAX_STEP_M = 80;
/** The key of a zone's loader in picking, hover and labels: `loader:<zone>`; a click on it selects the zone. */
const LOADER = 'loader:';
/** The loader of lhd.glb is 10 m long; it is drawn LOADER_SCALE times larger. */
const LOADER_LENGTH = 10 * LOADER_SCALE;
/** The most pixels the light quality renders (about a 1280×860 buffer). */
const LOW_PIXELS = 1.1e6;
const SPRITE_PX = {worker: 30, ring: 40, sensor: 22, exit: 30, sign: 24};
/** Opacity of the warm work light on a selected floor, and of the steel wash of an option's scope. */
const GLOW = 0.34;
const SCOPE_WASH = 0.2;
/** Durations of the transitions that explain a change (clarity spec B); each runs once, never on load. */
const MOTION = {hazard: 450, knowledge: 400, closed: 200, routeOut: 300, select: 200, scope: 150};
/** The light of the rest of the model while something is selected (the work light dims it slightly). */
const DIM = 0.78;
/** An incident is framed by itself only when the user left the camera alone this long. */
const HANDS_OFF_MS = 10000;
/** A size or a panel of the stage settles this long before the picture is refitted (after the strip has grown). */
const SETTLE_MS = 200;
const easeOut = (t) => 1 - (1 - t) ** 3;
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length === 0 ? 0 : sorted[Math.floor(sorted.length / 2)];
};

/**
 * @param {HTMLElement} host the #stage-3d element
 * @param {Object} options
 * @param {Object} options.ctx                 the view context of main.js
 * @param {'high'|'low'} options.quality
 * @param {number} options.explode             0 compact … 1 spread
 * @param {() => boolean} options.reducedMotion
 * @param {(type: string, detail?: *) => void} options.onEvent   'frame', 'context-lost', 'context-restored', 'explode-key', 'status'
 */
export function createScene(host, options) {
  const {ctx} = options;
  const low = options.quality === 'low';
  const reduced = () => options.reducedMotion();

  // ---- DOM ------------------------------------------------------------------------------
  const root = document.createElement('div');
  root.className = 's3';
  const canvas = document.createElement('canvas');
  canvas.className = 's3__canvas';
  canvas.tabIndex = 0;
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('data-testid', 'scene3d-canvas');
  const labelLayer = document.createElement('div');
  labelLayer.className = 's3__labels';
  const tip = document.createElement('div');
  tip.className = 's3__tip';
  tip.hidden = true;
  tip.setAttribute('role', 'tooltip');
  const old = document.createElement('div');
  old.className = 's3__old';
  old.hidden = true;
  const oldText = document.createElement('span');
  oldText.className = 's3__old-text';
  old.append(oldText);
  const gizmo = createGizmo();
  root.append(canvas, old, labelLayer, gizmo.element, tip);
  host.append(root);

  // ---- renderer, camera, lights ---------------------------------------------------------
  const renderer = new THREE.WebGLRenderer({canvas, antialias: !low, alpha: false, powerPreference: 'high-performance'});
  const pixelRatio = low ? 1 : Math.min(window.devicePixelRatio || 1, 2);
  renderer.setPixelRatio(pixelRatio);
  renderer.setClearColor(TOKEN.ink0, 1);
  renderer.info.autoReset = true;
  const gl = renderer.getContext();
  const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
  const rendererName = String(gl.getParameter(debugInfo ? debugInfo.UNMASKED_RENDERER_WEBGL : gl.RENDERER) || '');

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 1, 10000);
  const orbit = createOrbit(camera, {reducedMotion: reduced});
  // A cool sky over a warm key: the stone stays a cool grey, the few lamps of the high quality are the warm points.
  const hemi = new THREE.HemisphereLight('#DDE1E6', '#1C2025', low ? 1.45 : 1.2);
  const key = new THREE.DirectionalLight('#FFF4E8', low ? 2.0 : 1.9);
  key.position.set(420, 900, 520);
  const fill = new THREE.DirectionalLight('#B6C3D1', 0.55);
  fill.position.set(-700, 300, -300);
  scene.add(hemi, key, fill);
  const lamps = [];
  const baseLight = {hemi: hemi.intensity, key: key.intensity, fill: fill.intensity};

  const textures = makeTextures();
  const materials = makeMaterials(textures, low);
  const world = new THREE.Group();
  scene.add(world);

  // ---- state ---------------------------------------------------------------------------
  let layout = null;
  let attributesRef = null;
  let levelGroups = [];
  let staticParts = null;          // k-independent pieces per level, and zone frames
  let interGroup = new THREE.Group();
  let overlayGroups = [];
  let interOverlay = new THREE.Group();
  let routeGroup = new THREE.Group();
  world.add(interGroup, interOverlay, routeGroup);
  let desk = null;
  // The loaders of the zones: candidates per zone from the attributes, and the place each one took for this run.
  const loaders = createLoaders({low, shadow: textures.shadow, scale: LOADER_SCALE});
  world.add(loaders.group);
  let loaderCandidates = new Map();
  let loaderPlaces = new Map();      // zone -> {working, offsetM, facing, span}
  let loaderRun = null;              // the run (and topology) the places were chosen for
  let loaderFade = false;            // a change of a zone's work state is being shown
  let view = null;
  let signature = '';
  let groups = [];
  let explode = Number.isFinite(options.explode) ? options.explode : DIMS.explodeDefault;
  let k = verticalFactor(explode);
  let explodeTween = null;
  let overviewMode = true;
  let width = 0;
  let height = 0;
  let rafId = 0;
  let disposed = false;
  let lost = false;
  let frames = 0;
  let firstFrameAt = null;
  let renderMs = [];
  let hovered = null;
  let pointer = null;
  let selected = null;
  let state = null;
  const drawn = new Map();          // worker name -> {working, offsetM} on the screen
  const tweens = new Map();         // worker name -> {pieces, length, start}
  const drawIn = new Map();         // route key -> {start, progress}
  let routeMeshes = [];
  let spriteList = [];
  let spritesDirty = true;
  let pendingFocus = null;
  let obstaclesAt = 0;
  let fixedObstacles = [];

  // Transitions that explain a change (clarity spec B). Each runs once, ends in the published state, and is
  // skipped (the change shown at once) under reduced motion, on the first picture and while the data are old.
  let fx = null;                   // one publication's changes: hatch fades, outline sweeps, barricades, sensor marks
  let selectFx = null;             // the work light of a new selection fades in (M10)
  let selectLevel = 1;
  let scopeFx = null;              // the scope of a hovered decision option fades in or out (M5)
  let scopeLevel = 1;
  let scopeDrawn = {option: null, zones: [], workers: []};
  const ghosts = [];               // routes no longer published, fading out (M7)
  const ghostGroup = new THREE.Group();
  world.add(ghostGroup);
  // The camera: what it frames, and when the user last moved it (an incident is framed by itself only after a pause).
  let focusId = null;              // the object the camera was last asked to frame, until the user moves it
  let lastTouch = -Infinity;
  let situationKey = null;          // the situation of the shift last seen (choreograph)
  let settleTimer = 0;
  let settleWhy = null;            // 'size' | 'panel'
  let lastPanelCover = '';

  const atlasTexture = new THREE.Texture();
  atlasTexture.flipY = false;
  atlasTexture.colorSpace = THREE.SRGBColorSpace;
  atlasTexture.generateMipmaps = false;
  atlasTexture.minFilter = THREE.LinearFilter;
  const spriteMat = spriteMaterials(atlasTexture, pixelRatio);
  let spriteGeo = spriteGeometry(64);
  const spritesFront = new THREE.Points(spriteGeo, spriteMat.front);
  const spritesBehind = new THREE.Points(spriteGeo, spriteMat.behind);
  spritesFront.renderOrder = 20;
  spritesBehind.renderOrder = 19;
  spritesFront.frustumCulled = false;
  spritesBehind.frustumCulled = false;
  const pins = new THREE.LineSegments(new THREE.BufferGeometry(), materials.pin);
  pins.frustumCulled = false;
  scene.add(spritesFront, spritesBehind, pins);
  atlasTexture.image = drawAtlas();
  atlasTexture.needsUpdate = true;

  const labels = createLabels(labelLayer, (thingId) => ctx.select(thingId), (thingId) => {
    if (hovered !== thingId) {
      hovered = thingId;
      spritesDirty = true;
      updateHoverOverlay();
      invalidate();
    }
  });

  // ---- materials -------------------------------------------------------------------------

  function makeMaterials(tex, isLow) {
    const Lit = isLow ? THREE.MeshLambertMaterial : THREE.MeshStandardMaterial;
    const lit = (params, standard = {}) => new Lit(isLow ? params : {roughness: 0.93, metalness: 0, ...params, ...standard});
    const hazard = (map) => lit({map, emissive: '#ffffff', emissiveMap: map, emissiveIntensity: 0.32,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2});
    const flat = (color, opacity = 1, extra = {}) => new THREE.MeshBasicMaterial({
      color, transparent: opacity < 1, opacity, depthWrite: opacity >= 1, polygonOffset: true, polygonOffsetFactor: -4,
      polygonOffsetUnits: -4, ...extra,
    });
    return {
      top: lit({map: tex.top}),
      strata: lit({map: tex.strata, side: THREE.DoubleSide}),
      wall: lit({map: tex.wall, side: THREE.DoubleSide}),
      floor: lit({map: tex.floor}),
      bottom: lit({color: TONE.bottom}),
      zone: lit({map: tex.zone, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2}),
      attention: hazard(tex.attention),
      danger: hazard(tex.danger),
      unknown: hazard(tex.unknown),
      // A ramp is steep at the spread of the levels: its deck keeps a light of its own so it never turns black.
      road: lit({color: TONE.road, emissive: TONE.roadGlow, side: THREE.DoubleSide}),
      steel: lit({color: TONE.steel}, {metalness: 0.45, roughness: 0.5}),
      portal: lit({color: TONE.steelDark}, {metalness: 0.4, roughness: 0.55}),
      barricade: lit({map: tex.barricade}),
      collar: flat(TONE.collar),
      route: new THREE.MeshBasicMaterial({color: TOKEN.verdigris}),
      routeCore: new THREE.MeshBasicMaterial({color: '#BFE3DC'}),
      frame: {
        normal: flat(TOKEN.dust2, 0.75),
        attention: flat(TOKEN.attention),
        danger: flat(TOKEN.danger),
        unknown: flat(TOKEN.unknown),
        lastDanger: flat(TOKEN.danger),
        // Selection: the chalk-white double ring (its opacity is the fade-in of the work light, M10).
        select: flat(TOKEN.select, 1, {transparent: true}),
        // A command of this page not yet confirmed: the chalk of the scheme, dashed.
        pending: flat(TOKEN.chalk),
        // The scope of the hovered decision option (its opacity fades in and out, M5).
        scope: flat(TOKEN.action, 1, {transparent: true}),
      },
      glow: flat(TOKEN.lightWarm, GLOW, {blending: THREE.AdditiveBlending}),
      scopeWash: flat(TOKEN.action, SCOPE_WASH, {blending: THREE.AdditiveBlending}),
      hover: flat('#ffffff', 0.16, {blending: THREE.AdditiveBlending}),
      shadow: new THREE.MeshBasicMaterial({map: tex.shadow, transparent: true, depthWrite: false}),
      pin: new THREE.LineBasicMaterial({color: TOKEN.dust2, transparent: true, opacity: 0.75}),
    };
  }

  const meshOf = (geometry, material, order = 0) => {
    if (!geometry) return null;
    const mesh = new THREE.Mesh(geometry, material);
    mesh.renderOrder = order;
    mesh.matrixAutoUpdate = false;
    mesh.updateMatrix();
    return mesh;
  };

  function disposeGroup(group) {
    group.traverse((object) => {
      if (object.geometry && object !== spritesFront && object !== spritesBehind) object.geometry.dispose();
    });
    group.clear();
  }

  // ---- static model ----------------------------------------------------------------------

  /** The channel centre lines of a level, local plan, and the notches where an inter-level working leaves it. */
  function levelSegments(level) {
    const segments = [];
    for (const name of level.workings) {
      const line = layout.workings.get(name);
      for (let i = 1; i < line.plan.length; i += 1) segments.push({a: line.plan[i - 1], b: line.plan[i], half: DIMS.half});
    }
    for (const line of layout.workings.values()) {
      if (!line.between) continue;
      const ends = [[line.from, line.mine, line.plan], [line.to, [...line.mine].reverse(), [...line.plan].reverse()]];
      for (const [node, mineLine, plan] of ends) {
        if (layout.nodeLevel.get(node) !== level.name) continue;
        const rising = mineLine[mineLine.length - 1][2] > mineLine[0][2];
        const planLength = Math.hypot(plan[1][0] - plan[0][0], plan[1][1] - plan[0][1]);
        if (!rising || planLength < 1) continue;
        const reach = Math.min(planLength, 16);
        const t = reach / planLength;
        segments.push({a: plan[0], b: [plan[0][0] + (plan[1][0] - plan[0][0]) * t, plan[0][1] + (plan[1][1] - plan[0][1]) * t], half: DIMS.half * 0.85});
      }
    }
    return segments;
  }

  function buildStatic() {
    for (const group of levelGroups) disposeGroup(group);
    for (const group of levelGroups) world.remove(group);
    levelGroups = [];
    overlayGroups = [];
    if (desk) {
      disposeGroup(desk);
      scene.remove(desk);
      desk = null;
    }
    staticParts = {zoneFrames: new Map(), zoneSegments: new Map(), carved: []};
    if (!layout) return;

    for (const level of layout.levels) {
      const group = new THREE.Group();
      group.name = `level:${level.name}`;
      const segments = levelSegments(level);
      const carved = carveSlab(level.box, segments);
      staticParts.carved.push(carved);
      const slab = slabGeometry(level.box, carved);
      const parts = [
        meshOf(slab.top, materials.top), meshOf(merge([slab.rim, slab.sides]), materials.strata), meshOf(slab.walls, materials.wall),
        meshOf(slab.floor, materials.floor), meshOf(slab.bottom, materials.bottom),
      ].filter(Boolean);
      for (const part of parts) {
        part.userData.pickable = true;
        group.add(part);
      }
      // Mouths of workings that leave the level through its floor, downwards.
      const mouths = [];
      for (const line of layout.workings.values()) {
        if (!line.between) continue;
        for (const [node, other] of [[line.from, line.mine[line.mine.length - 1]], [line.to, line.mine[0]]]) {
          if (layout.nodeLevel.get(node) !== level.name) continue;
          const here = layout.nodes.get(node);
          if (other[2] < here[2]) mouths.push(disc(layout.toPlan(here), DIMS.half * 0.85, 0.06));
        }
      }
      const mouthMesh = meshOf(merge(mouths), materials.collar, 2);
      if (mouthMesh) group.add(mouthMesh);
      // Exits: portals on the floor at their node.
      const portals = [];
      for (const exit of state && state.model ? state.model.byKind.exit || [] : []) {
        const node = exit.attrs.node;
        if (layout.nodeLevel.get(node) !== level.name || !layout.nodes.has(node)) continue;
        const at = layout.toPlan(layout.nodes.get(node));
        portals.push(portal([at[0], 0, at[1]], facingAt(level, node), 9));
      }
      const portalMesh = meshOf(merge(portals), materials.portal);
      if (portalMesh) group.add(portalMesh);
      const overlay = new THREE.Group();
      group.add(overlay);
      overlayGroups.push(overlay);
      group.position.y = levelY(layout, level, k);
      group.userData.level = level;
      world.add(group);
      levelGroups.push(group);
    }
    // Zone frames, computed once per topology.
    for (const zone of state && state.model ? state.model.byKind.zone || [] : []) {
      const names = (Array.isArray(zone.attrs.workings) ? zone.attrs.workings : []).filter((name) => layout.workings.has(name)
        && !layout.workings.get(name).between);
      if (names.length === 0) continue;
      const segments = names.flatMap((name) => {
        const line = layout.workings.get(name);
        return line.plan.slice(1).map((b, i) => ({a: line.plan[i], b, half: DIMS.half}));
      });
      staticParts.zoneSegments.set(zone.name, segments);
      staticParts.zoneFrames.set(zone.name, {
        level: layout.workings.get(names[0]).level,
        loops: frameLoops(segments, DIMS.zoneReach),
      });
    }
    buildDesk();
    loaderCandidates = state && state.model ? candidatesOfLoaders() : new Map();
    loaderPlaces = new Map();
    loaderRun = null;
    placeLoaders();
  }

  /** Places for the loader of each zone that has horizontal workings, from the attributes only. */
  function candidatesOfLoaders() {
    const zones = (state.model.byKind.zone || []).map((zone) => ({name: zone.name,
      workings: (Array.isArray(zone.attrs.workings) ? zone.attrs.workings : []).filter((name) => layout.workings.has(name))}))
      .filter((zone) => zone.workings.some((name) => !layout.workings.get(name).between));
    const sensors = new Map();
    for (const sensor of thingsOfKind(state.model, 'sensor')) {
      if (typeof sensor.attrs.working !== 'string' || !Number.isFinite(sensor.attrs.offset_m)) continue;
      if (!sensors.has(sensor.attrs.working)) sensors.set(sensor.attrs.working, []);
      sensors.get(sensor.attrs.working).push(sensor.attrs.offset_m);
    }
    return placesForLoaders(layout, state.attributes.mine.nodes || {}, zones, sensors, LOADER_LENGTH);
  }

  /** The plan direction of the first horizontal working of a level at a node, for a portal to face along. */
  function facingAt(level, node) {
    for (const name of level.workings) {
      const line = layout.workings.get(name);
      if (line.from === node) return [line.plan[1][0] - line.plan[0][0], line.plan[1][1] - line.plan[0][1]];
      if (line.to === node) {
        const n = line.plan.length;
        return [line.plan[n - 2][0] - line.plan[n - 1][0], line.plan[n - 2][1] - line.plan[n - 1][1]];
      }
    }
    return [1, 0];
  }

  function buildDesk() {
    desk = new THREE.Group();
    const lowest = layout.levels[layout.levels.length - 1];
    const box = layout.levels.reduce((acc, level) => ({
      minX: Math.min(acc.minX, level.box.minX), maxX: Math.max(acc.maxX, level.box.maxX),
      minZ: Math.min(acc.minZ, level.box.minZ), maxZ: Math.max(acc.maxZ, level.box.maxZ),
    }), {minX: Infinity, maxX: -Infinity, minZ: Infinity, maxZ: -Infinity});
    const grow = Math.max(box.maxX - box.minX, box.maxZ - box.minZ) * 0.18;
    const shadow = meshOf(plane(box.minX - grow, box.maxX + grow, box.minZ - grow, box.maxZ + grow, 0), materials.shadow, -1);
    desk.add(shadow);
    desk.userData.lowest = lowest;
    scene.add(desk);
    placeDesk();
  }

  function placeDesk() {
    if (!desk) return;
    desk.position.y = levelY(layout, desk.userData.lowest, k) + DIMS.depth - DIMS.thickness - 0.6;
  }

  // ---- k-dependent: inter-level workings, positions ---------------------------------------

  function buildInter() {
    disposeGroup(interGroup);
    if (!layout) return;
    // The ways out between the levels carry the story of a withdrawal: they are drawn with weight. A shaft and
    // a raise are cased columns (solid collars of lining, open between them); a ramp is a solid road band.
    const casings = [];
    const decks = [];
    const sides = [];
    const steel = [];
    for (const line of layout.workings.values()) {
      if (!line.between) continue;
      const points = sceneLine(layout, line, k);
      const planLength = line.plan.slice(1).reduce((sum, p, i) => sum + Math.hypot(p[0] - line.plan[i][0], p[1] - line.plan[i][1]), 0);
      const vertical = planLength < 0.3 * line.total;
      if (vertical) {
        const raise = line.kind === 'raise';
        casings.push(casing(points, raise ? {half: 3, every: 10, collar: 2.6, wall: 0.9, post: 1}
          : {half: 4.6, every: 10, collar: 3, wall: 1.1, post: 1.3}));
      } else {
        const built = rampBand(points, 5, 2.4);
        decks.push(built.deck);
        sides.push(built.sides);
        steel.push(built.steel);
      }
    }
    const steelMesh = meshOf(merge([...casings, ...steel]), materials.steel);
    const deckMesh = meshOf(merge(decks), materials.road);
    const sideMesh = meshOf(merge(sides), materials.strata);
    if (steelMesh) interGroup.add(steelMesh);
    for (const mesh of [deckMesh, sideMesh]) {
      if (!mesh) continue;
      mesh.userData.pickable = true;
      interGroup.add(mesh);
    }
  }

  function applyK() {
    levelGroups.forEach((group) => {
      group.position.y = levelY(layout, group.userData.level, k);
      group.updateMatrixWorld(true);
    });
    placeDesk();
    placeLoaders();
    buildInter();
    buildInterOverlay();
    clearGhosts();
    buildRoutes(false);
    spritesDirty = true;
    const bounds = sceneBounds(layout, k);
    const pad = 200;
    orbit.limits.box = {minX: bounds.minX - pad, maxX: bounds.maxX + pad, minY: bounds.minY - pad, maxY: bounds.maxY + pad,
      minZ: bounds.minZ - pad, maxZ: bounds.maxZ + pad};
    orbit.limits.distMax = Math.max(bounds.maxX - bounds.minX, bounds.maxZ - bounds.minZ, 400) * 5;
    gizmo.setVertical(k);
  }

  // ---- state overlays (per level, local frame) ---------------------------------------------

  function lineOfPlan(line) {
    return line.plan;
  }

  function planCum(plan) {
    const cum = [0];
    for (let i = 1; i < plan.length; i += 1) cum.push(cum[i - 1] + Math.hypot(plan[i][0] - plan[i - 1][0], plan[i][1] - plan[i - 1][1]));
    return cum;
  }

  /** The floor of a horizontal working in pieces, leaving a gap around a barricade. */
  function floorPieces(line, gap) {
    const plan = lineOfPlan(line);
    if (!gap) return [plan];
    const cum = planCum(plan);
    const total = cum[cum.length - 1];
    const mid = total / 2;
    const half = Math.min(6, total / 4);
    return [geo.cut(plan, cum, 0, mid - half), geo.cut(plan, cum, mid + half, total)];
  }

  function frameStyle(zone) {
    if (zone.hazard === 'unknown' && zone.lastKnown === 'danger') return {material: materials.frame.lastDanger, width: 2.2, dash: [7, 4]};
    if (zone.hazard === 'danger') return {material: materials.frame.danger, width: 2.6, dash: null};
    if (zone.hazard === 'attention') return {material: materials.frame.attention, width: 1.8, dash: null};
    if (zone.hazard === 'unknown') return {material: materials.frame.unknown, width: 1.6, dash: [5, 4]};
    return {material: materials.frame.normal, width: 1.1, dash: null};
  }

  function zoneFrame(name, reachExtra) {
    const key = `${name}:${reachExtra}`;
    if (!staticParts.zoneFrames.has(key)) {
      const segments = staticParts.zoneSegments.get(name) || [];
      staticParts.zoneFrames.set(key, {level: staticParts.zoneFrames.get(name).level, loops: frameLoops(segments, DIMS.zoneReach + reachExtra)});
    }
    return staticParts.zoneFrames.get(key);
  }

  function buildOverlays() {
    for (const group of overlayGroups) disposeGroup(group);
    if (fx) {
      fx.sweeps = [];
      fx.scales = [];
    }
    if (!layout || !view) return;
    const perLevel = layout.levels.map(() => new Map());
    const levelIndex = (levelName) => layout.levels.findIndex((level) => level.name === levelName);
    const add = (levelName, material, geometry, order = 3) => {
      if (!geometry) return;
      const index = levelIndex(levelName);
      if (index < 0) return;
      const map = perLevel[index];
      if (!map.has(material)) map.set(material, {order, parts: []});
      map.get(material).parts.push(geometry);
    };
    /** A mesh of its own (a transition animates it), in the frame of its level. */
    const own = (levelName, mesh) => {
      const index = levelIndex(levelName);
      if (index < 0 || !mesh) return null;
      overlayGroups[index].add(mesh);
      return mesh;
    };
    const d = DIMS.depth;
    const sideRibbons = (plan, offset, width, y, dash) => {
      const out = [];
      for (const sign of [-1, 1]) {
        if (dash) {
          for (const piece of dashes(plan, dash[0], dash[1])) out.push(ribbon(piece, width, y, {offset: sign * offset}));
        } else {
          out.push(ribbon(plan, width, y, {offset: sign * offset}));
        }
      }
      return out;
    };
    const scopeZones = new Set(scopeDrawn.zones);

    for (const [name, working] of Object.entries(view.workings)) {
      const line = layout.workings.get(name);
      if (line.between) continue;
      const closed = working.passability === 'closed';
      const bare = working.quality === 'none' && working.hazard === 'unknown';
      let material = null;
      if (!bare && view.hasSnapshot) {
        material = {normal: materials.zone, attention: materials.attention, danger: materials.danger, unknown: materials.unknown}[working.hazard];
      }
      // A floor whose hazard has just changed: its hatch fades in (M6, M9).
      if (material && fx && fx.workings.has(name)) material = fadeMaterial(material);
      const width = DIMS.half * 2 - 1.2;
      if (material) for (const piece of floorPieces(line, closed)) add(line.level, material, ribbon(piece, width, 0.05, {period: 9}));
      if (closed) {
        const cum = planCum(line.plan);
        const mid = geo.pointAt(line.plan, cum, cum[cum.length - 1] / 2);
        if (fx && fx.closed.has(name)) {
          // A passage just closed: its barricade is set in place once (M8).
          const mesh = own(line.level, meshOf(barricade([0, 0, 0], [mid.dir[0], 0, mid.dir[1]], DIMS.half * 2 + 3, d + 6), materials.barricade, 4));
          if (mesh) {
            mesh.position.set(mid.point[0], 0, mid.point[1]);
            mesh.updateMatrix();
            fx.scales.push(mesh);
          }
        } else {
          add(line.level, materials.barricade, barricade([mid.point[0], 0, mid.point[1]], [mid.dir[0], 0, mid.dir[1]], DIMS.half * 2 + 3, d + 6), 4);
        }
      }
      const isSelected = working.thingId === view.selected;
      if (isSelected) {
        for (const piece of floorPieces(line, closed)) add(line.level, materials.glow, ribbon(piece, width, 0.12), 6);
        for (const offset of [DIMS.half + 1.3, DIMS.half + 3.3]) {
          for (const r of sideRibbons(line.plan, offset, 0.9, d + 0.12, null)) add(line.level, materials.frame.select, r, 7);
        }
      } else if (working.hazard === 'unknown' && working.lastKnown === 'danger') {
        for (const r of sideRibbons(line.plan, DIMS.half + 1.2, 1.3, d + 0.1, [6, 4])) add(line.level, materials.frame.lastDanger, r, 7);
      }
      if (working.pending) {
        for (const r of sideRibbons(line.plan, DIMS.half + 5, 1.1, d + 0.12, [5, 4])) add(line.level, materials.frame.pending, r, 7);
      }
      if (working.zone && scopeZones.has(working.zone)) add(line.level, materials.scopeWash, ribbon(line.plan, width, 0.13), 6);
    }
    for (const [name, zone] of Object.entries(view.zones)) {
      const frame = staticParts.zoneFrames.get(name);
      if (!frame) continue;
      const style = view.hasSnapshot ? frameStyle(zone) : {material: materials.frame.unknown, width: 1.4, dash: [5, 4]};
      const parts = [];
      for (const loop of frame.loops) {
        if (style.dash) for (const piece of dashes(loop, style.dash[0], style.dash[1], true)) parts.push(ribbon(piece, style.width, d + 0.08));
        else parts.push(ribbon(loop, style.width, d + 0.08, {closed: true}));
      }
      if (fx && fx.zones.has(name)) {
        // The outline of a zone whose state has just changed sweeps round it once (M6, M9).
        const mesh = own(frame.level, meshOf(merge(parts), style.material, 5));
        if (mesh) fx.sweeps.push({mesh, count: mesh.geometry.attributes.position.count, ms: MOTION[fx.zones.get(name)]});
      } else {
        for (const part of parts) add(frame.level, style.material, part, 5);
      }
      const isSelected = zone.thingId === view.selected;
      if (isSelected) {
        for (const reach of [2.6, 5]) {
          for (const loop of zoneFrame(name, reach).loops) add(frame.level, materials.frame.select, ribbon(loop, 1, d + 0.1, {closed: true}), 7);
        }
        for (const local of zone.workings) {
          const line = layout.workings.get(local);
          if (!line.between) add(line.level, materials.glow, ribbon(line.plan, DIMS.half * 2 - 1.2, 0.12), 6);
        }
      }
      if (zone.pending) {
        for (const loop of zoneFrame(name, 7.5).loops) {
          for (const piece of dashes(loop, 6, 5, true)) add(frame.level, materials.frame.pending, ribbon(piece, 1.3, d + 0.1), 7);
        }
      }
      if (scopeZones.has(name)) {
        for (const loop of zoneFrame(name, isSelected ? 9 : 3.6).loops) add(frame.level, materials.frame.scope, ribbon(loop, 3, d + 0.11, {closed: true}), 7);
      }
    }
    perLevel.forEach((map, index) => {
      for (const [material, entry] of map) {
        const mesh = meshOf(merge(entry.parts), material, entry.order);
        if (mesh) overlayGroups[index].add(mesh);
      }
    });
    buildInterOverlay();
    updateHoverOverlay();
    if (fx) applyFx(performance.now());
  }

  /** Overlays of inter-level workings, in the scene frame: hazard decks, barricades, selection. */
  function buildInterOverlay() {
    disposeGroup(interOverlay);
    if (!layout || !view) return;
    const byMaterial = new Map();
    const add = (material, geometry) => {
      if (!geometry) return;
      if (!byMaterial.has(material)) byMaterial.set(material, []);
      byMaterial.get(material).push(geometry);
    };
    for (const [name, working] of Object.entries(view.workings)) {
      const line = layout.workings.get(name);
      if (!line.between) continue;
      const points = sceneLine(layout, line, k);
      if (working.passability === 'closed') {
        const mid = geo.pointAt(points, line.cum, line.total / 2);
        add(materials.barricade, barricade(mid.point, mid.dir, 9, 6));
      }
      const selectedHere = working.thingId === view.selected;
      if (selectedHere || working.pending || (working.hazard !== 'unknown' && working.hazard !== 'normal')) {
        let material = materials.frame[working.hazard];
        if (working.pending) material = materials.frame.pending;
        if (selectedHere) material = materials.frame.select;
        add(material, tube(points.map((p) => [p[0], p[1] + 0.4, p[2]]), selectedHere ? 1.1 : 0.8, 5));
      }
    }
    for (const [material, parts] of byMaterial) {
      const mesh = meshOf(merge(parts), material, 6);
      if (mesh) interOverlay.add(mesh);
    }
  }

  let hoverMesh = null;
  function updateHoverOverlay() {
    if (hoverMesh) {
      if (hoverMesh.parent) hoverMesh.parent.remove(hoverMesh);
      hoverMesh.geometry.dispose();
      hoverMesh = null;
    }
    if (!layout || !hovered || !state || !state.model) return;
    const thing = state.model.things[hovered];
    if (!thing) return;
    const names = thing.kind === 'working' ? [thing.name] : (thing.kind === 'zone' && view.zones[thing.name] ? view.zones[thing.name].workings : []);
    const parts = [];
    let levelIndex = -1;
    for (const name of names) {
      const line = layout.workings.get(name);
      if (!line || line.between) continue;
      levelIndex = layout.levels.findIndex((level) => level.name === line.level);
      parts.push(ribbon(line.plan, DIMS.half * 2 - 1.2, 0.14));
    }
    const mesh = meshOf(merge(parts), materials.hover, 8);
    if (mesh && levelIndex >= 0) {
      overlayGroups[levelIndex].add(mesh);
      hoverMesh = mesh;
    }
  }

  // ---- transitions ------------------------------------------------------------------------

  /** A transparent copy of a floor material, for the floors whose hatch fades in during the current change. */
  function fadeMaterial(material) {
    if (!fx.fades.has(material)) {
      const clone = material.clone();
      clone.transparent = true;
      clone.opacity = 0;
      fx.fades.set(material, clone);
    }
    return fx.fades.get(material);
  }

  /** Start the transitions of one publication's changes (describe.changesBetween); a running set ends first. */
  function startFx(changes) {
    finishFx(false);
    const kinds = [...changes.zones.values(), ...changes.workings.values()];
    const total = Math.max(0, ...kinds.map((kind) => MOTION[kind]), changes.closed.size > 0 ? MOTION.closed : 0,
      changes.sensors.size > 0 ? MOTION.knowledge : 0);
    if (total === 0) return;
    fx = {...changes, start: null, total, fades: new Map(), sweeps: [], scales: []};
    root.setAttribute('data-fx', [...changes.zones.keys()].map((name) => `zone:${name}`)
      .concat([...changes.workings.keys()].map((name) => `working:${name}`), [...changes.closed].map((name) => `closed:${name}`),
        [...changes.sensors.keys()].map((name) => `sensor:${name}`)).join(' '));
    root.setAttribute('data-fx-count', String(Number(root.getAttribute('data-fx-count') || 0) + 1));
  }

  /** Eased progress (0…1) of a part of the current change that lasts `ms`. */
  function fxAt(ms, now = performance.now()) {
    if (!fx || fx.start === null) return 0;
    return easeOut(Math.min((now - fx.start) / ms, 1));
  }

  /** Write the current progress into the meshes and materials of the change. */
  function applyFx(now) {
    for (const [base, clone] of fx.fades) clone.opacity = base.opacity * fxAt(base === materials.unknown ? MOTION.knowledge : MOTION.hazard, now);
    for (const sweep of fx.sweeps) sweep.mesh.geometry.setDrawRange(0, Math.floor((sweep.count * fxAt(sweep.ms, now)) / 3) * 3);
    for (const mesh of fx.scales) {
      mesh.scale.setScalar(0.7 + 0.3 * fxAt(MOTION.closed, now));
      mesh.updateMatrix();
    }
  }

  function stepFx(now) {
    if (!fx) return false;
    if (fx.start === null) fx.start = now;
    if (reduced() || now - fx.start >= fx.total) {
      finishFx(true);
      return false;
    }
    applyFx(now);
    if (fx.sensors.size > 0) spritesDirty = true;
    return true;
  }

  /** End the change: the overlays are built again exactly as without a transition. */
  function finishFx(rebuild) {
    if (!fx) return;
    const done = fx;
    fx = null;
    for (const clone of done.fades.values()) clone.dispose();
    root.removeAttribute('data-fx');
    if (rebuild) {
      buildOverlays();
      spritesDirty = true;
      if (done.closed.size > 0) setLabels();
    }
  }

  /** The work light of the selection: glow, double ring and the dimming of the rest, at a level 0…1. */
  function applySelectLevel() {
    materials.glow.opacity = GLOW * selectLevel;
    materials.frame.select.opacity = selectLevel;
    const dim = view && view.selected ? 1 - (1 - DIM) * selectLevel : 1;
    hemi.intensity = baseLight.hemi * dim;
    key.intensity = baseLight.key * dim;
    fill.intensity = baseLight.fill * dim;
  }

  function stepSelect(now) {
    if (!selectFx) return false;
    if (selectFx.start === null) selectFx.start = now;
    const t = reduced() ? 1 : Math.min((now - selectFx.start) / MOTION.select, 1);
    selectLevel = easeOut(t);
    applySelectLevel();
    spritesDirty = true;
    if (t >= 1) selectFx = null;
    return selectFx !== null;
  }

  function applyScopeLevel() {
    materials.frame.scope.opacity = scopeLevel;
    materials.scopeWash.opacity = SCOPE_WASH * scopeLevel;
  }

  function stepScope(now) {
    if (!scopeFx) return false;
    if (scopeFx.start === null) scopeFx.start = now;
    const t = reduced() ? 1 : Math.min((now - scopeFx.start) / MOTION.scope, 1);
    scopeLevel = scopeFx.from + (scopeFx.to - scopeFx.from) * easeOut(t);
    applyScopeLevel();
    spritesDirty = true;
    if (t < 1) return true;
    const out = scopeFx.to === 0;
    scopeFx = null;
    if (out) {
      // Faded out: what was highlighted goes, and the materials are ready for the next option.
      scopeDrawn = view ? view.scope : {option: null, zones: [], workers: []};
      scopeLevel = 1;
      applyScopeLevel();
      buildOverlays();
    }
    return false;
  }

  /** A newly hovered or chosen option highlights its zones and people; none fades the highlight out. */
  function updateScope(animate) {
    const next = view.scope;
    const same = (a, b) => a.option === b.option && a.zones.join() === b.zones.join();
    const fadingOut = Boolean(scopeFx && scopeFx.to === 0);
    if (same(next, scopeDrawn) && !fadingOut) {
      scopeDrawn = next;
      return;
    }
    if (!animate) {
      scopeFx = null;
      scopeDrawn = next;
      scopeLevel = 1;
    } else if (next.zones.length > 0) {
      scopeDrawn = next;
      scopeFx = {start: null, from: 0, to: 1};
      scopeLevel = 0;
    } else if (scopeDrawn.zones.length > 0 && !fadingOut) {
      scopeFx = {start: null, from: scopeLevel, to: 0};
    } else if (!fadingOut) {
      scopeDrawn = next;
    }
    applyScopeLevel();
  }

  // ---- routes -------------------------------------------------------------------------

  function routeKey(route) {
    return `${route.worker}:${route.pieces.map((piece) => piece.working).join(',')}`;
  }

  /** The workings of a route key, after the worker. */
  const keyWorkings = (routeId) => routeId.slice(routeId.indexOf(':') + 1).split(',');

  /**
   * The published routes as tubes with arrow heads. A new route draws itself in once and the route it replaces
   * fades out (M7); a route that only got shorter because its walker went on along it is not a change of route.
   */
  function buildRoutes(animateNew) {
    const previous = new Map(routeMeshes.map((mesh) => [mesh.userData.worker, mesh]));
    const keep = new Set();
    routeMeshes = [];
    if (layout && view) {
      for (const route of view.routes) {
        const routeId = routeKey(route);
        const before = previous.get(route.worker);
        if (!before) continue;
        const was = keyWorkings(before.userData.key);
        const now = keyWorkings(routeId);
        const walking = now.length <= was.length && now.every((name, i) => name === was[was.length - now.length + i]);
        if (walking) {
          keep.add(route.worker);
          if (!drawIn.has(routeId)) drawIn.set(routeId, {start: -1});
        }
      }
    }
    // The routes that are not published any more fade out instead of vanishing.
    for (const [worker, mesh] of previous) {
      if (!animateNew || keep.has(worker) || reduced()) continue;
      routeGroup.remove(mesh);
      const material = mesh.material.clone();
      material.transparent = true;
      material.depthWrite = false;
      mesh.material = material;
      mesh.geometry.setDrawRange(0, mesh.userData.count);
      ghostGroup.add(mesh);
      ghosts.push({mesh, start: null});
    }
    disposeGroup(routeGroup);
    if (!layout || !view) return;
    const keys = new Set();
    for (const route of view.routes) {
      const runs = [];
      const arrows = [];
      for (const piece of route.pieces) {
        const line = layout.workings.get(piece.working);
        const points = geo.cut(sceneLine(layout, line, k), line.cum, piece.start, piece.end)
          .map((p) => [p[0], p[1] + (line.between ? 0.6 : 1.6), p[2]]);
        const last = runs[runs.length - 1];
        if (last && geo.dist(last[last.length - 1], points[0]) < 1) last.push(...points.slice(1));
        else runs.push(points);
      }
      const parts = [];
      for (const points of runs) {
        parts.push(tube(points, 1.9, low ? 5 : 7));
        const cum = geo.cumulative(points);
        const total = cum[cum.length - 1];
        for (let at = 40; at < total - 10; at += 55) {
          const {point, dir} = geo.pointAt(points, cum, at);
          arrows.push(arrowHead(point.map((v, i) => v + dir[i] * 4), dir, 3.6));
        }
        const end = geo.pointAt(points, cum, total);
        arrows.push(arrowHead(end.point, end.dir, 4.4));
      }
      const geometry = merge([...parts, ...arrows]);
      if (!geometry) continue;
      const mesh = meshOf(geometry, materials.route, 9);
      const routeId = routeKey(route);
      keys.add(routeId);
      mesh.userData.key = routeId;
      mesh.userData.worker = route.worker;
      mesh.userData.count = geometry.attributes.position.count;
      if (!drawIn.has(routeId)) drawIn.set(routeId, {start: animateNew && !reduced() ? null : -1});
      routeGroup.add(mesh);
      routeMeshes.push(mesh);
    }
    for (const routeId of [...drawIn.keys()]) if (!keys.has(routeId)) drawIn.delete(routeId);
    stepDrawIn(performance.now());
  }

  function stepGhosts(now) {
    for (const ghost of [...ghosts]) {
      if (ghost.start === null) ghost.start = now;
      const t = reduced() ? 1 : Math.min((now - ghost.start) / MOTION.routeOut, 1);
      ghost.mesh.material.opacity = 1 - easeOut(t);
      if (t >= 1) dropGhost(ghost);
    }
    return ghosts.length > 0;
  }

  function dropGhost(ghost) {
    ghostGroup.remove(ghost.mesh);
    ghost.mesh.geometry.dispose();
    ghost.mesh.material.dispose();
    ghosts.splice(ghosts.indexOf(ghost), 1);
  }

  function clearGhosts() {
    for (const ghost of [...ghosts]) dropGhost(ghost);
  }

  function stepDrawIn(now) {
    let active = false;
    for (const mesh of routeMeshes) {
      const entry = drawIn.get(mesh.userData.key);
      let t = 1;
      if (entry && entry.start !== -1) {
        if (entry.start === null) entry.start = now;
        t = Math.min((now - entry.start) / DRAW_IN_MS, 1);
        if (t >= 1) entry.start = -1;
        else active = true;
      }
      const count = mesh.userData.count;
      mesh.geometry.setDrawRange(0, t >= 1 ? count : Math.floor((count * t) / 3) * 3);
    }
    return active;
  }

  // ---- workers: honest motion -------------------------------------------------------------

  function motionAllowed() {
    return Boolean(state) && view.linkOk && !view.old && view.runState === 'running' && !reduced();
  }

  /** New published positions: glide between two published positions, or jump. */
  function updateMotion(previousRun) {
    const allow = motionAllowed() && previousRun === view.run;
    const now = performance.now();
    const seen = new Set();
    for (const [name, worker] of Object.entries(view.workers)) {
      if (!worker.at) continue;
      seen.add(name);
      const target = {working: worker.at, offsetM: worker.offsetM};
      const current = currentPosition(name, now);
      tweens.delete(name);
      if (current && allow && (current.working !== target.working || Math.abs(current.offsetM - target.offsetM) > 0.05)) {
        const pieces = stepBetween(layout, current, target);
        const length = pieces ? stepLength(pieces) : Infinity;
        if (pieces && length <= MAX_STEP_M && length > 0.05) tweens.set(name, {pieces, length, start: null});
      }
      drawn.set(name, target);
    }
    for (const name of [...drawn.keys()]) {
      if (!seen.has(name)) {
        drawn.delete(name);
        tweens.delete(name);
      }
    }
    spritesDirty = true;
  }

  function currentPosition(name, now) {
    const tween = tweens.get(name);
    if (tween && tween.start !== null) {
      const t = Math.min((now - tween.start) / TWEEN_MS, 1);
      return alongStep(tween.pieces, tween.length * t);
    }
    if (tween) return alongStep(tween.pieces, 0);
    return drawn.get(name) || null;
  }

  function snapMotion() {
    if (tweens.size === 0) return;
    tweens.clear();
    spritesDirty = true;
  }

  function stepTweens(now) {
    if (tweens.size === 0) return false;
    let active = false;
    for (const [name, tween] of tweens) {
      if (tween.start === null) tween.start = now;
      if (now - tween.start >= TWEEN_MS) tweens.delete(name);
      else active = true;
    }
    spritesDirty = true;
    return active;
  }

  function workerPoint(name, now = performance.now()) {
    const position = currentPosition(name, now);
    if (!position) return null;
    const at = pointOnWorking(layout, position.working, position.offsetM, k);
    return at ? at.point : null;
  }

  function groupPoint(group, now = performance.now()) {
    const points = group.members.map((name) => workerPoint(name, now)).filter(Boolean);
    if (points.length === 0) return null;
    const p = [0, 1, 2].map((i) => points.reduce((sum, q) => sum + q[i], 0) / points.length);
    return [p[0], p[1] + 6, p[2]];
  }

  // ---- sprites --------------------------------------------------------------------------

  function sensorPoint(name) {
    const thing = thingByName(state.model, name);
    const at = pointOnWorking(layout, thing.attrs.working, thing.attrs.offset_m, k);
    if (!at) return null;
    const side = [-at.dir[2], 0, at.dir[0]];
    const sl = Math.hypot(side[0], side[2]) || 1;
    const offset = DIMS.half - 1.3;
    return [at.point[0] + (side[0] / sl) * offset, at.point[1], at.point[2] + (side[2] / sl) * offset];
  }

  function exitPoint(name) {
    const node = view.exits[name].node;
    const p = toScene(layout, layout.nodes.get(node), k);
    return [p[0], p[1] + 15, p[2]];
  }

  function zonePoint(name, lift = 6) {
    const zone = view.zones[name];
    const points = zone.workings.map((local) => {
      const line = layout.workings.get(local);
      const scenePts = sceneLine(layout, line, k);
      return geo.pointAt(scenePts, line.cum, line.total / 2).point;
    });
    if (points.length === 0) return null;
    const p = [0, 1, 2].map((i) => points.reduce((sum, q) => sum + q[i], 0) / points.length);
    return [p[0], p[1] + DIMS.depth + lift, p[2]];
  }

  function workingPoint(name, closed) {
    const line = layout.workings.get(name);
    const mid = geo.pointAt(sceneLine(layout, line, k), line.cum, line.total / 2);
    return [mid.point[0], mid.point[1] + DIMS.depth + (closed ? 7 : 3), mid.point[2]];
  }

  function buildSprites() {
    spritesDirty = false;
    const list = [];
    const pinPoints = [];
    if (!layout || !view || !state || !state.model) {
      spriteGeo = writeSprites(spriteGeo, list);
      spritesFront.geometry = spriteGeo;
      spritesBehind.geometry = spriteGeo;
      return;
    }
    const now = performance.now();
    const signPosts = [];
    for (const [name, exit] of Object.entries(view.exits)) {
      const cell = ['available', 'unavailable'].includes(exit.state) ? `exit:${exit.state}` : 'exit:unknown';
      const p = exitPoint(name);
      if (exit.thingId === view.selected) list.push({position: p, cell: 'ring:selected', size: SPRITE_PX.ring + 12, key: exit.thingId, alpha: selectLevel});
      list.push({position: p, cell, size: SPRITE_PX.exit, key: exit.thingId});
    }
    for (const [name, sensor] of Object.entries(view.sensors)) {
      const base = sensorPoint(name);
      if (!base) continue;
      const p = [base[0], base[1] + 7.5, base[2]];
      signPosts.push([base, [base[0], base[1] + 6, base[2]]]);
      const cell = ['fresh', 'stale', 'lost'].includes(sensor.quality) ? `sensor:${sensor.quality}` : 'sensor:unknown';
      if (sensor.thingId === view.selected) list.push({position: p, cell: 'ring:selected', size: SPRITE_PX.sensor + 22, key: sensor.thingId, alpha: selectLevel});
      if (sensor.pending) list.push({position: p, cell: 'ring:pending', size: SPRITE_PX.sensor + 14, key: sensor.thingId});
      if (sensor.thingId === hovered) list.push({position: p, cell: 'ring:hover', size: SPRITE_PX.sensor + 12, key: sensor.thingId});
      // Data that stopped being fresh: the mark of the old state gives way to the new one (M9).
      const turned = fx && fx.sensors.has(name) ? fxAt(MOTION.knowledge, now) : 1;
      if (turned < 1) list.push({position: p, cell: `sensor:${fx.sensors.get(name)}`, size: SPRITE_PX.sensor, key: sensor.thingId, alpha: 1 - turned});
      list.push({position: p, cell, size: SPRITE_PX.sensor, key: sensor.thingId, alpha: turned});
    }
    // Signs: restriction of entry at the entrances of a zone, the state of a zone at its centre, pending commands.
    for (const [name, zone] of Object.entries(view.zones)) {
      if (zone.workings.length === 0) continue;
      if (zone.restriction === 'blocked') {
        for (const node of zoneEntrances(layout, zone.workings)) {
          const p = toScene(layout, layout.nodes.get(node), k);
          signPosts.push([[p[0], p[1], p[2]], [p[0], p[1] + 9, p[2]]]);
          list.push({position: [p[0], p[1] + 10.5, p[2]], cell: 'sign:blocked', size: SPRITE_PX.sign, key: zone.thingId});
        }
      }
      const thing = thingByName(state.model, name);
      const hazard = thing.hazard.state;
      const cell = hazard === 'unknown' && zone.lastKnown === 'danger' ? 'sign:lastDanger' : (hazard === 'normal' ? null : `sign:${hazard}`);
      if (cell && view.hasSnapshot) list.push({position: zonePoint(name, 3), cell, size: SPRITE_PX.sign + 4, key: zone.thingId});
    }
    for (const [name, working] of Object.entries(view.workings)) {
      const zone = working.zone ? view.zones[working.zone] : null;
      if (working.restriction === 'blocked' && !(zone && zone.restriction === 'blocked')) {
        const p = workingPoint(name, false);
        list.push({position: [p[0], p[1] + 4, p[2]], cell: 'sign:blocked', size: SPRITE_PX.sign, key: working.thingId});
      }
      if (working.pending) {
        const p = workingPoint(name, working.passability === 'closed');
        list.push({position: [p[0], p[1] + 8, p[2]], cell: 'sign:pending', size: SPRITE_PX.sign, key: working.thingId});
      }
    }
    // People last: on top of every other sprite.
    const scopeWorkers = new Set(scopeDrawn.workers);
    const rank = (group) => ({ok: 0, none: 2}[view.workers[group.front].egress] ?? 1);
    for (const group of [...groups].sort((a, b) => rank(a) - rank(b))) {
      const p = groupPoint(group, now);
      if (!p) continue;
      const front = view.workers[group.front];
      const thingId = front.thingId;
      const members = group.members.map((member) => view.workers[member]);
      pinPoints.push([p[0], p[1] - 6 + 0.3, p[2]], [p[0], p[1] - 1.8, p[2]]);
      if (members.some((member) => member.thingId === view.selected)) {
        list.push({position: p, cell: 'ring:selected', size: SPRITE_PX.ring + 14, key: thingId, alpha: selectLevel});
      }
      if (group.members.some((member) => scopeWorkers.has(member))) {
        list.push({position: p, cell: 'ring:scope', size: SPRITE_PX.ring + 10, key: thingId, alpha: scopeLevel});
      }
      if (members.some((member) => member.thingId === hovered)) list.push({position: p, cell: 'ring:hover', size: SPRITE_PX.ring + 4, key: thingId});
      if (members.some((member) => member.locationHazard === 'danger')) list.push({position: p, cell: 'ring:danger', size: SPRITE_PX.ring, key: thingId});
      const cell = front.egress === 'ok' ? 'worker:ok' : (front.egress === 'none' ? 'worker:none' : 'worker:unknown');
      list.push({position: p, cell, size: SPRITE_PX.worker, key: thingId, group});
    }
    spriteList = list;
    spriteGeo = writeSprites(spriteGeo, spriteList);
    spritesFront.geometry = spriteGeo;
    spritesBehind.geometry = spriteGeo;
    // Pins of the people and posts of the sensors and signs.
    const posts = signPosts.flat();
    const pinArray = new Float32Array([...pinPoints, ...posts].flat());
    pins.geometry.dispose();
    pins.geometry = new THREE.BufferGeometry();
    pins.geometry.setAttribute('position', new THREE.BufferAttribute(pinArray, 3));
  }

  // ---- loaders: the published work state of each zone ---------------------------------------

  /**
   * Once per run, the first place of each zone's list that nothing published occupies: no person, no published
   * route, no closed or pending working on the stretch it and its light cover. The loader then stays there for
   * the run: it never moves (it is a symbol of the zone's work, not a machine of the model). No free place: none.
   */
  function chooseLoaderPlaces() {
    const run = `${view.run}|${signatureOfTopology()}`;
    if (loaderRun === run || !view.hasSnapshot) return false;
    loaderRun = run;
    // A person is a marker drawn over everything and a route a tube along the floor: a short gap is enough.
    const margin = 1;
    const routes = thingsOfKind(state.model, 'worker').flatMap((worker) => {
      if (!isUnderground(worker)) return [];
      return geo.routePieces(routeOf(state.model, worker), {working: worker.values.at_working, offsetM: worker.values.offset_m}, (local) => {
        const line = layout.workings.get(local);
        return line ? {from: line.from, to: line.to, lengthM: line.lengthM, total: line.total} : null;
      });
    });
    const busy = (place) => {
      const [low0, high0] = place.span;
      const inside = (offset) => Number.isFinite(offset) && offset >= low0 - margin && offset <= high0 + margin;
      const working = view.workings[place.working];
      if (!working || working.passability === 'closed' || working.pending) return true;
      const near = (offset) => Number.isFinite(offset) && offset >= low0 - 1.5 && offset <= high0 + 1.5;
      if (Object.values(view.workers).some((worker) => worker.at === place.working && near(worker.offsetM))) return true;
      return routes.some((piece) => piece.working === place.working
        && Math.max(piece.start, piece.end) >= low0 - margin && Math.min(piece.start, piece.end) <= high0 + margin);
    };
    loaderPlaces = new Map();
    for (const [zone, candidates] of loaderCandidates) {
      const place = candidates.find((candidate) => !busy(candidate));
      if (place) loaderPlaces.set(zone, place);
    }
    placeLoaders();
    return true;
  }

  function signatureOfTopology() {
    return `${layout.levels.length}:${layout.workings.size}`;
  }

  /** The scene pose of each placed loader for the current spread of the slabs. */
  function placeLoaders() {
    const poses = new Map();
    if (layout) {
      for (const [zone, place] of loaderPlaces) {
        const at = pointOnWorking(layout, place.working, place.offsetM, k);
        if (!at) continue;
        const dir = place.facing > 0 ? at.dir : at.dir.map((v) => -v);
        poses.set(zone, {position: [at.point[0], at.point[1] + 0.06, at.point[2]], angle: Math.atan2(-dir[2], dir[0])});
      }
    }
    loaders.setPoses(poses);
    root.setAttribute('data-loaders', String(poses.size));
  }

  /** The published work state of a zone as the look of its loader: working, stopped, or unknown. */
  function workLook(zone) {
    if (!view.hasSnapshot || !zone) return 'unknown';
    return zone.workState === 'working' || zone.workState === 'stopped' ? zone.workState : 'unknown';
  }

  /** The looks follow the published work states; a change seen while watching fades the lights once (400 ms). */
  function updateLoaderLooks(animate) {
    let started = false;
    for (const name of loaderCandidates.keys()) started = loaders.setState(name, workLook(view.zones[name]), animate) || started;
    if (started) {
      loaderFade = true;
      root.setAttribute('data-loader-fx-count', String(Number(root.getAttribute('data-loader-fx-count') || 0) + 1));
    }
    if (!animate) {
      loaders.finish();
      loaderFade = false;
    }
  }

  /** Scene point of a loader's middle, a little above its roof (its label and its leader end there). */
  function loaderPoint(zone, lift = 1.2) {
    const pose = loaderPlaces.has(zone) && layout ? pointOnWorking(layout, loaderPlaces.get(zone).working, loaderPlaces.get(zone).offsetM, k) : null;
    return pose ? [pose.point[0], pose.point[1] + lift * LOADER_SCALE, pose.point[2]] : null;
  }

  /** The zone whose loader lies under a screen point, if any. */
  function overLoader(x, y) {
    if (!loaders.loaded) return null;
    let best = null;
    for (const zone of loaderPlaces.keys()) {
      const p = project(loaderPoint(zone));
      if (!p || !p.visible) continue;
      const d = Math.hypot(p.x - x, p.y - y);
      if (d < Math.max((LOADER_LENGTH / 2) * p.scale, 10) && (!best || d < best.d)) best = {d, zone};
    }
    return best ? best.zone : null;
  }

  /** The words of a loader's tooltip: the zone's published work state; the machine itself is not in the model. */
  function loaderLines(zoneName) {
    const thing = thingByName(state.model, zoneName);
    if (!thing) return [];
    const rate = thing.values.production_rate;
    const look = workLook(view.zones[zoneName]);
    const unit = thing.units && thing.units.production_rate;
    const words = look === 'unknown' ? SCENE.loaderUnknown
      : `${text.label('workState', look)}${look === 'working' && Number.isFinite(rate) ? ` · ${text.quantity(rate, unit || 't/h')}` : ''}`;
    return [SCENE.loaderTitle(thing.label, words), SCENE.loaderNote(LOADER_SCALE)];
  }

  async function loadLoaders() {
    try {
      await loaders.load(new URL('../../models/lhd.glb', import.meta.url).href);
      if (disposed) return;
      root.setAttribute('data-decor', 'loaded');
      gizmo.setDecor(true);
      placeLoaders();
      setLabels();
      invalidate();
    } catch (error) {
      // The work state of a zone is still on its tag and in the rail: the scene is complete without the machines.
      root.setAttribute('data-decor', 'absent');
      gizmo.setDecor(false);
    }
  }

  // ---- labels and the overlay -------------------------------------------------------------

  const anchors = {
    level(level) {
      const y = levelY(layout, level, k) + DIMS.depth;
      const b = level.box;
      const corners = [[b.minX, y, b.minZ], [b.maxX, y, b.minZ], [b.maxX, y, b.maxZ], [b.minX, y, b.maxZ]];
      let best = null;
      let bestX = Infinity;
      const v = new THREE.Vector3();
      for (const c of corners) {
        v.set(c[0], c[1], c[2]).project(camera);
        if (v.x < bestX && v.z < 1) {
          bestX = v.x;
          best = c;
        }
      }
      return best;
    },
    zone: (name) => zonePoint(name, 16),
    working: workingPoint,
    group: (group) => groupPoint(group),
    sensor: (name) => {
      const p = sensorPoint(name);
      return p ? [p[0], p[1] + 7.5, p[2]] : null;
    },
    exit: exitPoint,
    loader: (zone) => loaderPoint(zone, 2.6),
  };

  function setLabels() {
    if (!layout || !view || !state || !state.model) return labels.set([]);
    const arriving = new Set(fx ? [...fx.closed].map((name) => view.workings[name] && view.workings[name].thingId) : []);
    const placed = loaders.loaded ? [...loaderPlaces.keys()].map((zone) => ({zone, look: workLook(view.zones[zone]), lines: loaderLines(zone)})) : [];
    return labels.set(labelItems({model: state.model, view, layout, groups, anchors, arriving, loaders: placed}));
  }

  const v3 = new THREE.Vector3();
  function project(point) {
    if (!point) return null;
    v3.set(point[0], point[1], point[2]).project(camera);
    const visible = v3.z > -1 && v3.z < 1 && Math.abs(v3.x) < 1.2 && Math.abs(v3.y) < 1.2;
    const x = ((v3.x + 1) / 2) * width;
    const y = ((1 - v3.y) / 2) * height;
    // Pixels per metre at the point, from the distance to the camera.
    const distance = camera.position.distanceTo(new THREE.Vector3(point[0], point[1], point[2]));
    const scale = height / (2 * distance * Math.tan((camera.fov * DEG) / 2));
    return {x, y, visible, scale};
  }

  function refreshObstacles() {
    const now = performance.now();
    if (now - obstaclesAt < 400) return;
    obstaclesAt = now;
    const origin = root.getBoundingClientRect();
    fixedObstacles = [];
    // Controls over the stage: the HUD, the tabs when they lie over it, the legend chip (view/legend.js), the notice
    // of a fallback, the gizmo, the caption of old data, and in the shift desk the floating card of the selection,
    // the banners and the toasts of commands when they lie over the stage.
    const others = [...document.querySelectorAll('#stage-hud .hud__row, #stage-hud .hud__status, .hud__keys[open] .hud__keys-body, '
      + '#legend, .stage-notice:not([hidden]), #centre > .centre__bar, #banners > *, #pending > *, '
      + 'body[data-sheet="open"] #sheet, body[data-stand="open"] #stand-drawer, #panel, #rail-region')]
      // What lies beside the stage (the rail with its legend, the panel of the wide layout) is no obstacle.
      .filter((element) => overStage(element));
    // The legend counts for the camera only as its chip: the open legend is read and closed, it never moves the mine.
    const legendChip = document.querySelector('#legend [data-testid="legend-toggle"]');
    const chip = legendChip && overStage(legendChip) ? legendChip : null;
    for (const element of [...others, gizmo.element, ...(old.hidden ? [] : [oldText]), ...(chip ? [chip] : [])]) {
      const rect = element.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        fixedObstacles.push({x: rect.left - origin.left - 4, y: rect.top - origin.top - 4, w: rect.width + 8, h: rect.height + 8, key: 'fixed',
          camera: element.id !== 'legend' || !chip});
      }
    }
  }

  /** Whether an element lies over the 3D stage (a panel of a narrow screen) rather than beside it. */
  function overStage(element) {
    const r = element.getBoundingClientRect();
    const o = root.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.left < o.right - 1 && r.right > o.left + 1 && r.top < o.bottom - 1 && r.bottom > o.top + 1;
  }

  function placeLabels() {
    refreshObstacles();
    const obstacles = [...fixedObstacles];
    for (const sprite of spriteList) {
      if (!sprite.cell.startsWith('worker') && !sprite.cell.startsWith('exit') && !sprite.cell.startsWith('sign')) continue;
      const p = project(sprite.position);
      if (!p || !p.visible) continue;
      const r = sprite.size / 2 + 2;
      obstacles.push({x: p.x - r, y: p.y - r, w: 2 * r, h: 2 * r, key: sprite.group ? `worker:${sprite.group.key}` : sprite.key});
    }
    // The loaders: the labels of the scene leave them visible (their own sign excepted).
    if (loaders.loaded) {
      for (const zone of loaderPlaces.keys()) {
        const p = project(loaderPoint(zone, 1));
        if (!p || !p.visible) continue;
        const r = Math.max((LOADER_LENGTH / 2) * p.scale, 6);
        obstacles.push({x: p.x - r, y: p.y - r * 0.5, w: 2 * r, h: r, key: `${LOADER}${zone}`});
      }
    }
    // Barricades: a label never covers the barrier it explains.
    if (view) {
      for (const [name, working] of Object.entries(view.workings)) {
        if (working.passability !== 'closed') continue;
        const p = project(workingPoint(name, false));
        if (p && p.visible) obstacles.push({x: p.x - 16, y: p.y - 14, w: 32, h: 28, key: 'barrier'});
      }
    }
    const focused = labelLayer.contains(document.activeElement) ? document.activeElement : null;
    labels.place(project, width, height, obstacles, {focused, selected: view ? view.selected : null, hovered}, markPoint);
  }

  /** The scene point of an object's mark: the centre of a zone's floor, its marker, the middle of a working. */
  function markPoint(thingId) {
    if (!layout || !view || !state || !state.model) return null;
    const thing = state.model.things[thingId];
    // A zone first: the signs of its entrances carry its key too, but its tag belongs to its middle.
    if (thing && thing.kind === 'zone' && view.zones[thing.name] && view.zones[thing.name].workings.length > 0) {
      return zonePoint(thing.name, 3);
    }
    const sprite = spriteList.find((entry) => !entry.cell.startsWith('ring') && (entry.key === thingId
      || (entry.group && entry.group.members.some((member) => view.workers[member].thingId === thingId))));
    if (sprite) return sprite.position;
    if (typeof thingId === 'string' && thingId.startsWith(LOADER)) return loaders.loaded ? loaderPoint(thingId.slice(LOADER.length)) : null;
    if (thing && thing.kind === 'working' && layout.workings.has(thing.name)) {
      const line = layout.workings.get(thing.name);
      const mid = geo.pointAt(sceneLine(layout, line, k), line.cum, line.total / 2).point;
      return [mid[0], mid[1] + 0.2, mid[2]];
    }
    return null;
  }

  // ---- gizmo: north arrow, scale bar and honest captions --------------------------------------

  function createGizmo() {
    const NS = 'http://www.w3.org/2000/svg';
    const element = document.createElement('div');
    element.className = 's3__gizmo';
    element.setAttribute('data-testid', 'scene3d-gizmo');
    const compass = document.createElementNS(NS, 'svg');
    compass.setAttribute('viewBox', '-20 -20 40 40');
    compass.setAttribute('class', 's3__compass');
    compass.setAttribute('aria-hidden', 'true');
    const dial = document.createElementNS(NS, 'circle');
    dial.setAttribute('r', '17');
    dial.setAttribute('class', 's3__dial');
    const needle = document.createElementNS(NS, 'g');
    const arrow = document.createElementNS(NS, 'path');
    arrow.setAttribute('d', 'M0 -14L5 2L0 -1L-5 2Z');
    arrow.setAttribute('class', 's3__needle');
    const letter = document.createElementNS(NS, 'text');
    letter.setAttribute('class', 's3__north');
    letter.setAttribute('x', '0');
    letter.setAttribute('y', '12');
    letter.setAttribute('text-anchor', 'middle');
    letter.textContent = SCENE.north;
    needle.append(arrow, letter);
    compass.append(dial, needle);
    const scale = document.createElement('div');
    scale.className = 's3__scale';
    const barEl = document.createElement('span');
    barEl.className = 's3__bar';
    const barText = document.createElement('span');
    barText.className = 's3__bar-text';
    scale.append(barEl, barText);
    const notes = document.createElement('div');
    notes.className = 's3__notes';
    const vertical = document.createElement('span');
    const thickness = document.createElement('span');
    thickness.textContent = SCENE.notToScale;
    // The caption of the loaders, from the start (the box keeps its size while the model loads); gone if it cannot load.
    const decor = document.createElement('span');
    decor.textContent = SCENE.decorNote(LOADER_SCALE);
    notes.append(vertical, thickness, decor);
    const col = document.createElement('div');
    col.className = 's3__gizmo-text';
    col.append(scale, notes);
    element.append(compass, col);
    let lastAngle = null;
    let lastBar = null;
    return {
      element,
      /** The caption of the loaders (what they mean, how much larger they are drawn), once they are loaded. */
      setDecor(shown) {
        decor.hidden = !shown;
      },
      setVertical(factor) {
        const value = SCENE.vertical(factor);
        if (vertical.textContent !== value) vertical.textContent = value;
      },
      update() {
        if (!width) return;
        const target = orbit.state.target;
        const a = project([target.x, target.y, target.z]);
        const north = project([target.x, target.y, target.z - 100]);
        if (a && north) {
          const angle = Math.round((Math.atan2(north.x - a.x, a.y - north.y) * 180) / Math.PI);
          if (angle !== lastAngle) {
            needle.setAttribute('transform', `rotate(${angle})`);
            lastAngle = angle;
          }
        }
        const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
        const b = project([target.x + right.x * 100, target.y + right.y * 100, target.z + right.z * 100]);
        if (a && b) {
          const perMetre = Math.hypot(b.x - a.x, b.y - a.y) / 100;
          const nice = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000].find((m) => m * perMetre >= 56) || 1000;
          const px = Math.round(nice * perMetre);
          const key2 = `${nice}:${px}`;
          if (key2 !== lastBar) {
            barEl.style.width = `${px}px`;
            barText.textContent = `${text.quantity(nice, 'm')} ${SCENE.scaleAt}`;
            lastBar = key2;
          }
        }
      },
    };
  }

  // ---- frames -------------------------------------------------------------------------

  function invalidate() {
    if (disposed || lost || rafId || !width) return;
    rafId = requestAnimationFrame(frame);
    if (root.getAttribute('data-rendering') !== 'active') {
      root.setAttribute('data-rendering', 'active');
      options.onEvent('frame', {frames});
    }
  }

  function frame(now) {
    rafId = 0;
    if (disposed || lost) return;
    let active = false;
    active = orbit.step(now) || active;
    active = stepExplode(now) || active;
    active = stepTweens(now) || active;
    active = stepDrawIn(now) || active;
    active = stepFx(now) || active;
    active = stepSelect(now) || active;
    active = stepScope(now) || active;
    active = stepGhosts(now) || active;
    if (loaderFade) {
      loaderFade = loaders.step(now, reduced());
      active = loaderFade || active;
    }
    if (spritesDirty) buildSprites();
    const started = performance.now();
    renderer.render(scene, camera);
    renderMs.push(performance.now() - started);
    if (renderMs.length > 30) renderMs.shift();
    frames += 1;
    const firstWithContent = firstFrameAt === null && layout !== null && view !== null;
    if (firstWithContent) {
      firstFrameAt = performance.now();
      root.setAttribute('data-first-frame-ms', String(Math.round(firstFrameAt)));
    }
    placeLabels();
    gizmo.update();
    mirrorCamera();
    root.setAttribute('data-frames', String(frames));
    root.setAttribute('data-tweens', String(tweens.size));
    if (active) invalidate();
    // A refit waits for the stage to settle: the stage stays busy until it has run.
    else if (!settleTimer) root.setAttribute('data-rendering', 'idle');
    options.onEvent('frame', {frames});
    if (firstWithContent) options.onEvent('ready');
  }

  function mirrorCamera() {
    const {az, el, dist} = orbit.state;
    const azDeg = Math.round(((((az / DEG) % 360) + 540) % 360) - 180);
    root.setAttribute('data-camera', `${azDeg} ${Math.round(el / DEG)} ${Math.round(dist)}`);
  }

  // ---- explode ----------------------------------------------------------------------------

  function setExplode(value, animate = true) {
    const target = Math.min(Math.max(value, 0), 1);
    if (Math.abs(target - explode) < 1e-4 && !explodeTween) return;
    if (!layout || !animate || reduced()) {
      explodeTween = null;
      explode = target;
      k = verticalFactor(explode);
      if (layout) {
        applyK();
        if (overviewMode) overview(false);
      }
      root.setAttribute('data-explode', explode.toFixed(2));
      invalidate();
      return;
    }
    explodeTween = {from: explode, to: target, start: null};
    if (overviewMode) {
      const fitted = fitAll(verticalFactor(target));
      orbit.glideTo({target: fitted.target, dist: fitted.dist}, EXPLODE_MS);
    }
    invalidate();
  }

  function stepExplode(now) {
    if (!explodeTween) return false;
    if (explodeTween.start === null) explodeTween.start = now;
    const t = Math.min((now - explodeTween.start) / EXPLODE_MS, 1);
    const e = t < 0.5 ? 4 * t * t * t : 1 - ((-2 * t + 2) ** 3) / 2;
    explode = explodeTween.from + (explodeTween.to - explodeTween.from) * e;
    k = verticalFactor(explode);
    applyK();
    root.setAttribute('data-explode', explode.toFixed(2));
    if (t >= 1) {
      explodeTween = null;
      return false;
    }
    return true;
  }

  // ---- camera views -----------------------------------------------------------------------

  /** Pixels kept free around the model in the overview: room for the labels of the exits (top) and the ramps (right). */
  const PAD = {left: 14, right: 48, top: 44, bottom: 14};
  /** The label of a level stands to the left of its slab: this much room, in pixels, is part of the silhouette. */
  const LEVEL_LABEL_PX = 100;
  /** Around a focused object: it stays well inside the free part of the stage. */
  const PAD_FOCUS = {left: 120, right: 120, top: 90, bottom: 80};
  const probe = camera.clone();

  /**
   * Rectangles over the stage that the picture keeps clear of, in pixels of the stage: the HUD, the tabs,
   * the legend chip, the gizmo, a notice; the panel when it lies over the stage (compact layout) and
   * the open stand drawer.
   */
  function coverRects() {
    obstaclesAt = 0;
    refreshObstacles();
    const rects = fixedObstacles.filter((r) => r.camera).map(({x, y, w, h}) => ({x, y, w, h}));
    const chips = rects.length;
    const origin = root.getBoundingClientRect();
    const add = (element, grow = 8) => {
      const r = element.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) rects.push({x: r.left - origin.left - grow, y: r.top - origin.top - grow, w: r.width + 2 * grow, h: r.height + 2 * grow});
    };
    const drawer = document.getElementById('stand-drawer');
    if (drawer && document.body.dataset.stand === 'open') add(drawer, 12);
    // The shift desk: the right panel where it lies over the stage (the compact layout: positioned absolutely; in the
    // wide layout it is in flow and the stage itself is narrower), and the rail if it ever does.
    for (const id of ['panel', 'rail-region']) {
      const element = document.getElementById(id);
      if (element && !element.hidden && getComputedStyle(element).position === 'absolute' && overStage(element)) add(element, 4);
    }
    // The panel and the drawer cover a part of the stage; the other rectangles are chips that may give way.
    rects.forEach((r, index) => {
      r.cover = index >= chips;
    });
    return rects.filter((r) => r.x < width && r.y < height && r.x + r.w > 0 && r.y + r.h > 0);
  }

  function placeProbe(target, dist, az, el) {
    probe.fov = camera.fov;
    probe.aspect = width / Math.max(height, 1);
    probe.position.set(target.x + dist * Math.sin(az) * Math.cos(el), target.y + dist * Math.sin(el), target.z + dist * Math.cos(az) * Math.cos(el));
    probe.up.set(0, 1, 0);
    probe.lookAt(target);
    probe.near = Math.max(dist / 200, 0.5);
    probe.far = dist * 6 + 4000;
    probe.updateProjectionMatrix();
    probe.updateMatrixWorld();
  }

  /** Pixels of points seen from the probe. */
  function probePixels(vectors) {
    const v = new THREE.Vector3();
    return vectors.map((p) => {
      v.copy(p).project(probe);
      return [((v.x + 1) / 2) * width, ((1 - v.y) / 2) * height];
    });
  }

  /** The convex hull of pixel points (monotone chain), counter-clockwise on the screen. */
  function hull(points) {
    const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const half = (list) => {
      const out = [];
      for (const p of list) {
        while (out.length >= 2 && cross(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop();
        out.push(p);
      }
      out.pop();
      return out;
    };
    return [...half(sorted), ...half([...sorted].reverse())];
  }

  /** True when a convex polygon and a rectangle overlap (separating axes). */
  function overlaps(poly, r) {
    const axes = [[1, 0], [0, 1]];
    for (let i = 0; i < poly.length; i += 1) {
      const a = poly[i];
      const b = poly[(i + 1) % poly.length];
      axes.push([a[1] - b[1], b[0] - a[0]]);
    }
    const corners = [[r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h]];
    for (const [ax, ay] of axes) {
      let p0 = Infinity;
      let p1 = -Infinity;
      for (const p of poly) {
        const d = p[0] * ax + p[1] * ay;
        p0 = Math.min(p0, d);
        p1 = Math.max(p1, d);
      }
      let r0 = Infinity;
      let r1 = -Infinity;
      for (const p of corners) {
        const d = p[0] * ax + p[1] * ay;
        r0 = Math.min(r0, d);
        r1 = Math.max(r1, d);
      }
      if (p1 <= r0 || r1 <= p0) return false;
    }
    return true;
  }

  function clear(poly, rects, pad, dx = 0, dy = 0) {
    for (const [x, y] of poly) {
      const px = x + dx;
      const py = y + dy;
      if (px < pad.left || px > width - pad.right || py < pad.top || py > height - pad.bottom) return false;
    }
    const moved = dx === 0 && dy === 0 ? poly : poly.map(([x, y]) => [x + dx, y + dy]);
    return rects.every((r) => !overlaps(moved, r));
  }

  /**
   * The largest view of `points` from the azimuth and elevation that keeps their silhouette inside the stage
   * (with `pad` pixels) and clear of every control over it. The view is shrunk and shifted step by step;
   * a shift is tried in pixels first and confirmed with a real projection (perspective is not a translation).
   */
  function frameView(points, az, el, pad, rects, leftLabels = []) {
    return frameWith(points, az, el, pad, rects, leftLabels)
      // Too little room between the chips: only what covers the stage is avoided.
      || frameWith(points, az, el, pad, rects.filter((r) => r.cover), leftLabels)
      || {...orbit.fit(points.map((p) => new THREE.Vector3(p[0], p[1], p[2])), width / Math.max(height, 1), {x: 0.04, top: 0.1, bottom: 0.08},
        az, el), ok: false};
  }

  /** frameView against one set of rectangles; null when nothing fits down to a small view. */
  function frameWith(points, az, el, pad, rects, leftLabels) {
    const vectors = points.map((p) => new THREE.Vector3(p[0], p[1], p[2]));
    const labelVectors = leftLabels.map((p) => new THREE.Vector3(p[0], p[1], p[2]));
    const silhouettePx = () => hull([...probePixels(vectors), ...probePixels(labelVectors).map(([x, y]) => [x - LEVEL_LABEL_PX, y])]);
    const aspect = width / Math.max(height, 1);
    const ndc = (px, total) => (2 * px) / Math.max(total, 1);
    const base = orbit.fit([...vectors, ...labelVectors], aspect, {x: ndc((pad.left + pad.right) / 2, width), top: ndc(pad.top, height),
      bottom: ndc(pad.bottom, height)}, az, el);
    const offsets = [];
    for (let i = -6; i <= 6; i += 1) {
      for (let j = -6; j <= 6; j += 1) offsets.push([i * 0.04 * width, j * 0.035 * height]);
    }
    offsets.sort((a, b) => Math.hypot(a[0] / width, a[1] / height) - Math.hypot(b[0] / width, b[1] / height));
    for (let s = 1; s >= 0.45; s -= 0.025) {
      const dist = base.dist / s;
      placeProbe(base.target, dist, az, el);
      const poly = silhouettePx();
      const right = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 1);
      const perPixel = (2 * dist * Math.tan((camera.fov * DEG) / 2)) / Math.max(height, 1);
      for (const [dx, dy] of offsets) {
        if (!clear(poly, rects, pad, dx, dy)) continue;
        const target = base.target.clone().addScaledVector(right, -dx * perPixel).addScaledVector(up, dy * perPixel);
        placeProbe(target, dist, az, el);
        if (clear(silhouettePx(), rects, pad)) return {target, dist, ok: true};
        placeProbe(base.target, dist, az, el);
      }
    }
    return null;
  }

  function fitAll(factor = k) {
    const rects = coverRects();
    const corners = layout.levels.flatMap((level) => {
      const y = levelY(layout, level, factor) + DIMS.depth;
      const b = level.box;
      return [[b.minX, y, b.minZ], [b.maxX, y, b.minZ], [b.minX, y, b.maxZ], [b.maxX, y, b.maxZ]];
    });
    return frameView(silhouette(layout, factor), DEFAULT_VIEW.az, DEFAULT_VIEW.el, PAD, rects, corners);
  }

  function overview(animate = true) {
    if (!layout || !width) return false;
    overviewMode = true;
    focusId = null;
    const fitted = fitAll();
    const goal = {target: fitted.target, dist: fitted.dist, az: nearestAngle(orbit.state.az, DEFAULT_VIEW.az), el: DEFAULT_VIEW.el};
    if (animate) orbit.glideTo(goal);
    else orbit.set(goal);
    invalidate();
    return true;
  }

  function nearestAngle(from, to) {
    const turn = Math.PI * 2;
    return to + Math.round((from - to) / turn) * turn;
  }

  function coverKey(rects) {
    return `${width}x${height}:${rects.filter((r) => r.cover).map((r) => [r.x, r.y, r.w, r.h].map(Math.round).join(',')).join(';')}`;
  }

  /**
   * The part of the stage left free by what covers it: a panel over its bottom (a panel of the bottom), over its
   * left edge (the stand drawer, the rail) or over its right edge (the decision panel on a narrow screen).
   */
  function freeRect(rects) {
    let left = 0;
    let right = width;
    let bottom = height;
    for (const r of rects) {
      if (!r.cover) continue;
      if (r.w >= width * 0.6 && r.y > height * 0.2) bottom = Math.min(bottom, Math.max(r.y, 0));
      else if (r.h >= height * 0.6 && r.x < width * 0.25) left = Math.max(left, r.x + r.w);
      else if (r.h >= height * 0.6 && r.x + r.w > width * 0.75) right = Math.min(right, Math.max(r.x, 0));
    }
    return {x: left, y: 0, w: Math.max(right - left, 1), h: Math.max(bottom, 1)};
  }

  /** Margins of a framed object: inside the free part of the stage, smaller when that part is small. */
  function focusPad(rects) {
    const free = freeRect(rects);
    return {
      left: free.x + Math.min(PAD_FOCUS.left, free.w * 0.08),
      right: width - free.x - free.w + Math.min(PAD_FOCUS.right, free.w * 0.08),
      top: free.y + Math.min(PAD_FOCUS.top, free.h * 0.12),
      bottom: height - free.y - free.h + Math.min(PAD_FOCUS.bottom, free.h * 0.06),
    };
  }

  /** The corner of a level's slab its label stands at, for an azimuth: the leftmost on the screen. */
  function levelLabelPoint(level, az) {
    const y = levelY(layout, level, k) + DIMS.depth;
    const b = level.box;
    const corners = [[b.minX, y, b.minZ], [b.maxX, y, b.minZ], [b.maxX, y, b.maxZ], [b.minX, y, b.maxZ]];
    const along = (c) => c[0] * Math.cos(az) - c[2] * Math.sin(az);
    return corners.reduce((best, c) => (along(c) < along(best) ? c : best));
  }

  /** Pixels a horizon's width takes on the screen at a distance. */
  function horizonPx(level, dist) {
    const b = level.box;
    return (Math.max(b.maxX - b.minX, b.maxZ - b.minZ) * height) / (2 * dist * Math.tan((camera.fov * DEG) / 2));
  }

  /** The distance at which one horizon is about as wide as the stage: a framed zone is never shown closer. */
  function horizonDist(level) {
    const b = level.box;
    const span = Math.max(b.maxX - b.minX, b.maxZ - b.minZ);
    return (0.95 * span * height) / (2 * Math.tan((camera.fov * DEG) / 2) * Math.max(width, 1));
  }

  /**
   * What «показать» of a zone frames (clarity spec B, camera): the zone with its tag, the people now in it, the
   * end points of their published routes (a person without one: the nearest exit), and the level it lies on.
   */
  function zoneArea(zoneName, walkers = null) {
    const zone = view && view.zones[zoneName];
    if (!zone || zone.workings.length === 0) return null;
    const points = [];
    for (const local of zone.workings) points.push(...sceneLine(layout, layout.workings.get(local), k).map((p) => [p[0], p[1] + DIMS.depth, p[2]]));
    const tag = zonePoint(zoneName, 16);
    if (tag) points.push(tag);
    const inside = new Set(zone.workings);
    const people = [];
    const ends = [];
    const exitsNear = [];
    for (const [name, worker] of Object.entries(view.workers)) {
      if (!worker.at || !(inside.has(worker.at) || (walkers && walkers.has(name)))) continue;
      const at = workerPoint(name);
      if (!at) continue;
      people.push([at[0], at[1] + 6, at[2]]);
      const thing = thingByName(state.model, name);
      const pieces = thing && isUnderground(thing) ? geo.routePieces(routeOf(state.model, thing), {working: worker.at, offsetM: worker.offsetM},
        (local) => {
          const line = layout.workings.get(local);
          return line ? {from: line.from, to: line.to, lengthM: line.lengthM, total: line.total} : null;
        }) : [];
      const last = pieces[pieces.length - 1];
      if (last) {
        const line = layout.workings.get(last.working);
        const end = geo.pointAt(sceneLine(layout, line, k), line.cum, last.end).point;
        ends.push([end[0], end[1] + 15, end[2]]);
        // Where the route leaves the zone's level: kept in view when the whole way out does not fit.
        const leave = pieces.find((piece) => layout.workings.get(piece.working).between);
        if (leave) {
          const between = layout.workings.get(leave.working);
          exitsNear.push(geo.pointAt(sceneLine(layout, between, k), between.cum, leave.start).point);
        }
      } else {
        const exits = Object.keys(view.exits).map((exit) => exitPoint(exit));
        const nearest = exits.reduce((best, p) => (!best || geo.dist(p, at) < geo.dist(best, at) ? p : best), null);
        if (nearest) ends.push(nearest);
      }
    }
    // The zone of the open incident: the other published causes of the incident are part of what is framed.
    if (incidentZone() === zoneName) {
      for (const cause of incidentOf(state.model).values.causes || []) {
        const subject = cause && typeof cause.subject === 'string' ? cause.subject : null;
        if (!subject || subject === zoneName) continue;
        let at = null;
        if (view.sensors[subject]) at = sensorPoint(subject);
        else if (view.zones[subject] && view.zones[subject].workings.length > 0) at = zonePoint(subject, 16);
        else if (view.workings[subject]) at = workingPoint(subject, false);
        if (at) points.push(at);
      }
    }
    const frame = staticParts.zoneFrames.get(zoneName);
    const level = frame ? layout.levels.find((entry) => entry.name === frame.level) : null;
    return {points: [...points, ...people, ...ends], near: [...points, ...people, ...exitsNear], core: [...points, ...people], level};
  }

  /** The zone of the open incident, if any. */
  function incidentZone() {
    const incident = state && state.model ? incidentOf(state.model) : null;
    if (!incident || !['active', 'executing'].includes(incident.values.state) || typeof incident.values.zone !== 'string') return null;
    return view && view.zones[incident.values.zone] ? incident.values.zone : null;
  }

  /** Centre `points` at the distance `dist` in the free part of the stage, as `fitted` placed them. */
  function centred(points, fitted, dist) {
    const vectors = points.map((p) => new THREE.Vector3(p[0], p[1], p[2]));
    placeProbe(fitted.target, fitted.dist, orbit.state.az, orbit.state.el);
    const centre = probePixels(vectors).reduce((sum, p) => [sum[0] + p[0] / vectors.length, sum[1] + p[1] / vectors.length], [0, 0]);
    const right = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 1);
    const mid = vectors.reduce((sum, v) => sum.add(v), new THREE.Vector3()).multiplyScalar(1 / vectors.length);
    const perPixel = (2 * dist * Math.tan((camera.fov * DEG) / 2)) / Math.max(height, 1);
    const target = mid.addScaledVector(right, -(centre[0] - width / 2) * perPixel).addScaledVector(up, (centre[1] - height / 2) * perPixel);
    return {target, dist};
  }

  function fitPoints(points, minDist, rects = coverRects(), leftLabels = []) {
    const fitted = frameView(points, orbit.state.az, orbit.state.el, focusPad(rects), rects, leftLabels);
    // Not closer than minDist: the object is then centred in the free part of the stage, as framed above.
    return fitted.dist >= minDist ? fitted : {...centred(points, fitted, minDist), ok: fitted.ok};
  }

  /**
   * The view that frames a zone by the rule of «показать». When the whole way out does not fit the free part of
   * the stage at a readable scale (the panel over a small stage), the zone, its people and where their
   * routes leave its level are framed instead: never the whole mine shrunk into a strip.
   */
  function zoneGoal(zoneName, rects = coverRects(), walkers = null) {
    const area = zoneArea(zoneName, walkers);
    if (!area) return null;
    const label = area.level ? [levelLabelPoint(area.level, orbit.state.az)] : [];
    const minDist = area.level ? horizonDist(area.level) : 200;
    // The horizon must stay readable: as wide on the screen as about a third of the free stage, 300 px at least.
    const free = freeRect(rects);
    const readable = (dist) => !area.level || horizonPx(area.level, dist) >= Math.max(300, 0.3 * free.w);
    let fitted = null;
    const tried = [];
    for (const [name, points] of [['all', area.points], ['near', area.near], ['core', area.core]]) {
      fitted = fitPoints(points, minDist, rects, label);
      tried.push(`${name}:${fitted.ok === false ? 'no' : 'ok'}:${Math.round(fitted.dist)}`);
      if (fitted.ok !== false && readable(fitted.dist)) break;
    }
    root.setAttribute('data-framing', `${zoneName} min:${Math.round(minDist)} ${tried.join(' ')}`);
    return fitted;
  }

  /** The view that frames an object (full thingId) or a level (local name); null when it is not drawn. */
  function goalOf(id, rects = coverRects()) {
    const model = state.model;
    const level = layout.levels.find((entry) => entry.name === id || (entry.thingId && entry.thingId === id));
    if (level) {
      const y = levelY(layout, level, k);
      const b = level.box;
      return fitPoints([[b.minX, y + DIMS.depth, b.minZ], [b.maxX, y + DIMS.depth, b.maxZ], [b.minX, y - DIMS.thickness, b.maxZ],
        [b.maxX, y + DIMS.depth, b.minZ]], 120, rects);
    }
    if (typeof id === 'string' && id.startsWith(LOADER)) {
      // A zone's loader, close up: the machine and the light ahead of it fill the middle of the stage.
      const p = loaderPoint(id.slice(LOADER.length), 1);
      if (!p) return null;
      // About three machine lengths across the free part of the stage.
      const free = freeRect(rects);
      return centreIn(p, (3 * LOADER_LENGTH * height) / (2 * Math.tan((camera.fov * DEG) / 2) * Math.max(free.w, 1)), rects);
    }
    const thing = model.things[id] || thingByName(model, id);
    if (!thing) return null;
    if (thing.kind === 'zone') return zoneGoal(thing.name, rects);
    if (thing.kind === 'level') return goalOf(thing.name, rects);
    if (thing.kind === 'incident') {
      const zone = typeof thing.values.zone === 'string' ? thingByName(model, thing.values.zone) : null;
      return zone ? zoneGoal(zone.name, rects) : null;
    }
    let points = [];
    let minDist = 160;
    if (thing.kind === 'working' && layout.workings.has(thing.name)) {
      points = sceneLine(layout, layout.workings.get(thing.name), k);
      minDist = 150;
    } else if (thing.kind === 'worker') {
      const p = workerPoint(thing.name);
      if (p) points = [p];
    } else if (thing.kind === 'sensor' && view.sensors[thing.name]) {
      const p = sensorPoint(thing.name);
      if (p) points = [p];
      minDist = 130;
    } else if (thing.kind === 'exit' && view.exits[thing.name]) {
      points = [exitPoint(thing.name)];
    }
    if (points.length === 0) return null;
    // One mark (a person, a sensor, an exit): in the middle of the free stage at the smallest distance of its kind.
    if (points.length === 1) return centreIn(points[0], minDist, rects);
    return fitPoints(points, minDist, rects);
  }

  /** A view at `dist` that puts a scene point in the middle of the part of the stage no panel covers. */
  function centreIn(point, dist, rects) {
    const free = freeRect(rects);
    const at = new THREE.Vector3(point[0], point[1], point[2]);
    placeProbe(at, dist, orbit.state.az, orbit.state.el);
    const right = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 1);
    const perPixel = (2 * dist * Math.tan((camera.fov * DEG) / 2)) / Math.max(height, 1);
    const dx = free.x + free.w / 2 - width / 2;
    const dy = free.y + free.h / 2 - height / 2;
    return {target: at.addScaledVector(right, -dx * perPixel).addScaledVector(up, dy * perPixel), dist, ok: true};
  }

  /** Glide to an object (full thingId) or a level (local name); the azimuth is kept. */
  function focus(id) {
    if (!layout || !state || !state.model || !width) {
      pendingFocus = id;
      return true;
    }
    const goal = goalOf(id);
    if (!goal) return false;
    overviewMode = false;
    focusId = id;
    orbit.glideTo({target: goal.target, dist: goal.dist});
    invalidate();
    return true;
  }

  // ---- refits after a change of the stage's size or of the panels over it --------------------

  /** Mark the stage busy until a pending refit has run (tests and the HUD wait for 'idle'). */
  function markBusy() {
    if (root.getAttribute('data-rendering') !== 'active') {
      root.setAttribute('data-rendering', 'active');
      options.onEvent('frame', {frames});
    }
  }

  function idleIfQuiet() {
    if (rafId || settleTimer) return;
    root.setAttribute('data-rendering', 'idle');
    options.onEvent('frame', {frames});
  }

  /**
   * The size of the stage or a panel over it changed: refit once the change has settled (the situation strip
   * grows first, M2). A refit is instant; a panel causes one only when the picture would hide the incident area
   * or leave the stage mostly empty. The legend is not watched: opening it never moves the mine.
   */
  function settleSoon(why) {
    settleWhy = settleWhy === 'size' || why === 'size' ? 'size' : 'panel';
    clearTimeout(settleTimer);
    settleTimer = setTimeout(settle, SETTLE_MS);
    markBusy();
  }

  function settle() {
    settleTimer = 0;
    const why = settleWhy;
    settleWhy = null;
    if (disposed || !layout || !width || !view) {
      idleIfQuiet();
      return;
    }
    if (explodeTween) {
      settleSoon(why);
      return;
    }
    const rects = coverRects();
    const cover = coverKey(rects);
    if (why !== 'size' && cover === lastPanelCover) {
      idleIfQuiet();
      return;
    }
    lastPanelCover = cover;
    const goal = refitGoal(rects, why === 'size');
    if (!goal) {
      // The picture stays; its labels are placed once more clear of what now lies over the stage.
      obstaclesAt = 0;
      invalidate();
      return;
    }
    if (orbit.gliding) orbit.retarget(goal);
    else orbit.set(goal);
    root.setAttribute('data-refits', String(Number(root.getAttribute('data-refits') || 0) + 1));
    invalidate();
  }

  function refitGoal(rects, sized) {
    const hides = incidentHidden(rects);
    const zone = incidentZone();
    if (overviewMode) {
      // The overview is the whole mine in the stage: it follows a new size of the stage. A panel over the stage
      // that hides the incident area turns it into the framing of the incident in the part left free.
      if (hides && zone && !sized) {
        const goal = zoneGoal(zone, rects);
        if (goal) {
          overviewMode = false;
          focusId = thingByName(state.model, zone).thingId;
          return goal;
        }
      }
      if (!sized && !hides && !mostlyEmpty(rects)) return null;
      const fitted = fitAll();
      return fitted.ok || sized ? {target: fitted.target, dist: fitted.dist} : null;
    }
    if (!hides && !mostlyEmpty(rects)) return null;
    const id = focusId || (zone ? thingByName(state.model, zone).thingId : null);
    const goal = id ? goalOf(id, rects) : null;
    if (goal) focusId = id;
    return goal;
  }

  /** Project with the camera where it is going (the end of a glide), in pixels of the stage. */
  function projectGoal(points) {
    const goal = orbit.goal;
    placeProbe(goal.target, goal.dist, goal.az, goal.el);
    const v = new THREE.Vector3();
    return points.map((p) => {
      v.set(p[0], p[1], p[2]).project(probe);
      return {x: ((v.x + 1) / 2) * width, y: ((1 - v.y) / 2) * height, front: v.z > -1 && v.z < 1};
    });
  }

  /** True when the zone of the open incident or a person in it would be out of the free stage or under a panel. */
  function incidentHidden(rects) {
    const zone = incidentZone();
    const area = zone ? zoneArea(zone) : null;
    if (!area) return false;
    const free = freeRect(rects);
    const covers = rects.filter((r) => r.cover);
    return projectGoal(area.core).some((p) => !p.front || p.x < free.x || p.x > free.x + free.w || p.y < free.y || p.y > free.y + free.h
      || covers.some((r) => p.x > r.x && p.x < r.x + r.w && p.y > r.y && p.y < r.y + r.h));
  }

  /** True when the model would take less than a quarter of the free stage. */
  function mostlyEmpty(rects) {
    const free = freeRect(rects);
    const points = projectGoal(silhouette(layout, k)).filter((p) => p.front);
    if (points.length === 0) return true;
    const x0 = Math.max(Math.min(...points.map((p) => p.x)), free.x);
    const x1 = Math.min(Math.max(...points.map((p) => p.x)), free.x + free.w);
    const y0 = Math.max(Math.min(...points.map((p) => p.y)), free.y);
    const y1 = Math.min(Math.max(...points.map((p) => p.y)), free.y + free.h);
    return Math.max(x1 - x0, 0) * Math.max(y1 - y0, 0) < 0.25 * free.w * free.h;
  }

  function focusLevelStep(direction) {
    if (!layout) return;
    const y = orbit.state.target.y;
    const ordered = layout.levels.map((level) => ({level, y: levelY(layout, level, k)}));
    let index = ordered.reduce((best, entry, i) => (Math.abs(entry.y - y) < Math.abs(ordered[best].y - y) ? i : best), 0);
    index = Math.min(Math.max(index + direction, 0), ordered.length - 1);
    const level = ordered[index].level;
    focus(level.name || level.thingId);
  }

  // ---- picking -------------------------------------------------------------------------

  const raycaster = new THREE.Raycaster();

  /** The nearest stone along the ray through a screen point: distance from the camera, or Infinity. */
  function stoneDistance(x, y) {
    raycaster.setFromCamera(new THREE.Vector2((x / width) * 2 - 1, 1 - (y / height) * 2), camera);
    const targets = [];
    for (const group of [...levelGroups, interGroup]) {
      group.traverse((object) => {
        if (object.isMesh && object.userData.pickable) targets.push(object);
      });
    }
    const hits = raycaster.intersectObjects(targets, false);
    return hits.length > 0 ? hits[0] : null;
  }

  function segmentDistance(p, a, b) {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const l2 = dx * dx + dy * dy;
    let t = l2 > 0 ? ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2 : 0;
    t = Math.min(Math.max(t, 0), 1);
    return {d: Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy), t};
  }

  /** The object under a screen point: a marker first, then a working, then a zone; decor separately. */
  function pick(x, y) {
    if (!layout || !view) return null;
    const pointerAt = {x, y};
    let best = null;
    for (const sprite of spriteList) {
      if (sprite.cell.startsWith('ring')) continue;
      const p = project(sprite.position);
      if (!p || !p.visible) continue;
      const d = Math.hypot(p.x - x, p.y - y);
      const r = sprite.size / 2 + 3;
      if (d <= r && (!best || d < best.d)) {
        let thingId = sprite.key;
        if (sprite.group) {
          const members = sprite.group.members.map((member) => view.workers[member].thingId);
          const index = members.indexOf(view.selected);
          // A second click on a group cycles through its people.
          thingId = index >= 0 ? members[(index + 1) % members.length] : view.workers[sprite.group.front].thingId;
        }
        best = {d, thingId};
      }
    }
    if (best) return best.thingId;
    const machine = overLoader(x, y);
    if (machine) return `${LOADER}${machine}`;
    const hit = stoneDistance(x, y);
    const stoneAt = hit ? hit.distance : Infinity;
    // The floor of a channel lies under the top face: stone in front of it by up to the channel's width,
    // seen at the camera's elevation, still lets the channel be picked.
    const tolerance = DIMS.half * 1.6 + DIMS.depth / Math.tan(Math.max(orbit.state.el, 0.12)) + 8;
    let chosen = null;
    for (const [name] of Object.entries(view.workings)) {
      const line = layout.workings.get(name);
      const points = sceneLine(layout, line, k);
      for (let i = 1; i < points.length; i += 1) {
        const a3 = points[i - 1];
        const b3 = points[i];
        const pa = project(a3);
        const pb = project(b3);
        if (!pa || !pb) continue;
        const {d, t} = segmentDistance(pointerAt, pa, pb);
        const scale = (pa.scale + pb.scale) / 2;
        const reach = Math.max(DIMS.half * scale + 2, 6);
        if (d > reach) continue;
        const point = new THREE.Vector3(...a3.map((v, j) => v + (b3[j] - v) * t));
        const distance = camera.position.distanceTo(point);
        if (stoneAt + tolerance < distance) continue;
        if (!chosen || d < chosen.d) chosen = {d, thingId: view.workings[name].thingId};
      }
    }
    if (chosen) return chosen.thingId;
    if (hit) {
      // Inside the frame of a zone on the top face of its slab.
      const group = levelGroups.find((entry) => entry.getObjectById(hit.object.id));
      if (group) {
        const local = [hit.point.x, hit.point.z];
        for (const [name, zone] of Object.entries(view.zones)) {
          const frame = staticParts.zoneFrames.get(name);
          if (!frame || frame.level !== group.userData.level.name) continue;
          if (frame.loops.some((loop) => insideLoop(local, loop))) return zone.thingId;
        }
      }
    }
    return null;
  }

  function insideLoop(point, loop) {
    let hit = false;
    for (let i = 0, j = loop.length - 1; i < loop.length; j = i, i += 1) {
      const [xi, zi] = loop[i];
      const [xj, zj] = loop[j];
      if ((zi > point[1]) !== (zj > point[1]) && point[0] < ((xj - xi) * (point[1] - zi)) / (zj - zi) + xi) hit = !hit;
    }
    return hit;
  }

  /** A loader stands for its zone: picking it selects the zone. */
  function selectable(thingId) {
    if (typeof thingId !== 'string' || !thingId.startsWith(LOADER)) return thingId;
    const zone = state && state.model ? thingByName(state.model, thingId.slice(LOADER.length)) : null;
    return zone ? zone.thingId : null;
  }

  // ---- input ----------------------------------------------------------------------------

  let dragging = null;
  const local = (event) => {
    const rect = canvas.getBoundingClientRect();
    return {x: event.clientX - rect.left, y: event.clientY - rect.top};
  };

  canvas.addEventListener('contextmenu', (event) => event.preventDefault());
  canvas.addEventListener('pointerdown', (event) => {
    canvas.focus({preventScroll: true});
    const at = local(event);
    dragging = {
      id: event.pointerId, x: at.x, y: at.y, startX: at.x, startY: at.y, moved: false, t: performance.now(),
      kind: event.button === 2 || event.shiftKey ? 'pan' : 'rotate',
    };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', (event) => {
    const at = local(event);
    pointer = at;
    if (dragging && dragging.id === event.pointerId) {
      const dx = at.x - dragging.x;
      const dy = at.y - dragging.y;
      if (!dragging.moved && Math.hypot(at.x - dragging.startX, at.y - dragging.startY) < 4) return;
      dragging.moved = true;
      const now = performance.now();
      orbit.drag(dragging.kind, dx, dy, height, now - dragging.t);
      dragging.x = at.x;
      dragging.y = at.y;
      dragging.t = now;
      userMoved();
      hideTip();
      invalidate();
      return;
    }
    updateHover(at.x, at.y);
  });
  const endDrag = (event) => {
    if (!dragging || dragging.id !== event.pointerId) return;
    const wasMoved = dragging.moved;
    dragging = null;
    orbit.release();
    if (!wasMoved && event.type === 'pointerup') {
      const at = local(event);
      ctx.select(selectable(pick(at.x, at.y)));
    }
    invalidate();
  };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('pointerleave', () => {
    pointer = null;
    if (hovered) {
      hovered = null;
      spritesDirty = true;
      updateHoverOverlay();
      invalidate();
    }
    hideTip();
  });
  canvas.addEventListener('dblclick', (event) => {
    const at = local(event);
    const thingId = selectable(pick(at.x, at.y));
    if (thingId) {
      ctx.select(thingId);
      focus(thingId);
    }
  });
  canvas.addEventListener('wheel', (event) => {
    event.preventDefault();
    const factor = Math.exp(Math.max(Math.min(event.deltaY, 200), -200) * 0.0015);
    orbit.zoom(factor, false);
    userMoved();
    invalidate();
  }, {passive: false});
  canvas.addEventListener('keydown', (event) => {
    const step = 15 * DEG;
    const panBy = orbit.state.dist * 0.12;
    let handled = true;
    switch (event.key) {
      case 'ArrowLeft': if (event.shiftKey) orbit.pan(-panBy, 0); else orbit.rotate(step, 0); break;
      case 'ArrowRight': if (event.shiftKey) orbit.pan(panBy, 0); else orbit.rotate(-step, 0); break;
      case 'ArrowUp': if (event.shiftKey) orbit.pan(0, panBy); else orbit.rotate(0, 6 * DEG); break;
      case 'ArrowDown': if (event.shiftKey) orbit.pan(0, -panBy); else orbit.rotate(0, -6 * DEG); break;
      case '+': case '=': orbit.zoom(0.8, true); break;
      case '-': case '_': orbit.zoom(1.25, true); break;
      case 'Home': overview(true); break;
      case 'PageUp': focusLevelStep(-1); break;
      case 'PageDown': focusLevelStep(1); break;
      case 'Escape': ctx.select(null); break;
      default:
        if (event.code === 'KeyE' && !event.ctrlKey && !event.metaKey && !event.altKey) options.onEvent('explode-key');
        else handled = false;
    }
    if (handled) {
      event.preventDefault();
      if (event.key !== 'Escape' && event.code !== 'KeyE') lastTouch = performance.now();
      if (event.key !== 'Home' && event.key !== 'Escape' && event.code !== 'KeyE' && event.key !== 'PageUp' && event.key !== 'PageDown') userMoved();
      invalidate();
    }
  });

  /** The user moved the camera: it frames nothing in particular now, and an incident does not take it away soon. */
  function userMoved() {
    overviewMode = false;
    focusId = null;
    lastTouch = performance.now();
  }

  function updateHover(x, y) {
    const next = pick(x, y);
    const machine = typeof next === 'string' && next.startsWith(LOADER) ? next.slice(LOADER.length) : null;
    if (next !== hovered) {
      hovered = next;
      spritesDirty = true;
      updateHoverOverlay();
      invalidate();
    }
    if (!next) {
      hideTip();
      canvas.style.cursor = '';
      return;
    }
    canvas.style.cursor = 'pointer';
    const lines = machine ? loaderLines(machine) : tooltipLines(labels.items, next);
    if (lines.length === 0) {
      hideTip();
      return;
    }
    tip.replaceChildren(...lines.map((line, index) => {
      const span = document.createElement('span');
      span.className = index === 0 ? 's3__tip-line is-bold' : 's3__tip-line';
      span.textContent = line;
      return span;
    }));
    tip.hidden = false;
    const tx = Math.min(x + 16, width - tip.offsetWidth - 4);
    const ty = Math.min(y + 18, height - tip.offsetHeight - 4);
    tip.style.transform = `translate(${Math.max(tx, 4)}px, ${Math.max(ty, 4)}px)`;
  }

  function hideTip() {
    if (!tip.hidden) tip.hidden = true;
  }

  // ---- size --------------------------------------------------------------------------

  function resize() {
    const rect = host.getBoundingClientRect();
    const w = Math.round(rect.width);
    const hh = Math.round(rect.height);
    if (w === width && hh === height) return;
    width = w;
    height = hh;
    if (width < 10 || height < 10) {
      width = 0;
      return;
    }
    if (low) {
      // Software rendering is bound by the pixels it fills: the light quality draws at most about
      // LOW_PIXELS and lets the browser scale the picture up.
      const ratio = Math.min(1, Math.sqrt(LOW_PIXELS / (width * height)));
      renderer.setPixelRatio(ratio);
      spriteMat.front.uniforms.uPixelRatio.value = ratio;
      spriteMat.behind.uniforms.uPixelRatio.value = ratio;
    }
    renderer.setSize(width, height, false);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    obstaclesAt = 0;
    if (pendingFocus && layout) {
      const id = pendingFocus;
      pendingFocus = null;
      focus(id);
    }
    // The picture is refitted once the size has settled (the situation strip grows over SETTLE_MS, M2).
    if (layout) settleSoon('size');
    invalidate();
  }
  const resizeObserver = new ResizeObserver((entries) => {
    if (entries.some((entry) => entry.target === host)) resize();
    if (entries.some((entry) => entry.target !== host)) settleSoon('panel');
  });
  resizeObserver.observe(host);
  // Not the legend: opening it never moves the mine.
  for (const id of ['stage-hud', 'panel', 'rail-region', 'pending']) {
    const element = document.getElementById(id);
    if (element) resizeObserver.observe(element);
  }
  // Panels that unfold over the stage change no size of the stage: the body names them.
  const coverObserver = new MutationObserver(() => settleSoon('panel'));
  coverObserver.observe(document.body, {attributes: true, attributeFilter: ['data-stand', 'data-panel', 'data-sheet', 'data-rail', 'data-situation']});

  // ---- context loss ----------------------------------------------------------------------

  const onLost = (event) => {
    event.preventDefault();
    lost = true;
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
    if (!disposed) options.onEvent('context-lost');
  };
  const onRestored = () => {
    if (!disposed) options.onEvent('context-restored');
  };
  canvas.addEventListener('webglcontextlost', onLost);
  canvas.addEventListener('webglcontextrestored', onRestored);

  // ---- updates from the store ------------------------------------------------------------

  function update(next) {
    if (disposed) return;
    const previousRun = view ? view.run : null;
    const previousLinkOk = view ? view.linkOk && !view.old : true;
    state = next;
    // Attributes of another topology than the model's: no picture of a mine the model does not use (as the scheme).
    const link = next.link || {};
    const mismatch = link.snapshot === 'invalid' && link.invalid && link.invalid.code === 'topology_mismatch';
    if (!next.attributes || !next.model || mismatch) {
      layout = null;
      attributesRef = null;
      buildStatic();
      view = null;
      signature = '';
      loaderPlaces = new Map();
      loaderRun = null;
      placeLoaders();
      setLabels();
      root.removeAttribute('data-levels');
      root.removeAttribute('data-workings');
      invalidate();
      return;
    }
    let rebuilt = false;
    if (next.attributes !== attributesRef) {
      attributesRef = next.attributes;
      layout = buildLayout(next.model, next.attributes.mine);
      drawn.clear();
      tweens.clear();
      buildStatic();
      rebuilt = true;
      root.setAttribute('data-levels', String(layout ? layout.levels.length : 0));
      root.setAttribute('data-workings', String(layout ? layout.workings.size : 0));
      if (layout) {
        applyK();
        if (overviewMode || !width) overview(false);
        if (!root.hasAttribute('data-decor')) {
          root.setAttribute('data-decor', 'loading');
          loadLoaders();
        }
      }
    }
    if (!layout) return;
    const described = describe(next, layout);
    const linkNowOk = described.view.linkOk && !described.view.old;
    if (!linkNowOk && previousLinkOk) snapMotion();
    if (!rebuilt && described.signature === signature) {
      if (!linkNowOk && tweens.size > 0) snapMotion();
      // The age of a last known state («7 мин назад») follows the model time; a label that changed is placed anew.
      if (Object.values(view.zones).some((zone) => zone.lastKnown) || Object.values(view.workings).some((working) => working.lastKnown)) {
        if (setLabels()) invalidate();
      }
      // A situation may change with nothing else drawn differently (an option starts): the camera still follows it.
      choreograph(view.hasSnapshot);
      return;
    }
    const before = view;
    view = described.view;
    signature = described.signature;
    // A transition explains a change of a picture already seen: never on the first picture, a new run or a new
    // topology, never under reduced motion, and not while (or right after) the data were old or the link failed.
    const settled = Boolean(before) && before.hasSnapshot && !rebuilt && before.run === view.run;
    const calm = (v) => v.linkOk && !v.old;
    const animate = settled && calm(before) && calm(view) && !reduced();
    groups = groupWorkers(view.workers);
    updateMotion(previousRun);
    if (!linkNowOk) snapMotion();
    if (!animate) {
      finishFx(false);
      clearGhosts();
    }
    const changes = animate ? changesBetween(before, view) : null;
    if (changes && (changes.zones.size || changes.workings.size || changes.closed.size || changes.sensors.size)) startFx(changes);
    // The work light fades in on a new selection; it goes at once.
    const selectedNow = view.selected;
    if (selectedNow !== (before ? before.selected : null)) {
      selectFx = animate && selectedNow ? {start: null} : null;
      selectLevel = selectFx ? 0 : 1;
    } else if (!animate && selectFx) {
      selectFx = null;
      selectLevel = 1;
    }
    applySelectLevel();
    updateScope(Boolean(before) && calm(view) && !reduced());
    buildOverlays();
    buildRoutes(animate);
    // The loaders take their places once per run and then show the published work state of their zones.
    chooseLoaderPlaces();
    updateLoaderLooks(animate);
    setLabels();
    old.hidden = !view.old;
    root.toggleAttribute('data-old', view.old);
    // The moment of the data is named by the line above the stage (view/overlay.js); the caption says what it means here.
    oldText.textContent = view.old ? SCENE.oldData : '';
    root.setAttribute('data-workers-drawn', String(Object.values(view.workers).filter((worker) => worker.at).length));
    root.setAttribute('data-routes', String(view.routes.length));
    root.setAttribute('data-selected', view.selected || '');
    canvas.setAttribute('aria-label', summary());
    root.setAttribute('data-scope', view.scope.zones.join(' '));
    if (pendingFocus && width) {
      const id = pendingFocus;
      pendingFocus = null;
      focus(id);
    }
    choreograph(Boolean(before) && before.hasSnapshot && !rebuilt);
    spritesDirty = true;
    invalidate();
  }

  /** The zones a running withdrawal is about: the published scope of the option being executed, else the zones withdrawing. */
  function walkZones() {
    const option = thingsOfKind(state.model, 'option').find((entry) => entry.values.state === 'executing');
    const scope = option && Array.isArray(option.values.scope) ? option.values.scope.filter((name) => view.zones[name]) : [];
    if (scope.length > 0) return [...scope].sort();
    return Object.keys(view.zones).filter((name) => view.zones[name].withdrawal === 'in_progress').sort();
  }

  /** The situation of the shift (situation.js) with what it is about: the camera follows a change of it once. */
  function situationNow() {
    const situation = situationOf(state);
    const incident = incidentOf(state.model);
    const opened = incident ? (Number.isFinite(incident.values.opened_at_tick) ? incident.values.opened_at_tick
      : JSON.stringify(incident.values.causes || null)) : '';
    const about = incident && typeof incident.values.zone === 'string' ? `${incident.values.zone}:${opened}` : '';
    const subject = {decision: about, executing: `${walkZones().join(',')}|${about}`, done: about}[situation] || '';
    return {situation, key: `${view.run}|${situation}|${subject}`, incident: about ? `${view.run}:${about}` : null};
  }

  /**
   * Camera choreography of the situations (variant 2): an incident waiting for a decision frames its zone, its
   * people and their exits; an executed withdrawal frames the walk (the zone, the people walking out, the ends of
   * their published routes); a closed incident and the norm return to the overview. Once per change of the
   * situation, only while the page is watching (never on the first picture, a new run or old data) and only when the
   * user has left the camera alone for HANDS_OFF_MS. Instant under reduced motion (the orbit glides at once).
   */
  function choreograph(watching) {
    const now = situationNow();
    if (now.key === situationKey) return;
    const sameRun = situationKey !== null && situationKey.startsWith(`${view.run}|`);
    situationKey = now.key;
    if (!watching || !sameRun) return;
    const log = (what) => {
      root.setAttribute('data-choreo', `${now.situation}:${what}`);
      if (!what.startsWith('skipped')) root.setAttribute('data-choreo-count', String(Number(root.getAttribute('data-choreo-count') || 0) + 1));
    };
    if (view.old || !view.linkOk) return log('skipped-old');
    if (performance.now() - lastTouch < HANDS_OFF_MS) return log('skipped-touched');
    if (now.situation === 'decision') {
      const zone = incidentZone() ? thingByName(state.model, incidentZone()) : null;
      if (zone && focus(zone.thingId)) {
        root.setAttribute('data-auto-framed', now.incident);
        log(zone.name);
      }
    } else if (now.situation === 'executing') {
      const zones = walkZones();
      const walkers = new Set(Object.keys(view.workers).filter((name) => view.workers[name].status === 'moving_to_exit'));
      const goal = zones.length === 1 && width ? zoneGoal(zones[0], coverRects(), walkers) : null;
      if (goal) {
        overviewMode = false;
        focusId = thingByName(state.model, zones[0]).thingId;
        orbit.glideTo({target: goal.target, dist: goal.dist});
        invalidate();
        log(`walk:${zones[0]}`);
      } else if (overview(true)) {
        log('overview');
      }
    } else if ((now.situation === 'done' || now.situation === 'norm') && overview(true)) {
      log('overview');
    }
  }

  function summary() {
    const shift = state.model.shift ? state.model.shift.values : {};
    const parts = [SCENE.levelsCount(layout.levels.length), SCENE.workingsCount(layout.workings.size)];
    if (view.hasSnapshot) {
      parts.push(SCENE.workersShown(Object.values(view.workers).filter((worker) => worker.at).length));
      if (Number.isFinite(shift.workers_in_danger)) parts.push(SCENE.inDanger(shift.workers_in_danger));
      if (Number.isFinite(shift.workers_no_route)) parts.push(SCENE.noRoute(shift.workers_no_route));
    } else {
      parts.push(SCENE.noState);
    }
    return SCENE.canvas(parts);
  }

  // ---- lamps of the high quality ------------------------------------------------------------

  if (!low) {
    for (let i = 0; i < 3; i += 1) {
      const lamp = new THREE.PointLight(TOKEN.lightWarm, 0, 140, 1.6);
      lamps.push(lamp);
      scene.add(lamp);
    }
  }

  function placeLamps() {
    if (low || !layout || !view) return;
    const spots = Object.keys(view.exits).map((name) => exitPoint(name));
    lamps.forEach((lamp, i) => {
      const p = spots[i];
      if (p) {
        lamp.position.set(p[0], p[1] - 4, p[2]);
        lamp.intensity = 2200;
      } else {
        lamp.intensity = 0;
      }
    });
  }

  // ---- measuring ---------------------------------------------------------------------------

  /**
   * Render `count` frames back to back, each finished on the GPU before the next,
   * and give the median wall time of one frame (the first, with shader compilation, left out).
   */
  async function measure(count = 6) {
    const times = [];
    const pixel = new Uint8Array(4);
    for (let i = 0; i < count; i += 1) {
      if (disposed || lost) break;
      await new Promise((resolve) => {
        requestAnimationFrame(() => {
          const started = performance.now();
          if (spritesDirty) buildSprites();
          renderer.render(scene, camera);
          gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
          times.push(performance.now() - started);
          frames += 1;
          resolve();
        });
      });
    }
    root.setAttribute('data-frames', String(frames));
    // Frames asked for while measuring are drawn now, with the labels.
    invalidate();
    return median(times.slice(1));
  }

  function silhouetteBox() {
    const points = silhouette(layout, k).map((p) => project(p)).filter(Boolean);
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)].map(Math.round);
  }

  function info() {
    return {
      renderer: rendererName,
      triangles: renderer.info.render.triangles,
      calls: renderer.info.render.calls,
      geometries: renderer.info.memory.geometries,
      textures: renderer.info.memory.textures,
      frames,
      firstFrameAt,
      renderMedianMs: median(renderMs),
      // The pixels of the stage the model takes (its silhouette), and the size of the stage.
      model: layout && width ? silhouetteBox() : null,
      stage: [width, height],
      // The width of the world seen across the stage at the camera's target, and the widths of the horizons.
      viewWidth: Math.round((2 * orbit.state.dist * Math.tan((camera.fov * DEG) / 2) * width) / Math.max(height, 1)),
      levels: layout ? layout.levels.map((level) => ({name: level.name,
        width: Math.round(Math.max(level.box.maxX - level.box.minX, level.box.maxZ - level.box.minZ))})) : [],
      focus: focusId,
      overview: overviewMode,
      target: ['x', 'y', 'z'].map((axis) => Math.round(orbit.state.target[axis] * 10) / 10),
      // The labels of the last frame: box, anchor, how far the decluttering pushed each, and its leader.
      labels: labels.placement,
      // The transitions now running (for frame sampling in tests): progress of each part, 0…1.
      motion: {
        fx: fx ? {
          started: fx.start !== null, total: fx.total,
          fades: [...fx.fades.values()].map((material) => Math.round(material.opacity * 1000) / 1000),
          sweeps: fx.sweeps.map((sweep) => Math.round((sweep.mesh.geometry.drawRange.count / sweep.count) * 1000) / 1000),
          scales: fx.scales.map((mesh) => Math.round(mesh.scale.x * 1000) / 1000),
          sensors: [...fx.sensors.keys()],
        } : null,
        ghosts: ghosts.map((ghost) => Math.round(ghost.mesh.material.opacity * 1000) / 1000),
        drawIn: [...drawIn.values()].filter((entry) => entry.start !== -1).length,
        select: Math.round(selectLevel * 1000) / 1000,
        scope: Math.round(scopeLevel * 1000) / 1000,
        scopeZones: scopeDrawn.zones,
        scopeWorkers: scopeDrawn.workers,
      },
      // The loaders of the zones: where each stands (a working and an offset of length_m), its look and its light.
      loaders: loaders.loaded ? loaders.info().map((entry) => {
        const place = loaderPlaces.get(entry.zone);
        const p = loaderPoint(entry.zone, 0);
        // Its length on the screen now, in pixels (from the bucket to the counterweight).
        const at = pointOnWorking(layout, place.working, place.offsetM, k);
        const ends = at ? [-1, 1].map((sign) => project(at.point.map((v, i) => v + (sign * at.dir[i] * LOADER_LENGTH) / 2))) : null;
        return {...entry, zoneId: (thingByName(state.model, entry.zone) || {}).thingId || null,
          working: (layout.workings.get(place.working) || {}).thingId || null, offsetM: place.offsetM, span: place.span,
          world: p ? p.map((v) => Math.round(v * 100) / 100) : null,
          px: ends && ends[0] && ends[1] ? Math.round(Math.hypot(ends[0].x - ends[1].x, ends[0].y - ends[1].y)) : null};
      }) : null,
      loader: {lengthM: LOADER_LENGTH, scale: LOADER_SCALE, triangles: loaders.triangles(), calls: loaders.calls,
        // The places each zone's loader may take (attributes only), best first: [working, offset, span].
        candidates: Object.fromEntries([...loaderCandidates].map(([zone, list]) => [zone,
          list.map((place) => [place.working, Math.round(place.offsetM * 10) / 10, place.span.map((v) => Math.round(v * 10) / 10)])]))},
    };
  }

  function dispose() {
    disposed = true;
    loaders.dispose();
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
    resizeObserver.disconnect();
    coverObserver.disconnect();
    clearTimeout(settleTimer);
    settleTimer = 0;
    canvas.removeEventListener('webglcontextlost', onLost);
    canvas.removeEventListener('webglcontextrestored', onRestored);
    scene.traverse((object) => {
      if (object.geometry) object.geometry.dispose();
      if (object.material) [].concat(object.material).forEach((material) => material.dispose());
    });
    for (const value of Object.values(textures)) value.dispose();
    atlasTexture.dispose();
    renderer.dispose();
    root.remove();
  }

  root.setAttribute('data-quality', low ? 'low' : 'high');
  root.setAttribute('data-explode', explode.toFixed(2));
  root.setAttribute('data-rendering', 'idle');
  gizmo.setVertical(k);
  resize();

  return {
    root, canvas, rendererName,
    update(next) {
      update(next);
      placeLamps();
    },
    focus, overview, setExplode, measure, info, dispose,
    get explode() {
      return explode;
    },
    /** Pixel position of an object's marker or label anchor, for tests and the card. */
    screenOf(thingId) {
      const point = markPoint(thingId);
      const p = point ? project(point) : null;
      return p ? {...p, world: point.map((v) => Math.round(v * 100) / 100)} : null;
    },
    invalidate,
  };
}
