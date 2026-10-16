# Mine art: shared spec (branch `codex/claude-mine-art`)

The 3D stage of the dispatcher UI gets a hand-painted 2.5D look: the mine as an
illustrated cutaway in the style of the art references, seen by one orthographic
camera with smooth pan and zoom, light baked into textures, moving objects
separate. The interface around the stage (variant 3 "Depth") stays as it is.

Every agent on this branch reads this file. It is the contract between the
Blender build (environment, actors) and the browser code (scene3d).

## 1. Ground rules

- Worktree: `C:\Users\Azim\.codex\worktrees\claude-mine-ui\OpenegizRudnik`, branch
  `codex/claude-mine-art`. Never commit, push, merge or switch branches: the
  orchestrator commits.
- Never touch `C:\Users\Azim\Documents\ChatGPT\OpenegizRudnik` (the main checkout
  that runs the live stand), docker, or the servers on ports 8088 and 8091. Never
  kill a process by image name (`taskkill /IM`, `Stop-Process -Name`, `pkill`):
  only PIDs you started.
- Blender: CLI only, `"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
  --background --factory-startup --python <script>`. Never connect to the
  user's running Blender session. The page never needs Blender at run time.
- No downloads. three.js 0.186.1 is vendored in `team/ui/public/vendor/three/`
  (GLTFLoader in `addons/loaders`).
- Honesty rules of the UI hold: only published data drive state; no invented
  movement or counters; unknown never looks safe; hazard colours (red, amber,
  the unknown hatch) only for hazard; reduced motion respected; render on demand.
- Text that people read in the UI is Russian; code, comments and reports English.

## 2. The mine: the real topology

Source of truth: `team/sim/topology.py` (`build_attributes()`), the simulation
that runs on the stand. Levels: surface (0 m), level-120, level-240. Nodes
(x east, y north, z up, metres):

| node | x | y | z | kind |
|---|---|---|---|---|
| surface-a | 0 | 0 | 0 | exit (portal of ramp w-01) |
| surface-b | 420 | 180 | 0 | exit (portal of ramp w-02) |
| a, b, c | 0, 150, 300 | 0 | −120 | junctions |
| d | 150 | 160 | −120 | junction (crosscut loop) |
| face-a | 150 | −80 | −120 | dead end, zone A |
| e, f, g | 0, 150, 300 | 0 | −240 | junctions |
| face-b | 150 | −80 | −240 | dead end, zone B |

Workings: drifts w-03 a–b, w-04 b–c, w-10 e–f, w-11 f–g; crosscuts w-05 a–d,
w-06 d–c (polylines, 219.3 m each); zone drifts w-07 b–face-a (zone A),
w-12 f–face-b (zone B); ramps with bends: w-01 a→(−240,0,−60)→surface-a,
w-02 c→(540,0,−60)→surface-b, w-08 a→(−180,0,−180)→e, w-09 c→(480,0,−180)→g.
Read exact polylines from the attributes (`points`), never retype them.
Both exits are walkable ramps to the surface. **No shaft transport is
modelled**: a shaft or cage, if drawn, is decoration and never looks like a way
out (no exit sign, no route, no label "выход", not pickable).

