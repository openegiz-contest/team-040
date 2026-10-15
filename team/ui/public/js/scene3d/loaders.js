// The loaders of the mine, drawn from lhd_v2.glb (its light copy lhd_v2_lod.glb far away), else lhd.glb. Two modes, chosen by the scene:
// - without equipment twins, one copy per zone that has workings, the symbol of
//   the zone's published work state: it stands still where the scene put it;
// - with equipment twins (contract question 18), one copy per published loader,
//   placed and turned by the scene from its published position (actors.js).
// The look follows a published state —
//   working  painted, the lenses of its lamps lit and a flat warm patch of light
//            on the floor ahead of it (a decal: no glow, no bloom);
//   parked   (a loader idle by the model) painted, the lamps dimmed;
//   stopped  desaturated, the lenses dark, no light on the floor;
//   unknown  (no published state) a cold fog grey, lenses too.
// A loader published `loaded` carries a low heap of rock in its bucket, and the
// selected one a chalk double ring on the floor around it.
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
  working: {paint: '#8A98A6', steel: '#B5AEA2', rubber: '#3A3D41', lens: '#FFF1D2', light: '#A08262', load: '#6B5B4B'},
  parked: {paint: '#7D8995', steel: '#A39D93', rubber: '#3A3D41', lens: '#8C7E68', light: '#2E251C', load: '#6B5B4B'},
  stopped: {paint: '#45474A', steel: '#5E5B57', rubber: '#26282A', lens: '#232528', light: '#000000', load: '#4A4744'},
  unknown: {paint: '#959AA0', steel: '#959AA0', rubber: '#7A7E84', lens: '#959AA0', light: '#000000', load: '#959AA0'},
};
/** How far the lamps of a look are on, 0 dark … 1 lit (tests read it through info()). */
const LIGHT_LEVEL = {working: 1, parked: 0.35, stopped: 0, unknown: 0};
const PARTS = ['paint', 'steel', 'rubber', 'lens'];
/** Parts painted by the look of their machine (instance colours). */
const PAINTED = new Set([...PARTS, 'light', 'load']);
/** The materials of lhd.glb by part; the two copper pin caps are painted as steel (copper is not a state here). */
const PART_OF = {
  lhd_paint_graphite: 'paint', lhd_steel_worn: 'steel', lhd_rubber: 'rubber', lhd_lens: 'lens', lhd_copper: 'steel',
  // lhd_v2.glb and its light copy lhd_v2_lod.glb (assets/README.md): the dark paint and the glass read as rubber.
  lhd_paint: 'paint', lhd_paint_dark: 'rubber', lhd_steel: 'steel', lhd_glass: 'rubber',
};
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

