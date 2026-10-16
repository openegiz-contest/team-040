// The illustrated mine (mine-art SPEC §5–6): the environment GLB of the art and
// its actors, read for the 3D stage.
//
// The environment is shown only when its topology signature equals the one of
// the live twins (artSignature): the same working ids, end nodes and rounded
// polylines the art was built from. Then the stage switches to art mode with
// the GLB's MainView (azimuth, elevation, its rectangle as the overview) and
// its vertical factor; otherwise nothing of the art is used. The header (the
// glTF JSON of env.glb, 0.2 MB) is read first; the textures only on a match.
//
// Pure three.js and fetch; no DOM besides the loader's images.

import * as THREE from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';

const DEG = Math.PI / 180;

// ---- the topology signature ---------------------------------------------------------------------------

/** SHA-1 of a string (UTF-8), hex. Small and synchronous: crypto.subtle is missing outside secure origins. */
export function sha1(textValue) {
  const bytes = new TextEncoder().encode(textValue);
  const length = bytes.length;
  const words = new Uint32Array((((length + 8) >> 6) + 1) * 16);
  for (let i = 0; i < length; i += 1) words[i >> 2] |= bytes[i] << (24 - (i % 4) * 8);
  words[length >> 2] |= 0x80 << (24 - (length % 4) * 8);
  words[words.length - 1] = length * 8;
  let [h0, h1, h2, h3, h4] = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0];
  const w = new Uint32Array(80);
  const rotl = (x, n) => (x << n) | (x >>> (32 - n));
  for (let block = 0; block < words.length; block += 16) {
    for (let t = 0; t < 16; t += 1) w[t] = words[block + t];
    for (let t = 16; t < 80; t += 1) w[t] = rotl(w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16], 1);
    let [a, b, c, d, e] = [h0, h1, h2, h3, h4];
    for (let t = 0; t < 80; t += 1) {
      let f;
      let kk;
      if (t < 20) { f = (b & c) | (~b & d); kk = 0x5a827999; } else if (t < 40) { f = b ^ c ^ d; kk = 0x6ed9eba1; } else if (t < 60) { f = (b & c) | (b & d) | (c & d); kk = 0x8f1bbcdc; } else { f = b ^ c ^ d; kk = 0xca62c1d6; }
      const temp = (rotl(a, 5) + f + e + kk + w[t]) >>> 0;
      e = d; d = c; c = rotl(b, 30) >>> 0; b = a; a = temp;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
  }
  return [h0, h1, h2, h3, h4].map((h) => h.toString(16).padStart(8, '0')).join('');
}

/**
 * The topology signature of the live twins (SPEC §5): sha1 of JSON.stringify of the workings sorted by id, each
 * [id, from, to, [[x, y, z], …]] with the full polyline (from-node, bends, to-node), every coordinate Math.round()-ed.
 * Null when a working has no polyline from the attributes.
 * @param {Array<{name: string, attrs: Object}>} workings  the working twins
 * @param {Object} nodes                                    mine.attributes.nodes
 */
export function artSignature(workings, nodes) {
  const items = [];
  for (const working of [...workings].sort((p, q) => (p.name < q.name ? -1 : (p.name > q.name ? 1 : 0)))) {
    const {from, to} = working.attrs;
    const a = nodes && nodes[from];
    const b = nodes && nodes[to];
    if (!a || !b) return null;
    const bends = Array.isArray(working.attrs.points) ? working.attrs.points : [];
    const points = [[a.x, a.y, a.z], ...bends, [b.x, b.y, b.z]];
    if (!points.every((p) => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite))) return null;
    items.push([working.name, from, to, points.map((p) => p.map((v) => Math.round(v) + 0))]);
  }
  return {text: JSON.stringify(items), sha1: sha1(JSON.stringify(items))};
}

// ---- the environment ---------------------------------------------------------------------------------

/** The bytes of a GLB and its glTF JSON (no textures read yet). */
export async function readGlbHeader(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  const buffer = await response.arrayBuffer();
  const view = new DataView(buffer);
  if (view.getUint32(0, true) !== 0x46546c67) throw new Error(`${url}: not a GLB`);
  const length = view.getUint32(12, true);
  const json = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, length)));
  const scene = (json.scenes || [])[json.scene || 0] || {};
  return {url, buffer, json, extras: scene.extras || {}};
}

