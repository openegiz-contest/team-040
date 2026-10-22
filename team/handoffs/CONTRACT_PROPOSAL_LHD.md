# Contract change proposal: loaders (LHDs) and the cost of options

Status: **proposal, 16 October 2026**, not yet part of team/CONTRACT.md. Written against CONTRACT.md as of 14 October; the copies in the UI worktree and the main checkout are identical. Once the Team accepts it, Codex merges it into CONTRACT.md in Russian. The model behind these fields is specified in team/handoffs/CODEX_LHD_TASK.md, and the UI side in team/handoffs/LHD_UI_PLAN.md.

Every change is **additive**: `contract_version` stays 1. There is one change of meaning, the zone's `production_rate` (§3). `topology_version` changes "t1" → "t2" because the set of twins changes, while the geometry stays byte-identical (§1).

## 1. Versions, volume, reading

| Item | Today | Proposed | Why |
|---|---|---|---|
| `contract_version` | 1 | 1 | Only new fields and twins, plus one changed meaning (§3) |
| `topology_version` | "t1" (topology.py:13) | "t2" | manifest and dynamic_ids change, so an open UI must re-read attributes (CONTRACT.md §2, line 55) |
| Workings and nodes | 12 workings, 11 nodes | **unchanged** | People's routes stay comparable, and the art mode's topology hash (artenv.js:54-67) still matches |
| Model version | "0.1" | "0.2" | Store migration (CODEX_LHD_TASK.md §7) |
| manifest | 34 ids | 38 ids (+lhd-a, lhd-b, worker-a4, worker-b4) | Within the target of 80 (CONTRACT.md §1.5) |
| dynamic_ids / scene | 29 | 33 | Same |
| Publication | 1 per wall second, 10 model s | unchanged | Equipment twins are published like workers (twins.py:85-94) |

Reading is unchanged (CONTRACT.md §2, lines 48-53). The 38 ids are read in two batches of 20.

## 2. Equipment twins (reconciles UI contract question 18)

Thing ids: **`team040.mine:lhd-a`**, **`team040.mine:lhd-b`**. There is one per zone with workings, because the real topology has two zones. Q18's `lhd-a … lhd-d` came from the invented four-zone fixture mine.

### Attributes (static, from `build_attributes`)

| Attribute | Value | Q18 |
|---|---|---|
| `kind` | `equipment` | same |
| `equipment_kind` | `lhd` | same |
| `label` | "ПДМ-A" / "ПДМ-B" (same lettering as "Участок A", topology.py:69) | same |
| `synthetic` | true | (all twins) |
| `_parents` | `team040.mine:zone-a` / `zone-b` | same (the zone) |
| `zone` | `zone-a` / `zone-b` (local name) | same |
| `length_m` | 10 (m, machine length for drawing; TBD-source) | same |
| `payload_t` | value of `lhd_payload_t` (t) | new |
| `operator` | `worker-a4` / `worker-b4` | new |
| `load_point` | `{working: "w-07", offset_m: 80}` / `{working: "w-12", offset_m: 80}` | new |
| `dump_point` | `"op-120"` / `"op-240"` (id in `mine.attributes.dump_points`) | new |
| `bay` | `{working: "w-03", offset_m: 75}` / `{working: "w-10", offset_m: 75}` (offset_m in m) | new |
| `cycle_route` | `["w-07", "w-03"]` / `["w-12", "w-10"]` | new |
| `cycle_s` | undisturbed cycle time, s (179 with the placeholders) | new |
| `nominal_production_t_h` | `payload_t × 3600 / cycle_s` (≈ 201 t/h with the placeholders) | new |

Offsets follow the workers' convention: metres from the working's `from` node (routing.py:29-34; geometry.js:105-107 on the UI side).

### Features (in `scene` and on the twin; `tick`, `sim_time_s` and `idSimulationRun` as for every element)

| Feature | Type, unit | Values / meaning | Q18 / UI today |
|---|---|---|---|
| `state` | string | `working` (cycling) · `parked` (held by the model while its zone works) · `stopped` (its zone is stopped) | same three values; UI vocabulary text.js:42 |
| `hold_reason` | string | `none` · `zone_stopped` · `entry_blocked` (zone `routing_restriction ≠ allowed`) · `path_closed` (on or before a closed working) · `crew_absent` | **new**; UI needs a vocabulary |
| `activity` | string | `loading` · `hauling` · `dumping` · `returning` · `tramming` (to the bay after a stop) · `yielding` (move shortened by a walking person) · `idle`. Describes the last model second of the publication | Q18 had the first five and `idle` (text.js:43-45); `tramming` and `yielding` are **new** |
| `at_working` | string (local id) | always present: a machine never leaves the mine | same; describe.js:107 |
| `offset_m` | number, `m` | from the working's `from` node | same |
| `toward_node` | string | the end node of `at_working` it moves to or faces | same; describe.js:115 |
| `loaded` | boolean | true from the end of loading to the end of dumping | same; describe.js:116 |
| `location_hazard` | string | as a worker's (model.py:134-136): zone hazard, or `unknown` on an unzoned working | **new** |
| `operator_aboard` | boolean | the operator rides the machine | **new** |
| `yielding_to` | string | the worker the machine yields to; only while `activity = yielding` | **new** |
| `loads_dumped` | integer | dumps since the run started | **new** |
| `run_hauled_t` | number, `t` | tonnes dumped since the run started | **new** |

