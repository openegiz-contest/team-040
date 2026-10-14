// The application state and its observable store. Every view reads this
// shape; nothing but the modules named next to each field writes it.

/**
 * A feature set of one twin in plain form: `values.hazard_state`, `units.offset_m`.
 * A feature the platform did not publish is absent from both (never null).
 * @typedef {Object} Features
 * @property {Object<string, *>} values
 * @property {Object<string, string>} units
 */

/**
 * Static data, read from attributes. Written by poller.js.
 * @typedef {Object} Attributes
 * @property {Object<string, *>} mine          attributes of the mine twin (nodes, thresholds, presets, counts ...)
 * @property {Object<string, Object<string, *>>} things   attributes by full thingId, the mine included
 * @property {string} topologyVersion
 * @property {string[]} manifest               full thingIds, in the order of the platform
 * @property {string[]} dynamicIds             full thingIds of the scene
 */

/**
 * One full, validated snapshot of `shift` (validate.js). Never a mix of two polls or two runs.
 * @typedef {Object} Snapshot
 * @property {string} run                      idSimulationRun, a local name such as "run-0005"
 * @property {number} tick
 * @property {number} simTimeS
 * @property {number} seq                      publication_seq
 * @property {string} runState                 running | paused | resetting (or an unknown code)
 * @property {string} pauseReason              none | decision
 * @property {string} topologyVersion
 * @property {string} modified                 `_modified` of shift, ISO text of the platform
 * @property {number} modifiedMs               the same as epoch milliseconds
 * @property {number} revision
 * @property {number} dateMs                   HTTP Date of the response, epoch milliseconds
 * @property {Features} shift                  features of shift without `scene`
 * @property {Object<string, Features>} scene  by full thingId; exactly Attributes.dynamicIds
 */

/**
 * A twin as views use it (model.js). `hazard` exists for kinds working and zone.
 * @typedef {Object} Thing
 * @property {string} thingId                  full id, "team040.mine:w-12"
 * @property {string} name                     local name, "w-12"
 * @property {string} kind
 * @property {string} label                    code for the screen, "В-12"
 * @property {Object<string, *>} attrs
 * @property {Object<string, *>} values        empty when no full snapshot has been read
 * @property {Object<string, string>} units
 * @property {boolean} hasState                false: no published state for this twin
 * @property {DisplayedHazard} [hazard]
 */

/**
 * @typedef {Object} DisplayedHazard
 * @property {'normal'|'attention'|'danger'|'unknown'} state   what is drawn and written to data-hazard
 * @property {string|null} raw                 the published hazard_state
 * @property {boolean} known                   false: the published code is not in the vocabulary
 * @property {boolean} defensive               true: published `normal` without fresh data, shown as unknown
 */

/**
 * @typedef {Object} Condition
 * @property {string} raw                      the normalised key, unique in Model.conditions: "working_closed:w-07";
 *                                             for an entry of an unknown form, its JSON text
 * @property {string} kind                     working_closed | sensor_lost | instability | <unknown prefix>;
 *                                             empty for an entry of an unknown form
 * @property {string} target                   local name
 * @property {string|null} undoType            command type that cancels it; null for an unknown kind
 */

/**
 * The view model built from Attributes and the last full Snapshot (model.js).
 * @typedef {Object} Model
 * @property {Object<string, Thing>} things    by full thingId, every manifest twin
 * @property {Object<string, Thing[]>} byKind  in manifest order
 * @property {Object<string, Thing>} byName    by local name
 * @property {Thing|null} shift
 * @property {Condition[]} conditions          without repeats: every `raw` occurs once
 * @property {Object<string, Object>} acks     the acknowledgement record that counts, by command id
 * @property {boolean} hasSnapshot
 */

/**
 * Link status, derived by link.js and written by poller.js only when a value changes.
 * @typedef {Object} LinkStatus
 * @property {'ok'|'degraded'|'stale'|'unavailable'} link
 * @property {'alive'|'stopped'|'unknown'} publications
 * @property {'ok'|'invalid'|'none'} snapshot
 * @property {{kind: string, status: (number|null)}|null} failure   the last failed read while the link is not ok
 * @property {{code: string, params: Object, detail: string}|null} invalid   why the last read was not a full snapshot
 * @property {number|null} dataAgeS            whole seconds since the shown state was current; null without data
 * @property {boolean} blocked
 * @property {string|null} blockReason         platform_unavailable | stale | no_snapshot | snapshot_invalid |
 *                                             publications_stopped | resetting
 */

/**
 * A command of this page that still needs the user's attention (commands.js).
 * @typedef {Object} PendingCommand
 * @property {string} id                       command_id
 * @property {string} type
 * @property {string} target                   local name
 * @property {string} run
 * @property {string} bodyText                 the exact JSON sent; a retry sends it again unchanged
 * @property {'sending'|'sent'|'applied'|'rejected'|'no_ack'|'delivery_unknown'|'not_sent'} phase
 * @property {number} attempts                 POSTs started
 * @property {number} createdAt                performance.now() values
 * @property {number} phaseAt
 * @property {{kind: string, status: (number|null), reason: (string|undefined)}|null} failure
 * @property {boolean} maybeDelivered          an earlier POST was accepted or had an unknown outcome: a later refusal
 *                                             of a retry does not prove that the command never arrived
 * @property {Object|null} ack                 the acknowledgement record of shift.commands (applied or rejected)
 * @property {Object|null} oddAck              a record of this id with a status outside the contract: shown, resolves nothing
 */

