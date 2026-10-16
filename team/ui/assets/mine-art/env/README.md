# Mine-art environment (Blender build → `env.glb`)

The illustrated mine environment of SPEC.md sections 2–5, 7, 8. It is built from the real
topology (`team.sim.topology.build_attributes()`) by scripts that run Blender in background
mode only. Nothing at run time needs Blender.

## Rebuild

```
python rebuild.py                 # about 7 minutes on the RTX 4080 laptop (OptiX), 768 samples
python rebuild.py --samples 128   # quicker, noisier (about 3 minutes)
```

`rebuild.py` runs, in order:

1. `dump_topology.py` (system Python): imports `team.sim.topology.build_attributes()` and writes
   `build/topology.json` (nodes, the 12 workings with full polylines, `cx`, `cy`, the topology sha1).
2. `blender --background --factory-startup --python build_env.py -- --stage full --samples N`:
   geometry, props, lights, the camera-projected texture renders, `env.glb`, the lit previews,
   and `build/env_scene.blend` (the editable scene).
3. `blender --background --factory-startup --python check_unlit.py`: the browser-like check
   (five unlit previews, see below).
4. `check_env.py` (stdlib only): prints the contract and budget numbers, exit code 1 on failure.

`build_env.py -- --stage geo` stops after the geometry and saves the .blend with a quick lit
preview; `-- --no-previews` skips the lit previews of the full stage. `render_debug.py` renders
any zoom/focus from `build/env_scene.blend`.

Files:

| file | role |
|---|---|
| `mine_map.py` | the one transform (SPEC §3, `K = 1.35`), camera basis, topology signature |
| `env_geom.py` | massif (faceted front, block pile, crevices, faceted plateau), cutters (face plane, crosscut alcove, east slope, ramp trench, drill bay), island, zone spurs, render skins, facet attributes |
| `env_props.py` | steel sets, lamps, duct, cables, rubble, chamber and junction props, portals, tyre tracks |
| `env_shading.py` | painted-key materials (rock, walls, floors, ground, props), copper vein bands, lamp lights |
| `env_export.py`, `env_pipeline.py` | camera, frame and texture windows, projected renders + outlines, far atlas, GLB assembly (triangle clipping at the atlas borders), previews, walking-line visibility, anchors |
| `glb_writer.py` | minimal stdlib glTF 2.0 binary writer (exact control of extras, unlit, samplers) |
| `check_env.py`, `check_unlit.py` | checks |

## Mapping and composition

Blender works Z-up with `bx = x − cx`, `by = y − cy`, `bz = 1.35·z` (`cx = 150`, `cy = 50`);
glTF gets `(bx, bz, −by)`, which is exactly SPEC §3 `X = x − cx, Y = z·k, Z = cy − y` with
**k = 1.35** (written into `scene.extras.k`; SPEC §3/§5 still say 1.6 and need the same update).
Floors lie on the mapped polylines; workings are 14 m wide with 9 m walls. With k = 1.35 the
levels are 162 m (−120) and 324 m (−240) below the surface in scene metres.

- The four drifts and all straight ramp legs lie in one vertical plane (mine y = 0). Each is a
  gallery cut into the massif: a flat floor 24 m deep on average (back wall 10 m behind the
  centreline, the open front edge follows the faceted cliff 8.5–22 m in front of it), a 45 m light
  beige-grey back wall lit by lamp pools (bolting mesh, 12 m steel sets, cables and, on the main
  drifts, the duct on its lower part), and a flat ceiling that is the underside of the faceted
  section band above. Where ramps stack close (near junctions and bends) the gallery is as tall
  as the gap allows with a 9 m slab between the two floors (was 14 m). The switchback ramps
  zig-zag up both sides with landings at the bends; w-02's second leg climbs in a trench through
  a hillside to portal B.
