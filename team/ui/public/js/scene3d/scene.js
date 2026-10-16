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
// Variant 3 («Глубина»): poster scale — thicker workings, markers and labels about twice the size (stepping down on
// a short stage), a dark graphite stone with crisp edge lines (the lips of the cuts, the accent-tinted outline of each
// horizon: one line draw call per slab), the detailed loader lhd_v2.glb with its light copy at the overview and the
// miner of miner.glb (each falls back to the earlier file or the primitives), and the intro «вскрытие массива» once
// per page load (INTRO_MS). info().levels gives the horizon rail of the stage each horizon's screen y.
//
// Read-only mirrors on the scene root (.s3) for tests: data-fx (the changes now explained), data-fx-count,
// data-auto-framed (the incident framed by itself), data-refits (refits after a panel or a size change),
// data-framing (how the last zone framing was chosen), data-scope (zones of the hovered option), data-loaders
// (loaders placed), data-loader-fx-count (fades of their lights), data-choreo and data-choreo-count (the camera
// moves that followed the situation), data-intro (waiting | running | done | cut), data-compact (a short stage).
//
// The depth rail of the stage (view/horizons.js) reads and drives three things here: people() gives the depth of
// the place where each person is drawn now (the same playback as the figures), announced by onEvent('people') when
// it changes; setDepthProbe(z) draws a thin glowing guide at a depth across the massif (a contour line on the art's
// rock, a slice outline over the slabs of variant 3); setLevelHighlight(level) glows the outlines of one horizon's
// workings. Each is drawn in one frame per call: nothing is drawn while the pointer rests.
// The rail is also a scroll control through depth: depthView() gives the mine elevations seen at the top, the
// middle and the bottom of the free stage (through the plane of the camera's target), announced by
// onEvent('view') from every frame that changed them; scrollDepth() moves the camera along the screen's up (its
// horizontal place kept) to a depth, or zooms from the overview to a depth reading (DEPTH_READ_ZOOM).

import * as THREE from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
import {showsOldData} from '../link.js';
import {incidentOf, isUnderground, routeOf, thingByName, thingsOfKind} from '../model.js';
import {situationOf} from '../situation.js';
import * as geo from '../geometry.js';
import {SCENE} from '../text3d.js';
import * as text from '../text.js';
import {createOrbit, FOV, placeCamera} from './camera.js';
import {ART_ZOOM_MAX, createArtRig} from './artcamera.js';
import {createWalk, MACHINE} from './walk.js';
import {artSignature, loadArtEnv, loadArtMachine, readGlbHeader} from './artenv.js';
import {labelItems, machineLines, tooltipLines} from './content.js';
import {changesBetween, describe, groupWorkers} from './describe.js';
import {createLabels} from './labels.js';
import {createEnvironment} from './environment.js';
import {
  buildLayout, DIMS, levelY, LOADER_SCALE, loaderPlaces as placesForLoaders, pointOnWorking, sceneBounds, sceneLine, silhouette,
  toScene, verticalFactor, zoneEntrances,
} from './layout.js';
import {createActors, FIGURE_PX, FIGURE_PX_ART, FIGURE_SCALE, machineLeg, machineLimit, sideOf} from './actors.js';
import {createLoaders} from './loaders.js';
import {drawAtlas, spriteGeometry, spriteMaterials, writeSprites} from './markers.js';
import {TOKEN, TONE} from './palette.js';
import {
  arrowHead, barricade, carveSlab, casing, dashes, disc, edgeLines, edgeMaterial, frameLoops, merge, plane, portal, rampBand, ribbon,
  slabGeometry, tube,
} from './shapes.js';
import {makeTextures} from './textures.js';

const DEG = Math.PI / 180;
export const DEFAULT_VIEW = {az: 30 * DEG, el: 23 * DEG};
/**
 * Art mode (mine-art SPEC §3–4): the stage seen by one orthographic camera from a fixed direction, pan and zoom only
 * (artcamera.js), the vertical factor fixed by the art. Defaults of the spec until the art's GLB gives its MainView:
 * from the south, azimuth 12°, elevation 28°, k = 1.35 (the vertical factor of SPEC §3; the art's GLB carries its own).
 */
export const ART_DEFAULT = {az: 12 * DEG, el: 28 * DEG, k: 1.35};
/** The art of the mine (mine-art SPEC §5–6), next to the other models. */
const ART_URL = (name) => new URL(`../../models/mine-art/${name}`, import.meta.url).href;
/** «Показать» a zone in art mode frames it at most this many times the overview; a person and a walk at most ART_PERSON_ZOOM. */
const ART_FRAME_ZOOM = 3;
const ART_PERSON_ZOOM = 4;
/** The intro of the art: from a little closer (1.12×) back to the overview, this long (a view farther than 1× would show the stage beyond the art). */
const ART_INTRO = {from: 1.12, ms: 1100};
/** The lamps of a zone's loader fade once in this time when the zone's published work state changes. */
const ART_LAMP_MS = 300;
/**
 * Conventional sizes of the art (the scale note says so): the worker of worker.glb (5 m tall) is drawn ART_FIGURE_SCALE
 * times larger, 8 m for a person of about 1.8 m; the machines (built 1.5× real, their extras.scaleToReal) are drawn
 * ART_MACHINE_FACTOR times real, so that they do not look like toys next to the people. Their anchors in env.glb keep
 * them clear of every walking line at these sizes (tests/test_art_mode.py, ArtSizeTest).
 */
const ART_FIGURE_SCALE = 1.6;
const ART_FIGURE_FACTOR = (5 * ART_FIGURE_SCALE) / 1.8;
const ART_MACHINE_FACTOR = 2.2;
/**
 * Art mode with equipment twins (CONTRACT.md §9): the art's lhd.glb is drawn for each published loader at its published
 * place (the art's own loaders at the zones' anchors are then hidden; the truck and the drill stay as decoration, their
 * lamps dark). The roof of the drawn machine (lhd.glb is 4.68 m tall built 1.5× real, drawn 2.2× real): a marker of
 * the operator riding it stands over it. Lamps by the published state: lit while working, dim while held, dark
 * stopped or without a state. The heap in the bucket is drawn only while the loader is published `loaded`.
 */
const ART_LHD_TOP = 4.68 * (ART_MACHINE_FACTOR / 1.5);
const ART_LHD_LAMP = {working: 1, parked: 0.35, stopped: 0, unknown: 0};
/** The thin line from a yielding loader to the person it yields to (published `yielding_to`): neutral, not a hazard colour. */
const YIELD_COLOR = '#E8E3DA';
/** The walk cycle of the art's worker plays at most this many cycles a second (above it the feet slide a little). */
const ART_MAX_CYCLES = 2.4;
/**
 * Art mode: the markers of people at the overview (of the poster size), and their pins over the figures: at most
 * ART_PIN of a poster marker, and never much larger than the figure under it (ART_PIN_PX: a pin over a figure of
 * about 11 px at the overview is about 12 px, so the pins do not hide the figures).
 */
const ART_MARK = 0.62;
const ART_PIN = 0.4;
const ART_PIN_PX = {min: 12, perFigurePx: 1.05};
/** The depth rail: the zoom of a depth reading (from the overview, one horizon fills most of the free stage). */
const DEPTH_READ_ZOOM = 2;
/** Art mode, a withdrawal: the stretch of the walkers' routes ahead that is framed with them (m), the glide of a re-frame. */
const ART_WALK_AHEAD_M = 90;
const ART_FOLLOW_MS = 900;
const DRAW_IN_MS = 550;
const EXPLODE_MS = 600;
/** The key of a zone's loader in picking, hover and labels: `loader:<zone>`; a click on it selects the zone. */
const LOADER = 'loader:';
/** The loader of lhd.glb is 10 m long; it is drawn LOADER_SCALE times larger. */
const LOADER_LENGTH = 10 * LOADER_SCALE;
/** A loader shorter than this on the screen is drawn from its light copy (lhd_v2_lod.glb). */
const LOD_PX = 150;
/** The most pixels the light quality renders (about a 1500×1000 buffer; the textures of the light quality are cheap). */
const LOW_PIXELS = 1.5e6;
/** Markers in CSS pixels: poster scale (variant 3), about twice the size of variant 2. */
const SPRITE_PX = {worker: 54, ring: 72, sensor: 38, exit: 52, sign: 42};
/** Opacity of the warm work light on a selected floor, and of the steel wash of an option's scope. */
const GLOW = 0.34;
const SCOPE_WASH = 0.2;
/** Durations of the transitions that explain a change (clarity spec B); each runs once, never on load. */
const MOTION = {hazard: 450, knowledge: 400, closed: 200, routeOut: 300, select: 200, scope: 150};
/** The light of the rest of the model while something is selected (the work light dims it slightly). */
const DIM = 0.78;
/** The stylised edges: the lips of the cuts (bone white), the sawn outline of a horizon (accent-tinted), the cut faces. */
const EDGE_TONES = {lip: [TOKEN.edge, 0.95], rim: [TOKEN.edgeAccent, 0.95], cut: [TOKEN.edge, 0.4]};
/** An incident is framed by itself only when the user left the camera alone this long. */
const HANDS_OFF_MS = 10000;
/** A size or a panel of the stage settles this long before the picture is refitted (after the strip has grown). */
const SETTLE_MS = 200;
/** What lies over the stage and the camera keeps clear of, as of a panel (variant 3): the headline and the horizon rail. */
const COVERS = ['[data-testid="situation-headline"]', '[data-testid="horizon-rail"]'];
const easeOut = (t) => 1 - (1 - t) ** 3;
/**
 * The intro «вскрытие массива» (variant 3): once per page load, at the first picture of a mine, never under reduced
 * motion, in the scheme or over old data. The massif fades in, the slabs rise into place one after another, the
 * workings draw in as light lines, the markers of people drop onto their published places and the labels come in;
 * it ends exactly in the published state, and jumps to its end on any change of what is published (positions of
 * people excepted: they are drawn where published all along) or on a touch of the user.
 */
