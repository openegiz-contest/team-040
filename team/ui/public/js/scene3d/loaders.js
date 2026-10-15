// The loaders of the zones: one copy of lhd.glb per zone that has workings, the
// symbol of the zone's published work state. The machine itself is not in the
// model (no position, no motion, no state of its own): it stands still where the
// scene put it, and only its look follows the zone's `work_state` —
//   working  painted, the lenses of its lamps lit and a flat warm patch of light
//            on the floor ahead of it (a decal: no glow, no bloom);
//   stopped  desaturated, the lenses dark, no light on the floor;
//   unknown  (no published work state) a cold fog grey, lenses too.
// A change of the state fades from one look to the other once (LIGHT_MS); the
// caller decides whether the change may be shown with motion (never on load,
// over old data or under reduced motion).
//
// All loaders are drawn with a few instanced meshes, one per material of the
// model (paint, steel, rubber, lenses) plus their contact shadow, the light on
// the floor and, in the high quality only, an ink outline: the draw calls do not
// grow with the number of zones. Pure three.js; no DOM, no words.

import * as THREE from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';

/** How long the lights of a loader take to go out or come on when the work state of its zone changes. */
export const LIGHT_MS = 400;

/** The looks, as colours multiplied into white materials (instance colours). The light is additive: black adds nothing. */
const LOOK = {
  working: {paint: '#8A98A6', steel: '#B5AEA2', rubber: '#3A3D41', lens: '#FFF1D2', light: '#A08262'},
  stopped: {paint: '#45474A', steel: '#5E5B57', rubber: '#26282A', lens: '#232528', light: '#000000'},
  unknown: {paint: '#959AA0', steel: '#959AA0', rubber: '#7A7E84', lens: '#959AA0', light: '#000000'},
};
const PARTS = ['paint', 'steel', 'rubber', 'lens'];
/** The materials of lhd.glb by part; the two copper pin caps are painted as steel (copper is not a state here). */
const PART_OF = {lhd_paint_graphite: 'paint', lhd_steel_worn: 'steel', lhd_rubber: 'rubber', lhd_lens: 'lens', lhd_copper: 'steel'};
const easeOut = (t) => 1 - (1 - t) ** 3;

