# Codex task: loaders (LHDs) in the simulation and the cost of each option

Today every option the dispatcher sees reports the people side of the decision: how many are out, when, and the danger and unknown exposure (team/sim/model.py:328-343). It says nothing about what the option costs, so "withdraw everyone" always looks free. This task adds one load-haul-dump machine (LHD) per zone to the simulation and makes every option report its cost next to its benefit: tonnes lost, machines left in a hazard or stuck, and machine-person conflicts on shared workings.

Read team/CONTRACT.md in full first. The data contract for this task is in team/CONTRACT_PROPOSAL_LHD.md, and the UI side is in team/ui/LHD_UI_PLAN.md. All three documents use the same names. If they disagree, the proposal wins, and you report the disagreement.

## 1. Goal and why it serves the decision

The Concept (SUBMISSION.md:11-13) names one user, the shift dispatcher, and one decision: stop a zone and/or withdraw personnel, given ground stability and exit availability. Real dispatchers weigh that decision against production. Today the model has no production beyond a constant 30 t/h per staffed zone (team/sim/topology.py:70, model.py:144-147), so the comparison cannot show a cost.

After this task, each option at a decision point publishes, from the same checkpoint and the same code:

- **Benefit (already published):** people out, time until all are out, danger and unknown exposure, people without a route.
- **Cost (new):** tonnes not hauled within the horizon, machines that end the horizon in a danger or unknown zone or stuck on a closed working, and machine-person encounters on shared workings with the machine delay they caused.

The model does not rank the options. comparison.md keeps saying that the criteria differ ("Автоматического «лучшего варианта» в отчёте нет", team/research/comparison.md:117). The task makes the trade-off visible. It does not decide it.

## 2. Scope

