# UI plan: loaders and the cost of options

This plan covers the dispatcher UI changes that follow Codex's LHD work. The data is defined in team/handoffs/CONTRACT_PROPOSAL_LHD.md (cited as "proposal §n") and the model in team/handoffs/CODEX_LHD_TASK.md. The UI computes nothing: every number and position shown comes from a published field. Nothing is ranked or recommended.

The dependency order:

1. **U0** runs first: it needs Codex's commit.
2. **U1** comes next, because every later item reads its data.
3. **U2 to U5** can then run in parallel.
4. **U6** is the final pass.

## U0. Recordings of the new simulation

- Re-record `fixtures/sim_*.json.gz` with `python team/ui/tools/sim_fixtures.py` from Codex's branch.
- Update fixtures/SIM.md: 8 people, 2 machines, topology "t2", and the new option fields.
- The invented fixtures keep their four `lhd-a … lhd-d`. Add the new fields there only where a test needs them (`hold_reason`, `yielding`).

**Checks**
- `python team/ui/tools/sim_fixtures.py --check` passes.
- `tests.test_sim_fixtures` passes. Its forecast-equals-actual check covers `production_lost_t`, `planned_t`, `machines_*`, `conflicts` and `conflict_yield_s`.
- Every recorded frame passes validate.js.
- Art mode is still active on all four sim scenarios. The workings are unchanged, so artSignature (scene3d/artenv.js:54-67) still matches. Assert it in tests.test_art_mode.

## U1. Reading the data

- **validate.js:42-51:** make `state`, `at_working` and `offset_m` required for `equipment`, so the check fails closed like it does for workers.
- **describe.js:102-118:** also read `hold_reason`, `location_hazard`, `operator_aboard` and `yielding_to`.
  - For workers, read `role` and `aboard`.
  - For the mine, read `dump_points`.
  - From `parameter_registry`, read `lhd_speed_empty_m_s` and `speedup`.
- **text.js:**
  - Equipment vocabulary (text.js:42-46): add `tramming` («едет в нишу») and `yielding` («уступает дорогу»), plus a `hold_reason` vocabulary («вход в участок запрещён», «проход закрыт», «участок остановлен», «нет бригады»).
  - Units (text.js:138): `t` → «т», `machine*s` → «маш.·с».
  - Field labels for the new metrics and shift fields.
  - Journal text for `equipment.state_changed`, `equipment.hazard_changed` and `equipment.conflict`. The `arg` is already a ready sentence.

**Checks**
- A frame without an equipment `state` is rejected and the banner names the field.
- Every new enum value has a Russian label. An unknown value is still shown as is, not hidden.
- `tests.test_logic` covers all new vocabularies.

## U2. Machines on the stage (art mode first, then the procedural 3D and the scheme)

- **Art mode.** Today it shows the art's own loaders at `ANCHOR_lhd_zone-*` as symbols of the zone's work state (scene3d/scene.js:3714-3750).
  - With equipment twins present, hide the zone anchors' loaders. Draw each published machine with the art's `lhd.glb` at its published `at_working`/`offset_m` on the art's polylines, facing `toward_node`.
  - The truck and the drill stay decoration.
  - Without equipment twins, today's behaviour stays.
- **Motion.**
  - Glide between publications as actors.js does (actors.js:508-552).
  - The jump limit becomes `speedup × lhd_speed_empty_m_s × 1.1` from the registry. Today it is a fixed 30 m (actors.js:46), which is exactly the step at the placeholder speed.
  - Nothing moves on a pause, after a failed read, or in a new run (a new run is a jump).
  - Reduced motion makes every move instant.
- **Looks** (from published fields only):
  - `loaded`: the bucket holds rock (already supported, loaders.js:12).
  - `working`: lamps on.
  - `parked`: lamps dim, and a small tag gives the `hold_reason`.
  - `stopped`: lamps off, tag «участок остановлен».
  - `location_hazard = danger`: the same danger ring as a person.
- **Yielding.** While `activity = yielding`, draw a thin line from the machine to the figure of `yielding_to`, with the tooltip «уступает дорогу Р-A2». The line disappears with the next publication that no longer says so.
- **Operator aboard.** No separate figure. The machine's label gets a small person badge, and selecting the badge opens the operator's card. When `aboard` disappears, the figure appears at the published position and walks.
- **Ore passes.** A small grate marker at each `dump_points` entry, labelled «Рудоспуск 1/2». In art mode it is drawn on the floor of the art's drift.

**Checks** (tests.test_art_mode, tests.test_scene3d; screenshots at 1280×720 and 1920×1080)
- In `sim_instability` at the decision frame:
  - lhd-a is drawn within 1 m of the screen point of its published (w-07, offset), with the bucket full.
  - Advancing one publication glides it, and its drawn path never exceeds the registry limit.