Rules the UI may rely on (model: CODEX_LHD_TASK.md §3.6-3.9):

- A machine moves only along the workings of its `cycle_route`. It moves at most 10 × `lhd_speed_empty_m_s` metres per publication (30 m with the placeholders; `parameter_registry` has the exact value).
- It never teleports. Paused means it does not move.
- A new run puts it back at its load point.
- It never enters a zone whose `routing_restriction ≠ allowed`.

Q18's fixture rule "no closer than 20 m to a person" becomes this: no closer than `lhd_clearance_m` to a **walking** person on its path ahead. A crew at work in its own zone is exempt.

## 3. Zones, workers, mine

**Zone** (zone-a, zone-b):
- New attribute `equipment: ["lhd-a"]`.
- `nominal_production_t_h` keeps its name. Its value becomes the cycle rate (≈ 201 instead of 30).
- **Changed meaning:** the feature `production_rate` (t/h) is the nominal rate while the zone works, the crew is staffed **and** its LHD has `state = working`. Otherwise it is 0. So `downtime_s` also grows while a machine is held, under observe too.
- New feature `run_hauled_t` (t, since run start).

**Workers:**
- New twins `team040.mine:worker-a4` ("Р-A4") and `team040.mine:worker-b4` ("Р-B4"), with attributes `role = lhd_operator` and `vehicle = lhd-a` / `lhd-b`. `home_zone`, `initial_working` and `initial_offset_m` equal the machine's load point.
- All six existing workers get `role = crew`.
- New worker feature `aboard` (local equipment id). It is present only while the person rides a machine. Their `at_working`/`offset_m` then equal the machine's. The status is `working` in the normal cycle, and `moving_to_exit` while the machine trams to the bay under a withdrawal order. The published egress route stays the route from the current position.
- `workers_total` becomes 8, and the shared group of a decision includes the operators.

**Mine attributes:**
- New `dump_points`: `[{id: "op-120", label: "Рудоспуск 1", level: "level-120", working: "w-03", offset_m: 75}, {id: "op-240", label: "Рудоспуск 2", level: "level-240", working: "w-10", offset_m: 75}]`. These are not twins and have no state.
- New `parameter_registry` entries: `lhd_payload_t` (t), `lhd_speed_loaded_m_s` and `lhd_speed_empty_m_s` (m/s), `lhd_load_s` and `lhd_dump_s` (s), `lhd_availability` (1, research context only), `lhd_clearance_m` (m). Each has `status` and `source_ids`. Until notes-kz.md provides a cited source, status is `scenario_assumption` and the rationale says "TBD-source".
- `counts` gains `equipment: 2`, and `worker` becomes 8.

## 4. New forecast and actual fields on options

On each `option-*`, as `forecast_<key>` at the decision and `actual_<key>` when done. They also appear in the run archive under `<key>` (model.py:316-324). The mechanism is unchanged (model.py:235-239, twins.py:58-65).

| Key | Unit | Definition | Window |
|---|---|---|---|
| `hauled_t` | t | Tonnes dumped into ore passes | since the decision checkpoint |
| `planned_t` | t | Tonnes the same machines would have dumped from their state at the checkpoint with nothing stopping them. **Identical for the three options of one decision** | same |
| `production_lost_t` | t | `planned_t − hauled_t`, ≥ 0 | same |
| `machines_in_danger` | — | Machines on a working of a zone with `hazard_state = danger` | at the horizon end (like `in_danger`) |
| `machines_unknown` | — | Machines on a working of a controlled zone with `hazard_state = unknown` | at the horizon end |
| `machines_stuck` | — | Machines on a closed working or held with `path_closed` | at the horizon end |
| `conflicts` | — | Machine-person encounter episodes: a walking person within `lhd_clearance_m` + one second of travel ahead on the machine's path | since the checkpoint |
| `conflict_yield_s` | machine*s | Machine-seconds in which a machine's move was shortened by a walking person | since the checkpoint |

The forecast at the decision equals the actual result at the horizon for all of these, as for the existing metrics (comparison.py:55-60). `comparison_key` also covers the machine state.

Add these rows to the definitions table of CONTRACT.md §6:

- `production_lost_t`: tonnes not hauled because of holds, stops and yields relative to the undisturbed cycle. It is not a financial loss. The model has no prices.
- `conflicts`: an indicator of vehicle-pedestrian encounters in shared workings under the model's rule. It is not a probability of a collision.

## 5. Shift-level totals

New features on `shift`, current values like `workers_in_danger` (twins.py:69-75):

| Feature | Unit | Meaning |
|---|---|---|
| `production_rate` | t/h | sum of the zones' `production_rate` |
| `run_hauled_t` | t | tonnes since the run started |
| `machines_total` | — | 2 |
| `machines_working` | — | machines with `state = working` |
| `machines_in_danger` | — | as §4, now |
| `machines_stuck` | — | as §4, now |

New units in the model's unit table (twins.py:7-14): `t` and `machine*s`. History exports the integer counters `machines_*` and `loads_dumped` as integers, and tonnes as floats (team/history/ditto_scalar.star:4-7).

## 6. Journal codes

These are compatible with research/event-journal.md: `arg` is a ready Russian sentence and `details` is structured.

| Code | Subject | When | details |
|---|---|---|---|
| `equipment.state_changed` | lhd-x | `state` or `hold_reason` changed | before/after {state, hold_reason}, at_working, offset_m, causes |
| `equipment.hazard_changed` | lhd-x | `location_hazard` changed (it entered or left a zone, or the zone's state changed) | before/after, working, zone, causes |
| `equipment.conflict` | lhd-x | an encounter episode started | worker, working, gap_m, machine_offset_m, worker_offset_m, causes |

Cycle phases create no events. An operator getting off is the existing `worker.state_changed`. Forecast copies write nothing (model.py:80-82).

## 7. Rules to add to CONTRACT.md §7

- Machines follow the people's routing restrictions: no new entry into danger or unknown controlled zones, no passing through closed workings, no teleport, and cancelling a condition does not restart them (only `action.resume_zone` does).
- **People first.** Machines never slow or reroute people. A machine shortens its move to keep `lhd_clearance_m` from a walking person ahead on its path. A crew working in its own zone is assumed to be protected by the zone's traffic plan and is not counted. Parked machines stand in cut-outs and are not obstacles.
- Under a stop or withdrawal order, a machine drives to its bay at the ore-pass station, dumping first if loaded. It stops where it stands if the path is closed. Its operator gets off at the bay and walks out under the people's rules.
- `lhd_availability` is not applied inside the comparison window: the window assumes the machines are available.

## 8. What the UI supports today, and what it needs

Read in team/ui/public/js on branch codex/claude-mine-art.

| Item | Supported today | Needed |
|---|---|---|
| Equipment twins of kind `equipment` / `lhd` from attributes | yes: scene3d/actors.js:79-82, scene3d/describe.js:102-118 | — |
| `state`, `activity`, `at_working`, `offset_m`, `toward_node`, `loaded` | yes: describe.js:108-117; labels content.js:259-280; card card.js:376-379; vocabulary text.js:42-46 | vocabulary for `tramming`, `yielding` |
| Glide between publications | yes, up to 30 m per publication (actors.js:42-46) | take the limit from `parameter_registry` (10 × empty speed) |
| Validation of equipment elements | accepted (no required fields for the kind, validate.js:42-51) | add `state`, `at_working`, `offset_m` as required after Codex lands |
| Unknown enum value / unknown journal code | shown as is, no crash (text.js:209-212; event-journal.md:10) | Russian text for `hold_reason`, `equipment.*` |
| Art mode (illustrated mine) | shows the art's static loaders at anchors, lamps by zone work state (scene.js:3714-3750) | draw the model's loaders on the art instead; keep truck and drill as decoration |
| Option table rows | fixed lists decision.js:19 (METRIC_ORDER) and :27 (DECISION_ROWS); people only plus downtime | cost rows: `production_lost_t`, machines, `conflicts` |
| Units | `t/h`, `person*s`, `zone*s` (text.js:138) | `t`, `machine*s` |
| Worker `role`, `aboard` | not read | an operator aboard is drawn as part of the machine |
| `mine.attributes.dump_points` | not read | ore-pass marker in the scene and on the rail |
| Shift `production_rate`, `machines_*`, `run_hauled_t` | not read | status bar / depth rail summary |
| Depth rail | people only (view/horizons.js:1-30, :291) | machine markers at the depth of their working |

## 9. What the UI will show with it (brief; details in team/handoffs/LHD_UI_PLAN.md)

- **Stage:** loaders moving along their cycle from published positions. The bucket is full when `loaded`. They yield visibly to walking people, show the ore passes, and show held and stopped machines with the reason.
- **Options:** each card shows the benefit (people out, time, exposure) and the cost (tonnes lost of planned, machines in danger or stuck, encounters) side by side. The compare panel lines up both for the three options. Nothing is ranked or recommended.
- **Depth rail:** the machines at the depth where they are, and a level's summary including its machines and production.