- Behind level −120 the crosscut loop (to d) is an **alcove** under the massif, not an open pit:
  its roof is the plane through the top of the 45 m back wall that rises toward the viewer exactly
  as the lines of sight do (`loop_roof`), so the roof is seen edge-on, everything under it stays
  visible, and the window it cuts into the massif front ends on the same screen line as the back
  wall. The massif front (faceted, veined) continues above the window up to the surface; no rock
  mass stands up from the plateau any more. Inside the loop is a low rock island whose height at
  every point keeps the crosscut walking lines visible (`crosscut_view_hmax`).
- Zone drifts w-07 / w-12 run toward the viewer on faceted rock spurs (rings every 12.5 m, flank
  subdivisions denser toward the top, a faceted nose bulging below the floor), each with a face
  chamber 36 m wide on the west side (cabinets, switch panel, cable reels, pipe stack, spare
  arches, ventilation fan, timber, crates, spare tyre, two floodlight stands, three muck piles),
  an open face end, copper-rich rock around the face and warm spill light on the spur flanks.
- Surface (0 m): a quiet dark ground in low-poly facets (every inner vertex sunk by up to 2.8 m,
  flat around the portals), ending at the cliff top in a thin light lip; both portals with
  gantries, lamp rooms, light masts. The w-02 hillside meets the plateau along a smooth line (its
  cutter is the terrain lifted 0.6 m), so there are no wedges or stray triangles. No shaft or
  headframe is drawn.
- Camera MainView: orthographic, azimuth 12°, elevation 23°, frame width 924 m at 16:9
  (xmag 462, ymag 259.875). The frame top is 50 m above the highest working point (portal B road
  end: gantries, lamp rooms, masts fit), the rest of the height goes below the faces; frame
  centre in screen metres (−10.4, −182.1).

## The rock

The rock is built as real low-poly geometry, and the picture paints it per facet:

- **Massif front** (`massif_block`): variable-radius Poisson points (radius 15 m ± 45 %, × 1.35
  on the big section faces between the galleries, elongated 1.45× along a 28° rising grain),
  Delaunay triangles, so facets are about 12–40 m across (about 25–80 px at 1×, larger on the
  section faces). The front is a **pile of angular blocks** (`Lumps`, radius 27 m): every vertex is pushed
  toward the viewer by its block's height (4.5–11 m) times how far inside the block it is, so each
  block has a lit upper face, darker lower faces and a dark crease around it; 48 **crevices**
  (chains of 3–6 vertices pushed 7–11 m into the rock, kept 10 m away from every floor) carry a
  `crev` point attribute that sinks the facets sloping into them into darkness. The booleans cut
  this faceted surface, so facets stay flat and floors and walls stay exact.
- Alcove walls, spurs and the island are jittered lofts / heightfields triangulated before the
  booleans (facets defined, no non-planar quads).
- **Render skins** (not exported): the working walls are refined to ~9 m triangles (edges
  beautified) and every inner vertex is pushed 0.4–3.4 m into the rock — small flat facets that
  the lamps catch, no flagstone pattern; the rock gets a quiet second level (~9 m pieces tilted by
  ±0.45 m, below the outline threshold) that shows only at 3×.
