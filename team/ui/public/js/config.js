// Addresses and timing constants of team/CONTRACT.md. Nothing here changes behaviour for tests.

export const NAMESPACE = 'team040.mine';
export const CONTRACT_VERSION = 1;

export const MINE_ID = `${NAMESPACE}:mine`;
export const SHIFT_ID = `${NAMESPACE}:shift`;

export const THINGS_PATH = '/ditto/api/2/things';
export const COMMAND_PATH = `${THINGS_PATH}/${SHIFT_ID}/inbox/messages/command?timeout=0`;

export const FIELDS_ATTRIBUTES = 'thingId,attributes';
export const FIELDS_SHIFT = 'thingId,features,_modified,_revision';
export const FIELDS_RUN = 'thingId,attributes,features';

/** One poll of `shift` per interval, never two at once. */
export const POLL_INTERVAL_MS = 1000;
export const REQUEST_TIMEOUT_MS = 3000;
/** No full snapshot for this long: the screen is stale and commands are blocked. */
export const STALE_AFTER_MS = 2000;
export const UNAVAILABLE_AFTER_FAILURES = 3;
/** `publication_seq` unchanged for this long while polls succeed: publications stopped. */
export const PUBLICATIONS_STOPPED_AFTER_MS = 5000;
export const ACK_TIMEOUT_MS = 5000;
export const ATTR_BATCH = 20;
export const RUNS_LIMIT = 10;
/** After a failed read of the archive the next try waits this long. */
export const ARCHIVE_RETRY_MS = 5000;

/** Attributes are re-read on a topology mismatch at most this often. */
export const ATTR_REREAD_MIN_INTERVAL_MS = 5000;
/** Pause before the boot is tried again after an empty stand or a boot data error. */
export const BOOT_RETRY_MS = 2000;
/** How often thresholds are re-derived, so that they fire during a pending fetch. */
export const DERIVE_INTERVAL_MS = 250;
/** An applied command stays in the pending list this long, then leaves on its own. */
export const APPLIED_LINGER_MS = 4000;

/** Identifiers that may be put into a request path or query without escaping. */
export const ID_PATTERN = /^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$/;
export const LOCAL_NAME_PATTERN = /^[A-Za-z0-9_.-]+$/;
