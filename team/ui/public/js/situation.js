// The situation of the shift, derived only from the published state; the screen of
// the "Пульт смены" design follows it. One function, shared by the layout, the
// decision panel and the stage, so that they never disagree about what is going on.
//
//   'none'       no full snapshot yet (nothing to say about the shift)
//   'norm'       no open incident and no withdrawal in progress
//   'decision'   an incident is open and waits for (or allows) a choice
//   'executing'  a chosen option or a zone withdrawal is being carried out
//   'done'       the incident is closed and its result is published
//
// An incident state the vocabulary does not know is treated as 'decision': the
// panel then shows it (with its raw code) rather than hiding an open incident.

import {incidentOf, thingsOfKind} from './model.js';

const KNOWN_INCIDENT = new Set(['none', 'active', 'executing', 'done']);

/** @param {object} state the store state @returns {'none'|'norm'|'decision'|'executing'|'done'} */
export function situationOf(state) {
  const model = state && state.model;
  if (!model || !model.hasSnapshot) return 'none';
  const incident = incidentOf(model);
  const incidentState = incident ? incident.values.state : undefined;
  const optionExecuting = thingsOfKind(model, 'option').some((option) => option.values.state === 'executing');
  const withdrawing = thingsOfKind(model, 'zone').some((zone) => zone.values.withdrawal_state === 'in_progress');
  if (optionExecuting || incidentState === 'executing') return 'executing';
  if (incidentState === 'active') return 'decision';
  if (incidentState !== undefined && !KNOWN_INCIDENT.has(incidentState)) return 'decision';
  if (withdrawing) return 'executing';
  if (incidentState === 'done') return 'done';
  return 'norm';
}
