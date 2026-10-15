# Mine-art actors: worker, LHD, truck, drill

The moving and decorative actors of the illustrated mine (SPEC.md, sections 6 and 7),
built procedurally in Blender 5.1 and exported as GLB for three.js.

| File | What it is |
|---|---|
| `team/ui/public/models/mine-art/actors/worker.glb` | miner, 5 m tall, skinned, clips `walk` and `idle` |
| `team/ui/public/models/mine-art/actors/lhd.glb` | articulated loader (LHD) with bucket |
| `team/ui/public/models/mine-art/actors/truck.glb` | 6-wheel underground dump truck, box heaped with ore |
| `team/ui/public/models/mine-art/actors/drill.glb` | two-boom drill jumbo, booms forward, jacks down |

## Rebuild

Blender in background mode only (never the running Blender session). From the
repository root:

```
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --factory-startup --python team/ui/assets/mine-art/actors/worker.py
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --factory-startup --python team/ui/assets/mine-art/actors/lhd.py
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --factory-startup --python team/ui/assets/mine-art/actors/truck.py
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --factory-startup --python team/ui/assets/mine-art/actors/drill.py
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --factory-startup --python team/ui/assets/mine-art/actors/lineup.py
python team/ui/assets/mine-art/actors/check_actors.py
```

Options after `--`: `--no-render` (skip previews), `--samples N` (bake samples, default 128).
Each asset takes 30-70 s on the RTX 4080 (OptiX); the very first bake on a machine also
compiles the Cycles kernel (about 9 minutes once). Builds are deterministic.

Each script writes: the GLB, `<asset>.blend` (generated, not hand edited),
`textures/<asset>_paint.png` (the baked atlas, lossless; the GLB embeds it as JPEG q92),
and previews. `lineup.py` only reads the GLBs. `check_actors.py` is Python stdlib only.

## Files

- `actors_style.py` - shared: palette, paint (bake) shader, mesh builder, wheel, hidden-face
  culling, UV atlas, bake and gap fill, outline hull, shadow blob, export and GLB patch,
  preview and re-import renders, the common machine pipeline `build_machine()`.
- `worker.py`, `lhd.py`, `truck.py`, `drill.py` - geometry (and for the worker: rig, walk, idle).
- `lineup.py` - all four GLBs together from the main view.
- `check_actors.py` - parses the GLBs, prints the numbers below and checks SPEC section 6.

## How the look is made

- **Light baked into one texture.** Every surface is shaded once by a "paint" shader
  (shader math, no lamps) and baked (Cycles EMIT bake) into one atlas per asset: cool
  ambient from above, one soft warm key from above-front (mirrored left/right, so a
  machine looks the same with either side to the camera), ambient occlusion plus a short
  cavity occlusion for contact lines, rounded-edge normals (Bevel node) that give lit top
  rims and dark lower rims, a thin dark line on sharp edges only, dust of the floor colour
  on the lower 1.1 m. No noise, no gloss. Wheels use a rotation-invariant light so the
  shading does not turn with the wheel.
- **Outlines** are an inverted hull (a 5 cm outward shell with inverted faces) around the
  big parts and the tyres, in the same mesh and material; its UVs sample a 12 px block of
  the outline colour `#2A2018` painted into a free spot of the atlas. No extra texture, no
  extra draw call, no screen pass. About 1.3 px at the close zoom, sub-pixel at overview.
  The worker has no hull (no triangle budget left).
- **Atlas hygiene.** Faces no main-view ray can reach (any heading, elevation 20-36 deg)
  are deleted before unwrapping; gaps between islands are push-pull filled so mipmaps do
  not bleed black.
- **Materials** are `KHR_materials_unlit`, single-sided. Machines: `<asset>_paint`
  (texture), `<asset>_lamps` (flat colour), `shadow_blob` (BLEND, alpha in `COLOR_0`).
  Worker: one material `worker_paint`; the cap lamp lens is painted bright in the texture.

## Contract for the browser (SPEC section 6)

Axes in glTF: forward +X, up +Y, left -Z. Scene metres: machines are 1.5x real
(`extras.scaleToReal`), the worker is 5 m tall.

Machines (`lhd`, `truck`, `drill`):
- Root node named after the asset, origin on the ground at the middle of the length on
  the vehicle centreline, facing +X. Root `extras`: `lengthM`, `widthM`, `heightM`,
  `wheelRadiusM`, `wheelSpinAxis` = `[0,0,-1]`, `lampsNode`, `lampOn`, `lampOff`,
  `shadowNode` and a short description.
