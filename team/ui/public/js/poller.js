// Reading the platform: boot (mine, then the attributes of the manifest in
// batches), then one poll of shift per second with no overlap. Every failure
// is retried by the same loop; nothing here needs a page reload.
//
// Two rules keep the screen honest:
// - attributes and state are committed together, so the screen never shows
//   the state of one run or topology over the attributes of another;
// - a read that is not a full snapshot changes the link status only: the last
//   full snapshot stays on the screen.

import {
  ARCHIVE_RETRY_MS, ATTR_REREAD_MIN_INTERVAL_MS, BOOT_RETRY_MS, MINE_ID, POLL_INTERVAL_MS, RUNS_LIMIT,
} from './config.js';
import {deriveLink, initialLink, reduceLink, sameLinkStatus} from './link.js';
import {buildModel} from './model.js';
import {buildAttributes, plainRun, runNames, validateMine, validateShift} from './validate.js';

/** @typedef {import('./store.js').Attributes} Attributes */

function sameList(a, b) {
  return a.length === b.length && a.every((item, index) => item === b[index]);
}

function isNotFound(result) {
  return !result.ok && result.kind === 'http' && result.status === 404;
}

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

/**
 * @param {{store: import('./store.js').Store, api: import('./api.js').Api, now: () => number}} deps
 * @returns {{start: () => void, stop: () => void, tick: () => void}}
 */