const INTRO_MS = 1800;
const INTRO_HOLD_MS = 1500;
/** How far below its place a slab starts to rise, and how high above its place a person's marker starts to drop (scene m). */
const INTRO_RISE = 70;
const INTRO_DROP = 46;
let introSpent = false;
const phase = (t, from, to) => Math.min(Math.max((t - from) / (to - from), 0), 1);
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
 * @param {{az?: number, el?: number, k?: number}|null} [options.art]  art mode from the start (`?art=ortho`); see setArt
 * @param {boolean} [options.artEnv]           false: never the art of the mine (env.glb), even for its topology
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
  // The perspective orbit of the procedural scene, or the orthographic camera of art mode (setArt): `camera`, `orbit`
  // and `probe` are swapped together; everything reads them when it runs.
  let camera = new THREE.PerspectiveCamera(FOV, 1, 1, 10000);
  let orbit = createOrbit(camera, {reducedMotion: reduced});
  /** Art mode: {az, el, k} of its one view, or null (the perspective orbit of variant 3). */
  let art = null;
  const textures = makeTextures();
  // A software renderer pays for every texel fetch: the light quality samples one mip level, without anisotropy
  // (about a third of the frame at 1920×1080 on SwiftShader).
  if (low) {
    for (const map of Object.values(textures)) {
      map.anisotropy = 1;
      map.minFilter = THREE.LinearMipmapNearestFilter;
    }
  }
  const materials = makeMaterials(textures, low);
  // The massif around the slabs, the light (warm key, cool sky, rim), background and lamps: environment.js.
  const environment = createEnvironment(scene, {low, textures});
  const {hemi, key, fill} = environment.lights;
  const lamps = [];
  const baseLight = {hemi: hemi.intensity, key: key.intensity, fill: fill.intensity};
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
  // S3b: the loaders of the model (equipment twins) and the figures of people close up (actors.js). With equipment
  // twins, loaderPlaces holds the loaders by their local names, where the model publishes them.
  const actors = createActors({low, reducedMotion: reduced, source: {
    get layout() { return layout; }, get k() { return k; }, get view() { return view; }, get groups() { return groups; },
    get camera() { return camera; }, get height() { return height; }, position: (name) => currentPosition(name),
    viewDistance: (point) => viewDistance(point), get figurePx() { return art ? FIGURE_PX_ART : FIGURE_PX; },
    machine: (name) => machinePlace(name), get machineTop() { return machineTop(); },
  }});
  world.add(actors.group);
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
  // The illustrated mine (artenv.js): the header of env.glb (undefined while it is read, null when there is none),
  // the environment once a topology matched, and whether it is shown now (artOn: art mode with the art).
  let artHeader;
  let artEnv = null;
  let artEnvLoading = null;
  let artOn = false;
  let artMachines = null;          // {group, zone: [...], decor: [...], equip: Map} once loaded
  let artMachinesLoading = null;
  let artMachineSources = null;    // kind -> the loaded art machine (artenv.js loadArtMachine), for the published loaders
  let rockGeometry = null;          // the heap in a loaded bucket (art mode), built once
  // The yielding of a loader to a person (published `activity = yielding`, `yielding_to`): a thin line between them.
  const yieldLines = new THREE.LineSegments(new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({color: YIELD_COLOR, transparent: true, opacity: 0.85, depthTest: false}));
  yieldLines.renderOrder = 20;
  yieldLines.frustumCulled = false;
  yieldLines.name = 'yield-lines';
  yieldLines.visible = false;
  world.add(yieldLines);
  const orePassMaterial = new THREE.MeshBasicMaterial({vertexColors: true});
  /** A geometry painted one colour (vertex colours), for the unlit grate of an ore pass. */
  const painted = (geometry, colour) => {
    const c = new THREE.Color(colour);
    const colours = new Float32Array(geometry.attributes.position.count * 3);
    for (let i = 0; i < colours.length; i += 3) colours.set([c.r, c.g, c.b], i);
    geometry.setAttribute('color', new THREE.BufferAttribute(colours, 3));
    geometry.deleteAttribute('uv');
    geometry.deleteAttribute('normal');
    return geometry;
  };
  let yieldDrawn = [];             // [[machine, person]] drawn now
  // The ore passes of mine.attributes.dump_points (CONTRACT.md §9, not twins): a grate on the floor and a label.
  const orePassGroup = new THREE.Group();
  orePassGroup.name = 'ore-passes';
  world.add(orePassGroup);
  let orePassKey = null;
  let orePasses = [];              // [{id, label, working, offsetM, point}] drawn now
  // Art mode, a withdrawal: who walks out of which zone (person -> zone), and the walk the camera follows.
  const walkOrigins = new Map();
  let walkFollow = null;
  // The depth rail: the drawn depths last announced, the depth probe and the highlighted horizon (setDepthProbe, ...).
  let peopleKey = null;
  let depthProbe = null;            // {z, y}: the mine elevation and the scene height of the guide, or null
  let levelLit = null;              // the local name of the highlighted horizon, or null
  let viewKey = null;               // the depths of the free stage last announced (onEvent('view'))
  let freeCache = null;             // the free part of the stage for the depth rail, re-read at most twice a second
  let freeCacheAt = 0;
  const probeUniforms = {uProbe: {value: new THREE.Vector4(0, 0, 0, 0)}, uProbeColor: {value: new THREE.Color(TOKEN.verdigrisCore)},
    uProbeHalo: {value: new THREE.Color(TOKEN.verdigris)}};
  const probeGroup = new THREE.Group();
  probeGroup.name = 'depth-probe';
  probeGroup.visible = false;
  const highlightGroup = new THREE.Group();
  highlightGroup.name = 'level-highlight';
  const highlightLoops = new Map(); // level|mode -> {loops, plans} of this layout
  const artGroup = new THREE.Group();
  artGroup.name = 'art';
  artGroup.visible = false;
  scene.add(artGroup);
  // People: the playback buffer of their published places (walk.js), and the publication last given to it.
  const walk = createWalk();
  let walkSnapshot = null;
  let walking = false;
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
  world.add(probeGroup, highlightGroup);
  // The camera: what it frames, and when the user last moved it (an incident is framed by itself only after a pause).
  let focusId = null;              // the object the camera was last asked to frame, until the user moves it
  let lastTouch = -Infinity;
  let situationKey = null;          // the situation of the shift last seen (choreograph)
  let settleTimer = 0;
  let settleWhy = null;            // 'size' | 'panel'
  let lastPanelCover = '';
  // The intro (INTRO_MS): null when not running; its light (0…1) multiplies the lights, its pins (0…1) the markers.
  let intro = null;
  let introLight = 1;
  let introPins = 1;
  let spriteScale = 1;
  const introWanted = Boolean(options.intro) && !introSpent;

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
      // Variant 3: the sawn stone is a dark graphite, so the pale floors of the workings, their bone-white lips and
      // the markers carry the picture (a multiplier of the stone textures: no shader of its own).
      top: lit({map: tex.top, color: new THREE.Color().setScalar(0.5)}),
      strata: lit({map: tex.strata, side: THREE.DoubleSide, color: new THREE.Color().setScalar(0.62)}),
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
      routeCore: new THREE.MeshBasicMaterial({color: TOKEN.verdigrisCore}),
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
      // The crisp edges of the stone (shapes.edgeLines): the lips of the cuts, the outline of the horizons.
      edge: edgeMaterial(TOKEN.verdigrisCore),
      // The depth rail: the slice of the depth probe over the slabs (a faint sheet and its glowing rim), and the
      // glow of a hovered horizon's outlines (the accent-tinted outline of a horizon, variant 3). Never a hazard colour.
      probeFill: new THREE.MeshBasicMaterial({color: TOKEN.verdigris, transparent: true, opacity: 0.05, depthTest: false, depthWrite: false,
        blending: THREE.AdditiveBlending, side: THREE.DoubleSide}),
      probeHalo: new THREE.MeshBasicMaterial({color: TOKEN.verdigris, transparent: true, opacity: 0.22, depthTest: false, depthWrite: false,
        blending: THREE.AdditiveBlending, side: THREE.DoubleSide}),
      probeCore: new THREE.MeshBasicMaterial({color: TOKEN.verdigrisCore, transparent: true, opacity: 0.95, depthTest: false, depthWrite: false,
        side: THREE.DoubleSide}),
      // The glow shows through the rock in front (soft, like a light behind the wall); the crisp line only where seen.
      levelHalo: flat(TOKEN.edgeAccent, 0.2, {blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false}),
      levelGhost: flat(TOKEN.edgeAccent, 0.4, {blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false}),
      levelCore: flat(TOKEN.edgeAccent, 1, {depthWrite: false}),
      levelWash: flat(TOKEN.edgeAccent, 0.1, {blending: THREE.AdditiveBlending, depthWrite: false}),
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
    environment.build(layout, state && state.model ? state.model : null);
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
      for (const part of environment.levelDetail(layout, level, carved)) group.add(part);
      const edges = new THREE.LineSegments(edgeLines(level.box, carved, EDGE_TONES), materials.edge);
      edges.name = 'edges';
      edges.renderOrder = 4;
      edges.matrixAutoUpdate = false;
      group.add(edges);
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
    loaders.setMachines(actors.setModel(state && state.model));
    if (gizmo && root.getAttribute('data-decor') === 'loaded') gizmo.setDecor(true, actors.equipment);
    loaderCandidates = state && state.model && !actors.equipment ? candidatesOfLoaders() : new Map();
    loaderPlaces = new Map();
    loaderRun = null;
    if (artOn) loaderCandidates = new Map();
    placeLoaders();
    applyArtVisibility();
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
    environment.fit(k);
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
    if (orbit.art) {
      // Art mode: the target stays over the mine (its silhouette on the view plane); the camera stands beyond it.
      orbit.setBounds(artFrame() || silhouette(layout, k));
      orbit.limits.reach = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, bounds.maxZ - bounds.minZ, 400) * 2 + 1000;
    } else {
      orbit.limits.distMax = Math.max(bounds.maxX - bounds.minX, bounds.maxZ - bounds.minZ, 400) * 5;
    }
    gizmo.setVertical(k);
    if (levelLit) buildLevelHighlight();
    if (depthProbe) placeDepthProbe(depthProbe.z);
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
    // Over the art there is no slab: what stands on the top face of a slab lies on the drawn floor instead, inside it
    // (the floors of the art are 15 m wide or more: the outlines keep within ARTSIDE of the centre line).
    const d = artOn ? 0.1 : DIMS.depth;
    const ARTSIDE = DIMS.half - 0.4;
    const sideOf = (offset) => (artOn ? Math.min(ARTSIDE, ARTSIDE - (offset - DIMS.half - 1.2) * 0.45) : offset);
    const sideRibbons = (plan, offset, width, y, dash) => {
      const out = [];
      for (const sign of [-1, 1]) {
        if (dash) {
          for (const piece of dashes(plan, dash[0], dash[1])) out.push(ribbon(piece, width, y, {offset: sign * sideOf(offset)}));
        } else {
          out.push(ribbon(plan, width, y, {offset: sign * sideOf(offset)}));
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
      // The art paints its floors: a decal only where the published hazard is not normal (no colour of hazard in the art).
      if (artOn && working.hazard === 'normal') material = null;
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
    // The outlines of a zone: around its channels on the slab, or on the drawn floor of the art (reach relative to
    // the outline of variant 3, DIMS.zoneReach).
    const zoneLoops = (name, extra) => (artOn ? zoneFrame(name, -DIMS.zoneReach - 1.2 - Math.max(extra, 0) * 0.35) : zoneFrame(name, extra));
    for (const [name, zone] of Object.entries(view.zones)) {
      const base = staticParts.zoneFrames.get(name);
      const frame = base && artOn ? zoneLoops(name, 0) : base;
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
          for (const loop of zoneLoops(name, reach).loops) add(frame.level, materials.frame.select, ribbon(loop, 1, d + 0.1, {closed: true}), 7);
        }
        for (const local of zone.workings) {
          const line = layout.workings.get(local);
          if (!line.between) add(line.level, materials.glow, ribbon(line.plan, DIMS.half * 2 - 1.2, 0.12), 6);
        }
      }
      if (zone.pending) {
        for (const loop of zoneLoops(name, 7.5).loops) {
          for (const piece of dashes(loop, 6, 5, true)) add(frame.level, materials.frame.pending, ribbon(piece, 1.3, d + 0.1), 7);
        }
      }
      if (scopeZones.has(name)) {
        for (const loop of zoneLoops(name, isSelected ? 9 : 3.6).loops) add(frame.level, materials.frame.scope, ribbon(loop, 3, d + 0.11, {closed: true}), 7);
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
    hemi.intensity = baseLight.hemi * dim * introLight;
    key.intensity = baseLight.key * dim * introLight;
    fill.intensity = baseLight.fill * dim * introLight;
    materials.edge.uniforms.uDim.value = dim;
    if (actors.equipment) loaders.setSelected(view ? actors.selectedOf(view) : null, selectLevel);
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

  // ---- the intro «вскрытие массива» ---------------------------------------------------------

  /**
   * The mine is built but its first state has not come: the stage waits dark, the slabs below their places, so the
   * intro starts from nothing when it comes (at most INTRO_HOLD_MS, then the picture is shown as it is).
   */
  function holdIntro() {
    intro = {hold: true, start: null, routes: false, timer: setTimeout(() => finishIntro(), INTRO_HOLD_MS)};
    root.setAttribute('data-intro', 'waiting');
    applyIntro(0);
  }

  /**
   * The held intro starts once the first state has come and the stage knows whether the art of the mine is shown
   * (its header read; on a match, its environment loaded), so it plays once in the right picture.
   */
  function maybeStartIntro() {
    if (!intro || !intro.hold || !view) return;
    const calmNow = view.linkOk && !view.old;
    if (!view.hasSnapshot && calmNow) return;
    // The art decides first: its header is still read, or it matches and its environment is still loading.
    if (artHeader === undefined || (artHeader && !artOn && artMatches())) return;
    if (view.hasSnapshot && calmNow && !reduced() && !view.selected) startIntro();
    else finishIntro();
  }

  /** Start the intro at the first picture of a mine (the camera is at the overview): see INTRO_MS. */
  function startIntro() {
    introSpent = true;
    if (intro) clearTimeout(intro.timer);
    const goal = {target: orbit.state.target.clone(), az: orbit.state.az, el: orbit.state.el, dist: orbit.state.dist};
    intro = {start: null, goal, routes: false, art: artOn};
    if (artOn) {
      // The art: a short ease from a little closer (ART_INTRO.from times the overview) out onto the overview.
      orbit.set({target: goal.target, dist: goal.dist / ART_INTRO.from}, true);
      orbit.glideTo(goal, ART_INTRO.ms);
    } else {
      // The camera comes in from a little farther and higher, turning a few degrees onto the overview.
      orbit.set({target: goal.target, dist: goal.dist * 1.28, az: goal.az - 9 * DEG, el: goal.el + 7 * DEG});
      orbit.glideTo(goal, INTRO_MS);
    }
    root.setAttribute('data-intro', 'running');
    applyIntro(0);
  }

  /** The picture of the intro at `t` ms: every value here ends at its published or built value at INTRO_MS. */
  function applyIntro(t) {
    environment.setReveal(easeOut(phase(t, 0, 700)));
    introLight = 0.12 + 0.88 * easeOut(phase(t, 120, 1100));
    applySelectLevel();
    levelGroups.forEach((group, index) => {
      // The art does not rise: only its camera eases in (and the markers and labels come).
      const p = artOn ? 1 : easeOut(phase(t, 150 + index * 150, 850 + index * 150));
      group.position.y = levelY(layout, group.userData.level, k) - (1 - p) * INTRO_RISE * k;
      group.updateMatrixWorld(true);
    });
    // The ways between the horizons are drilled down from the upper one.
    const drill = artOn ? 1 : Math.max(easeOut(phase(t, 750, 1300)), 0.001);
    for (const group of [interGroup, interOverlay]) {
      group.scale.y = drill;
      group.updateMatrixWorld(true);
    }
    materials.edge.uniforms.uProgress.value = easeOut(phase(t, 800, 1450));
    materials.edge.uniforms.uGlow.value = 1 - phase(t, 1250, INTRO_MS);
    const landed = t >= 1050;
    loaders.group.visible = landed && !artOn;
    actors.group.visible = landed;
    routeGroup.visible = t >= 1250;
    if (routeGroup.visible && !intro.routes) {
      intro.routes = true;
      for (const mesh of routeMeshes) drawIn.set(mesh.userData.key, {start: null});
    }
    introPins = easeOut(phase(t, 1150, 1700));
    materials.pin.opacity = 0.75 * introPins;
    // What lies over the stage has settled by now (the headline, the rail): the overview the camera comes to is fitted
    // again, so the intro ends exactly where «Общий вид» would put it.
    if (t >= 900 && !intro.refit && overviewMode && orbit.gliding) {
      intro.refit = true;
      const fitted = fitAll();
      orbit.retarget({target: fitted.target, dist: fitted.dist});
    }
    labelLayer.style.opacity = String(phase(t, 1350, INTRO_MS));
    spritesDirty = true;
  }

  function stepIntro(now) {
    if (!intro) return false;
    if (intro.hold) {
      applyIntro(0);
      return false;
    }
    if (intro.start === null) intro.start = now;
    const t = now - intro.start;
    if (reduced() || t >= INTRO_MS || !layout) {
      finishIntro(false);
      return false;
    }
    applyIntro(t);
    return true;
  }

  /** End the intro: the picture as without it. `jump`: also the camera ends its glide at once. */
  function finishIntro(jump = true) {
    if (!intro) return;
    const done = intro;
    intro = null;
    introSpent = true;
    clearTimeout(done.timer);
    environment.setReveal(1);
    introLight = 1;
    introPins = 1;
    materials.pin.opacity = 0.75;
    applySelectLevel();
    if (layout) {
      for (const group of levelGroups) {
        group.position.y = levelY(layout, group.userData.level, k);
        group.updateMatrixWorld(true);
      }
    }
    for (const group of [interGroup, interOverlay]) {
      group.scale.y = 1;
      group.updateMatrixWorld(true);
    }
    materials.edge.uniforms.uProgress.value = 1;
    materials.edge.uniforms.uGlow.value = 0;
    loaders.group.visible = !artOn;
    actors.group.visible = true;
    routeGroup.visible = true;
    if (jump || !done.routes) for (const mesh of routeMeshes) drawIn.set(mesh.userData.key, {start: -1});
    stepDrawIn(performance.now());
    labelLayer.style.opacity = '';
    if (jump && orbit.gliding) orbit.set(orbit.goal);
    if (!done.hold && overviewMode && layout && width && !orbit.gliding) {
      const fitted = fitAll();
      orbit.set({target: fitted.target, dist: fitted.dist, az: nearestAngle(orbit.state.az, mainView().az), el: mainView().el});
    }
    spritesDirty = true;
    root.setAttribute('data-intro', jump ? 'cut' : 'done');
    invalidate();
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
        parts.push(tube(points, 2.3, low ? 5 : 7));
        const cum = geo.cumulative(points);
        const total = cum[cum.length - 1];
        for (let at = 40; at < total - 10; at += 55) {
          const {point, dir} = geo.pointAt(points, cum, at);
          arrows.push(arrowHead(point.map((v, i) => v + dir[i] * 5), dir, 4.8));
        }
        const end = geo.pointAt(points, cum, total);
        arrows.push(arrowHead(end.point, end.dir, 5.8));
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
    return Boolean(state) && view.linkOk && !view.old && view.runState === 'running' && !reduced() && !document.hidden;
  }

  /** The published route of a person as segments with their offsets: {working, from, to, fromOffsetM, toOffsetM}. */
  function routeSegments(thing) {
    const raw = Array.isArray(thing.values.route) ? thing.values.route : [];
    const segments = routeOf(state.model, thing);
    const objects = raw.filter((item) => item && typeof item === 'object' && typeof item.working === 'string');
    return segments.map((segment, index) => {
      const item = objects.length === raw.length ? objects[index] : null;
      return {...segment,
        fromOffsetM: item && Number.isFinite(item.from_offset_m) ? item.from_offset_m : null,
        toOffsetM: item && Number.isFinite(item.to_offset_m) ? item.to_offset_m : null};
    });
  }

  /**
   * A new publication (a new snapshot sequence or run): the published places and routes of the people go into the
   * playback buffer (walk.js). A new run or topology clears it; with motion not allowed everyone stands where
   * published. True while someone walks.
   */
  function publishPlaces(previousRun) {
    const snapshot = state && state.snapshot;
    if (!snapshot || !view || !view.hasSnapshot) return false;
    const key = `${snapshot.run}|${snapshot.seq}`;
    if (walkSnapshot === key) return false;
    const newRun = walkSnapshot !== null && !walkSnapshot.startsWith(`${snapshot.run}|`);
    walkSnapshot = key;
    if (newRun || previousRun !== view.run) walk.clear();
    const places = new Map();
    const routes = new Map();
    for (const [name, worker] of Object.entries(view.workers)) {
      if (!worker.at) continue;
      places.set(name, {working: worker.at, offsetM: worker.offsetM});
      const thing = thingByName(state.model, name);
      if (thing) routes.set(name, routeSegments(thing));
    }
    // The loaders play back with the people (walk.js): their path between two publications runs along their working
    // or through the node it shares with the next (actors.js machineLeg), within the registry's step (machineLimit).
    const paths = new Map();
    const limit = machineLimit(state.attributes && state.attributes.mine, state.model.shift ? state.model.shift.values.speedup : undefined);
    for (const [name, machine] of Object.entries(view.equipment)) {
      if (!machine.at) continue;
      places.set(MACHINE + name, {working: machine.at, offsetM: machine.offsetM});
      paths.set(MACHINE + name, (from, to) => machineLeg(layout, from, to, limit));
    }
    walking = walk.publish(layout, {at: performance.now(), places, routes, paths}, motionAllowed() && previousRun === view.run && !newRun);
    spritesDirty = true;
    return walking;
  }

  /**
   * Where a person is drawn now: on the machine the person rides (published `aboard`: the operator is part of it, the
   * machine's drawn place), else the playback buffer, else the published place.
   */
  function currentPosition(name) {
    const worker = view && view.workers[name];
    if (worker && worker.aboard && actors.equipment) {
      const riding = machinePlace(worker.aboard);
      if (riding) return riding;
    }
    const place = walk.place(name);
    if (place) return place;
    return worker && worker.at ? {working: worker.at, offsetM: worker.offsetM, facing: 1, moving: false} : null;
  }

  /**
   * Where a loader is drawn now: its playback (walk.js), facing its published `toward_node` while it stands and its
   * travel while it moves; null without a published place.
   */
  function machinePlace(name) {
    const machine = view && view.equipment[name];
    if (!machine || !machine.at || !layout) return null;
    const at = walk.place(MACHINE + name) || {working: machine.at, offsetM: machine.offsetM, facing: 1, moving: false};
    const toward = at.moving ? null : sideOf(layout.workings.get(at.working), machine.toward);
    return {working: at.working, offsetM: at.offsetM, facing: toward || at.facing || 1, moving: Boolean(at.moving)};
  }

  /** The height of the roof of a drawn loader over its floor (scene metres): the art's machine, or the variant 3 one. */
  function machineTop() {
    return artOn ? ART_LHD_TOP : 2.6 * LOADER_SCALE;
  }

  /** Every walk ends at once at the newest published place (a failed read, old data, a pause); loaders with them. */
  function snapMotion() {
    if (!walk.snap()) return;
    walking = false;
    placeLoaders();
    spritesDirty = true;
    invalidate();
  }

  /** Advance the people's playback clock; true while someone walks. */
  function stepWalk(now) {
    const before = walking;
    walking = walk.step(now);
    if (walking || before) spritesDirty = true;
    return walking;
  }

  function workerPoint(name) {
    const position = currentPosition(name);
    if (!position) return null;
    const at = pointOnWorking(layout, position.working, position.offsetM, k);
    return at ? at.point : null;
  }

  function groupPoint(group) {
    const points = group.members.map((name) => workerPoint(name)).filter(Boolean);
    if (points.length === 0) return null;
    const p = [0, 1, 2].map((i) => points.reduce((sum, q) => sum + q[i], 0) / points.length);
    return [p[0], p[1] + actors.liftOf(group), p[2]];
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
      if (exit.thingId === view.selected) list.push({position: p, cell: 'ring:selected', size: SPRITE_PX.ring + 22, key: exit.thingId, alpha: selectLevel});
      list.push({position: p, cell, size: SPRITE_PX.exit, key: exit.thingId});
    }
    for (const [name, sensor] of Object.entries(view.sensors)) {
      const base = sensorPoint(name);
      if (!base) continue;
      const p = [base[0], base[1] + 7.5, base[2]];
      signPosts.push([base, [base[0], base[1] + 6, base[2]]]);
      const cell = ['fresh', 'stale', 'lost'].includes(sensor.quality) ? `sensor:${sensor.quality}` : 'sensor:unknown';
      if (sensor.thingId === view.selected) list.push({position: p, cell: 'ring:selected', size: SPRITE_PX.sensor + 38, key: sensor.thingId, alpha: selectLevel});
      if (sensor.pending) list.push({position: p, cell: 'ring:pending', size: SPRITE_PX.sensor + 24, key: sensor.thingId});
      if (sensor.thingId === hovered) list.push({position: p, cell: 'ring:hover', size: SPRITE_PX.sensor + 20, key: sensor.thingId});
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
      if (cell && view.hasSnapshot) list.push({position: zonePoint(name, 3), cell, size: SPRITE_PX.sign + 8, key: zone.thingId});
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
    const pinScale = Math.min(ART_PIN, Math.max(ART_PIN_PX.min, actors.figurePx * ART_PIN_PX.perFigurePx) / (SPRITE_PX.worker * spriteScale));
    const rank = (group) => ({ok: 0, none: 2}[view.workers[group.front].egress] ?? 1);
    for (const group of [...(artOn ? artGroups() : groups)].sort((a, b) => rank(a) - rank(b))) {
      const at = groupPoint(group);
      if (!at) continue;
      // Art mode: a person drawn as a figure (the worker of the art) is the figure; its marker is a small pin over the
      // helmet. Below the figure's size the markers are smaller than the poster markers of variant 3.
      const k0 = artOn ? (actors.figured(group) ? pinScale : ART_MARK) : 1;
      // The intro drops the marker onto its published place from above (only its height moves).
      const p = introPins < 1 ? [at[0], at[1] + (1 - introPins) * INTRO_DROP, at[2]] : at;
      const front = view.workers[group.front];
      const thingId = front.thingId;
      const members = group.members.map((member) => view.workers[member]);
      pinPoints.push([at[0], at[1] - actors.liftOf(group) + actors.pinFrom(group), at[2]], [p[0], p[1] - 1.8, p[2]]);
      if (members.some((member) => member.thingId === view.selected)) {
        list.push({position: p, cell: 'ring:selected', size: (SPRITE_PX.ring + 24) * k0, key: thingId, alpha: selectLevel});
      }
      if (group.members.some((member) => scopeWorkers.has(member))) {
        list.push({position: p, cell: 'ring:scope', size: (SPRITE_PX.ring + 18) * k0, key: thingId, alpha: scopeLevel});
      }
      if (members.some((member) => member.thingId === hovered)) list.push({position: p, cell: 'ring:hover', size: (SPRITE_PX.ring + 8) * k0, key: thingId});
      if (members.some((member) => member.locationHazard === 'danger')) list.push({position: p, cell: 'ring:danger', size: SPRITE_PX.ring * k0, key: thingId});
      const cell = front.egress === 'ok' ? 'worker:ok' : (front.egress === 'none' ? 'worker:none' : 'worker:unknown');
      list.push({position: p, cell, size: SPRITE_PX.worker * k0, key: thingId, group});
      // Art mode: the people of one marker are counted on it (as the scheme does), never a stack of discs.
      if (artOn && group.members.length > 1) {
        list.push({position: p, cell: group.members.length > 9 ? 'count:many' : `count:${group.members.length}`, size: SPRITE_PX.worker * k0, key: thingId});
      }
    }
    if (introPins < 1) for (const item of list) item.alpha = (item.alpha ?? 1) * introPins;
    // Poster scale on a tall stage, smaller on a short one (the 1280×720 desk): the markers follow the stage height.
    if (spriteScale !== 1) for (const item of list) item.size *= spriteScale;
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

  /**
   * Art mode: the groups of people as markers on the screen. Groups not drawn as figures whose markers would overlap
   * (a working that runs towards the viewer, people close together at the overview) share one marker that counts
   * them; the front of a shared marker is the person with the worst reachability, as in a group.
   */
  function artGroups() {
    const radius = SPRITE_PX.worker * ART_MARK * spriteScale * 0.8;
    const placed = [];
    const out = [];
    for (const group of groups) {
      const at = groupPoint(group);
      const p = at ? project(at) : null;
      if (!p || actors.figured(group)) {
        out.push(group);
        continue;
      }
      const near = placed.find((entry) => Math.hypot(entry.x - p.x, entry.y - p.y) < radius);
      if (near) near.parts.push(group);
      else placed.push({x: p.x, y: p.y, parts: [group]});
    }
    const rank = (name) => ({ok: 0, none: 2}[view.workers[name].egress] ?? 1);
    for (const {parts} of placed) {
      if (parts.length === 1) {
        out.push(parts[0]);
        continue;
      }
      const members = parts.flatMap((group) => group.members).sort();
      const worst = Math.max(...members.map(rank));
      out.push({key: `shared:${parts.map((group) => group.key).join('+')}`, working: parts[0].working, members,
        front: members.find((name) => rank(name) === worst), parts});
    }
    return out;
  }

  // ---- loaders: the published work state of each zone ---------------------------------------

  /**
   * Once per run, the first place of each zone's list that nothing published occupies: no person, no published
   * route, no closed or pending working on the stretch it and its light cover. The loader then stays there for
   * the run: it never moves (it is a symbol of the zone's work, not a machine of the model). No free place: none.
   */
  function chooseLoaderPlaces() {
    const run = `${view.run}|${signatureOfTopology()}`;
    if (actors.equipment || loaderRun === run || !view.hasSnapshot) return false;
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
    if (actors.equipment) loaderPlaces = actors.places();
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
    placeArtEquipment();
    placeYieldLines();
  }

  /** The published work state of a zone as the look of its loader: working, stopped, or unknown. */
  function workLook(zone) {
    if (!view.hasSnapshot || !zone) return 'unknown';
    return zone.workState === 'working' || zone.workState === 'stopped' ? zone.workState : 'unknown';
  }

  /** The looks follow the published work states; a change seen while watching fades the lights once (400 ms). */
  function updateLoaderLooks(animate) {
    let started = false;
    const looks = actors.equipment ? actors.looks(view) : new Map([...loaderCandidates.keys()].map((name) => [name, workLook(view.zones[name])]));
    for (const [name, look] of looks) started = loaders.setState(name, look, animate) || started;
    if (actors.equipment) loaders.setLoaded(actors.loadedOf(view));
    if (started) {
      loaderFade = true;
      root.setAttribute('data-loader-fx-count', String(Number(root.getAttribute('data-loader-fx-count') || 0) + 1));
    }
    if (!animate) {
      loaders.finish();
      loaderFade = false;
    }
  }

  /** 'full' while some loader is at least LOD_PX long on the screen (with a margin both ways), else 'lod'. */
  function loaderDetail() {
    let largest = 0;
    for (const zone of loaderPlaces.keys()) {
      const p = project(loaderPoint(zone, 0));
      if (p && p.visible) largest = Math.max(largest, LOADER_LENGTH * p.scale);
    }
    return largest >= (loaders.detail === 'full' ? LOD_PX * 0.85 : LOD_PX) ? 'full' : 'lod';
  }

  /** Scene point of a loader's middle, a little above its roof (its label and its leader end there). */
  function loaderPoint(zone, lift = 1.2) {
    const pose = loaderPlaces.has(zone) && layout ? pointOnWorking(layout, loaderPlaces.get(zone).working, loaderPlaces.get(zone).offsetM, k) : null;
    // Art mode: the art's machine (ART_LHD_TOP tall at its roof, lift 2.6 of variant 3's loader).
    const rise = artOn && actors.equipment ? (lift / 2.6) * ART_LHD_TOP : lift * LOADER_SCALE;
    return pose ? [pose.point[0], pose.point[1] + rise, pose.point[2]] : null;
  }

  /** The zone whose loader lies under a screen point, if any (`withDistance`: {zone, d}). */
  function overLoader(x, y, withDistance = false) {
    if (!loaders.loaded) return null;
    let best = null;
    for (const zone of loaderPlaces.keys()) {
      const p = project(loaderPoint(zone));
      if (!p || !p.visible) continue;
      const d = Math.hypot(p.x - x, p.y - y);
      if (d < Math.max((LOADER_LENGTH / 2) * p.scale, 10) && (!best || d < best.d)) best = {d, zone};
    }
    if (withDistance) return best;
    return best ? best.zone : null;
  }

  /** The words of a loader's tooltip: the zone's published work state; the machine itself is not in the model. */
  function loaderLines(zoneName) {
    if (actors.equipment) return machineLines(state.model, zoneName, view.equipment[zoneName], actors.looks(view).get(zoneName), LOADER_SCALE);
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
      const model = (name) => new URL(`../../models/${name}`, import.meta.url).href;
      try {
        // The detailed machine of variant 3 and its light copy for the overview (assets/README.md).
        await loaders.load(model('lhd_v2.glb'), model('lhd_v2_lod.glb'));
      } catch (error) {
        if (disposed) return;
        await loaders.load(model('lhd.glb'));
      }
      if (disposed) return;
      // The figure of a person close up: miner.glb, or the primitives of actors.js when it cannot be read.
      if (await actors.loadFigure(model('miner.glb'))) spritesDirty = true;
      if (disposed) return;
      root.setAttribute('data-decor', 'loaded');
      gizmo.setDecor(true, actors.equipment);
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
      if (artOn) return artLevelPoint(level);
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
    orePass: (id) => {
      const entry = orePasses.find((item) => item.id === id);
      return entry ? [entry.point[0], entry.point[1] + 2.5, entry.point[2]] : null;
    },
  };

  /**
   * The art: a horizon's label stands on the rock left of everything drawn (the ramps' galleries included), at the
   * height of the horizon, in the plane of its galleries; placed to the left of that point.
   */
  function artLevelPoint(level) {
    let minX = Infinity;
    for (const line of layout.workings.values()) for (const p of sceneLine(layout, line, k)) minX = Math.min(minX, p[0]);
    const nodes = [...layout.nodes].filter(([node]) => layout.nodeLevel.get(node) === level.name).map(([, point]) => toScene(layout, point, k));
    if (!Number.isFinite(minX) || nodes.length === 0) return null;
    const z = median(nodes.map((p) => p[2]));
    return [minX - 18, levelY(layout, level, k) + 4, z];
  }

  /**
   * The ore passes (mine.attributes.dump_points: {id, label, level, working, offset_m}): a small grate lying on the floor
   * of the working at the published offset, in the colours of steel (no hazard colour). Rebuilt when the layout or the
   * vertical factor changes.
   */
  function placeOrePasses() {
    const mine = state && state.attributes ? state.attributes.mine : null;
    const list = mine && Array.isArray(mine.dump_points) ? mine.dump_points : [];
    const key = layout ? `${layout.cx}|${layout.cy}|${k}|${JSON.stringify(list)}` : null;
    if (key === orePassKey) return;
    orePassKey = key;
    for (const child of [...orePassGroup.children]) {
      orePassGroup.remove(child);
      child.geometry.dispose();
    }
    orePasses = [];
    if (!layout) return;
    for (const entry of list) {
      if (!entry || typeof entry.working !== 'string' || !Number.isFinite(entry.offset_m)) continue;
      const at = pointOnWorking(layout, entry.working, entry.offset_m, k);
      if (!at) continue;
      const parts = [];
      const frame = new THREE.BoxGeometry(7, 0.2, 7).toNonIndexed();
      parts.push(painted(frame, '#2B2824'));
      for (const z of [-2.2, -0.75, 0.75, 2.2]) {
        const bar = new THREE.BoxGeometry(6.4, 0.3, 0.45).toNonIndexed();
        bar.translate(0, 0.12, z);
        parts.push(painted(bar, '#8E877C'));
      }
      const geometry = mergeGeometries(parts, false);
      parts.forEach((part) => part.dispose());
      const mesh = new THREE.Mesh(geometry, orePassMaterial);
      mesh.position.set(at.point[0], at.point[1] + 0.12, at.point[2]);
      mesh.rotation.y = Math.atan2(-at.dir[2], at.dir[0]);
      mesh.renderOrder = 2;
      mesh.name = `ore-pass:${entry.id}`;
      orePassGroup.add(mesh);
      orePasses.push({id: String(entry.id), label: typeof entry.label === 'string' ? entry.label : String(entry.id), working: entry.working,
        offsetM: entry.offset_m, point: at.point});
    }
  }

  function setLabels() {
    if (!layout || !view || !state || !state.model) return labels.set([]);
    placeOrePasses();
    const arriving = new Set(fx ? [...fx.closed].map((name) => view.workings[name] && view.workings[name].thingId) : []);
    const placed = loaders.loaded ? [...loaderPlaces.keys()].map((zone) => ({zone, look: actors.equipment ? actors.looks(view).get(zone) : workLook(view.zones[zone]), lines: loaderLines(zone)})) : [];
    return labels.set(labelItems({model: state.model, view, layout, groups, anchors, arriving, loaders: placed, orePasses}));
  }

  const v3 = new THREE.Vector3();
  function project(point) {
    if (!point) return null;
    v3.set(point[0], point[1], point[2]).project(camera);
    const visible = v3.z > -1 && v3.z < 1 && Math.abs(v3.x) < 1.2 && Math.abs(v3.y) < 1.2;
    const x = ((v3.x + 1) / 2) * width;
    const y = ((1 - v3.y) / 2) * height;
    // Pixels per metre at the point, from the distance to the camera (art mode: one scale for the whole view).
    const scale = height / (2 * viewDistance(point) * Math.tan((camera.fov * DEG) / 2));
    return {x, y, visible, scale};
  }

  /**
   * The distance that sets the scale at a scene point: from the camera in perspective; in art mode the distance of
   * the rig, the same for every point (an orthographic camera carries `fov`, camera.js placeCamera).
   */
  function viewDistance(point) {
    if (camera.isOrthographicCamera) return orbit.state.dist;
    return camera.position.distanceTo(new THREE.Vector3(point[0], point[1], point[2]));
  }

  /** How far a point lies in front of the camera, along the ray through it: for comparing depths (picking). */
  function viewDepth(point) {
    if (!camera.isOrthographicCamera) return camera.position.distanceTo(point);
    const forward = new THREE.Vector3();
    camera.getWorldDirection(forward);
    return point.clone().sub(camera.position).dot(forward);
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
        // The situation headline and the horizon rail (variant 3) are covers of the camera (coverRects), not chips.
        fixedObstacles.push({x: rect.left - origin.left - 4, y: rect.top - origin.top - 4, w: rect.width + 8, h: rect.height + 8, key: 'fixed',
          camera: (element.id !== 'legend' || !chip) && !COVERS.some((selector) => element.matches(selector))});
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
    if (thing && thing.kind === 'equipment') return loaders.loaded && loaderPlaces.has(thing.name) ? loaderPoint(thing.name) : null;
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
    decor.textContent = SCENE.decorNote(LOADER_SCALE, FIGURE_SCALE);
    notes.append(vertical, thickness, decor);
    const col = document.createElement('div');
    col.className = 's3__gizmo-text';
    col.append(scale, notes);
    element.append(compass, col);
    let lastAngle = null;
    let lastBar = null;
    let artNotes = null;            // {machine, people}: the notes of the illustrated mine, or null
    let decorShown = true;
    let decorMachines = false;
    let lastFactor = null;
    const writeNotes = () => {
      if (artNotes) {
        vertical.textContent = SCENE.artVertical(lastFactor);
        thickness.textContent = SCENE.artDecor;
        decor.textContent = SCENE.artFigures(artNotes.machine, artNotes.people, decorMachines);
        decor.hidden = false;
        return;
      }
      // The rock around the slabs is decoration (environment.js): said on the short line, the gizmo keeps its size.
      const value = `${SCENE.vertical(lastFactor)} · ${SCENE.massifNote}`;
      if (vertical.textContent !== value) vertical.textContent = value;
      thickness.textContent = SCENE.notToScale;
      decor.hidden = !decorShown;
      decor.textContent = decorMachines ? SCENE.decorEquipment(LOADER_SCALE, FIGURE_SCALE) : SCENE.decorNote(LOADER_SCALE, FIGURE_SCALE);
    };
    return {
      element,
      /** The caption of the loaders (what they mean, how much larger they are drawn), once they are loaded. */
      setDecor(shown, machines = false) {
        decorShown = shown;
        decorMachines = machines;
        writeNotes();
      },
      setVertical(factor) {
        lastFactor = factor;
        writeNotes();
      },
      /** The notes of the illustrated mine ({machine, people}: how much larger machines and figures are), or null. */
      setArtNotes(notesOf) {
        artNotes = notesOf;
        writeNotes();
      },
      update() {
        if (!width) return;
        const target = orbit.state.target;
        const a = project([target.x, target.y, target.z]);
        const north = project([target.x, target.y, target.z - 100]);
        if (a && north) {
          const angle = Math.round((Math.atan2(north.x - a.x, a.y - north.y) * 180) / Math.PI);
          if (Number.isFinite(angle) && angle !== lastAngle) {
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

  /**
   * Ask for one frame. `people`: only for the people walking between publications (or their walk cycle fading):
   * frames of their own that leave data-rendering 'idle' (the camera, the transitions and the refits are at rest),
   * counted by data-tweens.
   */
  function invalidate(people = false) {
    // A hidden page spends nothing; it is drawn again when shown (onVisibility).
    if (disposed || lost || !width || document.hidden) return;
    // A frame already asked for by the walk alone becomes a frame of the stage when something else asks for it.
    if (rafId && (people || root.getAttribute('data-rendering') === 'active')) return;
    if (!rafId) rafId = requestAnimationFrame(frame);
    if (!people && root.getAttribute('data-rendering') !== 'active') {
      root.setAttribute('data-rendering', 'active');
      options.onEvent('frame', {frames});
    }
  }

  function frame(now) {
    rafId = 0;
    if (disposed || lost) return;
    let active = false;
    active = stepIntro(now) || active;
    const cameraMoving = orbit.step(now);
    if (cameraMoving && artOn) spritesDirty = true;
    active = cameraMoving || active;
    active = stepExplode(now) || active;
    const wasWalking = walking;
    const people = stepWalk(now);
    // The loaders play back with the people: placed again in every frame of the walk, and once when it ends.
    if ((people || wasWalking) && actors.equipment) placeLoaders();
    active = stepDrawIn(now) || active;
    active = stepFx(now) || active;
    active = stepSelect(now) || active;
    active = stepScope(now) || active;
    active = stepGhosts(now) || active;
    active = stepArtLamps(now) || active;
    if (loaderFade) {
      loaderFade = loaders.step(now, reduced());
      active = loaderFade || active;
    }
    // The light copies of the loaders while every one is small on the screen.
    if (loaders.loaded) loaders.setDetail(loaderDetail());
    // The figures of people close up first: a marker over a figure stands over its helmet.
    if (actors.drawFigures(now)) spritesDirty = true;
    // The depth rail follows the people where they are drawn (the same playback): told when a drawn depth changed;
    // and the depths the stage shows, in the frame that moved the camera.
    announcePeople();
    announceView();
    // A walk cycle fading in or out after a person started or stopped (actors.js, FADE_MS).
    const cycles = actors.animating;
    if (spritesDirty) buildSprites();
    // The far walls of the massif for this camera (no frame of its own).
    // Art mode: the walls are picked for the viewing direction (a far point along it), never for a panned target.
    environment.update(orbit.art ? {position: camera.position.clone().sub(orbit.state.target).multiplyScalar(100).add(orbit.state.target)} : camera);
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
    root.setAttribute('data-tweens', String(walking ? walk.moving().length : 0));
    // A hidden page asks for no frame (onVisibility draws again when it is shown). People walking between
    // publications ask for frames of their own: the stage is 'idle' for what waits on the camera and transitions.
    if (active && !document.hidden) invalidate();
    else {
      if ((people || cycles) && !document.hidden) invalidate(true);
      // A refit waits for the stage to settle: the stage stays busy until it has run.
      if (!settleTimer) root.setAttribute('data-rendering', 'idle');
    }
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
    // Art mode: the vertical factor is the art's (SPEC §3); the spread of the slabs changes no geometry.
    if (art) {
      explode = target;
      root.setAttribute('data-explode', explode.toFixed(2));
      return;
    }
    finishIntro();
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
  /** The label of a level stands to the left of its slab: this much room, in pixels, is part of the silhouette (poster type). */
  const levelLabelPx = () => (height < 820 ? 110 : 160);
  /** Around a focused object: it stays well inside the free part of the stage. */
  const PAD_FOCUS = {left: 120, right: 120, top: 90, bottom: 80};
  let probe = camera.clone();
  /** The azimuth and elevation of the overview: the main view of the art, or DEFAULT_VIEW. */
  const mainView = () => (art ? {az: art.az, el: art.el} : DEFAULT_VIEW);
  /** What the overview of art mode frames and the pan keeps over: the art's own frame (setArt), else the model's silhouette. */
  const artFrame = () => (art && Array.isArray(art.frame) && art.frame.length >= 2 ? art.frame : null);

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
    // Variant 3: the situation headline (top left) and the horizon rail (right edge) lie over the stage; the picture
    // keeps clear of them as of a panel.
    for (const selector of COVERS) {
      const element = document.querySelector(selector);
      if (element && !element.hidden && overStage(element)) {
        add(element, 6);
        rects[rects.length - 1].soft = true;
      }
    }
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
    placeCamera(probe, target, dist, az, el, width / Math.max(height, 1), orbit.limits.reach);
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
    const silhouettePx = () => hull([...probePixels(vectors), ...probePixels(labelVectors).map(([x, y]) => [x - levelLabelPx(), y])]);
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
    const frame = factor === k ? artFrame() : null;
    const covered = frame && orbit.art && orbit.limits.cover ? coveredOverview(frame) : null;
    const fitted = covered || frameView(frame || silhouette(layout, factor), mainView().az, mainView().el, PAD, rects, frame ? [] : corners);
    // Art mode: the overview is the zoom of 1×, a quarter of its distance the closest (ART_ZOOM_MAX).
    if (orbit.art && factor === k) {
      orbit.limits.distMax = fitted.dist;
      orbit.limits.distMin = fitted.dist / ART_ZOOM_MAX;
    }
    return fitted;
  }

  /**
   * Art mode with the art's coverage: the overview (1×) is the art's main view over the whole stage — its rectangle
   * widened to a wider stage or heightened to a taller one, centred as the art was painted — never larger than what
   * the art covers. The headline, the rail and the panel lie over the art; they do not move it (the framings of a
   * zone or a person keep clear of them).
   */
  function coveredOverview(frame) {
    const {right, up, forward} = orbit.axes;
    const points = frame.map((p) => new THREE.Vector3(p[0], p[1], p[2]));
    const us = points.map((p) => p.dot(right));
    const vs = points.map((p) => p.dot(up));
    const cu = (Math.min(...us) + Math.max(...us)) / 2;
    const cv = (Math.min(...vs) + Math.max(...vs)) / 2;
    const halfW = (Math.max(...us) - Math.min(...us)) / 2;
    const halfH = (Math.max(...vs) - Math.min(...vs)) / 2;
    const aspect = width / Math.max(height, 1);
    const wanted = Math.max(halfH, halfW / aspect);
    const halfView = Math.min(wanted, orbit.largestOnCover(cu, cv, aspect));
    if (!(halfView > 0)) return null;
    const w = points.reduce((sum, p) => sum + p.dot(forward), 0) / points.length;
    const target = new THREE.Vector3().addScaledVector(right, cu).addScaledVector(up, cv).addScaledVector(forward, w);
    return {target, dist: halfView / Math.tan((camera.fov * DEG) / 2), ok: true};
  }

  /** The art's coverage on the view plane of the rig, a little inside its borders (the fade of artenv.js). */
  function setArtCover() {
    if (!art || !art.cover) {
      orbit.setCover(null);
      return;
    }
    const inset = 3;
    orbit.setCover(art.cover.map((corners) => {
      const us = corners.map((p) => new THREE.Vector3(p[0], p[1], p[2]).dot(orbit.axes.right));
      const vs = corners.map((p) => new THREE.Vector3(p[0], p[1], p[2]).dot(orbit.axes.up));
      return {u0: Math.min(...us) + inset, u1: Math.max(...us) - inset, v0: Math.min(...vs) + inset, v1: Math.max(...vs) - inset};
    }));
  }

  function overview(animate = true) {
    if (!layout || !width) return false;
    if (animate) finishIntro();
    overviewMode = true;
    focusId = null;
    const fitted = fitAll();
    const goal = {target: fitted.target, dist: fitted.dist, az: nearestAngle(orbit.state.az, mainView().az), el: mainView().el};
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
    let top = 0;
    let bottom = height;
    // The largest first: the panel, then the horizon rail beside it, then the headline over what is left.
    for (const r of rects.filter((entry) => entry.cover).sort((p, q) => q.w * q.h - p.w * p.h)) {
      if (r.w >= width * 0.6 && r.y > height * 0.2) bottom = Math.min(bottom, Math.max(r.y, 0));
      else if (r.h >= height * 0.6) {
        if (r.x + r.w / 2 > (left + right) / 2) right = Math.min(right, Math.max(r.x, 0));
        else left = Math.max(left, r.x + r.w);
      } else if (r.y < height * 0.2 && r.y + r.h < height * 0.5 && r.w >= (right - left) * 0.4) {
        top = Math.max(top, r.y + r.h);
      }
    }
    return {x: left, y: top, w: Math.max(right - left, 1), h: Math.max(bottom - top, 1)};
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
  function centred(points, fitted, dist, rects = []) {
    const vectors = points.map((p) => new THREE.Vector3(p[0], p[1], p[2]));
    placeProbe(fitted.target, fitted.dist, orbit.state.az, orbit.state.el);
    const centre = probePixels(vectors).reduce((sum, p) => [sum[0] + p[0] / vectors.length, sum[1] + p[1] / vectors.length], [0, 0]);
    const right = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(probe.matrixWorld, 1);
    const mid = vectors.reduce((sum, v) => sum.add(v), new THREE.Vector3()).multiplyScalar(1 / vectors.length);
    const perPixel = (2 * dist * Math.tan((camera.fov * DEG) / 2)) / Math.max(height, 1);
    // The middle of the part of the stage left free (the panel, the horizon rail and the headline excepted).
    const free = freeRect(rects);
    const target = mid.addScaledVector(right, -(centre[0] - (free.x + free.w / 2)) * perPixel)
      .addScaledVector(up, (centre[1] - (free.y + free.h / 2)) * perPixel);
    return {target, dist};
  }

  function fitPoints(points, minDist, rects = coverRects(), leftLabels = []) {
    const fitted = frameView(points, orbit.state.az, orbit.state.el, focusPad(rects), rects, leftLabels);
    // Not closer than minDist: the object is then centred in the free part of the stage, as framed above.
    return fitted.dist >= minDist ? fitted : {...centred(points, fitted, minDist, rects), ok: fitted.ok};
  }

  /**
   * The view that frames a zone by the rule of «показать». When the whole way out does not fit the free part of
   * the stage at a readable scale (the panel over a small stage), the zone, its people and where their
   * routes leave its level are framed instead: never the whole mine shrunk into a strip.
   */
  function zoneGoal(zoneName, rects = coverRects(), walkers = null) {
    if (art) return artZoneGoal(zoneName, rects, walkers);
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

  /**
   * Art mode: a zone is framed close (no rule of one horizon width here): its workings, its tag, the people in it
   * (and those walking out of it) and its face chamber (36 m on the west side of a dead end, mine-art README), at most
   * ART_FRAME_ZOOM times the overview, in the part of the stage the panel, the headline and the rail leave free.
   */
  function artZoneGoal(zoneName, rects, walkers) {
    // During a withdrawal the people walking out of the zone are framed with it.
    const area = zoneArea(zoneName, walkers || new Set(walkersOf(zoneName)));
    if (!area) return null;
    const points = [...area.core];
    const nodesAttr = state.attributes && state.attributes.mine ? state.attributes.mine.nodes || {} : {};
    for (const local of view.zones[zoneName].workings) {
      const line = layout.workings.get(local);
      for (const node of [line.from, line.to]) {
        const at = layout.nodes.get(node);
        if (!at || !nodesAttr[node] || nodesAttr[node].node_kind !== 'dead_end') continue;
        const p = toScene(layout, at, k);
        for (const [dx, dz] of [[-44, -16], [-44, 18], [16, -16], [16, 18]]) points.push([p[0] + dx, p[1], p[2] + dz], [p[0] + dx, p[1] + 14, p[2] + dz]);
      }
    }
    const fitted = artFit(points, rects);
    root.setAttribute('data-framing', `${zoneName} art:${Math.round((orbit.limits.distMax / fitted.dist) * 100) / 100}`);
    return fitted;
  }

  /** Art mode: the view of `points` in the free stage, at most `zoom` times the overview, centred when it fits. */
  function artFit(points, rects, zoom = ART_FRAME_ZOOM) {
    const minDist = orbit.limits.distMax / zoom;
    let fitted = frameView(points, orbit.state.az, orbit.state.el, focusPad(rects), rects);
    {
      // The middle of what is framed in the middle of the free stage (below the headline, beside the panel and the
      // rail), at the distance found, never closer than `zoom`.
      const {right, up, forward} = orbit.axes;
      const vectors = points.map((p) => new THREE.Vector3(p[0], p[1], p[2]));
      const range = (axis) => [Math.min(...vectors.map((v) => v.dot(axis))), Math.max(...vectors.map((v) => v.dot(axis)))];
      const [u0, u1] = range(right);
      const [v0, v1] = range(up);
      const w = vectors.reduce((sum, v) => sum + v.dot(forward), 0) / vectors.length;
      const mid = new THREE.Vector3().addScaledVector(right, (u0 + u1) / 2).addScaledVector(up, (v0 + v1) / 2).addScaledVector(forward, w);
      fitted = centreIn(mid.toArray(), Math.max(fitted.dist, minDist), rects);
    }
    return fitted;
  }

  /**
   * Art mode, a withdrawal: the people walking out of `zoneName` (walkOrigins) and the next stretch of their published
   * routes (ART_WALK_AHEAD_M), centred in the free stage.
   */
  function artWalkGoal(zoneName, rects = coverRects()) {
    const names = walkersOf(zoneName);
    if (names.length === 0) return null;
    const points = [];
    for (const name of names) {
      const at = workerPoint(name);
      if (!at) continue;
      points.push([at[0], at[1], at[2]], [at[0], at[1] + 8, at[2]]);
      const thing = thingByName(state.model, name);
      const worker = view.workers[name];
      const pieces = thing ? geo.routePieces(routeOf(state.model, thing), {working: worker.at, offsetM: worker.offsetM}, (local) => {
        const line = layout.workings.get(local);
        return line ? {from: line.from, to: line.to, lengthM: line.lengthM, total: line.total} : null;
      }) : [];
      let left = ART_WALK_AHEAD_M;
      for (const piece of pieces) {
        if (left <= 0) break;
        const line = layout.workings.get(piece.working);
        const span = Math.abs(piece.end - piece.start);
        const end = piece.start + Math.sign(piece.end - piece.start) * Math.min(span, left);
        const scenePoints = sceneLine(layout, line, k);
        for (let i = 0; i <= 4; i += 1) points.push(geo.pointAt(scenePoints, line.cum, piece.start + ((end - piece.start) * i) / 4).point);
        left -= span;
      }
    }
    if (points.length === 0) return null;
    const fitted = artFit(points, rects, ART_PERSON_ZOOM);
    root.setAttribute('data-framing', `walk:${zoneName} art:${Math.round((orbit.limits.distMax / fitted.dist) * 100) / 100}`);
    return fitted;
  }

  /** The people still walking out who were in `zoneName` when their walk began. */
  function walkersOf(zoneName) {
    return [...walkOrigins].filter(([name, zone]) => zone === zoneName && view.workers[name] && view.workers[name].at
      && view.workers[name].status === 'moving_to_exit').map(([name]) => name).sort();
  }

  /** The zone with the most people still walking out of it, or null. */
  function busiestWalk() {
    const counts = new Map();
    for (const zone of new Set(walkOrigins.values())) counts.set(zone, walkersOf(zone).length);
    const best = [...counts].filter(([, count]) => count > 0).sort((p, q) => q[1] - p[1] || (p[0] < q[0] ? -1 : 1))[0];
    return best ? best[0] : null;
  }

  /** Who walks out of which zone: a person is counted for the zone it stood in when it began to walk out. */
  function trackWalkOrigins(previousRun) {
    if (!view || previousRun !== view.run) walkOrigins.clear();
    if (!view) return;
    const zoneOf = new Map();
    for (const [name, zone] of Object.entries(view.zones)) for (const local of zone.workings) zoneOf.set(local, name);
    for (const [name, worker] of Object.entries(view.workers)) {
      if (walkOrigins.has(name) || worker.status !== 'moving_to_exit' || !worker.at || !zoneOf.has(worker.at)) continue;
      walkOrigins.set(name, zoneOf.get(worker.at));
    }
  }

  /**
   * Art mode, while a withdrawal is followed: the camera frames the walk again, once, when one of its people has left
   * the free stage (never a continuous follow); the zone with the most people still walking when that one is empty.
   */
  function followWalk() {
    if (!artOn || !walkFollow || !view || !width || orbit.gliding) return;
    if (performance.now() - lastTouch < HANDS_OFF_MS || focusId !== walkFollow.focusId) {
      walkFollow = null;
      return;
    }
    let zone = walkFollow.zone;
    if (walkersOf(zone).length === 0) zone = busiestWalk();
    if (!zone) {
      walkFollow = null;
      return;
    }
    const rects = coverRects();
    const free = freeRect(rects);
    const points = walkersOf(zone).map((name) => workerPoint(name)).filter(Boolean);
    const out = projectGoal(points).some((p) => !p.front || p.x < free.x || p.x > free.x + free.w || p.y < free.y || p.y > free.y + free.h);
    if (!out && zone === walkFollow.zone) return;
    const goal = artWalkGoal(zone, rects);
    if (!goal) return;
    walkFollow.zone = zone;
    orbit.glideTo({target: goal.target, dist: goal.dist}, ART_FOLLOW_MS);
    root.setAttribute('data-walk-reframes', String(Number(root.getAttribute('data-walk-reframes') || 0) + 1));
    invalidate();
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
    if (thing.kind === 'equipment') return goalOf(`${LOADER}${thing.name}`, rects);
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
    // One mark (a person, a sensor, an exit): in the middle of the free stage at the smallest distance of its kind; in
    // art mode with a small surrounding, at ART_FRAME_ZOOM times the overview.
    if (points.length === 1) return centreIn(points[0], art ? orbit.limits.distMax / (thing.kind === 'worker' ? ART_PERSON_ZOOM : ART_FRAME_ZOOM) : minDist, rects);
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
    finishIntro();
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
  function incidentHidden(all) {
    const zone = incidentZone();
    const area = zone ? zoneArea(zone) : null;
    if (!area) return false;
    // The panels only: the headline and the rail (soft covers) shape a framing, they never cause one.
    const rects = all.filter((r) => !r.soft);
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
    // Poster-scale markers may lie over a loader: the mark whose centre is nearer the pointer wins.
    const near = overLoader(x, y, true);
    if (best && !(near && near.d < best.d)) return best.thingId;
    if (near) return `${LOADER}${near.zone}`;
    const machine = overLoader(x, y);
    if (machine) return `${LOADER}${machine}`;
    // The art: its invisible pick meshes of the workings (the drawn floors), nearest first.
    if (artOn && artEnv) return pickArtWorking(x, y);
    const hit = stoneDistance(x, y);
    const stoneAt = hit ? viewDepth(hit.point) : Infinity;
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
        const distance = viewDepth(point);
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
  // Art mode: the pointers down on the canvas (two of them pinch: zoom about their middle, pan with it).
  const touches = new Map();
  let pinch = null;
  const local = (event) => {
    const rect = canvas.getBoundingClientRect();
    return {x: event.clientX - rect.left, y: event.clientY - rect.top};
  };

  canvas.addEventListener('contextmenu', (event) => event.preventDefault());
  canvas.addEventListener('pointerdown', (event) => {
    finishIntro();
    canvas.focus({preventScroll: true});
    const at = local(event);
    touches.set(event.pointerId, at);
    canvas.setPointerCapture(event.pointerId);
    if (orbit.art && touches.size === 2) {
      // A second finger: the drag becomes a pinch.
      const [p, q] = [...touches.values()];
      pinch = {d: Math.hypot(p.x - q.x, p.y - q.y), x: (p.x + q.x) / 2, y: (p.y + q.y) / 2};
      dragging = null;
      return;
    }
    if (touches.size > 1) return;
    dragging = {
      id: event.pointerId, x: at.x, y: at.y, startX: at.x, startY: at.y, moved: false, t: performance.now(),
      // Art mode has no rotation: every drag pans.
      kind: orbit.art || event.button === 2 || event.shiftKey ? 'pan' : 'rotate',
    };
  });
  canvas.addEventListener('pointermove', (event) => {
    const at = local(event);
    pointer = at;
    if (touches.has(event.pointerId)) touches.set(event.pointerId, at);
    if (pinch && touches.size === 2) {
      const [p, q] = [...touches.values()];
      const d = Math.hypot(p.x - q.x, p.y - q.y);
      const mid = {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2};
      if (pinch.d > 0 && d > 0) orbit.zoom(pinch.d / d, true, {x: mid.x, y: mid.y, width, height});
      orbit.drag('pan', mid.x - pinch.x, mid.y - pinch.y, height, 0);
      pinch = {d, x: mid.x, y: mid.y};
      userMoved();
      hideTip();
      invalidate();
      return;
    }
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
    touches.delete(event.pointerId);
    if (touches.size < 2) pinch = null;
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
    finishIntro();
    const factor = Math.exp(Math.max(Math.min(event.deltaY, 200), -200) * 0.0015);
    // Art mode: smoothed, towards the pointer (a pinch of a touchpad comes as a wheel with Ctrl).
    if (orbit.art) orbit.zoom(factor, true, {...local(event), width, height});
    else orbit.zoom(factor, false);
    userMoved();
    invalidate();
  }, {passive: false});
  canvas.addEventListener('keydown', (event) => {
    finishIntro();
    const step = 15 * DEG;
    const panBy = orbit.state.dist * 0.12;
    let handled = true;
    // Art mode: the arrows pan along the screen (with or without Shift); there is no rotation.
    if (orbit.art && event.key.startsWith('Arrow')) {
      const move = {ArrowLeft: [-panBy, 0], ArrowRight: [panBy, 0], ArrowUp: [0, panBy], ArrowDown: [0, -panBy]}[event.key];
      if (move) {
        event.preventDefault();
        orbit.pan(move[0], move[1]);
        userMoved();
        invalidate();
        return;
      }
    }
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
    freeCacheAt = 0;
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
    spriteScale = Math.min(Math.max(height / 1000, 0.66), 1);
    root.toggleAttribute('data-compact', height < 820);
    spritesDirty = true;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    camera.aspect = width / height;
    if (orbit.art && orbit.limits.cover && layout && art && art.frame) {
      // Art mode on its coverage: another shape of the stage changes how much one view shows. The 1× view and the
      // camera are fitted to it at once (the refit after the size has settled comes too): no frame shows the stage
      // beyond the art.
      fitAll();
      orbit.reclamp();
    } else if (orbit.art) orbit.apply();
    else camera.updateProjectionMatrix();
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
  for (const id of ['stage-hud', 'panel', 'rail-region', 'pending', 'headline', 'horizons']) {
    const element = document.getElementById(id);
    if (element) resizeObserver.observe(element);
  }
  // Panels that unfold over the stage change no size of the stage: the body names them.
  const coverObserver = new MutationObserver(() => settleSoon('panel'));
  coverObserver.observe(document.body, {attributes: true, attributeFilter: ['data-stand', 'data-panel', 'data-sheet', 'data-rail', 'data-situation']});

  // ---- a hidden page -----------------------------------------------------------------------

  /** Shown again: the newest published state at once (no queue of publications is replayed), then one frame. */
  const onVisibility = () => {
    if (document.hidden || disposed) return;
    snapMotion();
    if (orbit.gliding) orbit.set(orbit.goal);
    spritesDirty = true;
    invalidate();
  };
  document.addEventListener('visibilitychange', onVisibility);

  // ---- art mode ----------------------------------------------------------------------------

  /**
   * Art mode on (`spec`: {az, el, k, frame} of the art's main view; az and el in radians, missing fields from
   * ART_DEFAULT) or off (null): the camera becomes the orthographic rig of artcamera.js (pan and zoom only) or the
   * perspective orbit again, the vertical factor the art's k or the spread of the slabs, and the stage returns to the
   * overview. `frame` (optional): scene points [x, y, z] that the overview (1×) frames and the pan stays over instead
   * of the model's silhouette, e.g. the corners of the MainView's rectangle at its target. Phase II calls it when the
   * art's GLB matches the topology, with the values read from the GLB (scene.extras.k, the MainView camera node).
   */
  function setArt(spec) {
    // A running intro ends; one still held (waiting for the first state or the art) starts in the new picture.
    if (intro && !intro.hold) finishIntro();
    const next = spec ? {
      az: Number.isFinite(spec.az) ? spec.az : ART_DEFAULT.az,
      el: Number.isFinite(spec.el) ? spec.el : ART_DEFAULT.el,
      k: Number.isFinite(spec.k) && spec.k > 0 ? spec.k : ART_DEFAULT.k,
      frame: Array.isArray(spec.frame) ? spec.frame.filter((p) => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite)) : null,
      // What the art's textures cover (artenv.js view.cover: the corners of each block of its atlas), or null.
      cover: Array.isArray(spec.cover) && spec.cover.length > 0 ? spec.cover : null,
    } : null;
    if (!next && !art) return;
    art = next;
    explodeTween = null;
    const aspect = width && height ? width / height : 1;
    if (art) {
      camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 10000);
      // The custom fields of placeCamera: dist means the same as for the perspective orbit.
      camera.fov = FOV;
      camera.aspect = aspect;
      orbit = createArtRig(camera, {reducedMotion: reduced, az: art.az, el: art.el});
      k = art.k;
      setArtCover();
    } else {
      camera = new THREE.PerspectiveCamera(FOV, aspect, 1, 10000);
      orbit = createOrbit(camera, {reducedMotion: reduced});
      k = verticalFactor(explode);
    }
    probe = camera.clone();
    root.toggleAttribute('data-art', Boolean(art));
    gizmo.setVertical(k);
    if (layout) {
      applyK();
      overview(false);
      if (view && state && state.model) canvas.setAttribute('aria-label', summary());
    }
    spritesDirty = true;
    invalidate();
  }

  // ---- the depth rail (view/horizons.js) -------------------------------------------------------

  /**
   * The people as drawn now, for the depth rail: [{name, thingId, z, working, moving}], z the mine elevation (m) of
   * the place where the figure stands (the playback of walk.js, as the figures and markers). Published places only.
   */
  function people() {
    if (!layout || !view) return [];
    const out = [];
    for (const [name, worker] of Object.entries(view.workers)) {
      if (!worker.at) continue;
      const position = currentPosition(name);
      const at = position ? pointOnWorking(layout, position.working, position.offsetM, k) : null;
      if (!at) continue;
      out.push({name, thingId: worker.thingId, z: at.point[1] / k + layout.zTop, working: position.working, moving: Boolean(position.moving)});
    }
    return out.sort((p, q) => (p.name < q.name ? -1 : (p.name > q.name ? 1 : 0)));
  }

  /**
   * The loaders as drawn now, for the depth rail: [{name, thingId, z, working, moving}], z the mine elevation (m) of
   * the place where the machine stands (the same playback as the people). Published places only.
   */
  function machines() {
    if (!layout || !view || !actors.equipment) return [];
    const out = [];
    for (const [name, place] of loaderPlaces) {
      const machine = view.equipment[name];
      const at = machine ? pointOnWorking(layout, place.working, place.offsetM, k) : null;
      if (!at) continue;
      out.push({name, thingId: machine.thingId, z: at.point[1] / k + layout.zTop, working: place.working, moving: Boolean(place.moving)});
    }
    return out.sort((p, q) => (p.name < q.name ? -1 : (p.name > q.name ? 1 : 0)));
  }

  /** Tell the stage (and so the depth rail) when a drawn depth changed: once per change, from the frame that drew it. */
  function announcePeople() {
    const key = [...people(), ...machines()].map((p) => `${p.name}:${p.z.toFixed(2)}`).join('|');
    if (key === peopleKey) return;
    peopleKey = key;
    options.onEvent('people');
  }

  // ---- the depth rail as a scroll control ----------------------------------------------------------

  /** The free part of the stage (as the framings use it), re-read at most every 500 ms (the rail reads it per frame). */
  function freeForDepth() {
    const now = performance.now();
    if (!freeCache || now - freeCacheAt > 500) {
      freeCache = freeRect(coverRects());
      freeCacheAt = now;
    }
    return freeCache;
  }

  /** The camera's up on the screen, in the scene (no roll: its height share is cos(el)). */
  const screenUp = (az, el) => new THREE.Vector3(-Math.sin(el) * Math.sin(az), Math.cos(el), -Math.sin(el) * Math.cos(az));

  /**
   * The mine elevation seen at the stage row `row` (pixels from the top) for a view {target, dist, el}: the point of
   * that row on the plane through the target facing the camera (the same for the orthographic rig and the orbit).
   */
  function depthAtRow(row, view) {
    const perPixel = (2 * view.dist * Math.tan((camera.fov * DEG) / 2)) / Math.max(height, 1);
    const y = view.target.y + Math.cos(view.el) * (height / 2 - row) * perPixel;
    return y / k + layout.zTop;
  }

  /** The view now and the view the camera goes to, as {target, dist, el, az}. */
  const viewNow = () => ({target: orbit.state.target, dist: orbit.state.dist, el: orbit.state.el, az: orbit.state.az});
  const viewGoal = () => {
    const g = orbit.goal;
    return {target: g.target, dist: g.dist, el: Number.isFinite(g.el) ? g.el : orbit.state.el, az: Number.isFinite(g.az) ? g.az : orbit.state.az};
  };

  /** True when a view is the overview (1×): the art's zoom range, or the overview of the orbit. */
  function atOverview(view) {
    if (orbit.art) return view.dist >= orbit.limits.distMax * 0.97;
    return overviewMode;
  }

  /**
   * What the stage shows in depth (the depth rail's window): the mine elevations at the top, the middle and the
   * bottom of the free stage now ({top, centre, bottom}), the middle where the camera goes (goalCentre), the zoom
   * (art mode) and whether this is the overview. Null without a mine.
   */
  function depthView() {
    if (!layout || !width || !height) return null;
    const free = freeForDepth();
    const now = viewNow();
    const goal = viewGoal();
    const mid = free.y + free.h / 2;
    return {
      top: depthAtRow(free.y, now), centre: depthAtRow(mid, now), bottom: depthAtRow(free.y + free.h, now),
      goalCentre: depthAtRow(mid, goal), goalTop: depthAtRow(free.y, goal), goalBottom: depthAtRow(free.y + free.h, goal),
      zoom: orbit.art ? orbit.zoomFactor : null, overview: atOverview(goal), gliding: orbit.gliding, art: Boolean(orbit.art),
    };
  }

  function announceView() {
    const view = depthView();
    const key = view ? [view.top, view.bottom].map((v) => v.toFixed(2)).join() : '';
    if (key === viewKey) return;
    viewKey = key;
    options.onEvent('view');
  }

  /**
   * Scroll the camera through depth (the depth rail): `to` a mine elevation or `by` metres (up positive) for the
   * middle of the free stage, moving along the screen's up so the horizontal place is kept; settling in `ms`
   * (0: at once, a drag); `read`: from the overview, zoom to a depth reading (DEPTH_READ_ZOOM) at that depth. The
   * pan clamp of the art keeps the stage on the art (the scroll stops at its limits). Returns the depth the
   * middle goes to, or null.
   */
  function scrollDepth({to = null, by = null, ms = 360, read = false} = {}) {
    if (!layout || !width || !state || !state.model) return null;
    finishIntro();
    const free = freeForDepth();
    const mid = free.y + free.h / 2;
    const goal = viewGoal();
    let dist = goal.dist;
    if (read) dist = orbit.art ? orbit.limits.distMax / DEPTH_READ_ZOOM : fitAll().dist / DEPTH_READ_ZOOM;
    const from = depthAtRow(mid, {...goal, dist});
    const wanted = Number.isFinite(to) ? to : from + (Number.isFinite(by) ? by : 0);
    // The plane's height moves by s·cos(el) for a move s along the screen's up.
    const shift = ((wanted - from) * k) / Math.max(Math.cos(goal.el), 1e-3);
    userMoved();
    if (orbit.art) {
      if (read) {
        const target = goal.target.clone().addScaledVector(orbit.axes.up, shift);
        orbit.glideTo({target, dist}, ms);
      } else {
        orbit.pan(0, shift, ms);
      }
    } else {
      const target = goal.target.clone().addScaledVector(screenUp(goal.az, goal.el), shift);
      orbit.glideTo({target, dist}, ms);
    }
    invalidate();
    return depthAtRow(mid, viewGoal());
  }

  /** The scene height of a mine elevation (the one transform of layout.js). */
  const depthY = (z) => (z - layout.zTop) * k;

  /**
   * The depth probe: a thin glowing guide at the mine elevation `z` (m) across the massif, or none (null). Over the
   * art a contour line where that depth meets the drawn rock (artenv.js, the probe uniforms); over the slabs of
   * variant 3 a faint sheet at that depth with a glowing rim. One frame per call; true when drawn.
   */
  function setDepthProbe(z) {
    const next = Number.isFinite(z) && layout ? z : null;
    if (next === null && depthProbe === null) return false;
    if (next !== null && depthProbe && Math.abs(depthProbe.z - next) < 1e-6) return true;
    placeDepthProbe(next);
    invalidate();
    return next !== null;
  }

  function placeDepthProbe(z) {
    for (const mesh of [...probeGroup.children]) {
      probeGroup.remove(mesh);
      mesh.geometry.dispose();
    }
    if (z === null || !layout) {
      depthProbe = null;
      probeGroup.visible = false;
      probeUniforms.uProbe.value.set(0, 0, 0, 0);
      root.removeAttribute('data-depth-probe');
      return;
    }
    const y = depthY(z);
    depthProbe = {z, y};
    root.setAttribute('data-depth-probe', String(Math.round(z * 10) / 10));
    if (artOn) {
      // The art's rock draws its own contour at this height (artenv.js).
      probeUniforms.uProbe.value.set(y, 1, 0, 0);
      probeGroup.visible = false;
      return;
    }
    probeUniforms.uProbe.value.set(0, 0, 0, 0);
    // The slabs of variant 3: the plan of the mine with a margin, at that height; its rim about 2 px wide.
    const xs = [];
    const zs = [];
    for (const level of layout.levels) {
      xs.push(level.box.minX, level.box.maxX);
      zs.push(level.box.minZ, level.box.maxZ);
    }
    for (const line of layout.workings.values()) {
      for (const p of line.plan) {
        xs.push(p[0]);
        zs.push(p[1]);
      }
    }
    const m = 24;
    const [x0, x1, z0, z1] = [Math.min(...xs) - m, Math.max(...xs) + m, Math.min(...zs) - m, Math.max(...zs) + m];
    const loop = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
    const perPixel = (2 * orbit.state.dist * Math.tan((camera.fov * DEG) / 2)) / Math.max(height, 1);
    const parts = [[plane(x0, x1, z0, z1, 0), materials.probeFill, 30], [ribbon(loop, perPixel * 7, 0, {closed: true}), materials.probeHalo, 31],
      [ribbon(loop, perPixel * 1.6, 0, {closed: true}), materials.probeCore, 32]];
    for (const [geometry, material, order] of parts) {
      const mesh = meshOf(geometry, material, order);
      if (mesh) {
        mesh.frustumCulled = false;
        probeGroup.add(mesh);
      }
    }
    probeGroup.position.y = y;
    probeGroup.visible = true;
  }

  /**
   * The outlines of a horizon's workings glow softly (the accent-tinted outline of a horizon), the rest untouched;
   * null takes it away. A horizon without workings of its own (the surface) glows round the mouths of the ramps that
   * reach it. One frame per call; true when something is highlighted.
   */
  function setLevelHighlight(name) {
    const next = layout && typeof name === 'string' && layout.levels.some((level) => level.name === name) ? name : null;
    if (next === levelLit) return next !== null;
    levelLit = next;
    buildLevelHighlight();
    invalidate();
    return next !== null;
  }

  function buildLevelHighlight() {
    for (const mesh of [...highlightGroup.children]) {
      highlightGroup.remove(mesh);
      mesh.geometry.dispose();
    }
    const level = levelLit && layout ? layout.levels.find((entry) => entry.name === levelLit) : null;
    if (!level) {
      root.removeAttribute('data-level-lit');
      return;
    }
    const key = `${level.name}|${artOn ? 'art' : 'slab'}`;
    if (!highlightLoops.has(key)) {
      const segments = [];
      for (const name of level.workings) {
        const line = layout.workings.get(name);
        for (let i = 1; i < line.plan.length; i += 1) segments.push({a: line.plan[i - 1], b: line.plan[i], half: DIMS.half});
      }
      // The mouths of the workings between levels that reach this one (the ramps at the surface).
      for (const line of layout.workings.values()) {
        if (!line.between) continue;
        for (const [node, plan] of [[line.from, line.plan], [line.to, [...line.plan].reverse()]]) {
          if (layout.nodeLevel.get(node) !== level.name || plan.length < 2) continue;
          const d = Math.hypot(plan[1][0] - plan[0][0], plan[1][1] - plan[0][1]);
          const t = d > 0 ? Math.min(1, 24 / d) : 0;
          segments.push({a: plan[0], b: [plan[0][0] + (plan[1][0] - plan[0][0]) * t, plan[0][1] + (plan[1][1] - plan[0][1]) * t], half: DIMS.half});
        }
      }
      highlightLoops.set(key, {loops: frameLoops(segments, artOn ? -1.2 : 2.5), plans: level.workings.map((name) => layout.workings.get(name).plan)});
    }
    const {loops, plans} = highlightLoops.get(key);
    const lift = artOn ? 0.16 : DIMS.depth + 0.14;
    const halo = merge(loops.map((loop) => ribbon(loop, 5, lift, {closed: true})));
    const core = merge(loops.map((loop) => ribbon(loop, 1.2, lift + 0.01, {closed: true})));
    const wash = merge(plans.map((plan) => ribbon(plan, DIMS.half * 2 - 1.2, 0.15)));
    const parts = [[wash, materials.levelWash, 8], [halo, materials.levelHalo, 9], [core ? core.clone() : null, materials.levelGhost, 10],
      [core, materials.levelCore, 11]];
    for (const [geometry, material, order] of parts) {
      const mesh = meshOf(geometry, material, order);
      if (mesh) highlightGroup.add(mesh);
    }
    highlightGroup.position.y = levelY(layout, level, k);
    root.setAttribute('data-level-lit', level.name);
  }

  // ---- the illustrated mine (env.glb of the art) ------------------------------------------------

  /** True when the art's topology signature equals the one of the live twins (the art was built for this mine). */
  function artMatches(next = state) {
    if (!artHeader || !next || !next.model || !next.attributes || !next.attributes.mine) return false;
    if (artHeader.extras.mineArt !== 1) return false;
    const signature = artSignature(thingsOfKind(next.model, 'working'), next.attributes.mine.nodes || {});
    return Boolean(signature) && signature.sha1 === artHeader.extras.topology;
  }

  /** The origin of the art (its GLB's cx, cy, zTop), for a layout of the topology it was built for. */
  function artOrigin() {
    const extras = artHeader ? artHeader.extras : {};
    return {cx: extras.cx, cy: extras.cy, zTop: Number.isFinite(extras.zTop) ? extras.zTop : 0};
  }

  /** Show the art when it was built for this topology, else the procedural scene of variant 3 (async: loads once). */
  async function checkArt() {
    if (disposed || !layout || artHeader === undefined) {
      maybeStartIntro();
      return;
    }
    const match = artMatches();
    if (!match) {
      if (artOn) disableArtEnv();
      root.setAttribute('data-art-env', 'off');
      maybeStartIntro();
      return;
    }
    if (artOn) {
      applyArtVisibility();
      return;
    }
    root.setAttribute('data-art-env', 'loading');
    if (!artEnv) {
      if (!artEnvLoading) {
        const anisotropy = low ? 1 : Math.min(8, renderer.capabilities.getMaxAnisotropy());
        artEnvLoading = loadArtEnv(artHeader, {anisotropy, edgeColor: TOKEN.ink0, light: low, probe: probeUniforms}).then((env) => {
          artEnv = env;
        }).catch(() => {
          artHeader = null;
        });
      }
      await artEnvLoading;
      if (disposed) return;
      if (!artEnv || !artMatches() || artOn || !layout) {
        if (!artEnv) root.setAttribute('data-art-env', 'off');
        maybeStartIntro();
        return;
      }
    }
    enableArtEnv();
  }

  /** The art on: its camera (MainView), its k and origin, its environment instead of the slabs, its actors. */
  function enableArtEnv() {
    const origin = artOrigin();
    if ([['cx', layout.cx], ['cy', layout.cy], ['zTop', layout.zTop]].some(([key, value]) => Math.abs(origin[key] - value) > 1e-6)) {
      layout = buildLayout(state.model, state.attributes.mine, origin);
      buildStatic();
    }
    artOn = true;
    if (!artGroup.children.includes(artEnv.group)) artGroup.add(artEnv.group);
    loaderCandidates = new Map();
    loaderPlaces = new Map();
    loaderRun = null;
    setArt({az: artEnv.view.az, el: artEnv.view.el, k: artEnv.extras.k, frame: artEnv.view.frame, cover: artEnv.view.cover});
    applyArtVisibility();
    placeLoaders();
    gizmo.setArtNotes({machine: ART_MACHINE_FACTOR, people: Math.round(ART_FIGURE_FACTOR * 10) / 10});
    root.setAttribute('data-art-env', 'on');
    actors.loadFigure(ART_URL('actors/worker.glb'), {scale: ART_FIGURE_SCALE, maxCycles: ART_MAX_CYCLES}).then((taken) => {
      if (disposed) return;
      if (!artOn) actors.clearRig();
      root.setAttribute('data-art-figure', taken && actors.rigged ? 'worker.glb' : 'none');
      spritesDirty = true;
      invalidate();
    });
    loadArtMachines();
    if (view) buildOverlays();
    if (levelLit) buildLevelHighlight();
    if (depthProbe) placeDepthProbe(depthProbe.z);
    setLabels();
    spritesDirty = true;
    invalidate();
    maybeStartIntro();
  }

  /** Back to the procedural scene of variant 3 (another topology). */
  function disableArtEnv() {
    artOn = false;
    setArt(options.art || null);
    actors.clearRig();
    gizmo.setArtNotes(null);
    loaderCandidates = state && state.model && !actors.equipment ? candidatesOfLoaders() : new Map();
    loaderPlaces = new Map();
    loaderRun = null;
    applyArtVisibility();
    placeLoaders();
    if (view) {
      chooseLoaderPlaces();
      buildOverlays();
    }
    if (levelLit) buildLevelHighlight();
    if (depthProbe) placeDepthProbe(depthProbe.z);
    setLabels();
    invalidate();
  }

  /** What the art replaces is hidden while it is shown: the slabs, the ramps, the desk, the massif, the zone loaders. */
  function applyArtVisibility() {
    const on = artOn;
    for (const group of levelGroups) {
      for (const child of group.children) if (!overlayGroups.includes(child)) child.visible = !on;
    }
    interGroup.visible = !on;
    if (desk) desk.visible = !on;
    if (on) loaders.group.visible = false;
    else if (!intro) loaders.group.visible = true;
    environment.group.visible = !on && Boolean(layout);
    artGroup.visible = on;
  }

  /** The machines of the art at their anchors: the loaders of the zones (lamps by work state), the parked truck and drill. */
  function loadArtMachines() {
    if (artMachines) return;
    if (artMachinesLoading || !artEnv) return;
    const kinds = ['lhd', 'truck', 'drill'];
    artMachinesLoading = Promise.all(kinds.map((kind) => loadArtMachine(ART_URL(`actors/${kind}.glb`)).catch(() => null))).then((loaded) => {
      if (disposed) return;
      const byKind = Object.fromEntries(kinds.map((kind, i) => [kind, loaded[i]]));
      artMachineSources = byKind;
      const group = new THREE.Group();
      group.name = 'art-machines';
      const zone = [];
      const decor = [];
      for (const [name, anchor] of artEnv.anchors) {
        const kind = anchor.extras.kind || name.split('_')[0];
        const source = byKind[kind];
        if (!source) continue;
        const made = source.make();
        made.group.position.copy(anchor.position);
        made.group.quaternion.copy(anchor.quaternion);
        // Built at extras.scaleToReal (1.5× real): drawn at ART_MACHINE_FACTOR, from its ground centre (the anchor).
        const built = Number.isFinite(source.extras.scaleToReal) && source.extras.scaleToReal > 0 ? source.extras.scaleToReal : 1.5;
        made.group.scale.setScalar(ART_MACHINE_FACTOR / built);
        made.group.updateMatrixWorld(true);
        group.add(made.group);
        const entry = {name, kind, zone: anchor.extras.zone || null, made, light: 0, fade: null};
        if (entry.zone) zone.push(entry);
        else decor.push(entry);
      }
      artGroup.add(group);
      artMachines = {group, zone, decor, equip: new Map()};
      placeArtEquipment();
      updateArtLamps(false);
      root.setAttribute('data-art-machines', String(zone.length + decor.length));
      invalidate();
    });
  }

  /** The heap of rock in a loaded bucket: a few low facets, shaded as the art is (light from above, unlit material). */
  function rockHeap() {
    if (rockGeometry) return rockGeometry;
    const parts = [];
    // Ore heaped over the rim of the bucket (front, +X; the rim stands about 2.3 m high in lhd.glb), lighter than the
    // gravel of the floors so that a loaded bucket reads at a glance.
    const stones = [[6.25, 1.9, 0, 1.1], [5.85, 2.15, -1.05, 0.85], [5.9, 2.1, 1.0, 0.86], [6.75, 1.65, -0.85, 0.75],
      [6.7, 1.65, 0.9, 0.76], [6.15, 2.7, 0.15, 0.7], [5.75, 2.6, -0.6, 0.55]];
    const base = new THREE.Color('#9A8268');
    const shade = new THREE.Color();
    stones.forEach(([x, y, z, r], index) => {
      const stone = new THREE.IcosahedronGeometry(r, 0).toNonIndexed();
      stone.scale(1, 0.62, 1);
      stone.rotateY(index * 0.9);
      stone.translate(x, y, z);
      stone.computeVertexNormals();
      const normals = stone.attributes.normal;
      const colours = new Float32Array(normals.count * 3);
      for (let i = 0; i < normals.count; i += 1) {
        // Painted light from above and a little from the front; darker facets below.
        const light = 0.55 + 0.45 * Math.max(0, normals.getY(i) * 0.85 + normals.getX(i) * 0.15);
        shade.copy(base).multiplyScalar(light * (0.92 + 0.08 * ((index * 7) % 3)));
        colours.set([shade.r, shade.g, shade.b], i * 3);
      }
      stone.setAttribute('color', new THREE.BufferAttribute(colours, 3));
      stone.deleteAttribute('uv');
      parts.push(stone);
    });
    rockGeometry = mergeGeometries(parts, false);
    parts.forEach((part) => part.dispose());
    return rockGeometry;
  }

  /**
   * Art mode with equipment twins: the art's loader for each published machine at the place where the scene draws it
   * (the playback), turned as its working runs; the zones' own loaders of the art are hidden. Without equipment twins,
   * the zones' loaders as before.
   */
  function placeArtEquipment() {
    if (!artMachines) return;
    const equipment = actors.equipment && artOn;
    for (const entry of artMachines.zone) entry.made.group.visible = !actors.equipment;
    const places = equipment && layout ? loaderPlaces : new Map();
    for (const [name, entry] of [...artMachines.equip]) {
      if (places.has(name)) continue;
      artMachines.group.remove(entry.made.group);
      if (entry.made.lampMaterial) entry.made.lampMaterial.dispose();
      artMachines.equip.delete(name);
    }
    const loaded = new Set(view ? actors.loadedOf(view) : []);
    for (const [name, place] of places) {
      let entry = artMachines.equip.get(name);
      if (!entry) {
        const source = artMachineSources && artMachineSources.lhd;
        if (!source) continue;
        const made = source.make();
        const built = Number.isFinite(source.extras.scaleToReal) && source.extras.scaleToReal > 0 ? source.extras.scaleToReal : 1.5;
        made.group.scale.setScalar(ART_MACHINE_FACTOR / built);
        made.group.name = `art-lhd:${name}`;
        const rock = new THREE.Mesh(rockHeap(), new THREE.MeshBasicMaterial({vertexColors: true}));
        rock.name = 'rock';
        rock.visible = false;
        made.group.add(rock);
        artMachines.group.add(made.group);
        const thing = state && state.model ? thingByName(state.model, name) : null;
        entry = {name, kind: 'lhd', zone: thing && typeof thing.attrs.zone === 'string' ? thing.attrs.zone : null, made, rock,
          light: 0, fade: null, published: true};
        artMachines.equip.set(name, entry);
        updateArtLamps(false);
      }
      const at = pointOnWorking(layout, place.working, place.offsetM, k);
      if (!at) {
        entry.made.group.visible = false;
        continue;
      }
      const dir = place.facing > 0 ? at.dir : at.dir.map((v) => -v);
      entry.made.group.position.set(at.point[0], at.point[1] + 0.02, at.point[2]);
      entry.made.group.rotation.set(0, Math.atan2(-dir[2], dir[0]), 0);
      entry.made.group.visible = true;
      entry.rock.visible = loaded.has(name);
      entry.made.group.updateMatrixWorld(true);
    }
  }

  /**
   * A loader that yields (published `activity = yielding`) to a person (`yielding_to`): a thin neutral line from its
   * roof to the marker of that person, as drawn now. It goes with the first publication that no longer says so.
   */
  function placeYieldLines() {
    const pairs = [];
    if (view && layout && actors.equipment) {
      for (const [name, machine] of Object.entries(view.equipment)) {
        if (machine.activity !== 'yielding' || !machine.yieldingTo || !loaderPlaces.has(name)) continue;
        const person = view.workers[machine.yieldingTo];
        if (!person || !person.at) continue;
        pairs.push([name, machine.yieldingTo]);
      }
    }
    // Nothing to draw and nothing drawn: no new geometry (this runs in every frame of a walk).
    if (pairs.length === 0 && yieldDrawn.length === 0) return;
    const points = [];
    for (const [name, person] of pairs) {
      const from = loaderPoint(name, 2.6);
      const position = currentPosition(person);
      const at = position ? pointOnWorking(layout, position.working, position.offsetM, k) : null;
      if (!from || !at) continue;
      const lift = artOn ? ART_FIGURE_SCALE * 5 * 0.6 : 3;
      points.push(from, [at.point[0], at.point[1] + lift, at.point[2]]);
    }
    yieldDrawn = pairs;
    yieldLines.geometry.dispose();
    yieldLines.geometry = new THREE.BufferGeometry();
    yieldLines.geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(points.flat()), 3));
    yieldLines.visible = points.length > 0;
    root.setAttribute('data-yielding', pairs.map((pair) => pair.join('>')).join(' '));
  }

  /**
   * The lamps of a zone's loader: lit while the zone's published work state is `working`, dark otherwise. The lamps of
   * a published loader: by its own published state (ART_LHD_LAMP).
   */
  function updateArtLamps(animate) {
    if (!artMachines) return;
    const looks = view && actors.equipment ? actors.looks(view) : new Map();
    for (const entry of [...artMachines.zone, ...artMachines.equip.values()]) {
      const zone = view && view.hasSnapshot ? view.zones[entry.zone] : null;
      const lit = entry.published ? ART_LHD_LAMP[looks.get(entry.name) || 'unknown'] ?? 0 : (zone && zone.workState === 'working' ? 1 : 0);
      const goal = entry.fade ? entry.fade.to : entry.light;
      if (goal === lit) continue;
      if (animate && !reduced()) entry.fade = {from: entry.light, to: lit, start: null};
      else {
        entry.fade = null;
        entry.light = lit;
      }
    }
    applyArtLamps();
  }

  function applyArtLamps() {
    if (!artMachines) return;
    for (const entry of [...artMachines.zone, ...artMachines.decor, ...artMachines.equip.values()]) {
      const {lampMaterial, lampOn, lampOff} = entry.made;
      if (lampMaterial) lampMaterial.color.copy(lampOff).lerp(lampOn, entry.light);
    }
  }

  /** One frame of the lamps' fades (ART_LAMP_MS, once per change); true while one runs. */
  function stepArtLamps(now) {
    if (!artMachines) return false;
    let active = false;
    for (const entry of [...artMachines.zone, ...artMachines.equip.values()]) {
      if (!entry.fade) continue;
      if (entry.fade.start === null) entry.fade.start = now;
      const t = Math.min((now - entry.fade.start) / ART_LAMP_MS, 1);
      entry.light = entry.fade.from + (entry.fade.to - entry.fade.from) * t;
      if (t >= 1) entry.fade = null;
      else active = true;
    }
    applyArtLamps();
    return active;
  }

  /** The working whose pick mesh of the art lies under a screen point, if any. */
  function pickArtWorking(x, y) {
    raycaster.setFromCamera(new THREE.Vector2((x / width) * 2 - 1, 1 - (y / height) * 2), camera);
    for (const hit of raycaster.intersectObjects(artEnv.picks, false)) {
      const working = view.workings[hit.object.userData.working];
      if (working) return working.thingId;
    }
    return null;
  }

  /** For tests: the box a machine of the art takes in the scene (axis-aligned, scene metres): [minX, minY, minZ, maxX, maxY, maxZ]. */
  function machineBox(entry) {
    // The body and its lamps; the contact shadow on the floor (renderOrder 1, loadArtMachine) is no part of the machine.
    entry.made.group.updateMatrixWorld(true);
    const box = new THREE.Box3();
    for (const mesh of entry.made.group.children) if (mesh.renderOrder !== 1) box.expandByObject(mesh);
    return [...box.min.toArray(), ...box.max.toArray()].map((v) => Math.round(v * 100) / 100);
  }

  /** For tests: the height of the art's floor under each drawn figure, minus the height of its feet (metres). */
  function floorGaps() {
    if (!artOn || !artEnv) return null;
    const figures = actors.info().figures;
    const out = {};
    const ray = new THREE.Raycaster();
    for (const [name, feet] of Object.entries(figures.feet || {})) {
      ray.set(new THREE.Vector3(feet[0], feet[1] + 4, feet[2]), new THREE.Vector3(0, -1, 0));
      ray.far = 12;
      const hit = ray.intersectObjects(artEnv.group.children, false)[0];
      out[name] = hit ? Math.round((hit.point.y - feet[1]) * 100) / 100 : null;
    }
    return out;
  }

  // Read the header of the art at once: the stage decides between the art and the procedural scene when it knows it.
  (options.artEnv === false ? Promise.reject(new Error('art off')) : readGlbHeader(ART_URL('env.glb'))).then((header) => {
    artHeader = header;
  }).catch(() => {
    artHeader = null;
  }).then(() => {
    if (!disposed) checkArt();
  });

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
      // Another mine (or the first one) under a running intro: it ends first.
      finishIntro();
      attributesRef = next.attributes;
      // A topology the art was built for is laid out in the art's origin (its GLB's cx, cy, zTop).
      layout = buildLayout(next.model, next.attributes.mine, artMatches(next) ? artOrigin() : null);
      walk.clear();
      walkSnapshot = null;
      buildStatic();
      rebuilt = true;
      root.setAttribute('data-levels', String(layout ? layout.levels.length : 0));
      root.setAttribute('data-workings', String(layout ? layout.workings.size : 0));
      if (layout) {
        applyK();
        if (overviewMode || !width) overview(false);
        checkArt();
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
      // A publication that moved nobody still tells the walk when it came (the interval of the playback).
      if (publishPlaces(previousRun)) invalidate();
      if (!linkNowOk) snapMotion();
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
    publishPlaces(previousRun);
    trackWalkOrigins(previousRun);
    actors.update(view, layout);
    placeLoaders();
    if (!linkNowOk) snapMotion();
    if (!animate) {
      finishFx(false);
      clearGhosts();
    }
    const changes = animate ? changesBetween(before, view) : null;
    const changed = Boolean(changes && (changes.zones.size || changes.workings.size || changes.closed.size || changes.sensors.size));
    // A change of what is published under the intro (positions of people excepted): the intro jumps to its end first.
    if (intro && !intro.hold && (changed || !animate || view.selected !== before.selected || situationNow().key !== situationKey)) finishIntro();
    if (changed) startFx(changes);
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
    if (!artOn) chooseLoaderPlaces();
    updateLoaderLooks(animate);
    updateArtLamps(animate);
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
    queueMicrotask(followWalk);
    // The first picture of the mine on this page: the intro, unless motion is reduced or the data are old.
    if (introWanted && !introSpent) {
      if (!intro && rebuilt && width && !reduced()) holdIntro();
      maybeStartIntro();
    }
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
    // The headline over the stage changes with the situation in the same update, after this view may have heard of
    // it: the framing waits for the end of the update (a microtask, still before the frame) and so keeps clear of
    // the new headline, not of the old one.
    queueMicrotask(() => frameSituation(now, log));
  }

  function frameSituation(now, log) {
    if (now.situation === 'decision') {
      const zone = incidentZone() ? thingByName(state.model, incidentZone()) : null;
      if (zone && focus(zone.thingId)) {
        root.setAttribute('data-auto-framed', now.incident);
        log(zone.name);
      }
    } else if (now.situation === 'executing' && artOn && busiestWalk()) {
      // Art mode: the people walking out of the zone with the most of them, close, and their way ahead.
      const zone = busiestWalk();
      const goal = width ? artWalkGoal(zone) : null;
      if (goal) {
        overviewMode = false;
        focusId = thingByName(state.model, zone).thingId;
        walkFollow = {zone, focusId};
        orbit.glideTo({target: goal.target, dist: goal.dist});
        invalidate();
        log(`walk:${zone}`);
      } else if (overview(true)) {
        log('overview');
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
    return art ? SCENE.canvasArt(parts) : SCENE.canvas(parts);
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

  /** The horizons for info(): see there. */
  function levelsInView() {
    let near = null;
    if (!overviewMode) {
      const y = orbit.state.target.y;
      near = layout.levels.reduce((best, level) => (Math.abs(levelY(layout, level, k) - y) < Math.abs(levelY(layout, best, k) - y) ? level : best));
    }
    const onLevel = layout.levels.some((level) => focusId !== null && (focusId === level.name || focusId === level.thingId));
    return layout.levels.map((level) => {
      const b = level.box;
      const p = project([(b.minX + b.maxX) / 2, levelY(layout, level, k) + DIMS.depth, (b.minZ + b.maxZ) / 2]);
      const focused = focusId !== null && (focusId === level.name || focusId === level.thingId);
      return {name: level.name, label: level.label, elevation_m: level.elevation,
        screenY: p && width ? Math.round(p.y) : null, current: focused || (!onLevel && near === level),
        width: Math.round(Math.max(b.maxX - b.minX, b.maxZ - b.minZ))};
    });
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
      // The horizons as drawn now, upper first (the rail of the stage reads them): the local name, label, published
      // elevation, the stage-pixel y of the middle of the slab's top face, and whether the camera is on it now.
      levels: layout ? levelsInView() : [],
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
      loader: {lengthM: LOADER_LENGTH, scale: LOADER_SCALE, triangles: loaders.triangles(), calls: loaders.calls, detail: loaders.detail,
        // The places each zone's loader may take (attributes only), best first: [working, offset, span].
        candidates: Object.fromEntries([...loaderCandidates].map(([zone, list]) => [zone,
          list.map((place) => [place.working, Math.round(place.offsetM * 10) / 10, place.span.map((v) => Math.round(v * 10) / 10)])]))},
      // The loaders of the model (equipment twins) as drawn now, and the figures of people of the last frame.
      actors: actors.info(),
      // The massif (its far walls for the current camera) and the lamps: environment.js.
      environment: environment.info(),
      // The camera: perspective (the orbit of variant 3) or orthographic (art mode), where it is and where it goes.
      camera: {
        type: camera.isOrthographicCamera ? 'orthographic' : 'perspective', gliding: orbit.gliding,
        dist: orbit.state.dist, goalDist: orbit.goal.dist, target: ['x', 'y', 'z'].map((axis) => orbit.state.target[axis]),
        goal: ['x', 'y', 'z'].map((axis) => orbit.goal.target[axis]), az: orbit.state.az / DEG, el: orbit.state.el / DEG,
      },
      // Art mode: its view, its vertical factor, the zoom now (1 at the overview … ART_ZOOM_MAX) and the pan bounds.
      art: art ? {az: art.az / DEG, el: art.el / DEG, k, zoom: orbit.zoomFactor, zoomMax: ART_ZOOM_MAX, distMax: orbit.limits.distMax,
        distMin: orbit.limits.distMin, pan: orbit.where(), cover: orbit.limits.cover,
        // The illustrated mine: shown, its origin, its machines and their lamps (0 dark … 1 lit), the floor under each figure.
        env: artOn, origin: artOn ? {cx: layout.cx, cy: layout.cy, zTop: layout.zTop} : null,
        // The art's own machines (the zones' loaders, shown only without equipment twins, the truck and the drill) and the
        // published loaders (`published`: drawn at the place of the model, `loaded`: the heap in the bucket).
        machines: artMachines ? [...artMachines.zone, ...artMachines.decor, ...artMachines.equip.values()].map((entry) => ({name: entry.name,
          kind: entry.kind, zone: entry.zone, published: Boolean(entry.published), shown: entry.made.group.visible,
          loaded: entry.rock ? entry.rock.visible : null, light: Math.round(entry.light * 1000) / 1000,
          world: entry.made.group.position.toArray().map((v) => Math.round(v * 10) / 10),
          angle: Math.round(entry.made.group.rotation.y * 1000) / 1000,
          scale: Math.round(entry.made.group.scale.x * 1000) / 1000, box: machineBox(entry)})) : [],
        machineTop: ART_LHD_TOP,
        yielding: yieldDrawn.map((pair) => [...pair]),
        machineFactor: ART_MACHINE_FACTOR, figureScale: ART_FIGURE_SCALE,
        floorGaps: floorGaps(),
        // The state drawn over the floors: the materials of the overlay meshes (hazard decals, outlines, routes).
        overlays: [...overlayGroups.flatMap((group) => group.children), ...interOverlay.children, ...routeMeshes].map((mesh) => {
          const named = Object.entries(materials).find(([, value]) => value === mesh.material)
            || Object.entries(materials.frame).map(([key, value]) => [`frame.${key}`, value]).find(([, value]) => value === mesh.material);
          return {material: named ? named[0] : 'transition', polygonOffset: Boolean(mesh.material.polygonOffset), order: mesh.renderOrder};
        })} : null,
      // The depth rail: the probe drawn now ({z: mine elevation, y: scene height, mode}) and the highlighted horizon.
      depthProbe: depthProbe ? {z: Math.round(depthProbe.z * 100) / 100, y: Math.round(depthProbe.y * 100) / 100,
        mode: artOn ? 'contour' : 'slice'} : null,
      levelHighlight: levelLit ? {level: levelLit, meshes: highlightGroup.children.length} : null,
      // The people's playback buffer (walk.js) and where each person is drawn now: [working, offset, facing, moving].
      walk: {...walk.info(), at: view ? Object.fromEntries(Object.keys(view.workers).filter((name) => view.workers[name].at).map((name) => {
        const place = currentPosition(name);
        return [name, place ? [place.working, Math.round(place.offsetM * 1000) / 1000, place.facing, place.moving] : null];
      })) : {}},
    };
  }

  function dispose() {
    disposed = true;
    if (intro) clearTimeout(intro.timer);
    intro = null;
    loaders.dispose();
    actors.dispose();
    if (artEnv) artEnv.dispose();
    environment.dispose();
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
    resizeObserver.disconnect();
    coverObserver.disconnect();
    document.removeEventListener('visibilitychange', onVisibility);
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
  if (options.art) setArt(options.art);
  gizmo.setVertical(k);
  resize();

  return {
    root, canvas, rendererName,
    update(next) {
      update(next);
      placeLamps();
    },
    focus, overview, setExplode, setArt, measure, info, dispose,
    /** The depth rail: the people as drawn now, the depth probe and the highlight of a horizon (see above). */
    people, machines, setDepthProbe, setLevelHighlight, depthView, scrollDepth,
    /** Art mode is on: the orthographic camera, pan and zoom only. */
    get art() {
      return Boolean(art);
    },
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