- **Painted key** (`env_shading.key_t`): every material's emission is a value set by its flat
  facet's orientation to a soft key from the upper left (`KEY = (−0.35, −0.45, 0.82)`), through a
  colour ramp of charcoal values (`ROCK_STOPS`, #0e0d0d … #625a55): upper planes light,
  undersides dark; ±12 % value and a slight warm/cool hue shift per facet (face attribute `fr`,
  equal for coplanar pieces); local AO (7 m) in creases; large ~250 m masses a little lighter/
  browner or darker/cooler; the rock in the top 75 m under the surface weathered darker. Measured
  on the unlit 1× overview (lower left, lower right, left edge), rock luminance percentiles
  5/25/50/75/95 are 19–23/31–32/40–41/51/70–77 (0–255); the reference overview's rock gives
  21–26/28–33/37–39/43–51/66–103. There is no sun; the warm 2700 K lamps (`#FFC37A`, 409 lights) are
  real lights on top (diffuse only), so facets near lamps warm up.
- **Copper veins** (`vein_bands`): three families of warped parallel planes (28°, −14°, 58°),
  each band present only on 60–200 m stretches, tapered at both ends, 0.5–3 m wide (wider and
  more frequent within 80 m of the two zone faces), with thin broken streaks beside it and a dark
  rim; the vein colour takes the facet's key value (`VEIN_STOPS`), so veins catch light on lit
  facets and go dark brown on shadowed ones.
- **Outlines** (`env_pipeline.outlined`, from the depth/kind/normal passes): silhouettes; hard
  creases (> 38°) on props; on rock every facet edge > 13°: a thin dark line on the darker side of
  a convex edge, on both sides of a concave crease, and a **light rim on the lit side of convex
  edges**; walls only get their concave creases, faintly; the ground/rock edge gets the light lip.

## Light scheme: combined bake, projected from MainView

Chosen: **combined bake (albedo × light) on one UV set**. Both textures are Cycles renders taken
from the MainView direction, and `TEXCOORD_0` of every vertex is its orthographic projection into
its texture's window. Because the browser only pans and zooms this exact orthographic camera (no
orbit), every screen pixel shows the render of the surface the camera sees.

- `env_far.jpg` 2048² is an **atlas** (`material.extras.atlas`, screen metres of MainView):
  - main block, rows 0–1487: 980 m × 712 m at 0.4785 m/texel, screen x −500.4…479.6,
    y −538.1…173.9. It covers the 1× stage from 16:9 to 4:3 (the 4:3 stage shows 87 m more at top
    and bottom). 1× on a 1920 px wide 16:9 or 4:3 stage: 0.481 m/px, **1.006 texels per pixel**.
  - two side wings, rows 1492–1767 (west, x −630.4…−494.4) and 1772–2047 (east, x 473.6…609.6),
    136 m × 540 m each, stored rotated (screen x along the rows at 0.493 m/texel, screen y along
    the columns at 0.264 m/texel): what a stage wider than 16:9 shows left and right. 1× on a
    1920 px wide 21:9 stage: 0.632 m/px, 1.28 texels per pixel in the wings, 1.32 in the main block.
  - triangles that cross the main/wing border (screen x = centre ± 487 m) are clipped there in
    the GLB (1 464 cuts); gutters of repeated edge rows separate the blocks.
- `env_near.jpg` 2048² covers a 320 m square around both zone faces (screen x −179.0…141.0,
  y −433.4…−113.4). At 3× zoom on a 1920 px stage: 0.156 m/texel vs 0.160 m/px, **1.03 texels
  per pixel** on floors and walls near both zones (0.77 at 4×).
- Outside the near window at 3× the far texture gives 0.33 texel/px (soft).

The massif extends to x ±780 m, the plateau to 900 m north and the cliff down to −900 m, so the
1× picture is rock or ground to every edge for any stage from 4:3 to 21:9 (checked by the two
extra unlit previews; no background and no fade at any edge).

The visible geometry in the GLB is the faceted rock before the render skins (back faces and faces
hidden from MainView removed). Props (steel, lamps, duct, cables, rubble, cabinets) are only in
the texture; portal gantries and lamp rooms are also geometry. Thin props therefore do not occlude
people in the browser; everything a person can walk behind is rock or a floor.

Sampler: linear/mipmapped, `CLAMP_TO_EDGE`. Textures are external files next to the GLB.
`material.extras.lightMap` is not used (no second UV set). `env_near` keeps
`extras.windowScreenM = [left, bottom, side]`; `env_far` has `extras.atlas` (block, screenM
[left, bottom, width, height], texels [col, row, cols, rows], rotated).

## Contract (SPEC §5)