export function createPoller({store, api, now}) {
  let link = initialLink();
  /** @type {Attributes|null} the attributes read last; a snapshot is validated against these */
  let latest = null;
  let attributesReadAt = -Infinity;
  let phase = 'boot';
  let running = false;
  let archiveBusy = false;
  let archiveFailedAt = -Infinity;

  function linkPatch(event) {
    link = reduceLink(link, event);
    const status = deriveLink(link, now());
    return sameLinkStatus(status, store.getState().link) ? {} : {link: status};
  }

  /** Re-derive the thresholds for the current moment; the store changes only when a value does. */
  function tick() {
    const status = deriveLink(link, now());
    if (!sameLinkStatus(status, store.getState().link)) store.update({link: status});
  }

  /**
   * Read the mine, and the rest of the manifest unless neither the manifest
   * nor the topology version changed (attributes are static within a topology).
   * @returns {Promise<{attributes: Attributes}|{empty: true}|{failure: Object}|{rejection: Object}>}
   */
  async function readAttributes() {
    const mine = await api.readMine();
    if (isNotFound(mine)) return {empty: true};
    if (!mine.ok) return {failure: mine};
    const checked = validateMine(mine.body);
    if (!checked.ok) return {rejection: checked};
    if (latest && latest.topologyVersion === checked.topologyVersion && sameList(latest.manifest, checked.manifest)) {
      if (JSON.stringify(latest.mine) === JSON.stringify(checked.attrs)) return {attributes: latest};
      return {
        attributes: {
          ...latest, mine: checked.attrs, dynamicIds: checked.dynamicIds,
          things: {...latest.things, [MINE_ID]: checked.attrs},
        },
      };
    }
    const rest = await api.readAttributes(checked.manifest);
    if (!rest.ok && rest.kind === 'incomplete') {
      return {
        rejection: {
          ok: false, code: 'manifest_incomplete',
          params: {ids: rest.missing, total: checked.manifest.length, duplicate: rest.duplicate, extra: rest.extra},
          detail: `attribute batch: missing ${rest.missing.join(', ') || 'none'}, duplicate ${rest.duplicate.join(', ') || 'none'}, `
            + `not requested ${rest.extra.join(', ') || 'none'}`,
        },
      };
    }
    if (!rest.ok) return {failure: rest};
    const built = buildAttributes(checked, rest.body);
    return built.ok ? {attributes: built.attributes} : {rejection: built};
  }

  function failed(result, at) {
    const patch = linkPatch({type: 'poll_failed', at, kind: result.kind, status: result.status});
    // The first poll has an outcome: the screen shows what is known, with the link status.
    if (phase === 'poll' && store.getState().boot === 'loading') patch.boot = 'ready';
    store.update(patch);
  }

  function goEmpty(at) {
    latest = null;
    phase = 'boot';
    link = reduceLink(initialLink(), {type: 'answered', at});
    store.update({
      boot: 'empty', bootError: null, attributes: null, snapshot: null, model: null,
      archive: {status: 'idle', ids: [], runs: [], failure: null},
      link: deriveLink(link, at),
    });
  }

  /** @returns {Promise<number>} the pause before the next step */
  async function bootStep() {
    const read = await readAttributes();
    const at = now();
    if (read.empty) {
      goEmpty(at);
      return BOOT_RETRY_MS;
    }
    if (read.failure) {
      failed(read.failure, at);
      return POLL_INTERVAL_MS;
    }
    if (read.rejection) {
      const {code, params, detail} = read.rejection;
      store.update({...linkPatch({type: 'answered', at}), boot: 'error', bootError: {code, params, detail}});
      return BOOT_RETRY_MS;
    }
    latest = read.attributes;
    attributesReadAt = at;
    phase = 'poll';
    link = reduceLink(link, {type: 'answered', at});
    store.update({
      ...linkPatch({type: 'polling_started', at}),
      boot: 'loading', bootError: null, attributes: latest, snapshot: null, model: buildModel(latest, null),
    });
    return 0;
  }

  function refreshArchive(snapshot) {
    const ids = runNames(snapshot.shift.values.runs).slice(-RUNS_LIMIT);
    const archive = store.getState().archive;
    const same = sameList(ids, archive.ids);
    if (archiveBusy || (same && archive.status === 'ready')) return;
    if (ids.length === 0) {
      store.update({archive: {status: 'ready', ids, runs: [], failure: null}});
      return;
    }
    // A failed read is tried again, but not with every poll, and the failure stays on the screen
    // until a read succeeds: the status must not flip between reading and failed.
    if (now() - archiveFailedAt < ARCHIVE_RETRY_MS) return;
    archiveBusy = true;
    // Finished runs do not change: the previous list stays visible while the new one is read.
    if (!(same && archive.status === 'error')) store.update({archive: {...archive, status: 'loading', ids, failure: null}});
    api.readRuns(ids).then((result) => {
      archiveBusy = false;
      if (store.getState().boot === 'empty') return;
      if (result.ok) {
        store.update({archive: {status: 'ready', ids, runs: result.body.map(plainRun), failure: null}});
      } else {
        const {kind, status, missing} = result;
        archiveFailedAt = now();
        store.update((state) => ({archive: {...state.archive, status: 'error', failure: {kind, status, missing}}}));
      }
    });
  }

  /** @returns {Promise<number>} the pause before the next step */
  async function pollStep() {
    const response = await api.readShift();
    // The moment the state was read. A re-read of attributes below takes time, and the state does not
    // get younger by it: its age and the link thresholds count from here.
    const at = now();
    if (!response.ok) {
      if (isNotFound(response) && isNotFound(await api.readMine())) {
        goEmpty(now());
        return BOOT_RETRY_MS;
      }
      failed(response, at);
      return POLL_INTERVAL_MS;
    }

    let result = validateShift(response, latest);
    const shown = store.getState().snapshot;
    const runChanged = shown !== null && result.info.run !== null && result.info.run !== shown.run;
    const mismatch = !result.ok && result.code === 'topology_mismatch';
    if (runChanged || (mismatch && at - attributesReadAt >= ATTR_REREAD_MIN_INTERVAL_MS)) {
      const read = await readAttributes();
      attributesReadAt = now();
      if (read.empty) {
        goEmpty(attributesReadAt);
        return BOOT_RETRY_MS;
      }
      if (read.failure && runChanged) {
        // The new run cannot be shown over attributes that were not confirmed for it.
        failed(read.failure, attributesReadAt);
        return POLL_INTERVAL_MS;
      }
      if (read.rejection) {
        result = {...read.rejection, info: result.info};
      } else if (read.attributes) {
        latest = read.attributes;
        result = validateShift(response, latest);
      }
    }

    const state = store.getState();
    const event = {
      type: 'poll_ok', at, seq: result.info.seq, dateMs: response.dateMs, modifiedMs: result.info.modifiedMs,
    };
    if (result.ok) {
      const patch = {
        ...linkPatch({...event, full: true, runState: result.snapshot.runState}),
        boot: 'ready', bootError: null, snapshot: result.snapshot, model: buildModel(latest, result.snapshot),
      };
      if (state.attributes !== latest) patch.attributes = latest;
      store.update(patch);
      refreshArchive(result.snapshot);
    } else {
      const {code, params, detail} = result;
      const patch = {...linkPatch({...event, full: false, rejection: {code, params, detail}}), boot: 'ready'};
      if (state.snapshot === null && state.attributes !== latest) {
        // Nothing of an older state is on the screen, so newer attributes can be shown at once.
        patch.attributes = latest;
        patch.model = buildModel(latest, null);
      }
      store.update(patch);
    }
    return POLL_INTERVAL_MS;
  }

  async function loop() {
    while (running) {
      const started = now();
      let pause = POLL_INTERVAL_MS;
      try {
        pause = phase === 'boot' ? await bootStep() : await pollStep();
      } catch (error) {
        // A defect in handling one answer must not stop the polling.
        console.error(error);
      }
      // The next read starts no earlier than `pause` after the previous start, and never before it ended.
      await sleep(Math.max(0, pause - (now() - started)));
    }
  }

  return {
    start() {
      if (running) return;
      running = true;
      loop();
    },
    stop() {
      running = false;
    },
    tick,
  };
}