/** The flat light ahead of the machine: warm near the bucket, fading forward and to the sides (black is no light). */
function lightTexture() {
  const width = 128;
  const height = 64;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const g = canvas.getContext('2d');
  const image = g.createImageData(width, height);
  for (let y = 0; y < height; y += 1) {
    const across = Math.abs((y + 0.5) / height * 2 - 1);
    const side = Math.max(0, 1 - across ** 2.2);
    for (let x = 0; x < width; x += 1) {
      const u = (x + 0.5) / width;
      const along = Math.min(u / 0.08, 1) * (1 - u) ** 1.25;
      const value = Math.round(255 * along * side);
      const i = (y * width + x) * 4;
      image.data[i] = value;
      image.data[i + 1] = value;
      image.data[i + 2] = value;
      image.data[i + 3] = 255;
    }
  }
  g.putImageData(image, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** A flat quad in the model's frame (y up), with u along +X and v across. */
function quad(x0, x1, nearHalf, farHalf, y) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute([
    x0, y, -nearHalf, x1, y, -farHalf, x1, y, farHalf, x0, y, nearHalf,
  ], 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0], 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
  geometry.setIndex([0, 2, 1, 0, 3, 2]);
  return geometry;
}

/**
 * @param {Object} options
 * @param {boolean} options.low          the light quality: Lambert materials, no outline
 * @param {THREE.Texture} options.shadow the soft contact shadow of the scene's textures
 * @param {number} options.scale         how many times the 10 m machine is drawn larger
 */
export function createLoaders({low, shadow, scale}) {
  const group = new THREE.Group();
  group.name = 'loaders';
  let parts = null;                 // part -> merged geometry, in the model's frame
  let extras = null;                // {shadow, light, outline} geometries
  let box = null;
  let meshes = [];
  let order = [];                   // zone names, in instance order
  const poses = new Map();          // zone -> {position: [x, y, z], angle}
  const looks = new Map();          // zone -> {state, from, start, level}
  const lit = (params, standard = {}) => (low
    ? new THREE.MeshLambertMaterial(params)
    : new THREE.MeshStandardMaterial({roughness: 0.6, metalness: 0.1, ...params, ...standard}));
  const materials = {
    paint: lit({color: '#ffffff', emissive: '#1B2128'}),
    steel: lit({color: '#ffffff', emissive: '#1B2128'}, {metalness: 0.25, roughness: 0.55}),
    rubber: lit({color: '#ffffff', emissive: '#121417'}, {roughness: 0.92, metalness: 0}),
    // The lenses are not lit by the scene: their colour is their light.
    lens: new THREE.MeshBasicMaterial({color: '#ffffff'}),
    shadow: new THREE.MeshBasicMaterial({map: shadow, transparent: true, depthWrite: false, opacity: 0.9,
      polygonOffset: true, polygonOffsetFactor: -6, polygonOffsetUnits: -6}),
    light: new THREE.MeshBasicMaterial({color: '#ffffff', map: lightTexture(), transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, polygonOffset: true, polygonOffsetFactor: -7, polygonOffsetUnits: -7}),
    outline: new THREE.MeshBasicMaterial({color: '#101215', side: THREE.BackSide}),
  };
  const colour = new THREE.Color();
  const other = new THREE.Color();
  const matrix = new THREE.Matrix4();
  const rotation = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);

  /** The geometry of lhd.glb, merged per part. Throws when the file cannot be read. */
  async function load(url) {
    const {GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js');
    const gltf = await new GLTFLoader().loadAsync(url);
    const byPart = Object.fromEntries(PARTS.map((part) => [part, []]));
    const all = [];
    gltf.scene.updateMatrixWorld(true);
    gltf.scene.traverse((object) => {
      if (!object.isMesh) return;
      const source = Array.isArray(object.material) ? object.material[0] : object.material;
      const part = PART_OF[source && source.name] || 'paint';
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', object.geometry.attributes.position.clone());
      if (object.geometry.attributes.normal) geometry.setAttribute('normal', object.geometry.attributes.normal.clone());
      else geometry.computeVertexNormals();
      if (object.geometry.index) geometry.setIndex(object.geometry.index.clone());
      geometry.applyMatrix4(object.matrixWorld);
      byPart[part].push(geometry);
      all.push(geometry);
    });
    gltf.scene.traverse((object) => {
      if (object.geometry) object.geometry.dispose();
      if (object.material) [].concat(object.material).forEach((material) => material.dispose());
    });
    parts = {};
    for (const part of PARTS) parts[part] = byPart[part].length > 0 ? mergeGeometries(byPart[part], false) : null;
    const merged = mergeGeometries(all.map((geometry) => geometry.clone()), false);
    merged.computeBoundingBox();
    box = merged.boundingBox.clone();
    const halfWidth = Math.max(-box.min.z, box.max.z);
    let outline = null;
    if (!low) {
      // An ink outline (the back faces pushed out along the normals): the machine keeps its silhouette on any floor.
      outline = merged;
      const position = outline.attributes.position;
      const normal = outline.attributes.normal;
      for (let i = 0; i < position.count; i += 1) {
        position.setXYZ(i, position.getX(i) + normal.getX(i) * 0.07, position.getY(i) + normal.getY(i) * 0.07,
          position.getZ(i) + normal.getZ(i) * 0.07);
      }
    } else {
      merged.dispose();
    }
    all.forEach((geometry) => geometry.dispose());
    extras = {
      shadow: quad(box.min.x - 0.7, box.max.x + 0.7, halfWidth + 0.6, halfWidth + 0.6, 0.02),
      // The light on the floor ahead of the bucket, inside the channel (half its width is about 2 m of the model).
      light: quad(box.max.x + 0.1, box.max.x + 7.5, 1.1, 1.9, 0.03),
      outline,
    };
    rebuild();
  }

  /** The number of triangles one machine is drawn with. */
  function triangles() {
    if (!parts) return 0;
    return PARTS.reduce((sum, part) => sum + (parts[part] ? parts[part].index.count / 3 : 0), 0);
  }

  function lookOf(zone) {
    return looks.get(zone) || {state: 'unknown', from: 'unknown', start: -1, level: 1};
  }

  /** Write the colour of every instance for the current progress of its change of look. */
  function paint() {
    for (const mesh of meshes) {
      const part = mesh.userData.part;
      if (!PARTS.includes(part) && part !== 'light') continue;
      order.forEach((zone, index) => {
        const look = lookOf(zone);
        colour.set(LOOK[look.state][part]);
        if (look.level < 1) colour.lerp(other.set(LOOK[look.from][part]), 1 - look.level);
        mesh.setColorAt(index, colour);
      });
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
  }

  function place() {
    for (const mesh of meshes) {
      order.forEach((zone, index) => {
        const pose = poses.get(zone);
        rotation.setFromAxisAngle(up, pose.angle);
        matrix.compose(new THREE.Vector3(...pose.position), rotation, new THREE.Vector3(scale, scale, scale));
        mesh.setMatrixAt(index, matrix);
      });
      mesh.instanceMatrix.needsUpdate = true;
    }
  }

  /** New instanced meshes for the zones that have a place (a new run or a new topology). */
  function rebuild() {
    for (const mesh of meshes) {
      group.remove(mesh);
      mesh.dispose();
    }
    meshes = [];
    order = [...poses.keys()].sort();
    if (!parts || order.length === 0) return;
    const add = (geometry, material, part, renderOrder = 0) => {
      if (!geometry) return;
      const mesh = new THREE.InstancedMesh(geometry, material, order.length);
      mesh.userData.part = part;
      mesh.renderOrder = renderOrder;
      mesh.frustumCulled = false;
      mesh.matrixAutoUpdate = false;
      meshes.push(mesh);
      group.add(mesh);
    };
    add(extras.shadow, materials.shadow, 'shadow', 8);
    add(extras.light, materials.light, 'light', 8);
    for (const part of PARTS) add(parts[part], materials[part], part);
    add(extras.outline, materials.outline, 'outline');
    place();
    paint();
  }

  return {
    group,
    load,
    triangles,
    get loaded() {
      return parts !== null;
    },
    /** The scene-metre box of one machine in its own frame (before the scale). */
    get box() {
      return box;
    },
    /**
     * Where each zone's loader stands (scene point of the floor, and the turn about the vertical); a zone left out has
     * none. A change of the set of zones rebuilds the meshes; the same set only moves them (another spread of the slabs).
     */
    setPoses(next) {
      const before = [...poses.keys()].sort().join();
      poses.clear();
      for (const [zone, pose] of next) poses.set(zone, pose);
      if ([...poses.keys()].sort().join() !== before) rebuild();
      else if (meshes.length > 0) place();
    },
    /** The published work state of a zone as a look; `animate` fades the change, otherwise it is shown at once. */
    setState(zone, state, animate) {
      const next = LOOK[state] ? state : 'unknown';
      const look = looks.get(zone);
      if (look && look.state === next) return false;
      looks.set(zone, look && animate ? {state: next, from: look.state, start: null, level: 0} : {state: next, from: next, start: -1, level: 1});
      paint();
      return Boolean(look && animate);
    },
    /** Advance the fades; true while one runs. `instant` ends them (reduced motion, old data). */
    step(now, instant = false) {
      let active = false;
      let changed = false;
      for (const look of looks.values()) {
        if (look.start === -1) continue;
        if (look.start === null) look.start = now;
        const t = instant ? 1 : Math.min((now - look.start) / LIGHT_MS, 1);
        look.level = easeOut(t);
        changed = true;
        if (t >= 1) {
          look.start = -1;
          look.from = look.state;
          look.level = 1;
        } else {
          active = true;
        }
      }
      if (changed) paint();
      return active;
    },
    /** End every fade at once. */
    finish() {
      for (const look of looks.values()) {
        look.start = -1;
        look.from = look.state;
        look.level = 1;
      }
      paint();
    },
    /** The look of each zone's loader and how far its lights are on (0 dark … 1 lit), for tests. */
    info() {
      return [...poses.keys()].sort().map((zone) => {
        const look = lookOf(zone);
        const lightOf = (state) => (state === 'working' ? 1 : 0);
        return {zone, state: look.state, fading: look.start !== -1,
          light: Math.round((lightOf(look.from) + (lightOf(look.state) - lightOf(look.from)) * look.level) * 1000) / 1000};
      });
    },
    get calls() {
      return meshes.length;
    },
    dispose() {
      for (const mesh of meshes) mesh.dispose();
      meshes = [];
      if (parts) for (const geometry of Object.values(parts)) if (geometry) geometry.dispose();
      if (extras) for (const geometry of Object.values(extras)) if (geometry) geometry.dispose();
      for (const material of Object.values(materials)) {
        if (material.map && material.map !== shadow) material.map.dispose();
        material.dispose();
      }
    },
  };
}