async function parseGlb(buffer, url) {
  const {GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js');
  const base = url.slice(0, url.lastIndexOf('/') + 1);
  return new Promise((resolve, reject) => new GLTFLoader().parse(buffer, base, resolve, reject));
}

/**
 * The contour of the depth probe on the rock (scene.js setDepthProbe): where the drawn surface crosses the height
 * uProbe.x, a line about 1.5 px wide with a soft halo, its width measured in pixels of the screen (derivatives), on
 * steep surfaces only (a floor at that height does not flood with it). uProbe.y: 0 off, 1 on.
 */
const PROBE_UNIFORMS = `uniform vec4 uProbe;
uniform vec3 uProbeColor;
uniform vec3 uProbeHalo;
`;
const PROBE_FRAGMENT = `
            if (uProbe.y > 0.0) {
              float probeDy = fwidth(vArtPos.y);
              float probeDxz = length(vec2(fwidth(vArtPos.x), fwidth(vArtPos.z)));
              float probeSteep = smoothstep(0.04, 0.22, probeDy / max(probeDxz, 1e-5));
              float probePx = abs(vArtPos.y - uProbe.x) / max(probeDy, 1e-5);
              float probeCore = 1.0 - smoothstep(0.7, 1.7, probePx);
              float probeHalo = exp(-probePx / 4.0) * 0.55;
              float probeAmount = uProbe.y * probeSteep;
              diffuseColor.rgb = mix(diffuseColor.rgb, uProbeHalo, probeHalo * probeAmount);
              diffuseColor.rgb = mix(diffuseColor.rgb, uProbeColor, probeCore * probeAmount);
            }`;

/**
 * The environment of the art: its visible meshes (unlit, sRGB, mipmapped), the invisible pick meshes per working,
 * the anchors of decor, and the main view: {az, el} (radians, the scene's azimuth convention of camera.js) and its
 * rectangle as four scene points (frame) with its half sizes.
 * @param {{buffer: ArrayBuffer, url: string, extras: Object}} header readGlbHeader
 * @param {{anisotropy?: number, edgeColor?: string, light?: boolean, probe?: Object}} options  probe: the uniforms
 *        {uProbe, uProbeColor, uProbeHalo} of the depth probe, shared with the scene
 */
export async function loadArtEnv(header, {anisotropy = 1, edgeColor = '#000000', light = false, probe = null} = {}) {
  const gltf = await parseGlb(header.buffer, header.url);
  const root = gltf.scene;
  root.updateMatrixWorld(true);
  const group = new THREE.Group();
  group.name = 'art-env';
  const picks = [];
  const anchors = new Map();
  let mainView = null;
  const meshes = [];
  root.traverse((object) => {
    if (object.isMesh) meshes.push(object);
    if (object.name.startsWith('ANCHOR_')) {
      const position = new THREE.Vector3();
      const quaternion = new THREE.Quaternion();
      object.matrixWorld.decompose(position, quaternion, new THREE.Vector3());
      anchors.set(object.name.slice('ANCHOR_'.length), {position, quaternion, extras: object.userData || {}});
    }
    if (object.isCamera && (object.name === header.extras.camera || object.parent && object.parent.name === header.extras.camera)) mainView = object;
  });
  if (!mainView) root.traverse((object) => { if (!mainView && object.isOrthographicCamera) mainView = object; });
  // The axes of MainView's screen (its right and up, scene units): an atlas's blocks are rectangles in metres of it.
  const screenAxes = {uScreenRight: {value: new THREE.Vector3(1, 0, 0)}, uScreenUp: {value: new THREE.Vector3(0, 1, 0)}};
  for (const mesh of meshes) {
    const node = mesh.userData && mesh.userData.pick ? mesh : (mesh.parent && mesh.parent.userData && mesh.parent.userData.pick ? mesh.parent : null);
    const geometry = mesh.geometry.clone();
    geometry.applyMatrix4(mesh.matrixWorld);
    const copy = new THREE.Mesh(geometry, mesh.material);
    copy.matrixAutoUpdate = false;
    if (node || /^PICK_/.test(mesh.name) || (mesh.parent && /^PICK_/.test(mesh.parent.name))) {
      const data = node ? node.userData : (mesh.parent.userData || {});
      copy.visible = false;
      copy.userData = {thingId: data.thingId || null, working: data.working || mesh.name.replace(/^PICK_/, '')};
      picks.push(copy);
      continue;
    }
    for (const material of [].concat(copy.material)) {
      if (material.map) {
        material.map.colorSpace = THREE.SRGBColorSpace;
        material.map.anisotropy = anisotropy;
        // The light quality (a software renderer pays for every texel fetch): one mip level per pixel.
        if (light) material.map.minFilter = THREE.LinearMipmapNearestFilter;
        material.map.needsUpdate = true;
      }
      material.toneMapped = false;
      // Beyond what its texture covers (a stage wider than the frame, a pan to the edge) the rock fades into the
      // background instead of smearing the clamped edge texels. A window texture (extras.windowScreenM) covers its
      // UV square: the fade follows the UV. An atlas (extras.atlas: blocks of the picture packed into one texture,
      // their screen rectangles in metres of MainView) covers the union of its blocks: the fade follows the position
      // on the screen of MainView, never the borders of the texture (those lie inside the picture).
      const blocks = material.userData && Array.isArray(material.userData.atlas)
        ? material.userData.atlas.filter((block) => Array.isArray(block.screenM) && block.screenM.length === 4 && block.screenM.every(Number.isFinite))
        : null;
      const atlas = blocks && blocks.length > 0;
      const fade = atlas ? `
            vec2 atlasAt = vec2(dot(vArtPos, uScreenRight), dot(vArtPos, uScreenUp));
            float atlasIn = 0.0;
            for (int i = 0; i < ${blocks.length}; i++) {
              vec2 atlasD = min(atlasAt - uAtlas[i].xy, uAtlas[i].xy + uAtlas[i].zw - atlasAt);
              atlasIn = max(atlasIn, smoothstep(-0.25, 2.5, min(atlasD.x, atlasD.y)));
            }
            diffuseColor.rgb = mix(uEdgeColor, diffuseColor.rgb, atlasIn);` : `
            vec2 edgeUv = min(vMapUv, 1.0 - vMapUv);
            float edgeFade = smoothstep(-0.002, 0.012, min(edgeUv.x, edgeUv.y));
            diffuseColor.rgb = mix(uEdgeColor, diffuseColor.rgb, edgeFade);`;
      if (material.map) {
        material.onBeforeCompile = (shader) => {
          shader.uniforms.uEdgeColor = {value: new THREE.Color(edgeColor)};
          if (probe) Object.assign(shader.uniforms, probe);
          if (atlas) {
            Object.assign(shader.uniforms, screenAxes);
            shader.uniforms.uAtlas = {value: blocks.map((block) => new THREE.Vector4(...block.screenM))};
          }
          if (probe || atlas) {
            shader.vertexShader = `varying vec3 vArtPos;
${shader.vertexShader}`.replace('#include <begin_vertex>', `#include <begin_vertex>
            vArtPos = (modelMatrix * vec4(transformed, 1.0)).xyz;`);
          }
          const head = `uniform vec3 uEdgeColor;
${probe || atlas ? 'varying vec3 vArtPos;' : ''}
${probe ? PROBE_UNIFORMS : ''}${atlas ? `uniform vec3 uScreenRight;
uniform vec3 uScreenUp;
uniform vec4 uAtlas[${blocks.length}];
` : ''}`;
          shader.fragmentShader = `${head}${shader.fragmentShader}`
            .replace('#include <map_fragment>', `#include <map_fragment>${fade}${probe ? PROBE_FRAGMENT : ''}`);
        };
        material.customProgramCacheKey = () => `art${atlas ? `-atlas${blocks.length}` : '-edge-fade'}${probe ? '-probe' : ''}`;
      }
    }
    group.add(copy);
  }
  if (!mainView) throw new Error('env.glb: no MainView camera');
  const quaternion = new THREE.Quaternion();
  const position = new THREE.Vector3();
  mainView.matrixWorld.decompose(position, quaternion, new THREE.Vector3());
  const back = new THREE.Vector3(0, 0, 1).applyQuaternion(quaternion);
  const right = new THREE.Vector3(1, 0, 0).applyQuaternion(quaternion);
  const up = new THREE.Vector3(0, 1, 0).applyQuaternion(quaternion);
  screenAxes.uScreenRight.value.copy(right);
  screenAxes.uScreenUp.value.copy(up);
  const halfW = mainView.right !== undefined ? (mainView.right - mainView.left) / 2 : 462;
  const halfH = mainView.top !== undefined ? (mainView.top - mainView.bottom) / 2 : 259.875;
  // The frame at the depth of the scene's origin (any depth gives the same rectangle on the screen).
  const centre = position.clone().addScaledVector(back, -position.dot(back));
  const frame = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy]) => centre.clone().addScaledVector(right, sx * halfW)
    .addScaledVector(up, sy * halfH).toArray());
  return {
    group, picks, anchors, extras: header.extras,
    view: {az: Math.atan2(back.x, back.z), el: Math.asin(Math.max(-1, Math.min(1, back.y))), frame, halfW, halfH},
    textures: [...new Set(group.children.flatMap((mesh) => [].concat(mesh.material)).map((material) => material.map).filter(Boolean))],
    dispose() {
      for (const mesh of [...group.children, ...picks]) mesh.geometry.dispose();
      for (const material of new Set(group.children.flatMap((mesh) => [].concat(mesh.material)))) {
        if (material.map) material.map.dispose();
        material.dispose();
      }
    },
  };
}