- `WHEELS` with `WHEEL_FL/FR/(ML/MR)/RL/RR`, each with its origin on its axle and identity
  rotation. Forward motion of `d` metres: rotate each wheel about its local `[0,0,-1]` by
  `d / wheelRadiusM` radians (the right-hand wheels are mirrored meshes, so the same sign
  holds for all). Spin only on real movement.
- `LAMPS`: one mesh, material `<asset>_lamps` (unlit flat colour `#FFE7B8`, with
  `extras.lampOn` / `lampOff` = `#5B544B`): headlights, roof and rear lamps, beacon. The
  beacon is the same warm white, never amber (hazard colours stay out of the art).
- `SHADOW`: soft contact shadow under the machine (alpha blend, 3 cm above the floor).
  Optional: hide it if the environment already has a shadow there.

Worker:
- Root `worker` (static) > `worker_rig` (armature, 13 bones: root, hips, spine, head,
  thigh/shin/foot and upperarm/forearm per side) > `worker_body` (skinned mesh).
- Clips: `walk` 1.0 s loop, `idle` 4.0 s loop; the root never moves. Root `extras`:
  `strideM` = 3.0 (metres the feet cover per walk cycle at scale), `walkCycleS` = 1.0,
  `walkSpeedAtRate1` = 3.0 m/s, so `timeScale = groundSpeed / 3.0` keeps the feet planted.
  `strideM` is also in `scene.extras` and in the `walk` animation's `extras`.
- The walk is computed: the stance foot is planted (heel strike 14 deg, flat, roll over
  the ball to 25 deg) and slides back at exactly `strideM` per cycle; the legs follow by
  analytic two-bone IK (max reach 0.997 of the leg); pelvis bob 4.5 cm, sway 3.5 cm,
  yaw 5 deg, hip drop 3 deg; shoulders counter-rotate; arms swing 20 deg with elbow bend.

## Numbers (from `check_actors.py`)

| Asset | Triangles (budget) | Materials | Texture | GLB | Size (L x W x H, m) |
|---|---|---|---|---|---|
| worker | 1 360 (1 500) | 1 | 512x512 JPEG, 48 KiB | 215 KiB | 1.2 x 1.9 x 5.02 |
| lhd | 5 166 (6 000) | 3 | 1024x1024 JPEG, 186 KiB | 302 KiB | 15.3 x 5.0 x 4.7 |
| truck | 4 727 (6 000) | 3 | 1024x1024 JPEG, 177 KiB | 268 KiB | 15.3 x 4.8 x 5.8 (heap) |
| drill | 3 756 (7 000) | 3 | 1024x1024 JPEG, 163 KiB | 247 KiB | 21.4 x 4.9 x 4.7 |

Triangles are counted as rendered (each wheel instance counted), including outline hulls,
lamps and the 84-triangle shadow blob. Total of the four GLBs: about 1.0 MiB. Draw calls
per machine: body + one per wheel + LAMPS + SHADOW (7 for the LHD, 9 for the truck);
worker: 1. Animations: `walk` 1.0 s and `idle` 4.0 s, 42 channels each.

## Previews (`previews/`)

Main view of SPEC section 4 (orthographic, azimuth 12 deg, elevation 28 deg), on the floor
tone `#857B6E`, four headings per row (E, SE = toward the camera, S, W):

- `<machine>_glb_unlit_overview.png` (7.7 px/m: LHD ~120 px long) and
  `<machine>_glb_unlit_close.png` (25.6 px/m: LHD ~400 px): the GLB re-imported with
  emission-only materials, i.e. what three.js shows.
- `<machine>_source_*.png`: the paint shader itself before baking (no outline hull) - the
  difference to the GLB shows what the bake and the hull change.
- `worker_glb_unlit_40px.png`, `worker_glb_unlit_40px_x4.png` (nearest upscale for
  reading), `worker_glb_unlit_150px.png`: idle (top row) and a walk frame (bottom row).
- `worker_walk_contact_sheet.png`: 8 frames of the GLB walk clip, side view and
  three-quarter view, 150 px.
- `lineup_overview.png`, `lineup_close.png`: all actors together, for scale.
- `_tiles/`: intermediate single renders, regenerated by the scripts.

## Known gaps

- Compared with the references the machines are cleaner: no scuffs, bolts, worn edges or
  hand-painted texture; the tyres' tread reads mainly in silhouette.
- The worker has no outline hull; at 150 px it is softer-edged than the reference figures.
- Not yet seen in the browser: three.js mipmapping, the alpha of `SHADOW` from `COLOR_0`
  (unsigned short, normalised), the wheel spin sign, and playback of the clips in
  `AnimationMixer` were checked only by reasoning and by the Blender re-import.
