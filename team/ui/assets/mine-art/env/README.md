# Mine-art environment (Blender build → `env.glb`)

The illustrated mine environment of SPEC.md sections 2–5, 7, 8. It is built from the real
topology (`team.sim.topology.build_attributes()`) by scripts that run Blender in background
mode only. Nothing at run time needs Blender.

Fourth art pass: the balance of the clean isometric reference (`scratchpad\ref2\reference-iso.webp`:
tunnels opened along their length, natural ceiling edge with drips, light floor > mid walls >
dark rock, calm palette) and the richness of the faceted pass (sculpted rock, steel sets, duct,
cables, gravel and tracks, rich face chambers, warm lamps).

## Rebuild

```
python rebuild.py                 # about 5 minutes on the RTX 4080 laptop (OptiX), 256 samples
python rebuild.py --samples 128   # quicker, noisier
```

`rebuild.py` runs, in order:

1. `dump_topology.py` (system Python): writes `build/topology.json` (nodes, the 12 workings with
   full polylines, `cx`, `cy`, the topology sha1).
2. `blender --background --factory-startup --python build_env.py -- --stage full --samples N`:
   geometry, sculpted skins, props, lights, the camera-projected texture renders, `env.glb`, the
   lit previews and `build/env_scene.blend`.
3. `blender --background --factory-startup --python check_unlit.py`: the browser-like check (five
   unlit previews, see below).
4. `check_env.py` (stdlib only): contract, camera, texel and budget numbers; exit code 1 on failure.

`build_env.py -- --stage geo [--quick]` stops after the geometry (quick preview);
`render_debug.py` renders any zoom/focus from `build/env_scene.blend`; `compare.py` makes the
side-by-side sheet `previews/compare_prev_new_ref.jpg` (previous pass | this pass | reference).

| file | role |
|---|---|
| `mine_map.py` | the one transform (SPEC §3, `K = 1.35`), camera angles and their allowed ranges, camera basis, topology signature |
| `env_geom.py` | gallery stack (floor fronts, clear heights, drip edges), cutters (slots, air in front of the terraces, bay, crosscuts, zone trenches and chambers, w-02 trench, truck pocket, island tips), massif block, promontory and peninsula, sculpted skins, facet attributes |
| `env_props.py` | steel sets with lamps, duct, cables, tyre tracks, stones along the floor lips, chamber and junction supplies, bays, portals |
| `env_shading.py` | sculpted-rock, wall, gravel-floor materials (painted, camera rays only), props, lamp lights |
| `env_export.py`, `env_pipeline.py` | camera, frame and texture windows, projected renders + outlines, far atlas, GLB assembly, visibility, anchors, previews |
| `glb_writer.py` | minimal stdlib glTF 2.0 binary writer |
| `check_env.py`, `check_unlit.py`, `compare.py` | checks and the comparison sheet |

## Mapping and camera

Blender works Z-up with `bx = x − cx`, `by = y − cy`, `bz = 1.35·z` (`cx = 150`, `cy = 50`);
glTF gets `(bx, bz, −by)` = SPEC §3 with **k = 1.35**. Levels: −162 m (−120) and −324 m (−240)
in scene metres.