- `scene.extras = {"mineArt":1,"k":1.35,"cx":150.0,"cy":50.0,"zTop":0.0,"topology":"b4b9acd7…","workings":[12 ids],"camera":"MainView"}`.
- `topology` = sha1 of `JSON.stringify(list)` (no spaces), list sorted by working id, items
  `[id, from, to, [[x,y,z], …]]` with the full polyline (from-node, bends `points`, to-node)
  in mine metres, each coordinate `Math.round()`-ed. Python reference: `mine_map.signature`.
  (Unchanged by k: the signature is in mine metres.)
- One camera node `MainView` (orthographic, extras: az 12°, el 23°, 16:9, zoom 1–4, the stage
  aspects it is painted for); no lights, no animations; all materials `KHR_materials_unlit`.
- `PICK_w-01 … PICK_w-12`: boxes from 1 m below to 7 m above the floor along each polyline,
  covering the drawn floor (gallery segments: from 2 m beyond the mean cliff line to the back
  wall; zone drifts, crosscuts and the w-02 trench: 15 m wide), material `pick` (unlit, alpha 0,
  BLEND), `extras.thingId = "team040.mine:<id>"`.
- Anchors (empties, yaw about up; actors face +X locally), all on the floor; the clearance is
  now measured from the footprint to the nearest walking line on the same level:

| node | glTF position | yaw | place, clearance from the walking line |
|---|---|---|---|
| `ANCHOR_lhd_zone-a` | (−16, −162, 116) | −90° (faces the face, south) | zone-A chamber, 13.8 m |
| `ANCHOR_lhd_zone-b` | (−16, −324, 116) | −90° | zone-B chamber, 13.8 m |
| `ANCHOR_truck` | (87, −162, 33) | 180° (faces west) | bay behind drift w-04, 14.4 m |
| `ANCHOR_drill` | (−76, −324, 33.5) | 180° | bay behind drift w-10, 14.6 m |

## Numbers (last build, `python check_env.py`)

| item | value | budget (SPEC §8) |
|---|---|---|
| visible triangles | 9 800 (+192 invisible pick) | ≤ 100 k, aim ≤ 60 k |
| primitives / draw calls | 2 visible (+12 pick, hidden by the browser) | ≤ 80 |
| materials | 3 (`env_far`, `env_near`, `pick`) | |
| textures | 2 × 2048² JPEG (572 KB far atlas, 632 KB near) | light maps ≤ 2 × 2048² |
| env.glb + textures | 1.33 MiB (env.glb 194 KB) | whole `models/mine-art/` ≤ 8 MiB (2.35 MiB with the actors present now) |

Walking-line visibility from MainView (`build/visibility.json` against the GLB geometry,
`build/visibility_render.json` against the render rock; mid-body 2.5 m sampled every 2 m):
drifts w-03/w-04/w-10, crosscuts w-05/w-06 and both zone drifts 0 % hidden. Hidden stretches are
where the topology stacks ramps in one vertical plane: the lower ramp passes under the upper
ramp's floor for 12–16 m after junctions a and c and before the hairpin bends (w-08 8.1 %, w-09
7.6 %, w-01 4.3 % of their length, longest 18 m), 2 m of w-11 next to g, and 2–4 m under each
portal gantry (w-01, w-02). With k = 1.35 the stacked gaps are smaller than with 1.6; the thinner
9 m slab more than makes up for it (before: w-08 10.2 %, w-09 9.8 %, w-01 5.4 %).

## Previews

`previews/overview.png`, `zone_a_3x.png`, `zone_b_3x.png`: Cycles renders of the lit scene from
MainView at 1920×1080 (256 samples). `previews/unlit_*.png`: `env.glb` re-imported into an empty scene,
emission-only materials, no lights (what three.js shows): `unlit_overview.png` (16:9),
`unlit_zone_a_3x.png`, `unlit_zone_b_3x.png`, and the 1× overview on a 1920 px wide 21:9 stage
(`unlit_overview_21x9.png`, 1920×823, 1212.75 m wide) and 4:3 stage (`unlit_overview_4x3.png`,
1920×1440, 693 m tall).
