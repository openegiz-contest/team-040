# Mine-art environment (Blender build → `env.glb`)

The illustrated mine environment of SPEC.md sections 2–5, 7, 8. It is built from the real
topology (`team.sim.topology.build_attributes()`) by scripts that run Blender in background
mode only. Nothing at run time needs Blender.

## Rebuild

```
python rebuild.py                 # about 5 minutes on the RTX 4080 laptop (OptiX), 768 samples
python rebuild.py --samples 256   # quicker, noisier
```

`rebuild.py` runs, in order:

1. `dump_topology.py` (system Python): imports `team.sim.topology.build_attributes()` and writes
   `build/topology.json` (nodes, the 12 workings with full polylines, `cx`, `cy`, the topology sha1).
2. `blender --background --factory-startup --python build_env.py -- --stage full --samples N`:
   geometry, props, lights, the two projected texture renders, `env.glb`, the lit previews,
   and `build/env_scene.blend` (the editable scene).
3. `blender --background --factory-startup --python check_unlit.py`: the browser-like check.
4. `check_env.py` (stdlib only): prints the contract and budget numbers, exit code 1 on failure.

`build_env.py -- --stage geo` stops after the geometry and saves the .blend with a quick preview.

Files:

| file | role |
|---|---|
| `mine_map.py` | the one transform (SPEC §3), camera basis, topology signature |
| `env_geom.py` | massif block, cutters (face plane, crosscut loop, valley/east slope, ramp trench, drill bay), pillar, zone spurs, rock faceting |
| `env_props.py` | steel sets, lamps, duct, cables, rubble, chamber and junction props, portals, tyre tracks |
| `env_shading.py` | procedural materials, world, cool fill, lamp lights |
| `env_export.py`, `env_pipeline.py` | camera, renders, projected textures + outlines, GLB assembly, previews, walking-line visibility report |
| `glb_writer.py` | minimal stdlib glTF 2.0 binary writer (exact control of extras, unlit, samplers) |
| `check_env.py`, `check_unlit.py` | checks |

## Mapping and composition

Blender works Z-up with `bx = x − cx`, `by = y − cy`, `bz = 1.6·z` (`cx = 150`, `cy = 50`);
glTF gets `(bx, bz, −by)`, which is exactly SPEC §3 `X = x − cx, Y = z·k, Z = cy − y`.
Floors lie on the mapped polylines; workings are 14 m wide with 9 m walls.

- The four drifts and all straight ramp legs lie in one vertical plane (mine y = 0). Each is a
  gallery cut into the massif: a flat floor 24 m deep (front edge 14 m in front of the model
  centreline, back wall 10 m behind it), a tall (up to 45 m) light grey-beige back wall lit by
  lamp pools (bolting mesh, 12 m steel sets, cables and, on the main drifts, the duct on its
  lower part), and a flat ceiling that is the underside of the dark section band above. The
  band's front is a crisp near-vertical faceted section face with copper veins. Gallery height
  adapts where ramps stack close (near junctions and bends). The switchback ramps are these
  galleries zig-zagging up both sides, with landings at the bends; w-02's second leg climbs in
  a trench through a hillside to portal B.
- Behind level −120 the crosscut loop (to d) is an open terrace down to its floor, closed at
  the back by a tall lit wall (45 m) and a faceted, veined rock mass above it up to the surface
  (its corners slope back 2.2 m per metre, with a bench, so it does not read as a box). Inside the
  loop is a low rock island whose height at every point is limited so the crosscut walking
  lines stay visible from MainView (`crosscut_view_hmax`).
- Zone drifts w-07 / w-12 run toward the viewer on faceted rock spurs, each with a face
  chamber 36 m wide on the west side (cabinets, switch panel, two cable reels, pipe stack on
  bearers, spare arches, ventilation fan, timber, crates, spare tyre, two floodlight stands,
  three muck piles), an open face end, copper-rich rock around the face and warm spill light
  on the spur flanks. The −120 spur is a buttress, so the
  −240 zone below it stays visible.
- Surface (0 m): both portals with gantries, lamp rooms, light masts. No shaft or headframe
  is drawn.
- Camera MainView: orthographic, azimuth 12°, elevation 23° (tuned from 28°/30° so the
  gallery back walls show, as in the reference), frame width 924 m at 16:9
  (xmag 462, ymag 259.875); the whole mine with both portals fits the overview.

## Light scheme: combined bake, projected from MainView

Chosen: **combined bake (albedo × light) on one UV set**. Both textures are Cycles renders
(warm 2700 K lamps `#FFC37A`: per lamp a floor/wall-foot spot, a wall-wash spot up the
gallery wall and a soft point light; warm spill lights in front of the section faces above
 and below the galleries; 421 lights in all; a cool sun fill;
diffuse only, no gloss) taken from the MainView direction, and `TEXCOORD_0` of every vertex
is its orthographic projection into the texture's window. Because the browser only pans and
zooms this exact orthographic camera (no orbit), every screen pixel shows the render of
the surface the camera sees. Thin selective dark outlines are painted in afterwards from the
depth and normal passes (silhouettes, convex edges, hard creases; none on flat ground).