In scope (Codex owns): team/sim/*.py and its tests, team/history/ditto_scalar.star, team/research/ (new equipment.md, updates to parameters.md, comparison.md, comparison.json, event-journal.md, sensitivity.json if regenerated), team/sim/README.md, the "Mine"/"What works" numbers in SUBMISSION.md that this change alters, and merging the proposal into team/CONTRACT.md once the Team accepts it.

Out of scope:
- team/ui/: Claude will re-record the sim fixtures and change the UI after your commit (LHD_UI_PLAN.md).
- New workings or nodes (see 3.1).
- Trucks, hoisting, ore-pass capacity and hang-ups, refuelling, breakdowns, stochastic availability, machine-machine traffic, fire and smoke.

## 3. The model

### 3.1 Geometry: no new workings or nodes

The load points, dump points and bays are **positions on existing workings**. They are published as attributes, so the routing graph and the topology geometry stay exactly as they are today (topology.py:18-66). There are two reasons:

1. People's routes, and so every people number in comparison.md, depend only on the graph (routing.py:7-54). Leaving the graph alone keeps every crew member's route and exit time identical to the published results. Only the two new operators (3.2) add people numbers.
2. The UI's illustrated art mode is shown only when a hash of the working ids, their end nodes and their rounded polylines equals the hash the art was built from (team/ui/public/js/scene3d/artenv.js:54-67). Any new working or node turns art mode off until the art is rebuilt in Blender.

| Place | Zone A (level −120) | Zone B (level −240) | Status |
|---|---|---|---|
| Load point (face draw point) | w-07 at 80 m = node face-a | w-12 at 80 m = node face-b | Team geometry. The face is the dead end of the zone drift (topology.py:25, :29, :48, :53) |
| Dump point: ore pass | `op-120`: w-03 at 75 m from a (75 m from b) | `op-240`: w-10 at 75 m from e (75 m from f) | Offset 75 m is a placeholder, **TBD-source**: typical LHD tramming distance (notes-kz.md, see 3.3) |
| Bay (parking cut-out) | same place as op-120 | same place as op-240 | Convention. See below |
| Fixed cycle route | w-07 (face-a → b), w-03 (b → 75 m) | w-12 (face-b → f), w-10 (f → 75 m) | Shortest path from load point to dump point on t1 geometry |

Haul length is 80 + 75 = 155 m one way for both zones.

**Why the bay is the ore-pass station.** The station is outside both controlled zones, so a machine parked there is never in a hazard zone. It is also off the base egress routes: crew A walks w-07 → b → w-04 → c → w-02 and crew B walks w-12 → f → w-11 → g → w-09 → c → w-02 (comparison.md:79-81: 641.886 m for worker-a1). And it needs no second set of coordinates. The model treats the station as a side cut-out, so **a parked machine is not an obstacle to people**. Say this assumption in README and in parameters.md. In p-detour (w-04 closed) crew A walks w-03 past op-120, and the conflicts there are the visible effect of that detour.

The ore passes are attributes only (`mine.attributes.dump_points`). They are not twins and have no state.

### 3.2 Machines and operators

- **Two equipment twins:** `lhd-a` (zone-a) and `lhd-b` (zone-b), `kind = equipment`, `equipment_kind = lhd`. The full attributes and features are in CONTRACT_PROPOSAL_LHD.md §2.
- **Two operators:** `worker-a4` and `worker-b4`, ordinary `kind = worker` with `role = lhd_operator` and `vehicle = lhd-a` / `lhd-b`. The existing six get `role = crew`. While an operator is aboard, their `at_working`/`offset_m` equal the machine's and the worker feature `aboard` names the machine.

  Why operators are people in the model: a machine in a danger zone has a person in it. If the operator is not modelled, the observe option hides that operator's exposure, and the time to bring the machine out never shows up in people-out times. The cost is that the shared group grows from 6 to 8. All people numbers in comparison.md change and must be re-run, but they stay mutually comparable because the same rule applies to every option. If the Team rejects this, see Q1 in §12.
- **Staffing:** `required_workers` (topology.py:71) counts `role = crew` only. A machine works only with its operator aboard. Change the staffing count at model.py:144-145 and the `insufficient_workers` check at model.py:461-464 to match. resume_zone also requires the operator aboard.
- **Cohort:** operators enter the shared group like anyone underground (model.py:204, :329). Scope reasons (model.py:161-189) include them automatically through `home_zone`.

### 3.3 Parameters

Add these to `PARAMETERS` (parameters.py:5-15), with units and rationale in `registry()` (parameters.py:42-65) and checks in `validate()` (parameters.py:28-39): `lhd_load_s` and `lhd_dump_s` are integers, `0 < lhd_availability ≤ 1`, and `lhd_speed_loaded_m_s ≤ lhd_speed_empty_m_s`. Every value below is a **placeholder marked TBD-source**. Until a source is recorded, the registry entry has `status = scenario_assumption` and `source_ids = []`.

Kazakhstan and manufacturer data are collected in `team/research/kz-open-sources.md` (`notes-kz.md` below; every number there carries its URL and a [F]/[S]/[U] verification mark — use only [F] values as sources). Take values only from what that file actually cites. Copy each value with its source into a new team/research/equipment.md, and put the source in `SOURCES` (parameters.py:17-25). Any value notes-kz.md does not cover stays a placeholder marked TBD-source in the registry and in equipment.md. Do not invent a source.

| Key | Placeholder | Unit | Used for | Status |
|---|---:|---|---|---|
| `lhd_payload_t` | 14 | t | tonnes per dump | Sourced: Sandvik LH514 rated capacity 14 000 kg (https://www.mining.sandvik/en/products/equipment/loaders/lh514-underground-lhd, [F] in notes-kz.md). A 14-t class LHD matches Kazakhstan practice (ERG Donskoy GOK orders Epiroc ST14, notes-kz.md). Rated capacity, not an average fill: say so in equipment.md |
| `lhd_speed_loaded_m_s` | 2.5 | m/s | travel loaded | TBD-source: operating speed loaded on a level drift, not the top speed in the brochure |
| `lhd_speed_empty_m_s` | 3.0 | m/s | travel empty, tramming | TBD-source: as above, empty |
| `lhd_load_s` | 45 | s (integer) | loading at the face | TBD-source: bucket fill time at the draw point |
| `lhd_dump_s` | 20 | s (integer) | dumping into the ore pass | TBD-source |
| `lhd_availability` | 0.8 | 1 | **registry and equipment.md only**: the shift capacity context in the README. Not used inside the window | TBD-source: mechanical availability of underground LHDs |
| `lhd_clearance_m` | 20 | m | machine-person interaction rule (3.8) | TBD-source: minimum separation of a moving vehicle from pedestrians in an underground working, from the Kazakhstan industrial safety rules for mining or a mine traffic management plan (notes-kz.md). The fixtures also use 20 m (team/ui/fixtures/README.md, «Техника») |

Equipment attributes (not `PARAMETERS`): `length_m` — take the LH514 length from its spec page if it is published there, else TBD-source (LH517i is 11.5 m, [F] in notes-kz.md), used for drawing only. Geometry offsets are in 3.1.

**Why availability does not enter the window.** The model is deterministic and the window is 900 s. A breakdown in a 15-minute window would be a random event, and the model has none (seed 40 is only an identifier, research/parameters.md, Seed row). Scaling tonnes by 0.8 would publish fractional "expected" tonnes, which the model never actually hauls, and the forecast-equals-actual check would stop meaning anything physical. So availability is stated only in research as context for shift tonnage. Say so in the registry rationale.

**Speed and the UI.** One publication covers `speedup` = 10 model seconds (service.py:95-98), so a machine moves up to 10 × `lhd_speed_empty_m_s` = 30 m between publications. The UI treats a step longer than 30 m as a jump, not a glide (scene3d/actors.js:42-46). If a sourced speed raises this above 30 m, say so in your report so that the UI changes its limit (LHD_UI_PLAN.md U2).

### 3.4 Cycle and production rate

Each LHD runs the deterministic cycle **loading → hauling → dumping → returning** on its fixed cycle route:

- `loading` lasts `lhd_load_s` one-second steps at the load point, empty. `loaded` becomes true at its end.
- `hauling` moves toward the dump point at `lhd_speed_loaded_m_s` per step.
- `dumping` lasts `lhd_dump_s` steps at the dump point. At its end, add `lhd_payload_t` to the counters and set `loaded` to false.
- `returning` moves toward the load point at `lhd_speed_empty_m_s`.
- A travel leg ends in the step where the remaining distance is ≤ the step length. The next phase starts in the next step, and unused distance is not carried into it. Distance does carry across a node within a leg, as for workers (model.py:260-274).
- LHDs drive both ways, so a reversal (3.6) takes no time and no turning space.

With the placeholders the cycle is 45 + 62 + 20 + 52 = **179 s**, so the cycle rate is 10 × 3600 / 179 ≈ **201 t/h** per zone. Do not hard-code this. Compute `cycle_s` by stepping an undisturbed machine through one cycle in `build_attributes`, and publish it as an equipment attribute.

**This replaces today's 30 t/h.** The zone attribute `nominal_production_t_h` (topology.py:70) keeps its name, because the UI and tests read it, but its value becomes `lhd_payload_t × 3600 / cycle_s`. The zone feature `production_rate` (model.py:146-147) becomes:

> `nominal_production_t_h` if the zone's `work_state = working`, its crew is staffed (≥ `required_workers` with `role = crew`, status `working`), and its LHD has `state = working`; otherwise 0.

`downtime_s` keeps its definition: zone-seconds with `production_rate = 0` (model.py:287-289). This fixes a limitation that comparison.md states for p-trapped: observe used to show zero downtime although the zone could not ship ore. Now a held machine stops production.

**Starting state.** At tick 0 of every run both machines are at their load points at the start of `loading`, with operators aboard. This is a convention, not a measured value. With the placeholders, at tick 60 (the preset event) each machine is hauling on its zone drift at about 42.5 m from the junction (w-07 / w-12), among the crew.

### 3.5 Order of one model second

Keep advance() (model.py:276-310) and insert the machines after the workers:

1. Exposure and downtime from the left endpoint (unchanged, model.py:284-289).
2. Workers move (model.py:290-291). Operators aboard do not move by themselves.
3. **Machines step** (3.4, 3.6-3.8), using the people positions after step 2. Operators aboard take the machine's position. Shadow machines step (§4).
4. Sensors, tick, schedule, `_refresh` (model.py:292-300). `_refresh` computes the machine `state`/`hold_reason`/`location_hazard` and the zone `production_rate`.

The machines are always processed in sorted id order.

### 3.6 Behaviour under each command and option

| Situation | Machine | Operator |
|---|---|---|
| Normal, zone `working` | cycles. `state = working` | aboard, `status = working` |
| **observe** | keeps cycling while every rule below allows | stays aboard |
| **stop_withdraw_zone** for a zone in scope / **action.withdraw_zone** (model.py:254-258, :472-477) | `state = stopped`, `hold_reason = zone_stopped`. If loaded, it drives on to the ore pass and dumps (the tonnes count). If empty, it reverses or continues toward the bay. At the bay `activity = idle`. If the path to the bay is closed, it stops where it stands (`hold_reason = path_closed`) | stays aboard (`status = moving_to_exit`, `aboard = lhd-x`) while the machine moves, and gets off when it parks, then walks the published route (routing.py). If there is no route, `waiting` |
| **withdraw_all** | every machine as above | every operator as above |
| **action.stop_zone** without withdrawal (model.py:468-471) | trams to the bay as above and parks | stays aboard, `status = working` |
| **action.resume_zone** (model.py:458-467) | resumes the cycle from where it stands if the zone may be entered and the operator is aboard. resume_zone is also accepted when the zone is `working` but its machine is held (`parked`): today that case returns `already_in_state` (model.py:465-466) | — |

**Why drive to the bay rather than stop in place.** Driving out moves the machine out of a possible hazard and frees the drift, and the operator rides most of the distance at machine speed, which is faster than walking. Stopping in place would leave the machine in the zone and add an obstacle. Stopping in place is used only when the path to the bay is closed, the same way a person on a closed working does not teleport (CONTRACT.md §7, line 146).

### 3.7 Hazards and closures

Machines follow the people's routing rules (routing.py:14-17, :29-34; CONTRACT.md §7, line 147):

- **No new entry** into a controlled zone whose `routing_restriction ≠ allowed` (danger, or unknown after sensor loss, model.py:114, :123-124). The entry check is made before a machine starts the leg into the zone, which is the start of `returning` at the dump point. A held machine waits there with `state = parked`, `hold_reason = entry_blocked`, `activity = idle`. A machine already inside may finish its current task and leave.
- **Closed working:** a machine that stands on a closed working stops where it stands (`path_closed`). So does a machine whose next step would enter one. It never teleports.
- **Crew missing:** a zone that is still `working` but no longer staffed (3.2) holds its machine at the next stop of the cycle with `state = parked`, `hold_reason = crew_absent`.
- **State and reason.** `state` is `stopped` exactly when the zone's `work_state = stopped`, `parked` when the zone works but the machine is held, and `working` otherwise. `hold_reason` is the first that applies: `path_closed`, `zone_stopped`, `entry_blocked`, `crew_absent`, `none`.
- **Cancelling a condition restarts nothing.** A held machine stays held until action.resume_zone (CONTRACT.md §7, line 151).
- **`location_hazard`** of a machine is computed as for a worker (model.py:134-136): the zone hazard of its working, or `unknown` on an unzoned working.
- **Hazard metrics** (end of horizon, like `in_danger`): `machines_in_danger` counts machines on a working of a zone with `hazard_state = danger`. `machines_unknown` counts machines on a working of a controlled zone with `hazard_state = unknown`. `machines_stuck` counts machines on a closed working, or held with `path_closed`.

### 3.8 Machine-person interaction: people first, machines yield

The rule must be minimal, deterministic and fixed:

- **Who counts.** A person counts if they are walking, which means `status` is `moving_to_exit` or `waiting` and they are not aboard a machine. A crew member at work (`status = working`) in their own zone does not count, because the crew works under the zone's traffic plan and steps into refuges when the loader passes. This is a stated simplification: without it the cycle would collide with its own crew in every cycle.
- **Gap.** Each step, take the machine's remaining planned path (its leg, or its path to the bay). The **gap** is the path distance to the nearest counted person standing on that path ahead of the machine. People behind the machine and people past the end of its path do not count.
- **Move.** The machine moves `min(speed, max(0, gap − lhd_clearance_m))`. If that is less than `speed`, the machine **yielded** this second: `activity = yielding`, `yielding_to = <worker>`, and the second adds 1 to `conflict_yield_s`.
- **Episodes.** A (machine, person) **encounter episode** starts in the first second that person is within `lhd_clearance_m + speed` ahead on the path, and ends in the first second they are not. `conflicts` counts episode starts.
- **Effect on people.** People are never slowed and never rerouted by machines. Their trajectories are exactly those of the model without machines, apart from the two operators. Parked or stationary machines (loading, dumping, idle) are not obstacles and create no episodes.

Why "people first". It keeps all crew exit times identical to today's tested values (test_model.py:79-92) and keeps the meaning of the people metrics unchanged. The cost of the conflict shows up where it belongs: as machine delay, which means fewer tonnes and a later parking, and as a count of encounters, which is the risk indicator. A delay for people (stepping into a refuge) is a possible later refinement, see Q3 in §12.

With the placeholders the result is not cooked. At the decision (tick 60) each machine is hauling about 42.5 m into its zone drift. In a withdrawal the crew members ahead of it start walking toward the same junction, so the machine follows at clearance distance. Under observe nobody walks, so there are no conflicts. In p-detour crew A also walks w-03 past op-120.

LHD-A and LHD-B never share a working, so machine-machine traffic is not modelled. Add a test that the cycle routes are disjoint.

### 3.9 Pause, reset, new run

Machines behave exactly like workers:

- Paused (`run_state = paused`) means no machine step, because advance() breaks first (model.py:280-281). Heartbeats republish unchanged positions.
- `run.reset` and `run.start_preset` rebuild the machines from attributes in `_new_run` (model.py:36-78): the initial phase from 3.4, counters at zero.
- Forecast copies carry the machines automatically, because `copy.deepcopy(self)` copies the whole model (model.py:229).

## 4. Forecast metrics and the comparison discipline

Add these keys to `metrics()` (model.py:328-343). They then appear as `forecast_*` on options (model.py:239), as `actual_*` on a done option (twins.py:64-65), in the run archive (model.py:319) and in the forecast-equals-actual check (comparison.py:55-60), with no other code.

| Key | Unit | Definition |
|---|---|---|
| `hauled_t` | t | Tonnes dumped into ore passes since the window started. The window starts at the decision checkpoint, or at run start before any decision, and resets in `_open_decision` like exposure (model.py:203) |
| `planned_t` | t | Tonnes the same machines would have dumped over the same window from their state at the window start, **undisturbed**: no holds, stops, yields, hazards or closures |
| `production_lost_t` | t | `planned_t − hauled_t`. ≥ 0 by construction |
| `machines_in_danger` | — | 3.7, at the moment of evaluation (the horizon end for forecasts) |
| `machines_unknown` | — | 3.7 |
| `machines_stuck` | — | 3.7 |
| `conflicts` | — | encounter episodes started in the window (3.8) |
| `conflict_yield_s` | machine*s | machine-seconds of yielding in the window (3.8) |

**Shadow machines for `planned_t`.** In `_new_run` and in `_open_decision`, copy each machine's cycle state into `self.shadow`. Each second, step every shadow with the cycle of 3.4 only. Each shadow dump adds the payload to `planned_t`. Because the shadow ignores the chosen option, **`planned_t` is identical for all three options of one decision**. That is a free invariant: test it.

Comparison discipline (unchanged, and it must keep holding):
- The three options run from deep copies of one checkpoint (model.py:225-240).
- `comparison_key` must cover the machines: add `machines=self.machines, shadow=self.shadow` to the fingerprint (model.py:212-216). The new parameters are already covered by `parameters`.
- The forecast at the decision equals the actual result at the horizon for **every** metric key (comparison.py:55-60, test_model.py:152-170). Extend the key list at test_model.py:158-161.
- Trial copies write no journal events (model.py:80-82, journal.py:21-22).

Extend comparison.py:
- the table (comparison.py:91-100) with "Недовывезено, т", "ПДМ в опасности / застряли" and "Встречи с людьми".
- each row with `machines` (`state`, `hold_reason`, `at_working`, `offset_m`, `loaded`, `location_hazard`) and the zones' `run_hauled_t`.
- `peak.machines_in_danger`.

Bump the JSON `schema_version` to 2. Re-run `--output`, rewrite comparison.md with the new numbers and explain them in its "Почему результаты различаются" section. Expected qualitative results with the placeholders (assert the invariants, not these numbers):

- p-instability and p-sensor: under observe, LHD-A finishes its haul and is then held at op-120 (entry blocked), so zone A loses production even without an order. Withdrawing zone A therefore costs almost no extra tonnes over observe. withdraw_all adds zone B's lost tonnes. Conflicts are 0 under observe and > 0 under the withdrawals.
- p-detour: under observe LHD-A keeps cycling (w-04 is not on its route), so observe loses about 0 t. The withdrawals cost tonnes, and crew A on w-03 meets LHD-A.
- p-trapped: w-07 closes under LHD-A, so `machines_stuck = 1` in every option, operator A has no route, and `no_route = 4`.

## 5. Publication

- **Attributes** (topology.py): the two equipment twins, the two operator workers, `role` on all workers, `equipment` and the derived `nominal_production_t_h` on zones, `mine.attributes.dump_points`, and the new registry entries. `counts`, `manifest` and `dynamic_ids` grow automatically (topology.py:106-109): manifest 34 → 38, dynamic_ids 29 → 33, well within the 80 of CONTRACT.md §1.5.
- **Versions:** `TOPOLOGY_VERSION` "t1" → **"t2"** (topology.py:13). The geometry is identical, but the set of twins changed and an open UI must re-read attributes (CONTRACT.md §2, line 55). `MODEL_VERSION` "0.1" → "0.2" (topology.py:12). `contract_version` stays 1: every change is additive.
- **Dynamic state** (twins.py:30-82): add `mine.machines` to the dynamic collections (twins.py:37-38), so `lhd-a`/`lhd-b` appear in `scene` and get their own MQTT message `telemetry/team040.mine/lhd-a` on every publication (twins.py:85-94). There is no new cadence: one publication per wall second, 10 model seconds each (service.py:95-117). New twins are created by the existing bootstrap (service.py:102-105).
- **Units:** add to `UNITS` (twins.py:7-14): `hauled_t`, `planned_t`, `production_lost_t`, `run_hauled_t` → `t`; `conflict_yield_s` → `machine*s`. Equipment features: `state`, `hold_reason`, `activity`, `at_working`, `offset_m`, `toward_node`, `loaded`, `location_hazard`, `operator_aboard`, `yielding_to` (only while yielding), `loads_dumped`, `run_hauled_t`. Worker additions: attribute `role` (and `vehicle` for operators), feature `aboard`. Zone additions: attribute `equipment`, feature `run_hauled_t`. The exact types and values are in the proposal §2-§3 and §5.
- **Shift** (twins.py:69-75): add `production_rate` (sum, t/h), `run_hauled_t`, `machines_total`, `machines_working`, `machines_in_danger`, `machines_stuck`.
- **History:** add the integer counters `machines_total`, `machines_working`, `machines_in_danger`, `machines_stuck`, `loads_dumped` to `INTEGER_FIELDS` (team/history/ditto_scalar.star:4-7). Tonnes are exported as floats.
- **Honesty:** publish nothing the model does not compute. There are no engine hours, fuel, GPS noise or random breakdowns. Equipment attributes carry `synthetic = true` like every twin (topology.py:34-35).

## 6. Journal

Add these codes to `journal.observe` (journal.py:20-71) and their fields to `capture` (journal.py:6-17). Document them in research/event-journal.md. The UI already prints an unknown code with its `arg` (event-journal.md:10).

| Code | When | arg (Russian, ready to show) | details |
|---|---|---|---|
| `equipment.state_changed` | `state` or `hold_reason` changed | «ПДМ-A: работает → стоит без работы (вход в участок запрещён)» | before/after {state, hold_reason}, at_working, offset_m, causes |
| `equipment.hazard_changed` | the machine's `location_hazard` changed | «ПДМ-A вышла из участка A (danger → unknown)» | before/after, working, zone, causes |
| `equipment.conflict` | an encounter episode started (3.8) | «ПДМ-A уступает дорогу Р-A2 на В-07, 20 м» | worker, working, gap_m, machine_offset_m, worker_offset_m, causes |

Normal cycle phases (`activity`) create no events. An operator getting off creates the existing `worker.state_changed`.

## 7. Migration

Store refuses a checkpoint whose model version differs (storage.py:22-23). Add an explicit 0.1 → 0.2 migration. It keeps `publication_seq`, `run_number`, `journal_seq`, `events`, `ledger`, `commands` and `archive`, archives the current run with `completion_reason = reset` (as model.py:440), and starts a fresh run from the new attributes. Write a journal event so that the restart is visible. `publication_seq` must keep rising (CONTRACT.md §2, line 34).

## 8. Tests to add or change

New tests (in test_model.py, or a new test_equipment.py):

1. **Geometry guard:** the working ids, from/to and points equal the t1 values (a frozen list in the test), so the art signature cannot break silently.
2. **Cycle:** an undisturbed machine is back in the same phase and position after `cycle_s`. `nominal_production_t_h == lhd_payload_t × 3600 / cycle_s`. The two cycle routes are disjoint.
3. **Placement:** the load, dump and bay points lie on existing workings within `[0, length_m]`. The bays are outside every zone and off the base egress routes of the crews.
4. **People first:** in every preset and option, every crew member's exit tick equals the value computed from distance / 1.25 (as in test_model.py:79-92), with or without machines moving behind them.
5. **Yield rule:** a hand-built case with a walking person 10 m ahead of a hauling machine gives a move of 0, `activity = yielding`, one episode, and `conflict_yield_s` growing by 1 per second. A person behind the machine gives no episode.
6. **Entry blocked:** with instability on zone A, LHD-A never enters w-07 again and holds at op-120. After `condition.instability_off` it stays held until `action.resume_zone`, which then succeeds.
7. **Closure under the machine:** close the machine's current working. It does not move, `machines_stuck = 1`, and its operator has `egress_reason = current_working_closed` after withdrawal.
8. **Stop and withdraw:** a loaded machine dumps at op-120 before parking. The operator rides, then walks. `withdrawal_state = done` only after the operator is out.
9. **Forecast = actual** for all keys including the new ones (extend test_model.py:158-161). `planned_t` is equal across the three options. `production_lost_t ≥ 0`. `conflicts = 0` under observe.
10. **Pause and reset:** machine positions are unchanged across paused heartbeats. A reset restores the initial phase and zeroes the counters.
11. **Snapshot:** `lhd-a`/`lhd-b` are in manifest, dynamic_ids and scene. The units are correct. There are MQTT messages for both. `topology_version = t2`.
12. **Journal:** each new code is written once per transition, never from forecast copies.
13. **comparison_key** differs when only a machine's state differs.
14. **Migration:** a 0.1 checkpoint fixture loads, `publication_seq` continues, and the ledger is preserved.

Existing tests with values that will change: test_comparison.py:18 (6 workers), :28 and :41 (30 t/h), test_model.py:65 (`no_route` 6) and :88 (6 workers). Change these values deliberately and list each changed expectation with its reason in your report.

## 9. Documentation

- team/research/equipment.md (new): the parameter table with sources from notes-kz.md, or TBD-source; the geometry choices of 3.1; the people-first rule and its limits; what is not modelled.
- team/research/parameters.md: the new rows. The 30 t/h row (parameters.md:42) becomes "derived from the LHD cycle".
- team/sim/README.md: replace the limitation "Производство пока только текущая скорость и простой, без баланса руды и оборудования" (README.md:77-78) with the new model and its limits.
- team/research/comparison.md and comparison.json: re-run them. SUBMISSION.md: update the numbers at SUBMISSION.md:62-63 (6 из 6, 850 с, 96 чел·с) after re-running team.smoke.
- team/CONTRACT.md: merge CONTRACT_PROPOSAL_LHD.md in Russian once the Team accepts it, and record the date.

## 10. Acceptance criteria

The work is done when all of the following pass and are reported with their output:

1. `python -m unittest team.sim.test_model team.sim.test_comparison team.sim.test_scope team.sim.test_journal team.sim.test_parameters team.sim.test_platform` plus the new tests.
2. `python -m team.sim.comparison --output team/research/comparison.json` prints "PASS: 12 executions match forecasts" for the new metrics too. `--check` against the saved file passes.
3. Every new parameter appears in `mine.attributes.parameter_registry`, either with a source id or with an explicit TBD-source status. equipment.md lists the same values.
4. The topology geometry is byte-identical to t1 (test 1). The working list used by artSignature is unchanged.
5. On the local stand: `team.smoke` passes. GET `team040.mine:lhd-a` returns attributes and features from Ditto. One shift snapshot carries 33 scene elements. Report the snapshot size before and after, and the publish loop time.
6. No number in the UI-facing data is invented: every published value comes from `Mine` state or from `build_attributes`.

## 11. Delivery

Work in your own branch. Make a local commit with a message that describes the model change. Report the SHA, the changed files, the commands run with their output, the changed test expectations with reasons, the new comparison table, the stand measurements, and anything you deviated from in this document or in the proposal. Do not push and do not merge into main. Then Claude re-records team/ui/fixtures/sim_*.json.gz with team/ui/tools/sim_fixtures.py and implements LHD_UI_PLAN.md.

## 12. Open questions for the Team (defaults apply unless the Team decides otherwise)

| # | Question | Default in this document |
|---|---|---|
| Q1 | Are operators modelled as people (8 instead of 6 in the shared group)? | Yes (3.2). Alternative: machines without persons. Then the machine metrics are about assets only, and an operator in a danger zone is invisible |
| Q2 | Where are the bays: at the ore-pass station, or at a separate cut-out on a crosscut (w-05/w-06)? | At the ore-pass station (3.1) |
| Q3 | Do conflicts also delay people (a refuge stop of N s per encounter)? | No: people first, machines yield (3.8) |
| Q4 | Does a crew at work count in conflicts? | No: the zone's traffic plan is assumed (3.8) |
| Q5 | Is `lhd_availability` applied inside the window? | No: stated only in research (3.3) |
| Q6 | Is a horizon of 900 s still right for a production cost? 15 minutes of two loaders is about 100 t with the placeholders | Unchanged. Mention the scale in comparison.md |

Report in English.