- Paused frames: the machine's screen position is unchanged across 5 heartbeats.
- A new run puts the machine back at the load point without a glide.
- In `sw_exec` the yielding line is drawn exactly in the publications where lhd-a publishes `activity = yielding` and in no others. With the placeholder parameters these are the first publications after the decision, while crew A walks out of w-07 ahead of the machine.
- The p-trapped recording shows lhd-a parked on w-07 with «проход закрыт».
- No operator figure is drawn while `aboard` is published.
- The scheme mode places a machine symbol at the same working and offset.

## U3. Option cards: benefit and cost on one card

Each option card (view/decide.js:204-224) keeps its headline: people out, time, exposure. A second line gives the cost from the published `forecast_*` fields:

- e.g. «Недовывезено 52 т из 100 т плана» (`production_lost_t` of `planned_t`; the numbers here illustrate the format only),
- «ПДМ в опасности: 1» or «ПДМ застряла: 1», shown only when > 0,
- «Встреч с людьми: 2 (ПДМ ждала 40 с)» (`conflicts`, `conflict_yield_s`).

Rules:
- If a field is not published, say «цена не опубликована». Never write 0 for a missing value.
- Keep the tonnes as published (t). They are not converted to money.

**Checks**
- With the recorded `sim_instability` forecasts, the three cards show exactly the published numbers. Compare them with the raw `forecast_*` values in the test.
- A frame without the cost fields shows «цена не опубликована» and no zeros.
- Keyboard and screen reader: the cost line is part of the card's accessible name.

## U4. Compare panel: people against cost

The variant table (view/decision.js, DECISION_ROWS :27) gets two labelled groups in the same columns:

1. **Люди:** `in_danger`, all out and when, `out`, `no_route`, exposures. These are today's rows.
2. **Цена:** `production_lost_t` with `planned_t` in its title, `machines_in_danger`, `machines_stuck`, `conflicts`, `downtime_s`. `downtime_s` moves here, because it is production time.

Rules:
- `planned_t` is the same for all three options by definition, so it is written once in the group header («план за 15 мин: 100 т»).
- No column is highlighted as best. The chosen option keeps its existing outline.
- After execution the fact (`actual_*`) is shown next to the forecast as today. The archive table (METRIC_ORDER, decision.js:19) gains the same cost metrics.

**Checks** (tests.test_clarity VariantTableTest, tests.test_panels)
- Row order and group labels are as above.
- `planned_t` appears once.
- With the p-detour recording, observe shows the smallest tonnes lost and the withdrawals show `conflicts` > 0. The test reads both from the published data, not from constants.
- The panel fits 1280×720 without hiding the people group. It may scroll, as today (README.md:149).

## U5. Depth rail and status bar

- **Depth rail** (view/horizons.js):
  - Draw a machine marker, a small loader glyph distinct from the person dots, at the depth where the stage draws the machine (the same playback rule as people, horizons.js:291).
  - A held or stopped machine shows its state in the marker.
  - The level chip adds «ПДМ-A: везёт руду» and the level's zone `production_rate`.
  - Draw the ore passes as ticks on their level.
- **Status bar:** add the shift's `production_rate` (t/h) and `run_hauled_t`. Add `machines_in_danger` / `machines_stuck` only when > 0.

**Checks** (tests.test_depth_rail)
- The machine marker's depth equals the stage's drawn machine depth within 1 px.
- Nothing moves on a pause.
- The chip of level −120 in the `sim_instability` decision frame names ПДМ-A and its activity.
- The status bar shows the published `production_rate`, and 0 when every machine is held.

## U6. Card, list, journal; final pass

- The equipment card shows:
  - state with reason,
  - activity,
  - load,
  - position (working and metres),
  - `location_hazard`,
  - operator aboard,
  - `loads_dumped` and `run_hauled_t`,
  - the cycle attributes (`cycle_s`, `nominal_production_t_h`, `payload_t`), with the registry's TBD-source status in the tooltip.
- The list gets a «Техника» group.
- The journal filters `equipment.*` with the people events.
- README.md:
  - Mark contract question 18 as answered by the proposal.
  - Update the volume note: 38 twins, so the earlier 81/82 concern no longer applies (README.md:198).
  - Update the test table.

**Checks**
- The full UI suite passes: `PYTHONUTF8=1 python -m unittest discover -s team/ui/tests -t team/ui -v` (README.md:83).
- Screenshots of the four sim scenarios at both sizes in art mode, viewed by eye: machines visible, cost rows readable, no overlapping labels on the machines at 1280×720.
- A grayscale screenshot keeps the machine states and the cost rows readable without colour.

## Open points for the UI

- If Codex sources a speed that gives more than 30 m per publication, U2's registry-based limit covers it. Until U2 lands, the UI would show jumps instead of glides.
- If the Team rejects operators as people (CODEX_LHD_TASK.md §12, Q1), drop the aboard badge. The people bar's group goes back to 6.
- The art has no ore-pass geometry. The marker in U2 is drawn by the browser. A grate in the art itself would need a Blender rebuild with an `ANCHOR_orepass_*` node (assets/mine-art/SPEC.md:116-117), which is optional.