// ---- the machines of the art ---------------------------------------------------------------------------

/**
 * A machine of the art (lhd, truck, drill) as few draw calls: its painted parts merged by material (the wheels
 * never turn: nothing publishes machine movement), its lamps a mesh of their own (one material per copy, for the
 * zone's work state), its contact shadow. `make()` gives a new copy.
 */
export async function loadArtMachine(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  const gltf = await parseGlb(await response.arrayBuffer(), url);
  const scene = gltf.scene;
  scene.updateMatrixWorld(true);
  let extras = {};
  scene.traverse((object) => {
    if (object.userData && (object.userData.lampsNode || object.userData.lampOn)) extras = object.userData;
  });
  const lampsName = extras.lampsNode || 'LAMPS';
  const shadowName = extras.shadowNode || 'SHADOW';
  const within = (object, name) => {
    for (let node = object; node; node = node.parent) if (node.name === name) return true;
    return false;
  };
  const byMaterial = new Map();
  let lamps = null;
  let shadow = null;
  scene.traverse((object) => {
    if (!object.isMesh) return;
    let geometry = object.geometry.clone();
    geometry.applyMatrix4(object.matrixWorld);
    if (within(object, lampsName)) {
      lamps = {geometry, material: object.material};
      return;
    }
    if (within(object, shadowName)) {
      shadow = {geometry, material: object.material};
      return;
    }
    if (geometry.index) geometry = geometry.toNonIndexed();
    for (const name of Object.keys(geometry.attributes)) if (!['position', 'uv'].includes(name)) geometry.deleteAttribute(name);
    const key = object.material.uuid;
    if (!byMaterial.has(key)) byMaterial.set(key, {material: object.material, parts: []});
    byMaterial.get(key).parts.push(geometry);
  });
  const bodies = [...byMaterial.values()].map(({material, parts}) => {
    const merged = mergeGeometries(parts, false);
    parts.forEach((part) => part.dispose());
    if (material.map) material.map.colorSpace = THREE.SRGBColorSpace;
    return {geometry: merged, material};
  });
  const lampOn = new THREE.Color(extras.lampOn || '#FFE7B8');
  const lampOff = new THREE.Color(extras.lampOff || '#5B544B');
  return {
    extras,
    make() {
      const group = new THREE.Group();
      for (const body of bodies) group.add(new THREE.Mesh(body.geometry, body.material));
      let lampMaterial = null;
      if (lamps) {
        lampMaterial = [].concat(lamps.material)[0].clone();
        lampMaterial.color.copy(lampOff);
        group.add(new THREE.Mesh(lamps.geometry, lampMaterial));
      }
      if (shadow) {
        const mesh = new THREE.Mesh(shadow.geometry, shadow.material);
        mesh.renderOrder = 1;
        group.add(mesh);
      }
      for (const mesh of group.children) mesh.frustumCulled = true;
      return {group, lampMaterial, lampOn, lampOff};
    },
    triangles: bodies.reduce((sum, body) => sum + body.geometry.attributes.position.count / 3, 0),
  };
}

export {DEG};