**MainView**: orthographic, **azimuth 24°** (from south toward the east), **elevation 28°**, 16:9,
frame 834 m × 469.1 m (xmag 417, ymag 234.56), centred on the screen bounds of the workings
(46 m above the highest point, 40 m below the lowest). Chosen by comparing overviews at azimuth
22°, 24°, 30° and 40° (elevation 28°): at 40° (the reference's iso angle) the mine is small in a
frame of large empty dark faces; at 22–24° it fills the frame, drifts and ramps still run
diagonally and the lit back walls show. Allowed ranges (checked): azimuth 20–50°, elevation 26–34°.

## Geometry: tunnels opened along their length

All dimensions in scene metres; `RISE_S` = sight rise per metre toward the camera's south
(tan el / cos az = 0.582).

- **Face-plane galleries** (the four drifts, all straight ramp legs; mine y = 0) are slots in a
  terraced section face: floor from the back wall (`B_BACK` = 10 behind the walking line) to its
  front edge `F` in front of it, the back wall, and a ceiling (the underside of the rock band
  above) whose front edge hangs down in a calm wavy line with a jag now and then (0–5.5 m).
  `F` of each floor is as deep as the visibility of the gallery below allows
  (`(gap − 2.5 − 3.5) / RISE_S`, 8–22 m), then slope-limited along the gallery (0.5 m/m), so the
  section face never steps; every floor meeting at a junction ends at the shallowest of their
  fronts (one continuous edge through a and c, no step where a ramp meets a drift), and each
  profile is opened (running min, then running mean over ±7 m): the floor edges flow in curves
  and never exceed the visibility limit. The lowest floor
  at each x reaches 22 m (30 m under the level −240 drifts, 40 m on the drill terrace). Clear
  heights 38 m (42 m on the level −240 drifts) where the stack allows. Hairpin landings extend
  beyond the bend in a half ellipse (12 m) that turns into the rock face through a 9 m fillet;
  the ceiling arcs down to the floor over the whole landing (no vertical end edge). A landing on the side the lines
  of sight run to (east) stays as shallow as the upper leg, with a recess in the face below it.
- **Air cutters**: in front of every gallery with another below, from the lower floor up to its own
  ceiling (the sky for the top-most), so lower floors stick out as open terraces.
- **Bay** above level −120 between a and c: cut down to a 7 m bench (the island). Crosscut a–d is
  a slot in the bay's north-west wall (open floor 4 m in front of its drip edge); d–c an open
  trench at the foot of the north-east wall; both end at d, where a sector of 10–10.5 m around d
  rounds the loop's outer corner; the island's corners are rounded (18 m).
- **Zone drifts** run toward the viewer on a promontory (w-07) and a peninsula (w-12): a trench to
  a rounded face chamber (46 m west of the drift, 8 m beyond the face, 19 m north of it, corner
  radius 13.4 m); 9 m fillets round the drift mouth and the trench's corners with the chamber. The
  bench is 5.5 m east of the drift (the walking line shows over it), rising to 16 m in the west and
  dropping to a 2.5 m lip at the south end (the face end and its rubble show). The promontory's
  underside rises toward the viewer as the lines of sight from level −240 do.
- **Surface**: dark plateau at 0 m; w-02's second leg climbs to portal B in a trench through a
  hillside descending with the road (`EastSlope`, 5 m / 9 m walls); a 16 m fillet with a blended
  floor rounds the rock nose between the first leg's back wall and the trench. Portal frames and lamp rooms
  at both exits. No shaft, rails, trains, crushers or conveyors.
- **Sculpted rock (render only)**: every visible rock face is built from ~12 m quads; the skin
  pushes every inner vertex of the cut faces and tops into the rock by a piecewise-planar field
  (each ~50 m Voronoi cell one tilted plane, 0.6–7 m deep on the faces, 0.3–2.6 m on the tops,
  plus a slow 220 m swell), so the planes break into big facets independent of the
  triangulation; tunnel walls are refined to ~6 m facets pushed 0.3–1.8 m into the rock. Vertices
  shared with floors never move, so floors stay exact; nothing moves toward the camera side. The
  GLB gets the clean pre-skin geometry (`PROXY_*`).

## Look

- **Rock**: painted key value per facet (orientation to a key from the upper left) through a
  charcoal ramp of moderate contrast (`ROCK_STOPS` #1c1a19 … #534d48), ±4.5 % per facet, soft
  strata on the cut faces, large lighter/browner and darker masses, local AO in creases, two
  families of thin copper veins (0.3–1.3 m, a little more near the zone faces); tops darker.
- **Walls**: beige-grey rock in small facets, lighter toward the key, light drips hanging from the
  visible top (UV v = metres below where the rock edge cuts the view), copper staining on veins.
- **Floors**: light gravel (two pebble tones, dark gaps), tyre tracks, stones along the lips.
- **Props**: steel sets every 22–30 m with lamps on arms, waler beams, three cables, the
  ventilation duct along the four drifts and down both zone drifts, chamber supplies (muck piles,
  cabinets, switch panel, cable reels, pipe stack, spare arches, timber, crates, floodlights),
  junction supplies at b and f, lamps in the truck pocket and on the drill terrace.
- **Light**: paint is seen by camera rays only (painted surfaces never light each other); the warm
  lamps (2700 K) are real Cycles lights on top, diffuse only: a pool on the floor, a wash up the
  wall, a faint additive cone.
- **Outlines** (`env_pipeline.outlined`): faint silhouettes, dark ink on rock facet edges > 24°,
  a light rim on the lit side of convex edges, faint wall creases; tracks and cones are kept out
  of the outline passes.

## Textures: combined bake projected from MainView

Both textures are Cycles renders taken from the MainView direction; `TEXCOORD_0` of every vertex
is its orthographic projection into its texture's window (pan and zoom only, no orbit).

- `env_far.jpg` 2048² atlas (`material.extras.atlas`, screen metres of MainView): main block
  884.0 m × 641.9 m at 0.4317 m/texel (covers the 16:9 and 4:3 1× stages: **1.006 texels per
  pixel** at 1920 px), two rotated side wings for stages up to 21:9 (0.5367 m/texel, **1.062
  texels per pixel**; the atlas spans −555.3 … +555.3 m around the frame centre for a 1094.6 m
  wide 21:9 stage).
- `env_near.jpg` 2048² covers a 293 m square around both zone faces: 0.1431 m/texel, **1.012
  texels per pixel at 3×** on a 1920 px stage.

## Contract (SPEC §5)

- `scene.extras = {"mineArt":1,"k":1.35,"cx":150.0,"cy":50.0,"zTop":0.0,"topology":"b4b9acd7…","workings":[12 ids],"camera":"MainView"}`; the signature is unchanged (mine metres).
- One camera node `MainView` (orthographic, extras azimuthDeg 24, elevationDeg 28, 16:9, zoom
  1–4); no lights, no animations; all materials `KHR_materials_unlit`.
- `PICK_w-01 … PICK_w-12`: boxes 1 m below to 7 m above the floor along each polyline (face-plane
  segments: from 1 m beyond the deepest floor front to the back wall; a–d: 16 m toward the island,
  10 m behind; others 15 m wide), `extras.thingId = "team040.mine:<id>"`.
- Anchors (empties, yaw about up, actors face +X locally; machines drawn 2.2× real, clearance
  measured from the footprint to the nearest walking line on the same level):

| node | glTF position | yaw | footprint | place, clearance |
|---|---|---|---|---|
| `ANCHOR_lhd_zone-a` | (−24, −162, 123) | 180° (faces west) | 34 × 11 m | face chamber of w-07, 7.0 m |
| `ANCHOR_lhd_zone-b` | (−24, −324, 123) | 180° | 34 × 11 m | face chamber of w-12, 7.0 m |
| `ANCHOR_truck` | (87, −162, 32.5) | 180° | 34 × 11 m | pocket behind drift w-04, 12.0 m |
| `ANCHOR_drill` | (−100, −324, 79) | 180° | 47 × 11 m | terrace in front of drift w-10, 23.5 m |

## Numbers (last build, `python check_env.py`)

| item | value | budget (SPEC §8) |
|---|---|---|
| visible triangles | 42 526 (+192 invisible pick) | ≤ 100 k, aim ≤ 60 k |
| primitives / draw calls | 2 visible (+12 pick, hidden by the browser) | ≤ 80 |
| materials | 3 (`env_far`, `env_near`, `pick`) | |
| textures | 2 × 2048² JPEG | light maps ≤ 2 × 2048² |
| env.glb + textures | 1.66 MiB | whole `models/mine-art/` ≤ 8 MiB (2.86 MiB with the actors) |

Walking-line visibility from MainView (`build/visibility.json` against the GLB geometry, a
person's mid-body 2.5 m sampled every 2 m): drifts w-03/w-04/w-10/w-11, crosscuts w-05/w-06 and
both zone drifts 0 % hidden. Hidden stretches are where the topology stacks ramps in one vertical
plane: the lower ramp passes under the upper ramp's floor for 8–12 m after junctions a and c and
at the hairpin bends — w-09 5.1 %, w-08 3.6 %, w-01 2.8 % (longest 10 m), w-02 0.8 % (2 m under
the portal frame).

## Previews

`previews/overview.jpg`, `zone_a_3x.jpg`, `zone_b_3x.jpg`: Cycles renders of the lit scene from
MainView at 1920×1080. `previews/unlit_*.jpg`: `env.glb` re-imported into an empty scene,
emission-only materials, no lights (what three.js shows): `unlit_overview.jpg` (16:9),
`unlit_zone_a_3x.jpg`, `unlit_zone_b_3x.jpg`, and the 1× overview on a 1920 px wide 21:9 stage
(`unlit_overview_21x9.jpg`) and 4:3 stage (`unlit_overview_4x3.jpg`).
`previews/compare_prev_new_ref.jpg`: previous pass (c33b22f) | this pass | reference, overview
row and zone-A-at-3× row, all 600 px high. `previews/compare_smooth.jpg`: before | after the
smoothing pass (unlit overview and zone A at 3×).

The scripts write these previews as PNG; the repository keeps them as JPEG, quality 85
(same names, `.jpg`; the PNGs were 1.7-4 MB each).
