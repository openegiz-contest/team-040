# LHD delivery — 16 October 2026

Implemented on `codex/lhd-simulation`, based on `c767bd4`, in a separate managed
worktree. The local commit SHA is supplied in the delivery message (a commit
cannot contain its own SHA). Nothing is pushed or merged into main. No files in
`team/ui/` or Claude's worktree were changed. The Team's Concept is unchanged.

## Delivered behavior

Two deterministic LHDs, two operators as ordinary people, a shared pure cycle
for actual/shadow/cycle-time calculations, people-first yielding, entry/closure
holds, stop-to-bay and operator dismounting, eight additional option metrics,
equipment twins and shift totals, transition events, and persistent 0.1→0.2
migration. Contract 1 / model 0.2 / topology t2; manifest 38, scene 33. The
11 nodes and 12 working polylines are guarded against a frozen t1 fixture.

Full Russian data contract: [CONTRACT.md](../CONTRACT.md#9-принятое-расширение-пдм-и-цена-вариантов-16-октября-2026).
Parameters and limitations: [equipment.md](equipment.md). Detailed comparison
and interpretation: [comparison.md](comparison.md), [comparison.json](comparison.json).

## Commands and observed results

Windows uses `py -3 -X utf8`; Linux uses `python3`.

```text
python -m unittest team.sim.test_equipment team.sim.test_model team.sim.test_comparison team.sim.test_scope team.sim.test_journal team.sim.test_parameters team.sim.test_platform -q
Windows: Ran 59 tests in 52.545s — OK
Linux:   Ran 59 tests in 29.133s — OK

python -m unittest team.gateway.test_gateway team.gateway.test_readiness team.gateway.test_ui_contract -q
Ran 7 tests in 2.641s — OK

python -m team.sim.comparison --output team/research/comparison.json
python -m team.sim.comparison --check team/research/comparison.json
PASS: 12 executions match forecasts; shared checkpoints were not modified. Offline synthetic experiment.

python -m team.sim.sensitivity
Recomputed and saved sensitivity.json; all forecast/actual assertions passed.
At walking speeds 0.5 / 0.75 / 1 / 1.25 m/s: out 0 / 3 / 4 / 8.
Danger exposure 368 / 249 / 188 / 152 person*s; only 1.25 has all_out, at 866 s.

make up  (isolated nested Docker only, upgrade from 0.1)
UPGRADE_READY
python3 -m team.smoke
run.start_preset ack 0.572 s; duplicate ack 0.046 s; execute ack 0.584 s
PASS: run-0005, last_out_s=866, danger_exposure_person_s=152,
production_lost_t=112.0, conflicts=4

make smoke
PLATFORM_SMOKE_PASS
PYTHONPATH=/tmp python3 -m team.history_smoke
PASS: history_fields=27, sensor_history=true,
structured_fields_expanded=false, live_command_credentials_leaked=false
```

The outer audit container lacked paho and ensurepip. The already installed
pure-Python paho package was copied from its nested simulator container into
`/tmp` for history_smoke; no host or application dependencies were changed.

## Live stand measurements

All mutations and resets ran inside `team040-cleancheck-20261015`, an isolated
Ubuntu 24.04 / nested Docker test environment. The main and Claude stacks were
not addressed by these commands. Logs stay outside the repository and contain
no credentials in this report.

* 0.1→0.2 migration: old run-0003 archived; new run-0004; live model.migrated
  event seq=35 records previous_run. Publication seq observed 535 before and
  610 after, never reset. Fixture tests additionally prove ledger preservation,
  idempotent replay and one-time persisted migration.
* GET `team040.mine:lhd-a` returned kind=equipment with attributes/features.
  Manifest counts worker=8, equipment=2; a single coherent shift scene has 33
  elements, all with the same run/tick. The smoke test compares all eight new
  actual metric values with the offered forecast.
* GET shift, same p-instability decision tick=60, compact UTF-8 JSON
  (`ensure_ascii=False`, separators `,`/`:`), including thingId, attributes,
  features, _modified and _revision: **32,870 → 47,205 bytes**, scene **29 → 33**.
  Journal, command and archive history also grew between samples; this is a
  measured end-to-end response, not an isolated estimate of equipment overhead.
* New publisher, 13 logged command-free iterations: **0.0307–0.0455 s**, median
  **0.0368 s**. This includes model/store/serialization/MQTT PUBACK and excludes
  the deliberate wall-time wait; not browser latency or a capacity guarantee.
  Sample paused decision batch: 39 messages, 108,505 payload bytes in total,
  shift MQTT payload 49,420 bytes (JSON uses ASCII escaping). Message count
  includes archived runs, so it is not equal to dynamic_ids.

## History upgrade finding

Telegraf does not reload its Starlark file when source files are copied. Our
first upgrade left the old process running and therefore wrote the new integer
counters as doubles. Recreating Telegraf then exposed Influx field-type conflicts.
This was a deployment sequencing failure, not hidden by the passing general
smoke. The documented upgrade order is: stop only team-simulator, recreate
Telegraf with the new script, then make up. This must happen before the first
0.2 publication. Existing production history is never deleted automatically.
For the disposable isolated stand only, a fresh start was used to validate the
int/float types with the correct exporter loaded from the beginning.

Fresh-start verification passed: `make up` returned FRESH_READY; an authenticated
Flux query of actual Influx rows returned `machines_total: long`,
`loads_dumped: long`, and `run_hauled_t: double` (observed values 2, 5, 70).
The fresh stand also passed `make smoke` (FRESH_PLATFORM_SMOKE_PASS).
The query reads credentials inside the disposable stand and prints only field
types and values. No credentials are written to the repository.

Final host audit: all 15 containers recorded before the isolated run are still
running with the same IDs and StartedAt earlier than this audit. No main-stack
restart occurred. The isolated outer container is stopped after verification,
restoring its initial stopped state.

## Deliberately changed existing test expectations

| Test | Before → after / reason |
|---|---|
| test_model: both exits unavailable | no_route 6→8; operators are people |
| test_model: total cohort / local exit | total 6→8; local group 3→4; original crew arrival-time assertions remain crew-only |
| test_model: manually triggered danger at tick 0 | 2700→2777 person*s under observe; operator spends 77 s loading/hauling in the zone |
| test_model: forecast equality | now also checks all eight equipment/cost keys |
| test_comparison: cohort / local withdrawal / trapped | 6→8, 3→4, trapped no_route 3→4; operators participate in every option |
| test_comparison: B continues production | 30→14×3600/179 t/h, derived cycle nominal |
| test_comparison: sensor observe exposure | 2700→2703; operator spends 3 more seconds in unknown zone |
| test_journal: route lost/restored | 3→4 events; operator also has a route |
| test_journal: no spurious movement reroutes | applies to six crew; a riding operator legitimately changes route/exit as the machine travels |
| test_journal: exit events | 6→8 distinct worker.exited events |
| team.smoke | expected total from manifest; all new actual/forecast metrics, scene=33 and real equipment GET checked |

The 19 equipment tests cover frozen geometry/placement, cycles and parameter
variation, initial position, all 12 original crew exit trajectories, yielding
episodes and behind/beyond-leg exclusions, closure/entry latches including a
hazard during the return leg, loaded withdrawal/stop-only/resume/staffing,
shared shadows and nonnegative losses, pause/reset, projections/units/MQTT,
fingerprinting, journal isolation, persisted migration and provenance.

## Comparison (window = 900 s after decision)

All rows have planned_t=140. Terminal machines_in_danger=0 and machines_unknown=0;
the trapped scenario has one stuck machine in all three options. Peak danger
is separately recorded, including the LHD initially inside the dangerous zone.

| Scenario | Option | Out / 8 | All out s | Danger person*s | Unknown person*s | Hauled t | Lost t | Conflicts | Yield machine*s |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| p-instability | observe | 0 | — | 2717 | 0 | 84 | 56 | 0 | 0 |
| p-instability | stop_withdraw_zone | 4 | — | 152 | 0 | 84 | 56 | 2 | 47 |
| p-instability | withdraw_all | 8 | 866 | 152 | 0 | 28 | 112 | 4 | 94 |
| p-detour | observe | 0 | — | 0 | 0 | 140 | 0 | 0 | 0 |
| p-detour | stop_withdraw_zone | 4 | — | 0 | 0 | 84 | 56 | 2 | 108 |
| p-detour | withdraw_all | 8 | 866 | 0 | 0 | 28 | 112 | 4 | 155 |
| p-trapped | observe | 0 | — | 0 | 0 | 70 | 70 | 0 | 0 |
| p-trapped | stop_withdraw_zone | 0 | — | 0 | 0 | 70 | 70 | 0 | 0 |
| p-trapped | withdraw_all | 4 | — | 0 | 0 | 14 | 126 | 2 | 47 |
| p-sensor | observe | 0 | — | 0 | 2703 | 84 | 56 | 0 | 0 |
| p-sensor | stop_withdraw_zone | 4 | — | 0 | 99 | 84 | 56 | 0 | 0 |
| p-sensor | withdraw_all | 8 | 850 | 0 | 99 | 28 | 112 | 0 | 0 |

## Clarifications and deviations from the draft

1. Arithmetic corrected: 14 t and 179 s give 281.564 t/h, not 201 (the task
   accidentally used 10 in the numerator). No hard-coded nominal rate.
2. length_m is 11, replacing the proposal's 10 m TBD placeholder, per the task's
   instruction to use the manufacturer's published LH514 length. Only length
   and rated payload are manufacturer-sourced; other operating values remain
   explicit TBD-source assumptions. Availability is research context only.
3. Stop-only leaves the operator aboard. The proposal's general stop/withdraw
   sentence was ambiguous; the task's explicit command table distinguishes
   stop-only from withdrawal. The merged Russian contract states that distinction.
4. p-sensor withdrawals produce zero conflicts, contrary to the draft's expected
   positive count: decision is at tick 75, when the machine is ahead of the crew.
   No results or initial conditions were adjusted to force the expected outcome.
5. A danger that appears mid-return outside the zone holds the machine at its
   current position, not at the bay. This preserves no-entry and no-teleport.
6. Added team.smoke assertions outside the simulator directory because the task
   explicitly requires live acceptance with eight people and equipment metrics.
7. Sample history upgrade ordering is now documented; automated migration of
   already mistyped Influx fields is out of scope and not silently performed.

## Claude integration

Cherry-pick the delivery commit when ready; re-record `team/ui/fixtures/sim_*.json.gz`
with `team/ui/tools/sim_fixtures.py` in Claude's branch, then implement LHD_UI_PLAN.
Use two real LHDs and eight people, hide a separate walking glyph while aboard,
read activity/loaded/hold_reason, and show cost next to benefit without ranking.
Map tramming/yielding and the new units. Reload attributes for t2. Geometry art
signature is unchanged. At defaults, interpolation must accept 30 m/publication.
Follow the exporter-before-simulator upgrade order in the simulator README.

## Changed files

- `SUBMISSION.md`
- `team/CONTRACT.md`
- `team/history/ditto_scalar.star`
- `team/research/comparison.json`
- `team/research/comparison.md`
- `team/research/equipment.md`
- `team/research/event-journal.md`
- `team/research/lhd-delivery.md`
- `team/research/parameters.md`
- `team/research/sensitivity.json`
- `team/sim/README.md`
- `team/sim/comparison.py`
- `team/sim/equipment.py`
- `team/sim/fixtures/checkpoint-0.1.json`
- `team/sim/fixtures/topology-t1.json`
- `team/sim/journal.py`
- `team/sim/model.py`
- `team/sim/parameters.py`
- `team/sim/service.py`
- `team/sim/storage.py`
- `team/sim/test_comparison.py`
- `team/sim/test_equipment.py`
- `team/sim/test_journal.py`
- `team/sim/test_model.py`
- `team/sim/topology.py`
- `team/sim/twins.py`
- `team/smoke.py`