- `env_far.jpg` 2048² covers a 980 m square around the overview frame (frame width 924 m;
  margin for wider/taller stages). 1× overview on a 1920 px stage: 0.479 m/texel vs
  0.481 m/px, **1.00 texel per pixel**.
- `env_near.jpg` 2048² covers a 320 m square around both zone faces (screen window
  x −179…141 m, y −449…−129 m). At 3× zoom: 0.156 m/texel vs 0.160 m/px,
  **1.03 texels per pixel** on floors and walls near both zones (0.77 at 4×).
- Outside the near window at 3× the far texture gives 0.33 texel/px (soft).

Why not the light-map scheme: it meets the texel rule only through tiled detail, the light
itself would be at ~0.3 m/texel near the zones, and painted facets, outlines and light pools
would not line up. The projection gives the reference's painted look at 2 draw calls.

The visible geometry in the GLB is a coarse depth proxy (the rock before faceting, back faces
and faces hidden from MainView removed). The render uses a crystalline skin of that rock
(displaced ≤ 5 m, never raised on upward faces, floors and walls exact). Props (steel, lamps,
duct, cables, rubble, cabinets) are only in the texture; portal gantries and lamp rooms are
also geometry. Thin props therefore do not occlude people in the browser; everything a
person can walk behind is rock or a floor.

Material `extras.windowScreenM = [left, bottom, side]` records each window in screen metres
of MainView. Sampler: linear/mipmapped, `CLAMP_TO_EDGE`. Textures are external files next to
the GLB. `material.extras.lightMap` is not used (no second UV set).

## Contract (SPEC §5)

- `scene.extras = {"mineArt":1,"k":1.6,"cx":150.0,"cy":50.0,"zTop":0.0,"topology":"b4b9acd7…","workings":[12 ids],"camera":"MainView"}`.
- `topology` = sha1 of `JSON.stringify(list)` (no spaces), list sorted by working id, items
  `[id, from, to, [[x,y,z], …]]` with the full polyline (from-node, bends `points`, to-node)
  in mine metres, each coordinate `Math.round()`-ed. Python reference: `mine_map.signature`.
- One camera node `MainView` (orthographic); no lights, no animations; all materials
  `KHR_materials_unlit`.
- `PICK_w-01 … PICK_w-12`: boxes from 1 m below to 7 m above the floor along each polyline,
  covering the drawn floor (gallery segments: from the open front edge to the back wall;
  zone drifts, crosscuts and the w-02 trench: 15 m wide), material `pick` (unlit, alpha 0, BLEND), `extras.thingId = "team040.mine:<id>"`.
- Anchors (empties, yaw about up; actors face +X locally), all on the floor, clear of the
  walking lines:

| node | glTF position | yaw | place, clearance from the walking line |
|---|---|---|---|
| `ANCHOR_lhd_zone-a` | (−16, −192, 116) | −90° (faces the face, south) | zone-A chamber, 13.7 m |
| `ANCHOR_lhd_zone-b` | (−16, −384, 116) | −90° | zone-B chamber, 13.7 m |
| `ANCHOR_truck` | (87, −192, 33) | 180° (faces west) | bay behind drift w-04, 14.4 m |
| `ANCHOR_drill` | (−76, −384, 33.5) | 180° | bay behind drift w-10, 14.6 m |

## Numbers (last build, `python check_env.py`)

| item | value | budget (SPEC §8) |
|---|---|---|
| visible triangles | 8 458 (+192 invisible pick) | ≤ 100 k, aim ≤ 60 k |
| primitives / draw calls | 2 visible (+12 pick, hidden by the browser) | ≤ 80 |
| materials | 3 (`env_far`, `env_near`, `pick`) | |
| textures | 2 × 2048² JPEG (721 KB far, 756 KB near) | light maps ≤ 2 × 2048² |
| env.glb + textures | 1.57 MiB | whole `models/mine-art/` ≤ 8 MiB (2.58 MiB with the actors present now) |

Walking-line visibility from MainView (`build/visibility.json` against the GLB geometry,
`build/visibility_render.json` against the faceted render rock; mid-body 2.5 m sampled every
2 m): drifts, crosscut w-05 and both zone drifts 0 % hidden. Hidden stretches are where the
topology stacks ramps in one vertical plane: the lower ramp passes under the upper ramp's
floor for 15–25 m after junctions a and c and before the hairpin bends (w-01 5 %, w-08 10 %,
w-09 10 % of their length), 2 m of w-11 next to g, 1 sample of w-06 at c, and 2 m under each
portal gantry.

## Previews

`previews/overview.png`, `zone_a_3x.png`, `zone_b_3x.png`: Cycles renders of the lit scene
from MainView at 1920×1080. `previews/unlit_*.png`: `env.glb` re-imported into an empty scene,
emission-only materials, no lights, same views (what three.js shows).