/** The chalk double ring of a selected machine, drawn flat on the floor (selection, clarity spec A9). */
function ringTexture() {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size * 2;
  canvas.height = size;
  const g = canvas.getContext('2d');
  g.strokeStyle = '#F2EFE9';
  const rounded = (inset, width) => {
    g.lineWidth = width;
    const w = size * 2 - 2 * inset;
    const hh = size - 2 * inset;
    const r = hh / 2;
    g.beginPath();
    g.moveTo(inset + r, inset);
    g.lineTo(inset + w - r, inset);
    g.arc(inset + w - r, inset + r, r, -Math.PI / 2, Math.PI / 2);
    g.lineTo(inset + r, inset + hh);
    g.arc(inset + r, inset + r, r, Math.PI / 2, (3 * Math.PI) / 2);
    g.closePath();
    g.stroke();
  };
  rounded(5, 6);
  rounded(20, 4);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/**
 * A low heap of broken rock in the bucket (the box of `lhd_bucket` in the model's frame): a squashed half sphere
 * with its vertices pushed in and out by a fixed pattern, so every machine carries the same heap.
 */
function heapGeometry(bucket) {
  const geometry = new THREE.SphereGeometry(1, 9, 4, 0, Math.PI * 2, 0, Math.PI / 2).toNonIndexed();
  const position = geometry.attributes.position;
  const length = bucket.max.x - bucket.min.x;
  const width = bucket.max.z - bucket.min.z;
  const height = bucket.max.y - bucket.min.y;
  for (let i = 0; i < position.count; i += 1) {
    const x = position.getX(i);
    const y = position.getY(i);
    const z = position.getZ(i);
    // A fixed bumpiness: the same for the same direction, whatever triangle the vertex belongs to.
    const bump = 1 + 0.16 * Math.sin(x * 7.1 + z * 3.3) * Math.cos(z * 5.7 - x * 2.1) * (y < 0.05 ? 0.3 : 1);
    position.setXYZ(i, bucket.min.x + length * 0.42 + x * length * 0.36 * bump,
      bucket.min.y + height * 0.66 + y * height * 0.6 * bump, (bucket.min.z + bucket.max.z) / 2 + z * width * 0.4 * bump);
  }
  geometry.deleteAttribute('uv');
  geometry.computeVertexNormals();
  return geometry;
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
  let lod = null;                   // the light copy {parts, outline}, or null
  let detail = 'full';              // which copy is drawn: 'full' | 'lod'
  let extras = null;                // {shadow, light, outline} geometries
  let box = null;
  let meshes = [];
  let order = [];                   // zone names, in instance order
  const poses = new Map();          // zone -> {position: [x, y, z], angle}
  const looks = new Map();          // zone -> {state, from, start, level}
  const loaded = new Set();         // keys of the machines published with a load
  let selected = null;              // the key of the selected machine (its ring on the floor)
  let machines = false;             // drawn from equipment twins (not as the symbols of the zones)
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
    load: lit({color: '#ffffff', emissive: '#15120F', flatShading: true}, {roughness: 1, metalness: 0}),
    ring: new THREE.MeshBasicMaterial({color: '#ffffff', map: ringTexture(), transparent: true, depthWrite: false,
      polygonOffset: true, polygonOffsetFactor: -8, polygonOffsetUnits: -8}),
  };
  const colour = new THREE.Color();
  const other = new THREE.Color();
  const matrix = new THREE.Matrix4();
  const rotation = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);

  /** One file of the machine, merged per part (in the model's frame), its box, bucket and silhouette source. */
  async function readModel(url) {
    const {GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js');
    const gltf = await new GLTFLoader().loadAsync(url);
    const byPart = Object.fromEntries(PARTS.map((part) => [part, []]));
    const all = [];
    let bucket = null;
    gltf.scene.updateMatrixWorld(true);
    gltf.scene.traverse((object) => {
      if (!object.isMesh) return;
      if (/bucket/.test(object.name) || /bucket/.test(object.parent ? object.parent.name : '')) {
        object.geometry.computeBoundingBox();
        const own = object.geometry.boundingBox.clone().applyMatrix4(object.matrixWorld);
        bucket = bucket ? bucket.union(own) : own;
      }
      const source = Array.isArray(object.material) ? object.material[0] : object.material;
      const part = PART_OF[source && source.name] || 'paint';
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', object.geometry.attributes.position.clone());
      if (object.geometry.attributes.normal) geometry.setAttribute('normal', object.geometry.attributes.normal.clone());
      else geometry.computeVertexNormals();
      if (object.geometry.index) geometry.setIndex(object.geometry.index.clone());
      else geometry.setIndex([...Array(geometry.attributes.position.count).keys()]);
      geometry.applyMatrix4(object.matrixWorld);
      byPart[part].push(geometry);
      all.push(geometry);
    });
    gltf.scene.traverse((object) => {
      if (object.geometry) object.geometry.dispose();
      if (object.material) [].concat(object.material).forEach((material) => material.dispose());
    });
    const model = {parts: {}, bucket, outline: null};
    for (const part of PARTS) model.parts[part] = byPart[part].length > 0 ? mergeGeometries(byPart[part], false) : null;
    const merged = mergeGeometries(all.map((geometry) => geometry.clone()), false);
    merged.computeBoundingBox();
    model.box = merged.boundingBox.clone();
    if (!low) {
      // An ink outline (the back faces pushed out along the normals): the machine keeps its silhouette on any floor.
      const position = merged.attributes.position;
      const normal = merged.attributes.normal;
      for (let i = 0; i < position.count; i += 1) {
        position.setXYZ(i, position.getX(i) + normal.getX(i) * 0.07, position.getY(i) + normal.getY(i) * 0.07,
          position.getZ(i) + normal.getZ(i) * 0.07);
      }
      model.outline = merged;
    } else {
      merged.dispose();
    }
    all.forEach((geometry) => geometry.dispose());
    return model;
  }

  /**
   * The machine of `url` (throws when it cannot be read) and, when given and readable, its light copy `lodUrl`, drawn
   * instead while every machine is small on the screen (setDetail).
   */
  async function load(url, lodUrl = null) {
    const full = await readModel(url);
    let light = null;
    if (lodUrl) {
      try {
        light = await readModel(lodUrl);
      } catch (error) {
        light = null;
      }
    }
    parts = full.parts;
    lod = light;
    box = full.box;
    const halfWidth = Math.max(-box.min.z, box.max.z);
    const bucket = full.bucket;
    extras = {
      shadow: quad(box.min.x - 0.7, box.max.x + 0.7, halfWidth + 0.6, halfWidth + 0.6, 0.02),
      // The light on the floor ahead of the bucket, inside the channel (half its width is about 2 m of the model).
      light: quad(box.max.x + 0.1, box.max.x + 7.5, 1.1, 1.9, 0.03),
      outline: full.outline,
      // The load: in the bucket when the file names it, else in the front fifth of the machine.
      load: heapGeometry(bucket || new THREE.Box3(new THREE.Vector3(box.max.x - (box.max.x - box.min.x) * 0.2, 0, box.min.z * 0.8),
        new THREE.Vector3(box.max.x, (box.max.y - box.min.y) * 0.4, box.max.z * 0.8))),
      ring: quad(box.min.x - 1.4, box.max.x + 1.4, halfWidth + 1.4, halfWidth + 1.4, 0.04),
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

  /** The heap of a machine without a load and the ring of a machine not selected are drawn at scale 0. */
  function shown(part, key) {
    if (part === 'load') return loaded.has(key);
    if (part === 'ring') return key === selected;
    return true;
  }

  /** Write the colour of every instance for the current progress of its change of look. */
  function paint() {
    for (const mesh of meshes) {
      const part = mesh.userData.part;
      if (!PAINTED.has(part)) continue;
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
        const size = shown(mesh.userData.part, zone) ? scale : 0;
        matrix.compose(new THREE.Vector3(...pose.position), rotation, new THREE.Vector3(size, size, size));
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
    const add = (geometry, material, part, renderOrder = 0, set = 'any') => {
      if (!geometry) return;
      const mesh = new THREE.InstancedMesh(geometry, material, order.length);
      mesh.userData.part = part;
      mesh.userData.set = set;
      mesh.visible = set === 'any' || set === detail;
      mesh.renderOrder = renderOrder;
      mesh.frustumCulled = false;
      mesh.matrixAutoUpdate = false;
      meshes.push(mesh);
      group.add(mesh);
    };
    add(extras.shadow, materials.shadow, 'shadow', 8);
    add(extras.light, materials.light, 'light', 8);
    for (const part of PARTS) add(parts[part], materials[part], part, 0, lod ? 'full' : 'any');
    add(extras.outline, materials.outline, 'outline', 0, lod ? 'full' : 'any');
    if (lod) {
      for (const part of PARTS) add(lod.parts[part], materials[part], part, 0, 'lod');
      add(lod.outline, materials.outline, 'outline', 0, 'lod');
    }
    // The heap and the ring belong to machines of the model only (equipment twins): the symbols of the zones
    // carry no load and are never selected, and keep their draw calls.
    if (machines) {
      add(extras.load, materials.load, 'load');
      add(extras.ring, materials.ring, 'ring', 8);
    }
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
    /** Draw machines of the model (equipment twins: a load and a selection ring) or the symbols of the zones. */
    setMachines(on) {
      if (machines === Boolean(on)) return;
      machines = Boolean(on);
      rebuild();
    },
    get machines() {
      return machines;
    },
    /** The machines that carry a load (published `loaded`); a change of the set only rescales their heaps. */
    setLoaded(keys) {
      const next = [...keys].sort().join();
      if ([...loaded].sort().join() === next) return;
      loaded.clear();
      for (const key of keys) loaded.add(key);
      if (meshes.length > 0) place();
    },
    /** The selected machine (its ring on the floor) and how far the work light of the selection is in (0…1). */
    setSelected(key, level = 1) {
      materials.ring.opacity = level;
      if (key === selected) return;
      selected = key;
      if (meshes.length > 0) place();
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
        const lightOf = (state) => LIGHT_LEVEL[state] || 0;
        return {zone, state: look.state, fading: look.start !== -1, loaded: loaded.has(zone), selected: zone === selected,
          light: Math.round((lightOf(look.from) + (lightOf(look.state) - lightOf(look.from)) * look.level) * 1000) / 1000};
      });
    },
    get calls() {
      return meshes.filter((mesh) => mesh.visible).length;
    },
    /** Draw the full machines or their light copies (when there is one); true when it changed. */
    setDetail(level) {
      const next = lod && level === 'lod' ? 'lod' : 'full';
      if (next === detail) return false;
      detail = next;
      for (const mesh of meshes) mesh.visible = mesh.userData.set === 'any' || mesh.userData.set === detail;
      return true;
    },
    get detail() {
      return detail;
    },
    dispose() {
      for (const mesh of meshes) mesh.dispose();
      meshes = [];
      if (parts) for (const geometry of Object.values(parts)) if (geometry) geometry.dispose();
      if (extras) for (const geometry of Object.values(extras)) if (geometry) geometry.dispose();
      if (lod) for (const geometry of [...Object.values(lod.parts), lod.outline]) if (geometry) geometry.dispose();
      for (const material of Object.values(materials)) {
        if (material.map && material.map !== shadow) material.map.dispose();
        material.dispose();
      }
    },
  };
}