Workers: worker-a1..a3 (zone A, on w-07 at 20/40/60 m), worker-b1..b3 (zone B,
on w-12). Positions arrive as `at_working` + `offset_m` (metres from the
working's `from` node), status working | moving_to_exit | waiting | out, and a
`route` of segments `{working, from, to, from_offset_m, to_offset_m}`. One
publication about every wall second advances 10 model seconds; a walking person
covers 12.5 m per publication.

## 3. From the mine to the scene (one transform for everything)

Scene metres, three.js axes (Y up): `X = x − cx`, `Y = (z − zTop)·k`,
`Z = cy − y` — the formula of `public/js/scene3d/layout.js`. For the art:

- `cx`, `cy`: centre of the bounding box of all nodes and polyline points in
  plan; `zTop` = 0 (the surface).
- `k = 1.35` (vertical exaggeration; 1.6 until the third art pass). The value is written into the GLB (section
  5) and the browser uses the value it reads there, never its own explode
  slider, while the art is shown.
- The same transform for workings, people, sensors, routes, hazard overlays and
  labels. Simulation distances are never changed: positions along a working
  are measured on the model polyline and then mapped.

Conventional sizes (drawn larger than real, and the scale note in the UI says
so): a working is drawn as a roofless trench 14 m wide with walls about 9 m
high; a person 5 m tall; machines 1.5× real. Floors of trenches lie exactly on
the mapped polyline (Y of the floor = mapped z).

## 4. Camera and composition

- One orthographic camera, looking from the south-east (azimuth measured from
  south toward the east), azimuth 24°, elevation 28° (chosen in the fourth art
  pass by comparing overviews at 22°, 24°, 30° and 40°: the drifts and ramps run
  diagonally, the mine fills the 16:9 frame and the lit back walls show). The
  Blender build may tune azimuth within 20–50° and elevation within 26–34°; the
  chosen camera is exported in the GLB (section 5) and is the only definition of
  the main view.
- The overview frames the whole mine, surface portals included, at 16:9.
- The browser allows pan and zoom only (zoom 1× to 4× of the overview, pan
  clamped to the mine's bounds), smoothed (critically damped, no overshoot,
  no shake). No orbit.

## 5. The environment GLB (Blender build → browser)

Files: `team/ui/public/models/mine-art/env.glb` plus its textures in the same
folder (`*.jpg` / `*.png`, referenced by the GLB or by extras).

- Scene extras (`scene.extras` in glTF): `{"mineArt": 1, "k": 1.35, "cx": …,
  "cy": …, "zTop": 0, "topology": "<sha1 of the sorted list of working ids with
  their from/to nodes and rounded polyline points>", "workings": [ids], "camera":
  "MainView"}`. The browser computes the same signature from the live twins;
  if it differs, it does not show the art and keeps the procedural scene of
  variant 3 (a mock with another topology, or a changed mine).
- `MainView`: a glTF orthographic camera node.
- Static environment merged by material, all materials `KHR_materials_unlit`.
  Light is baked. Either combined bake (albedo × light) on one UV set, or tiled
  painted detail on TEXCOORD_0 plus a baked light map on TEXCOORD_1 named in
  `material.extras.lightMap` (the browser sets `material.lightMap` with
  `channel = 1`). Whatever is chosen, near the two zones at 3× zoom on a
  1920×1080 stage there is at least one texel per screen pixel on floors and
  walls.
- Nodes whose names start with `PICK_` are invisible simplified pick meshes,
  one per working, `extras.thingId` = `team040.mine:<working id>`.
- Nodes `ANCHOR_<name>` (empties) mark places for decor that the browser adds
  (e.g. `ANCHOR_lhd_zone-a`).
- No lights, no cameras other than MainView, no animation in env.glb.

## 6. The actors GLBs (Blender build → browser)

Folder `team/ui/public/models/mine-art/actors/`:

- `worker.glb`: one person in orange coveralls with reflective stripes,
  yellow-white helmet with a cap lamp, 5 m tall in scene metres, origin between
  the feet, facing +X. Animation clips `walk` (a loop, root not moving, stride
  per cycle in `extras.strideM`) and `idle` (a still or a barely visible breath
  loop). Unlit materials with shading painted or baked into the texture.
  Budget ≤ 1 500 triangles, one material, one texture ≤ 512².
- `lhd.glb`, `truck.glb`, `drill.glb`: yellow mining machines in the same
  painted style, origin at ground centre, facing +X, unlit with baked shading.
  Separate nodes for anything that can change look: `LAMPS` (headlights and
  beacon, emissive), `WHEELS` (named `WHEEL_*`, spun only on real movement).
  Budgets: LHD ≤ 6 000 tris, truck ≤ 6 000, drill ≤ 7 000; one texture ≤ 1024²
  each.
- Without equipment twins, machines are decoration: the only state a machine
  may show is the published work state of the zone it stands in (lamps on when
  the zone works, off when it is stopped).
- With equipment twins (CONTRACT.md §9, model 0.2: `lhd-a`, `lhd-b`) the browser
  draws `lhd.glb` for each published loader at its published `at_working` /
  `offset_m`, turned towards `toward_node`, playing back between publications
  with the people (at most the registry's step, 30 m), lamps by its published
  `state` (working lit, parked dim, stopped or unknown dark), a browser-made heap
  of rock in the bucket only while `loaded`. The art's loaders at
  `ANCHOR_lhd_zone-*` are then hidden. The truck and the drill stay decoration
  with dark lamps (no telemetry, not pickable, said in the scale note). An
  operator riding a loader (`aboard`) is drawn as part of it, not as a figure.

## 7. Art direction

References (look only, not geometry):
`scratchpad\scene-kit\mine-scene-kit\reference-overview.png`,
`reference-detail.png` (full path:
`C:\Users\Azim\AppData\Local\Temp\claude\C--Users-Azim--codex-worktrees-claude-mine-ui-OpenegizRudnik\cd68de12-3493-40a6-92f0-63e15136b8d7\scratchpad\scene-kit\mine-scene-kit\`).

- Fourth pass: the balance of the clean isometric reference
  `scratchpad\ref2\reference-iso.webp` (natural reading, value structure) and the
  richness of the faceted pass.
- Rock: a dark charcoal body sculpted into big facets (large planes, soft strata
  on the cut faces, moderate contrast, light rims on upper edges), a few thin
  copper veins. The workings are tunnels opened along their length: light gravel
  floor > mid textured rock walls > dark rock, an irregular rock edge above with
  drips, rounded junctions, landings and face chambers.
- Workings: gravel floors with tyre tracks and loose stones, textured rock walls
  with light drips, steel sets (I-beam frames) every ~20–30 m, cables, a
  ventilation duct along the main drifts and down the zone drifts, warm lamps
  (≈2700 K, `#FFC37A`) with faint light cones, soft pools on the floor and a wash
  up the walls.
- Machines yellow (`#E8B22A` family), people safety orange (`#F26A1B`), steel
  mid grey, cabinets red/yellow as small props.
- Limited palette, slight hue variation, no plastic gloss, no random noise; thin
  selective dark outlines (painted or baked edge darkening), no full-screen
  outline pass.
- Hazard colours never appear in the art (no red floors, no amber stripes):
  hazard is drawn by the browser as overlays.

## 8. Budgets (targets)

Visible scene ≤ 100 k triangles (aim ≤ 60 k); ≤ 80 draw calls in an active
frame; textures: light maps ≤ 2 × 2048², detail textures ≤ 6 × 1024²; the
whole `models/mine-art/` ≤ 8 MiB. 60 fps on a laptop GPU, stable 30 fps on
SwiftShader at 1280×720 (no shadows, no post-processing, DPR ≤ 1.5).
