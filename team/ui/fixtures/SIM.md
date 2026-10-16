# Fixtures recorded from the real mine simulation

`sim_instability.json.gz`, `sim_detour.json.gz`, `sim_trapped.json.gz`, `sim_sensor.json.gz` (gzipped JSON, mtime 0) are written by
`team/ui/tools/sim_fixtures.py`. Unlike the other files of this folder (invented mine, scripted stepper,
see README.md) these hold what `team/sim` publishes: the tool drives `team.sim.model.Mine` publication by
publication and takes `team.sim.twins.snapshot()` after each one, as `team/sim/service.py` does, without
Ditto, MQTT or storage. The frames are the shift features as published, the `scene` array included.
The numbers are those of the simulation's demonstration model, not measurements of the stand.

```text
python team/ui/tools/sim_fixtures.py           rewrite the four files (about one minute: the model computes its forecasts)
python team/ui/tools/sim_fixtures.py --check   exit 1 if they differ from a fresh recording
python team/ui/tools/mock_server.py --port 0 --scenario sim_instability
python -m unittest tests.test_sim_fixtures     from team/ui
```

The recording is deterministic (no clock, no random numbers, sorted keys, LF); a second run gives the same
bytes. The four files weigh about 0.9 MB each gzipped: every publication of the story is a full frame, nothing is repeated.

## Model 0.2: loaders and the cost of options (CONTRACT.md §9)

Recorded from the merged `codex/lhd-simulation` (contract 1, model 0.2, topology `t2`). The attribute set of each file
is keyed by the published `topology_version` (`t2`): 38 twins in the manifest, 33 in the scene. Next to the six crew
(`role = crew`) there are two operators, `worker-a4` / `worker-b4` (`role = lhd_operator`, `vehicle = lhd-a/b`), so
every count of people is 8. The loaders `lhd-a` / `lhd-b` (kind `equipment`) publish `state`, `hold_reason`,
`activity`, `at_working`, `offset_m`, `toward_node`, `loaded`, `location_hazard`, `operator_aboard`, `yielding_to`,
`loads_dumped`, `run_hauled_t`; an operator riding one publishes `aboard` and the machine's place. The mine lists
its ore passes in `dump_points` (not twins) and the `lhd_*` parameters in `parameter_registry`. Each option publishes
eight more `forecast_*` / `actual_*` fields: `hauled_t`, `planned_t`, `production_lost_t` (t), `machines_in_danger`,
`machines_unknown`, `machines_stuck`, `conflicts` and `conflict_yield_s` (machine*s); the forecast equals the fact for
all of them (tests/test_sim_fixtures.py). The shift adds `production_rate` (t/h), `run_hauled_t` (t) and
`machines_total/working/in_danger/stuck`. The working geometry is that of t1, so the art's topology signature still
matches. With the published parameters a loader moves at most 30 m per publication (25 m loaded) along its cycle
`[w-07, w-03]` / `[w-12, w-10]`, through node b / f.

The recorder needed one change: the key of the attribute set is the published `TOPOLOGY_VERSION` (it was `t1`).

## The story of a scenario

One scenario per preset of the mine twin. Everything is the model's own run; the mock only decides which
recorded frames to show after which command.

| State | Clock | Frames | Leaves by |
|---|---|---|---|
| `initial` | runs | 6 publications of `run-0001` (ticks 0-50), the last one repeated | rule `run.start_preset <preset>`: ack `applied`, `new_run = run-0002` |
| `preset_run` | runs | `run-0002` from tick 10 to the publication before the decision | `next: decision` |
| `decision` | held | the paused run: `run_state = paused`, `pause_reason = decision`, incident `active`, three options `offered` with forecasts | rules `action.execute_option` for each of the three options with `decision_id = run-0002-d1` (`goto <o>_exec`); any other decision id is `rejected / stale_decision` |
| `observe_exec`, `sw_exec`, `wa_exec` | runs | the state at the launch (tick of the decision, incident `executing`), then one real publication per 10 model seconds | `next: <o>_done` |
| `observe_done`, `sw_done`, `wa_done` | held | the publication of the horizon (decision tick + 900): incident `done`, run paused, run archived | none (the last frame stays) |