/**
 * A finished run of the archive: values come from features first, then attributes.
 * @typedef {Object} ArchiveRun
 * @property {string} thingId
 * @property {string} name
 * @property {string} label
 * @property {Object<string, *>} values
 * @property {Object<string, string>} units
 */

/**
 * @typedef {Object} State
 * @property {'loading'|'ready'|'empty'|'error'} boot
 *           loading: nothing to show yet; ready: attributes are read and the first poll has an outcome;
 *           empty: the mine twin does not exist; error: attributes cannot be used (see bootError)
 * @property {{code: string, params: Object, detail: string}|null} bootError   contract_version | manifest_incomplete | malformed
 * @property {Attributes|null} attributes      the attributes the shown state belongs to
 * @property {Snapshot|null} snapshot          the last full snapshot; kept while later reads fail or are invalid
 * @property {Model|null} model                null only while attributes are null
 * @property {LinkStatus} link
 * @property {boolean} commandsBlocked         link.blocked, boot not ready, or an own unconfirmed reset
 * @property {string|null} blockReason         not_ready | own_reset_pending | one of LinkStatus.blockReason
 * @property {PendingCommand[]} pending        oldest first
 * @property {{status: 'idle'|'loading'|'ready'|'error', ids: string[], runs: ArchiveRun[], failure: (Object|null)}} archive
 *           ids: the local run names the list was read for (the last RUNS_LIMIT of shift.runs)
 * @property {{view: 'scheme'|'list'|'runs', projection: 'axo'|'plan', level: (string|null),
 *             selected: (string|null), listType: string, stageMode: ('3d'|'scheme'|null),
 *             quality: ('high'|'low'|null), explode: (number|null), hoverOption: (string|null)}} ui
 *           level: local name of a level for the plan; selected: full thingId; listType: a kind or "all";
 *           stageMode, quality, explode: choices of the stage (view/stage.js), null = not chosen (automatic or stored);
 *           hoverOption: full thingId of the option the user points at or has chosen in the decision dock
 *           (view/decision.js); the stage and the scheme highlight the zones of its published `scope`
 */

/** @returns {State} */
export function initialState() {
  return {
    boot: 'loading',
    bootError: null,
    attributes: null,
    snapshot: null,
    model: null,
    link: {
      link: 'ok', publications: 'unknown', snapshot: 'none', failure: null, invalid: null,
      dataAgeS: null, blocked: true, blockReason: 'no_snapshot',
    },
    commandsBlocked: true,
    blockReason: 'not_ready',
    pending: [],
    archive: {status: 'idle', ids: [], runs: [], failure: null},
    ui: {view: 'scheme', projection: 'axo', level: null, selected: null, listType: 'all', stageMode: null, quality: null, explode: null,
      hoverOption: null},
  };
}

/**
 * True when two selector results are the same: identical, or arrays with identical items.
 * @param {*} a
 * @param {*} b
 */
export function sameSelection(a, b) {
  if (Object.is(a, b)) return true;
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  return a.every((item, index) => Object.is(item, b[index]));
}

/**
 * @typedef {Object} Store
 * @property {() => State} getState
 * @property {(patch: (Partial<State>|((state: State) => Partial<State>|null))) => void} update
 *           shallow merge of top-level fields; fields are replaced, never mutated in place
 * @property {(listener: (state: State, previous: State) => void) => (() => void)} subscribe
 * @property {(selector: (state: State) => *, listener: (selected: *, state: State) => void) => (() => void)} watch
 *           calls `listener` now and whenever the selected value (or any item of a selected array) changes
 */

/**
 * @param {State} [state]
 * @param {(state: State) => Partial<State>} [derive] recomputes fields that follow from the others after every update
 * @returns {Store}
 */
export function createStore(state = initialState(), derive = null) {
  const listeners = new Set();
  let notifying = false;
  let queued = null;

  function withDerived(next) {
    return derive ? {...next, ...derive(next)} : next;
  }
  state = withDerived(state);

  function notify(previous) {
    if (notifying) {
      // An update made by a listener: the outer loop delivers it after the current round.
      queued = queued || previous;
      return;
    }
    notifying = true;
    try {
      let from = previous;
      while (from) {
        queued = null;
        const current = state;
        for (const listener of [...listeners]) {
          // One failing listener must not keep the state from the others: every view gets every poll.
          try {
            listener(current, from);
          } catch (error) {
            console.error(error);
          }
        }
        from = queued;
      }
    } finally {
      notifying = false;
    }
  }

  function update(patch) {
    const change = typeof patch === 'function' ? patch(state) : patch;
    if (!change) return;
    const keys = Object.keys(change).filter((key) => !Object.is(change[key], state[key]));
    if (keys.length === 0) return;
    const previous = state;
    state = withDerived({...state, ...change});
    notify(previous);
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function watch(selector, listener) {
    let selected = selector(state);
    listener(selected, state);
    return subscribe((current) => {
      const next = selector(current);
      if (sameSelection(next, selected)) return;
      selected = next;
      listener(next, current);
    });
  }

  return {getState: () => state, update, subscribe, watch};
}