Options: `option-observe`, `option-stop_withdraw_zone`, `option-withdraw_all`; `o` = `observe`, `sw`, `wa`.

- All three options of each scenario are launchable and each is answered with its own frames to the end
  (12 chains). The forecast at the decision equals the actual result at the horizon for every metric
  (the simulation's own promise; `tests/test_sim_fixtures.py` checks it on the recording).
- The only commands scripted are the preset of the scenario and the options. Any other command (another
  preset, a manual condition, `run.reset`, a repeat of the preset after the end) is answered
  `rejected / not_scripted`, the mock's limitation, not the model's. To go again, restart the scenario
  from `/__mock__/`.
- The frame of the launch (`<o>_exec[0]`) is the model's state right after the command, before it advances: the
  service never publishes it (it applies commands, then advances, then publishes), but the mock's clock
  needs it, so that model time keeps the real ticks: decision tick, then +10 per publication.
- Acknowledgements are not recorded: `commands` is empty in every frame and the mock writes its own. The
  journal events caused by the recorded commands carry `command_id: "@preset"` / `"@exec"`, which the mock
  binds to the id of the command it received.
- The archive of runs: `run-0001` (cut short by the preset, `completion_reason = reset`) is in the file's
  `archive`; the finished `run-0002` differs per option and is listed in the `archive` of the `<o>_done` state.

### Model time

`CLOCK` is the one of build_fixtures.py with `last_known_hazard_tick` among the fields that follow the
clock: the simulation publishes it always (the tick of the last fresh assessment), so while it equals the
element's own tick it must move with the publication.

In `sim_sensor` the decision opens at tick 74 (the extensometer is 15 s stale), not on a multiple of 10. The mock
counts model time in steps of 10, so from the decision on it shows every tick 6 s later (decision at
00:01:20, the incident at 00:01:20, the horizon 900 s after). Moments before the decision keep their
recorded time: the last measurement shows 00:00:59 and the last known state 00:01:19 (recorded 73), so the
age of the data reads 21 s at the decision where the model had 15 s. The published `quality` is the model's.

## Where the published form differs from what the interface read, and what was done

The UI was made tolerant where a form can reasonably be accepted (so the live stand works too); only
what cannot be accepted is converted by the recorder. Nothing in `public/js/scene3d/` was touched.

| # | Mismatch | Decision |
|---|---|---|
| 1 | `incident.causes` are texts `"hazard:zone-a"`, `"passage_closed:w-04"`, `"data_lost:zone-a"` (the subject of `data_lost` is the zone, not the sensor); the interface read records `{trigger, subject, tick}` and dropped every other form: the cause list, the headline and its subject were empty or named the wrong object | UI: `normalizeCause()` in `validate.js` turns a text into `{trigger, subject}` while the snapshot is built (so every reader, `scene3d` included, sees records), and `causesOf()` in `model.js` accepts both. No tick is invented: a text has none; the panel uses `opened_at_tick` |
| 2 | Presets are `{id, label, at_s, type, target}`; the interface read `schedule` and `expect` | UI: `presetsOf()` in `view/pending.js` builds the one-step `schedule` from the preset itself. `expect` is absent in the simulation and shows nothing |
| 3 | `egress_crosses = "unknown"` for any route over a working without a zone (and so without sensors): every walking person has it | UI: `crossesText()` in `text.js` says "маршрут проходит через места с неизвестным состоянием" for `unknown` instead of "через участок «неизвестно»" (a ramp is not a zone). The value still drives its badge: unknown never looks safe. Other codes read as before |
| 4 | `egress_detour_m` / `egress_detour_s` are not published | Nothing: the interface reads them optionally; with the simulation "длиннее на N м" never appears. They are not computed on the page (no derived numbers) |
| 5 | `level` of a working is the level of its start node: ramps `w-08`, `w-09` are filed under `level-120`, `w-01`, `w-02` too | Nothing: the scheme and the stage take the level of a working from the heights of its ends. The list and the card name the level it starts on. No change |
| 6 | A `surface` level with no workings or zones, only the two exits | Nothing needed: scheme and stage draw it (a slab with the exit signs), the `0 м` mark is on the depth scale |
| 7 | `downtime_s` of a zone has the unit `zone*s` (the fixtures use `s` for a zone) | Nothing: shown as «уч.·с», which is right for one zone's seconds |
| 8 | `all_out`, `downtime_s` and the exposures are not on `shift`, only per option and per archive run | Nothing: no reader of the page looks for them on the shift |
| 9 | `run_state = resetting` is never published (the reset is atomic) | Nothing to convert; no story uses it: the preset goes straight to the new run, the mock shows no `resetting` |
| 10 | Options not chosen are `inactive`, the fixtures say `unavailable` | Nothing: both are in the vocabulary |
| 11 | Journal events always have `arg` and `command_id`, empty when not given | UI: `view/journal.js` hides the "команда …" tag for an empty id (an empty `arg` was already ignored) |
| 12 | `mine.thresholds` is `{attention_rate: {value, unit}, ...}` | Nothing: the interface does not read thresholds from the attributes |
| 13 | `manifest` lists `mine` last; the scene lists twins by kind, not in `dynamic_ids` order | Nothing: validation compares sets (all recorded frames pass `validateShift`) |
| 14 | `shift.runs` holds full thingIds | The interface reads both forms. The mock looked a run twin up by its local name only: `mock_server.py` now compares local names |
| 15 | No shaft or raise kind | Nothing |
| 16 | `last_known_hazard_state` / `_tick` are published always, not only for stale or lost data; with fresh data every zone and working said "последнее известное: норма в … (сейчас)" | UI: `lastKnownText()` in `text.js` says nothing when `data_quality` is `fresh` (then the current state is the last known one) |
| 17 | Journal codes the interface did not know (`decision.opened`, `decision.selected`, `run.finished`, `sensor.state_changed`, `hazard.transition`, `work.changed`, `withdrawal.changed`, `worker.exited`, `route.changed`, `worker.state_changed`) were shown raw | UI: words added to the journal vocabulary in `text.js`; the option kind in `decision.selected` is said in words (`view/journal.js`). The free-text `arg` of some events is the simulation's own Russian sentence with raw codes ("Вывод: in_progress → done"), shown as published |
| 18 | `completion_reason` of an archived run is `horizon` (the fixtures say `horizon_reached`) | UI: the label of `horizon` in `text.js`; `groupRuns()` in `view/runs.js` counts it as a completed ending |

Left as published, noticed on the screens:

- The option twins are labelled with their kind codes (`withdraw_all`): the decision panel names options in
  words by `option_kind`, but the archive row and the "связанные объекты" of a card print the label.
- `incident.scope_reasons` is a nested object: the card's "все поля" shows it as one JSON line.
- Workers walking over workings without sensors have `location_hazard = unknown` (the same as the invented
  fixtures); their rows carry the question mark glyph and "выработка без датчиков, состояние не оценивается".

## Changes outside the files of this tool

- `tools/mock_server.py`: a state may list `archive` twins of its own (the finished run differs per option and
  the file has one `archive`), and `shift.runs` is read as local names or full thingIds. Two small edits in
  `Timeline.thing()`; the format of the invented fixtures is unchanged.
- `tests/test_mock_server.py`, `tests/test_scenarios.py`, `tests/test_panels.py` and `tools/build_fixtures.py
  --check`: the lists of "all scenarios" and "all files in fixtures/" skip the names that start with `sim_`.
  Those tests and the generator stay about the invented fixtures.
