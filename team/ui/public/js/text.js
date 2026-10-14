// Every user-visible string of the interface, the labels of the platform's
// codes, and the formatters. Pure: no DOM. Wording rules of DESIGN.md 2.2:
// "расчётный маршрут (модель)", "синтетический индекс нестабильности",
// "нет расчётного маршрута", "прогноз модели"; an unknown code is never
// shown as a normal state.

import {ACK_TIMEOUT_MS, NAMESPACE, REQUEST_TIMEOUT_MS, RUNS_LIMIT, STALE_AFTER_MS} from './config.js';

export const DASH = '—';
export const NOTICE = 'Синтетические данные. Расчёт модели, не сведения о реальной шахте';

// --------------------------------------------------------------------------
// Vocabularies: code of the platform -> text on the screen
// --------------------------------------------------------------------------

export const VOCAB = {
  kind: {
    mine: 'рудник', level: 'горизонт', working: 'выработка', zone: 'участок', sensor: 'датчик',
    worker: 'работник', exit: 'выход', shift: 'смена', incident: 'инцидент', option: 'вариант',
    run: 'прогон', journal: 'журнал',
  },
  kindPlural: {
    all: 'все объекты', level: 'горизонты', working: 'выработки', zone: 'участки', sensor: 'датчики',
    worker: 'работники', exit: 'выходы', incident: 'инцидент', option: 'варианты', journal: 'журнал',
  },
  hazard: {normal: 'норма', attention: 'внимание', danger: 'опасно', unknown: 'состояние неизвестно'},
  quality: {
    fresh: 'данные актуальны', stale: 'данные устарели', lost: 'данные потеряны',
    none: 'без датчиков, состояние не оценивается',
  },
  posQuality: {fresh: 'положение актуально', stale: 'положение устарело', lost: 'последнее известное положение'},
  linkState: {online: 'связь есть', offline: 'нет связи'},
  passability: {open: 'проход открыт', closed: 'проход закрыт'},
  closedBy: {none: '', scenario: 'условие стенда', dispatcher: 'решение диспетчера'},
  restriction: {
    blocked: 'новый вход запрещён моделью', allowed: 'вход разрешён моделью', unknown: 'ограничение входа неизвестно',
  },
  workState: {working: 'работает', stopped: 'остановлен'},
  withdrawal: {
    none: 'приказа о выводе нет', in_progress: 'вывод персонала идёт', done: 'вывод персонала завершён',
    incomplete: 'вывод не завершён',
  },
  workerStatus: {
    working: 'работает', moving_to_exit: 'идёт к выходу', waiting: 'ожидает на месте', out: 'вышел',
    unknown: 'статус неизвестен',
  },
  egress: {ok: 'расчётный маршрут (модель)', none: 'нет расчётного маршрута', unknown: 'маршрут не рассчитан'},
  egressReason: {
    none: '', no_open_path: 'в графе модели нет открытого пути до выхода', position_unknown: 'положение неизвестно',
    not_computed: 'расчёт не выполнен', current_working_closed: 'закрыта выработка, в которой находится работник',
  },
  exitState: {
    available: 'выход доступен (модель)', unavailable: 'выход недоступен', unknown: 'состояние выхода неизвестно',
  },
  exitKind: {shaft: 'ствол', ramp: 'съезд', raise: 'восстающий'},
  sensorKind: {extensometer: 'экстензометр', convergence: 'датчик сближения', geophone: 'геофон'},
  workingKind: {drift: 'штрек', crosscut: 'квершлаг', ramp: 'съезд', shaft: 'ствол', raise: 'восстающий'},
  reasonCode: {
    none: '', rate_above_attention: 'скорость изменения выше порога «внимание»',
    rate_above_danger: 'скорость изменения выше порога «опасно»',
    events_above_danger: 'число событий выше порога «опасно»',
    index_above_attention: 'синтетический индекс нестабильности выше порога «внимание»',
    index_above_danger: 'синтетический индекс нестабильности выше порога «опасно»',
    sensor_stale: 'данные датчика устарели', sensor_lost: 'данные датчика потеряны',
    no_sensor: 'без датчиков, состояние не оценивается',
  },
  // mine.attributes.thresholds: a demonstration setting, shown in the legend and never applied by the interface.
  threshold: {
    rate: 'скорость изменения', index: 'синтетический индекс нестабильности', events: 'число событий за окно',
  },
  thresholdLevel: {attention: 'внимание', danger: 'опасно'},
  runState: {running: 'модель идёт', paused: 'модель на паузе', resetting: 'выполняется сброс'},
  pauseReason: {none: '', decision: 'для выбора действия'},
  incidentState: {none: 'Инцидентов нет', active: 'Инцидент', executing: 'Инцидент: решение исполняется', done: 'Инцидент завершён'},
  incidentTrigger: {hazard: 'опасность на участке', passage_closed: 'закрыт проход', data_lost: 'потеряны данные датчиков'},
  optionKind: {
    observe: 'Наблюдать', stop_withdraw_zone: 'Остановить участок и вывести персонал', withdraw_all: 'Вывести всех',
    withdraw_level: 'Вывести горизонт',
  },
  optionState: {inactive: 'не предложен', offered: 'предложен', executing: 'исполняется', done: 'исполнен', unavailable: 'недоступен'},
  forecastQuality: {full: 'по полным данным', partial: 'по неполным данным'},
  archiveRunState: {running: 'идёт', finished: 'завершён'},
  completionReason: {withdrawal_done: 'вывод завершён', horizon_reached: 'достигнут горизонт расчёта', reset: 'прерван сбросом'},
  incomparableReason: {condition_changed_after_decision: 'условие изменено после решения'},
  presetExpect: {detour: 'обход есть', no_path: 'пути нет'},
  conditionKind: {working_closed: 'закрыта', sensor_lost: 'без связи', instability: 'рост нестабильности'},
  commandType: {
    'condition.close_working': 'Закрыть выработку', 'condition.open_working': 'Открыть выработку',
    'condition.sensor_lost': 'Потерять связь с датчиком', 'condition.sensor_restored': 'Вернуть связь с датчиком',
    'condition.instability_on': 'Запустить рост нестабильности', 'condition.instability_off': 'Остановить рост нестабильности',
    'action.stop_zone': 'Остановить участок', 'action.withdraw_zone': 'Вывести персонал участка',
    'action.resume_zone': 'Возобновить работу', 'action.execute_option': 'Запустить вариант',
    'run.reset': 'Полный сброс прогона', 'run.start_preset': 'Запустить сценарий',
  },
  ackReason: {
    none: '', already_in_state: 'состояние уже такое', not_allowed_in_state: 'недопустимо в текущем состоянии',
    malformed: 'команда составлена неверно', unknown_type: 'неизвестный тип команды',
    unknown_target: 'неизвестная цель команды', invalid_run: 'команда относится к другому прогону',
    command_id_conflict: 'этот идентификатор уже использован с другим содержанием',
    stale_decision: 'решение устарело: условия изменились', insufficient_workers: 'на участке недостаточно персонала',
  },
  journalCode: {
    'run.started': 'прогон начат', 'run.reset': 'прогон прерван сбросом', 'condition.set': 'условие задано',
    'condition.cancelled': 'условие отменено', 'hazard.changed': 'изменилась опасность',
    'quality.changed': 'изменилось качество данных', 'command.applied': 'команда применена',
    'command.rejected': 'команда отклонена', 'zone.stopped': 'участок остановлен', 'zone.resumed': 'работа участка возобновлена',
    'withdrawal.started': 'начат вывод персонала', 'withdrawal.finished': 'вывод персонала окончен',
    'worker.route_changed': 'изменён расчётный маршрут', 'worker.no_route': 'нет расчётного маршрута',
    'worker.out': 'работник вышел',
  },
  linkStatus: {ok: 'связь есть', degraded: 'связь ухудшилась', stale: 'данные устарели', unavailable: 'недоступна'},
  publications: {alive: 'публикации идут', stopped: 'публикации остановились', unknown: 'публикации: неизвестно'},
  blockReason: {
    not_ready: 'данные ещё не загружены', platform_unavailable: 'платформа недоступна', stale: 'данные устарели',
    no_snapshot: 'нет полного снимка состояния', snapshot_invalid: 'последний снимок отклонён',
    publications_stopped: 'публикации модели остановились', resetting: 'выполняется сброс',
    own_reset_pending: 'сброс отправлен и ещё не подтверждён',
  },
  pendingPhase: {
    sending: 'Команда отправляется', sent: 'Команда отправлена, не подтверждена', applied: 'Команда применена',
    rejected: 'Команда отклонена', no_ack: `Нет подтверждения ${ACK_TIMEOUT_MS / 1000} с. Команда могла не дойти`,
    delivery_unknown: 'Результат доставки неизвестен', not_sent: 'Команда не отправлена',
  },
  unit: {m: 'м', mm: 'мм', 'mm/h': 'мм/ч', 't/h': 'т/ч', s: 'с', 'person*s': 'чел.·с', 'zone*s': 'уч.·с', 1: ''},
};

/** Names of features and attributes as captions. */
const FIELD = {
  tick: 'тик', sim_time_s: 'время модели', idSimulationRun: 'прогон',
  passability: 'проходимость', closed_by: 'кем закрыта', hazard_state: 'опасность', data_quality: 'знание',
  instability_index: 'синтетический индекс нестабильности', index_at_tick: 'тик расчёта индекса',
  reason_code: 'причина состояния', reason_sensor: 'датчик', reason_value: 'значение', reason_threshold: 'порог',
  last_known_hazard_state: 'последняя известная опасность', last_known_hazard_tick: 'тик последней оценки',
  routing_restriction: 'ограничение маршрутов',
  work_state: 'работа участка', withdrawal_state: 'вывод персонала', workers_count: 'работников на участке',
  production_rate: 'производительность', downtime_s: 'суммарный простой участков',
  value: 'смещение', rate: 'скорость изменения', events_count: 'событий за окно',
  measured_at_tick: 'тик измерения', measured_at_sim_s: 'время измерения (модель)', link_state: 'связь', quality: 'знание',
  status: 'статус', at_working: 'выработка', offset_m: 'расстояние от узла', at_exit: 'выход',
  pos_quality: 'знание о положении', location_hazard: 'опасность в месте нахождения',
  egress_status: 'достижимость', egress_reason: 'причина', route: 'маршрут', route_next_node: 'следующий узел',
  egress_exit: 'выход по маршруту', egress_length_m: 'длина маршрута', egress_eta_s: 'время по модели',
  egress_detour_m: 'удлинение маршрута', egress_detour_s: 'удлинение по времени',
  egress_crosses: 'худшее состояние вдоль маршрута',
  state: 'состояние', workers_out: 'вышло',
  run_state: 'состояние модели', pause_reason: 'причина паузы', speedup: 'ускорение', seed: 'seed',
  topology_version: 'версия топологии', conditions: 'условия стенда', workers_total: 'всего работников',
  workers_in_danger: 'в опасных зонах', workers_no_route: 'без расчётного маршрута',
  workers_unknown: 'состояние неизвестно', publication_seq: 'номер публикации', contract_version: 'версия контракта',
  trigger: 'причина открытия', zone: 'участок', opened_at_tick: 'открыт на тике', selected_option: 'выбранный вариант',
  causes: 'причины', scope: 'участки варианта', decision_id: 'идентификатор решения', comparison_key: 'ключ сравнения',
  forecast_tick: 'тик прогноза', forecast_horizon_s: 'горизонт прогноза', forecast_quality: 'полнота прогноза',
  completion_reason: 'чем завершён', comparable: 'сравним с прогнозом', incomparable_reason: 'почему не сравним',
  executed_option: 'исполненный вариант', finished_at_sim_s: 'завершён (время модели)',
  last_seq: 'номер последнего события', events: 'события',
  kind: 'тип', label: 'код', length_m: 'длина', working_kind: 'вид выработки', from: 'от узла', to: 'до узла',
  level: 'горизонт', points: 'промежуточные точки', elevation_m: 'отметка', order: 'порядок',
  sensor_kind: 'вид датчика', working: 'выработка', stale_after_s: 'допуск устаревания (модель)',
  lost_after_s: 'допуск потери (модель)', window_s: 'окно счёта событий', home_zone: 'участок приписки',
  exit_kind: 'вид выхода', node: 'узел', option_kind: 'вид варианта', workings: 'выработки', sensors: 'датчики',
};

/** Result metrics of CONTRACT.md, section 6: bare for a run, with forecast_ / actual_ for an option. */
export const METRICS = ['in_danger', 'danger_exposure_person_s', 'unknown_exposure_person_s', 'no_route', 'out',
  'all_out', 'last_out_s', 'downtime_s'];

const METRIC = {
  in_danger: 'в опасных зонах', danger_exposure_person_s: 'пребывание в опасных зонах',
  unknown_exposure_person_s: 'пребывание в зонах с неизвестным состоянием', no_route: 'без расчётного маршрута',
  out: 'вышло', all_out: 'все вышли', last_out_s: 'время выхода всех', downtime_s: 'суммарный простой участков',
};

const METRIC_SHORT = {
  in_danger: 'в оп. зонах', danger_exposure_person_s: 'в оп. зонах, чел.·с',
  unknown_exposure_person_s: 'неизв., чел.·с', no_route: 'без маршр.', out: 'вышло', all_out: 'все вышли',
  last_out_s: 'выход всех', downtime_s: 'простой, уч.·с',
};

function own(map, key) {
  return (typeof key === 'string' || typeof key === 'number') && Object.prototype.hasOwnProperty.call(map, key);
}

/** True when the code belongs to the vocabulary. @param {keyof typeof VOCAB} vocab */
export function isKnown(vocab, code) {
  return own(VOCAB[vocab], code);
}

/**
 * The text of a state code. Not published: a dash. Outside the vocabulary:
 * "неизвестно (код)", so that an unknown state never reads as a normal one.
 * @param {keyof typeof VOCAB} vocab
 * @param {*} code
 */
export function label(vocab, code) {
  if (code === undefined || code === null) return DASH;
  return own(VOCAB[vocab], code) ? VOCAB[vocab][code] : unknownCode(code);
}

/** The text of a code that is shown as is when it is not known (journal events, option kinds, command types). */
export function codeLabel(vocab, code) {
  if (code === undefined || code === null) return DASH;
  return own(VOCAB[vocab], code) ? VOCAB[vocab][code] : String(code);
}

export function unknownCode(code) {
  return `неизвестно (${String(code)})`;
}

/**
 * The caption of a feature or attribute; an unknown name is returned as is.
 * `forecast_x` and `actual_x` read as "прогноз: x" and "факт: x".
 * @param {string} name
 * @param {string} [kind] the kind of the twin, for names that mean different things
 */
export function fieldLabel(name, kind) {
  for (const [prefix, word] of [['forecast_', 'прогноз'], ['actual_', 'факт']]) {
    const rest = name.slice(prefix.length);
    if (name.startsWith(prefix) && own(METRIC, rest)) return `${word}: ${METRIC[rest]}`;
  }
  if (name === 'downtime_s' && kind === 'zone') return 'простой участка';
  if (name === 'value' && kind === 'sensor') return 'показание';
  if (kind === 'run' && own(METRIC, name)) return METRIC[name];
  return own(FIELD, name) ? FIELD[name] : name;
}

/** @param {string} suffix one of METRICS @param {boolean} [short] a column heading */
export function metricLabel(suffix, short = false) {
  const map = short ? METRIC_SHORT : METRIC;
  return own(map, suffix) ? map[suffix] : suffix;
}

// --------------------------------------------------------------------------
// Formatters. Own code, not the browser's locale: the judge's browser is unknown.
// --------------------------------------------------------------------------

const MINUS = '−';
const NBSP = ' ';

/**
 * A number with a decimal comma. Integers are written whole; other values
 * with at most `digits` decimals and no trailing zeros.
 * @param {*} value
 * @param {number} [digits]
 */
export function num(value, digits = 2) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DASH;
  let text = Number.isInteger(value) ? String(Math.abs(value)) : Math.abs(value).toFixed(digits);
  if (text.includes('.')) text = text.replace(/\.?0+$/, '');
  text = text.replace('.', ',');
  return (value < 0 && text !== '0' ? MINUS : '') + text;
}

/** The unit of the platform as written on the screen; "1" (dimensionless) gives nothing. */
export function unit(code) {
  if (code === undefined || code === null) return '';
  return own(VOCAB.unit, code) ? VOCAB.unit[code] : String(code);
}

/** A value with its unit: "2,6 мм/ч"; a dash when the value is not published. */
export function quantity(value, unitCode, digits = 2) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DASH;
  const suffix = unit(unitCode);
  return suffix ? `${num(value, digits)}${NBSP}${suffix}` : num(value, digits);
}

const two = (value) => String(value).padStart(2, '0');

/** Model seconds from the start of the run as ЧЧ:ММ:СС. */
export function modelTime(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return DASH;
  const whole = Math.floor(seconds);
  return `${two(Math.floor(whole / 3600))}:${two(Math.floor(whole / 60) % 60)}:${two(whole % 60)}`;
}

/** A duration in words: "44 с", "8 мин 44 с", "1 ч 5 мин". */
export function duration(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return DASH;
  const whole = Math.round(seconds);
  const parts = [];
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor(whole / 60) % 60;
  const rest = whole % 60;
  if (hours > 0) parts.push(`${hours}${NBSP}ч`);
  if (minutes > 0) parts.push(`${minutes}${NBSP}мин`);
  if (rest > 0 || parts.length === 0) parts.push(`${rest}${NBSP}с`);
  return parts.join(' ');
}

/** Platform wall time, always UTC and always labelled: "09:02:11 UTC". @param {number|string|null} time epoch ms or ISO text */
export function utcTime(time) {
  const ms = typeof time === 'string' ? Date.parse(time) : time;
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return DASH;
  const date = new Date(ms);
  return `${two(date.getUTCHours())}:${two(date.getUTCMinutes())}:${two(date.getUTCSeconds())} UTC`;
}

/** "00:21:20 · тик 1280" */
export function tickTime(simTimeS, tick) {
  const parts = [];
  if (typeof simTimeS === 'number') parts.push(modelTime(simTimeS));
  if (typeof tick === 'number') parts.push(`тик${NBSP}${tick}`);
  // The dot stays with the tick when a narrow cell breaks the line.
  return parts.length > 0 ? parts.join(` ·${NBSP}`) : DASH;
}

/** The Russian plural form for a count. @param {[string, string, string]} forms one, few, many: работник, работника, работников */
export function plural(count, forms) {
  const n = Math.abs(count) % 100;
  const last = n % 10;
  if (n > 10 && n < 20) return forms[2];
  if (last === 1) return forms[0];
  if (last >= 2 && last <= 4) return forms[1];
  return forms[2];
}

/** "2 работника" */
export function counted(count, forms) {
  return `${num(count)}${NBSP}${plural(count, forms)}`;
}

export const FORMS = {
  worker: ['работник', 'работника', 'работников'],
  object: ['объект', 'объекта', 'объектов'],
  zone: ['участок', 'участка', 'участков'],
  event: ['событие', 'события', 'событий'],
  run: ['прогон', 'прогона', 'прогонов'],
};

export function yesNo(value) {
  if (value === true) return 'да';
  if (value === false) return 'нет';
  return DASH;
}

/** A twin in a message: "Р-05 (worker-05)"; the bare name when no label is known. */
export function codeAndName(name, labelOf) {
  const code = labelOf ? labelOf(name) : name;
  return code && code !== name ? `${code} (${name})` : String(name);
}

function listOf(names, labelOf, limit = 5) {
  const shown = names.slice(0, limit).map((name) => codeAndName(name, labelOf));
  return names.length > limit ? `${shown.join(', ')} и ещё ${names.length - limit}` : shown.join(', ');
}

// --------------------------------------------------------------------------
// State of one twin in words
// --------------------------------------------------------------------------

/**
 * The displayed hazard of a working or a zone.
 * @param {import('./store.js').DisplayedHazard} hazard
 */
export function hazardText(hazard) {
  if (!hazard.known) return `${VOCAB.hazard.unknown} (код ${hazard.raw})`;
  return VOCAB.hazard[hazard.state];
}

/** A hazard code without a quality next to it (location_hazard, egress_crosses, last_known_hazard_state). */
export function hazardCodeText(code) {
  return label('hazard', code);
}

/** "последнее известное: опасно (тик 810)", or an empty string when nothing is kept. */
export function lastKnownText(values) {
  if (typeof values.last_known_hazard_state !== 'string') return '';
  const state = hazardCodeText(values.last_known_hazard_state);
  const tick = typeof values.last_known_hazard_tick === 'number' ? ` (тик${NBSP}${values.last_known_hazard_tick})` : '';
  return `последнее известное: ${state}${tick}`;
}

/** Why a working or a zone is in its state: "скорость изменения 2,6 мм/ч по Э-03 выше порога «опасно» 2 мм/ч". */
export function reasonText(values, labelOf) {
  const code = values.reason_code;
  if (code === undefined || code === null || code === 'none') return '';
  let text = label('reasonCode', code);
  const details = [];
  if (typeof values.reason_sensor === 'string') details.push(`датчик ${labelOf ? labelOf(values.reason_sensor) : values.reason_sensor}`);
  if (typeof values.reason_value === 'number') details.push(`значение ${quantity(values.reason_value, values.reason_unit)}`);
  if (typeof values.reason_threshold === 'number') details.push(`порог ${quantity(values.reason_threshold, values.reason_unit)}`);
  if (details.length > 0) text += `: ${details.join(', ')}`;
  return text;
}

/** Passability of a working with the author of the closure: "проход закрыт (условие стенда)". */
export function passabilityText(values) {
  const text = label('passability', values.passability);
  const by = values.passability === 'closed' && values.closed_by && values.closed_by !== 'none'
    ? label('closedBy', values.closed_by) : '';
  return by ? `${text} (${by})` : text;
}

/**
 * Reachability of a worker as the model published it:
 * "расчётный маршрут (модель): 655 м (длиннее на 243 м), около 8 мин 44 с, выход Съезд".
 */
export function egressText(values, labelOf) {
  const status = values.egress_status;
  if (values.status === 'out') {
    const exit = typeof values.at_exit === 'string' ? ` через ${labelOf ? labelOf(values.at_exit) : values.at_exit}` : '';
    return `вышел${exit}`;
  }
  if (status !== 'ok') {
    const text = label('egress', status);
    const reason = values.egress_reason && values.egress_reason !== 'none' ? label('egressReason', values.egress_reason) : '';
    return reason ? `${text}: ${reason}` : text;
  }
  const parts = [];
  if (typeof values.egress_length_m === 'number') {
    const detour = typeof values.egress_detour_m === 'number' && values.egress_detour_m > 0
      ? ` (длиннее на ${quantity(values.egress_detour_m, 'm')})` : '';
    parts.push(`${quantity(values.egress_length_m, 'm')}${detour}`);
  }
  if (typeof values.egress_eta_s === 'number') parts.push(`около ${duration(values.egress_eta_s)}`);
  if (typeof values.egress_exit === 'string') parts.push(`выход ${labelOf ? labelOf(values.egress_exit) : values.egress_exit}`);
  return parts.length > 0 ? `${VOCAB.egress.ok}: ${parts.join(', ')}` : VOCAB.egress.ok;
}

/** "маршрут проходит через участок «опасно»", or an empty string. */
export function crossesText(values) {
  if (typeof values.egress_crosses !== 'string' || values.egress_crosses === 'normal') return '';
  return `маршрут проходит через участок «${hazardCodeText(values.egress_crosses)}»`;
}

/** An active scenario condition as a chip: "В-07 закрыта". @param {import('./store.js').Condition} condition */
export function conditionText(condition, labelOf) {
  const target = labelOf ? labelOf(condition.target) : condition.target;
  return isKnown('conditionKind', condition.kind) ? `${target} ${VOCAB.conditionKind[condition.kind]}`
    : `${condition.raw} (неизвестное условие)`;
}

/**
 * A place as words: "В-21, 35 м от узла n-14", "вышел: Ствол", "Гор. −320 м".
 * @param {ReturnType<typeof import('./model.js').placeOf>} place
 */
export function placeText(place) {
  if (place.exit) return `выход ${place.exit.label}`;
  const parts = [];
  if (place.working) {
    let text = place.working.label;
    if (place.offsetM !== null) {
      text += `, ${quantity(place.offsetM, 'm')}`;
      if (place.fromNode) text += ` от узла ${place.fromNode}`;
    }
    parts.push(text);
  }
  if (place.zone) parts.push(place.zone.label);
  // A position on a working is already exact; the level is added only when it is the best that is known.
  if (place.level && !(place.working && place.offsetM !== null)) parts.push(place.level.label);
  if (place.node) parts.push(`узел ${place.node}`);
  return parts.length > 0 ? parts.join(' · ') : DASH;
}

// --------------------------------------------------------------------------
// Link, banners, blocking
// --------------------------------------------------------------------------

/** A failed read in a few words: "HTTP 502", "нет ответа за 3 с". */
export function failureText(failure) {
  if (!failure) return '';
  if (failure.kind === 'http') return `HTTP ${failure.status}`;
  if (failure.kind === 'timeout') return `нет ответа за ${REQUEST_TIMEOUT_MS / 1000} с`;
  if (failure.kind === 'network') return 'ошибка сети';
  if (failure.kind === 'body') return 'ответ не разобран';
  if (failure.kind === 'incomplete') return 'неполный ответ';
  if (failure.kind === 'blocked') return `команды заблокированы: ${label('blockReason', failure.reason)}`;
  return String(failure.kind);
}

/** "данные 1 с назад" */
export function ageText(seconds) {
  return seconds === null || seconds === undefined ? 'данных нет' : `данные ${duration(seconds)} назад`;
}

/** Which data are on the screen: "Показаны данные на 09:02:11 UTC, тик 812". @param {import('./store.js').Snapshot|null} snapshot */
export function shownDataText(snapshot) {
  return snapshot ? `Показаны данные на ${utcTime(snapshot.modifiedMs)}, тик${NBSP}${snapshot.tick}` : 'Данные ещё не получены';
}

/**
 * Why a read was not accepted as a full snapshot, or why attributes cannot be used.
 * @param {{code: string, params: Object, detail: string}} rejection
 * @param {(name: string) => string} [labelOf]
 */
export function rejectionText(rejection, labelOf) {
  const p = rejection.params || {};
  const thing = p.thing ? codeAndName(p.thing, labelOf) : '';
  switch (rejection.code) {
    case 'no_metadata':
      return `ответ платформы без метаданных (${p.field}): его нельзя считать актуальным`;
    case 'contract_version':
      return `версия контракта данных ${String(p.actual)}, интерфейс работает с версией ${p.expected}`;
    case 'topology_mismatch':
      return `версия топологии в двойниках (${p.attributes}) не совпадает с версией модели (${p.shift})`;
    case 'scene_missing_id':
      return `в состоянии нет ${counted(p.ids.length, FORMS.object)}: ${listOf(p.ids.map(shortId), labelOf)}`;
    case 'scene_extra_id':
      return `в состоянии есть объекты вне списка двойников: ${listOf(p.ids.map(shortId), labelOf)}`;
    case 'scene_duplicate_id':
      return `объект повторяется в состоянии: ${listOf(p.ids.map(shortId), labelOf)}`;
    case 'scene_mixed_tick':
      return `объект ${thing} относится к другому моменту модели: ${p.field} ${String(p.actual)} вместо ${String(p.expected)}`;
    case 'scene_mixed_run':
      return `объект ${thing} относится к другому прогону: ${String(p.actual)} вместо ${String(p.expected)}`;
    case 'missing_field':
      return `у объекта ${thing} нет обязательного поля ${p.field}`;
    case 'malformed':
      return `у объекта ${thing} поле ${p.field} имеет неверный вид`;
    case 'manifest_incomplete':
      return `платформа не вернула атрибуты ${p.ids.length} из ${p.total} объектов: ${listOf(p.ids.map(shortId), labelOf)}`;
    default:
      return `${rejection.code}: ${rejection.detail}`;
  }
}

function shortId(thingId) {
  const at = String(thingId).indexOf(':');
  return at < 0 ? String(thingId) : String(thingId).slice(at + 1);
}

/** Codes of the banners, most severe first. */
export const BANNER_ORDER = ['platform_unavailable', 'empty_stand', 'contract_version', 'manifest_incomplete',
  'topology_mismatch', 'snapshot_invalid', 'stale', 'publications_stopped', 'link_degraded', 'resetting',
  'paused_decision'];

export const BANNER_SEVERITY = {
  platform_unavailable: 'danger', empty_stand: 'danger', contract_version: 'danger', manifest_incomplete: 'danger',
  topology_mismatch: 'danger', snapshot_invalid: 'danger', stale: 'danger', publications_stopped: 'danger',
  link_degraded: 'attention', resetting: 'attention', paused_decision: 'info',
};

const COMMANDS_BLOCKED = 'Команды заблокированы';

/**
 * The words of a banner. The title and the text read as one message.
 * @param {string} code one of BANNER_ORDER
 * @param {import('./store.js').State} state
 * @param {(name: string) => string} [labelOf]
 * @returns {{title: string, text: string}}
 */
export function bannerText(code, state, labelOf) {
  const {link, snapshot} = state;
  const cause = failureText(link.failure);
  const inBrackets = cause ? ` (${cause})` : '';
  switch (code) {
    case 'platform_unavailable':
      return {
        title: `Платформа недоступна${inBrackets}.`,
        text: `${shownDataText(snapshot)}. Текущее состояние неизвестно`,
      };
    case 'empty_stand':
      return {
        title: 'Двойники рудника не найдены в платформе.',
        text: `Платформа отвечает, объектов в ${NAMESPACE} нет`,
      };
    case 'contract_version': {
      const rejection = state.bootError || link.invalid;
      return {
        title: 'Неизвестная версия контракта данных.',
        text: `${capitalize(rejectionText(rejection, labelOf))}. Данные не показаны`,
      };
    }
    case 'manifest_incomplete': {
      const rejection = state.bootError || link.invalid;
      return {
        title: 'Состав двойников неполный.',
        text: `${capitalize(rejectionText(rejection, labelOf))}. ${COMMANDS_BLOCKED}`,
      };
    }
    case 'topology_mismatch': {
      const p = link.invalid.params;
      return {
        title: `Схема не показана: версия топологии в двойниках (${p.attributes}) не совпадает с версией модели (${p.shift}).`,
        text: `Вид «Список» доступен. ${COMMANDS_BLOCKED}`,
      };
    }
    case 'snapshot_invalid':
      return {
        title: `Состояние не принято: ${rejectionText(link.invalid, labelOf)}.`,
        text: `${snapshot ? `${shownDataText(snapshot).replace('Показаны данные на', 'Показан последний полный снимок:')}` : 'Полного снимка ещё не было'}. ${COMMANDS_BLOCKED}`,
      };
    case 'stale':
      return {
        title: `Данные устарели: полного снимка нет дольше ${STALE_AFTER_MS / 1000} с${inBrackets}.`,
        text: `${shownDataText(snapshot)}. ${COMMANDS_BLOCKED}`,
      };
    case 'publications_stopped':
      return {
        title: 'Публикации модели остановились.',
        text: `Платформа отвечает, но номер публикации не меняется. ${snapshot ? `Показано последнее состояние: ${utcTime(snapshot.modifiedMs)}, тик${NBSP}${snapshot.tick}` : 'Данных нет'}. ${COMMANDS_BLOCKED}`,
      };
    case 'link_degraded':
      return {
        title: `Связь с платформой ухудшилась${inBrackets}.`,
        text: 'Движение на схеме остановлено, показано последнее полученное состояние',
      };
    case 'resetting':
      return {title: 'Выполняется сброс.', text: `Новый прогон ещё не начался. ${COMMANDS_BLOCKED}`};
    case 'paused_decision':
      return {title: 'Модель на паузе для выбора действия.', text: 'Время модели стоит, публикации идут'};
    default:
      return {title: String(code), text: ''};
  }
}

function capitalize(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** "Команды заблокированы: платформа недоступна" */
export function blockText(reason) {
  return reason ? `${COMMANDS_BLOCKED}: ${label('blockReason', reason)}` : '';
}

// --------------------------------------------------------------------------
// Commands
// --------------------------------------------------------------------------

/** "Остановить участок: Участок Б"; a command without a target is its name alone. */
export function commandText(type, target, labelOf) {
  const name = codeLabel('commandType', type);
  if (type === 'run.reset' || typeof target !== 'string' || target === '') return name;
  const aim = labelOf ? labelOf(target) : target;
  return aim ? `${name}: ${aim}` : name;
}

/** The result of an acknowledgement record: "применена", "применена без изменения: состояние уже такое", "отклонена: ... (код)". */
export function ackText(record) {
  const reason = record.reason && record.reason !== 'none' ? record.reason : null;
  if (record.status === 'applied') {
    return reason === 'already_in_state' ? `применена без изменения: ${VOCAB.ackReason.already_in_state}`
      : (reason ? `применена (${codeLabel('ackReason', reason)})` : 'применена');
  }
  if (record.status === 'rejected') {
    if (!reason) return 'отклонена';
    return isKnown('ackReason', reason) ? `отклонена: ${VOCAB.ackReason[reason]} (${reason})` : `отклонена: неизвестная причина (${reason})`;
  }
  return record.status === undefined || record.status === null ? 'результат не указан'
    : `неизвестный результат (${String(record.status)})`;
}

function phaseText(entry, elapsedS) {
  const waited = typeof elapsedS === 'number' ? ` (${duration(elapsedS)})` : '';
  const failure = entry.failure;
  switch (entry.phase) {
    case 'sent':
      return `${VOCAB.pendingPhase.sent}${waited}`;
    case 'applied':
    case 'rejected':
      return entry.ack ? `Команда ${ackText(entry.ack)}` : VOCAB.pendingPhase[entry.phase];
    case 'delivery_unknown':
      // The platform refused a retry, but an earlier sending may have arrived.
      if (failure && failure.kind === 'http' && failure.status >= 400 && failure.status < 500) {
        return `${VOCAB.pendingPhase.delivery_unknown}: повтор не принят (${failureText(failure)}), но предыдущая отправка могла дойти до модели`;
      }
      return `${VOCAB.pendingPhase.delivery_unknown} (${failureText(failure)}). Команда могла дойти до модели`;
    case 'not_sent':
      return `${VOCAB.pendingPhase.not_sent}: ${failureText(failure)}`;
    default:
      return own(VOCAB.pendingPhase, entry.phase) ? VOCAB.pendingPhase[entry.phase] : String(entry.phase);
  }
}

/**
 * The message of a pending command. A record of the model with a status
 * outside the contract settles nothing and is named next to the phase.
 * @param {import('./store.js').PendingCommand} entry
 * @param {number} [elapsedS] whole seconds in the current phase, shown while waiting
 */
export function pendingText(entry, elapsedS) {
  const words = phaseText(entry, elapsedS);
  return entry.oddAck && !entry.ack ? `${words}. Запись модели: ${ackText(entry.oddAck)}` : words;
}

/** "c-5f2a9c1e…" for a compact mention; the full id goes into a title or the journal. */
export function shortCommandId(id) {
  return typeof id === 'string' && id.length > 12 ? `${id.slice(0, 10)}…` : String(id);
}

// --------------------------------------------------------------------------
// Fixed strings of the screen, by region
// --------------------------------------------------------------------------

export const UI = {
  status: {
    region: 'Состояние стенда',
    platform: 'Платформа',
    model: 'Модель',
    run: 'Прогон',
    seed: 'seed',
    conditions: 'Условия стенда',
    noConditions: 'нет',
    noData: 'нет данных',
    commandsBlocked: COMMANDS_BLOCKED,
    oldTag: 'последние полученные данные:',
    speed: (value) => `×${num(value)}`,
  },
  incident: {
    region: 'Инцидент и люди',
    inDanger: 'в опасных зонах',
    noRoute: 'без расчётного маршрута',
    unknown: 'состояние неизвестно',
    total: 'всего',
    out: 'вышло',
    overlap: 'числа считает модель; один работник может входить в несколько',
    zone: 'участок',
  },
  tabs: {
    region: 'Вид',
    scheme: 'Схема',
    list: 'Список',
    runs: 'Прогоны',
    rightRegion: 'Правая панель',
    decision: 'Решение',
    card: 'Карточка',
    journal: 'Журнал',
    journalOpen: 'Развернуть журнал',
    journalClose: 'Свернуть журнал',
    runBox: 'Прогон',
  },
  oldData: (snapshot) => `${shownDataText(snapshot)}. Текущее состояние неизвестно`,
  list: {
    title: 'Список объектов',
    filter: 'Тип объектов',
    columns: ['Тип', 'Код', 'Место', 'Опасность', 'Знание', 'Достижимость', 'Значение и состояние', 'Время модели', 'Время платформы'],
    empty: 'Объектов этого типа нет',
    noAttributes: 'Атрибуты двойников ещё не прочитаны',
    noState: 'состояние не получено',
    selected: 'выбран',
    count: (shown) => `Показано: ${counted(shown, FORMS.object)}`,
    measured: 'измерено',
    pending: 'команда отправлена, не подтверждена',
    // The knowledge cell of a twin without sensors; the card gives the full sentence.
    noSensors: 'без датчиков',
  },
  scheme: {
    title: 'Схема рудника',
    projection: 'Вид',
    axo: 'Аксонометрия',
    plan: 'План горизонта',
    level: 'Горизонт',
    allLevels: 'все горизонты',
    note: 'Вертикаль не в масштабе; координаты условные, метры',
    notDrawn: 'Схема не показана',
    noSensors: 'без датчиков, состояние не оценивается',
    byStaleData: 'по устаревшим данным',
    out: (count) => `вышло ${num(count)}`,
    grouped: (count) => `×${num(count)}`,
    pending: 'команда отправлена, не подтверждена',
    leadsTo: (level) => `на ${level}`,
    planOf: (level) => `План: ${level}`,
    noPosition: (codes) => `Без опубликованного положения: ${codes}`,
    inGroup: (count) => `в группе из ${num(count)}`,
  },
  legend: {
    title: 'Легенда',
    hazard: 'Опасность',
    knowledge: 'Знание',
    reach: 'Достижимость',
    exit: 'Выход',
    stale: 'устарели',
    lost: 'потеряны',
    inDangerZone: 'работник в опасной зоне',
    group: 'группа на одном отрезке',
    route: 'маршруты выбранного объекта или участка инцидента',
    pending: 'команда отправлена, не подтверждена',
    exitAvailable: 'доступен (модель)',
    exitUnavailable: 'недоступен',
    exitUnknown: 'состояние неизвестно',
  },
  card: {
    title: 'Карточка',
    summary: 'Сводка смены',
    nothingSelected: 'Объект не выбран. Выберите объект на схеме или в списке',
    notFound: 'Выбранного объекта нет среди двойников',
    close: 'Снять выбор',
    state: 'Состояние',
    attributes: 'Атрибуты',
    related: 'Связанные объекты',
    modelTime: 'время модели',
    platformTime: 'платформа',
    measuredAt: (time) => `Измерено ${time} модельного времени`,
    lastMeasurement: (time) => `Последнее измерение ${time} модельного времени`,
    indexLastComputed: (tick) => `последнее рассчитанное, тик${NBSP}${tick}`,
    noRoute: (code) => `${code}: нет расчётного маршрута. В графе модели нет открытого пути до выхода`,
    notPublished: 'не опубликовано',
    none: 'нет',
    graphOnly: 'Это утверждение о графе модели, а не о реальной шахте',
    defensive: ' (опубликовано «норма» без актуальных данных)',
    records: (count) => `записей: ${num(count)}`,
    indexAt: (tick) => `рассчитан на тике${NBSP}${tick}`,
    thresholds: 'Пороги — настройка демонстрации',
    marks: 'Обозначения на схеме',
    // What the legend of the compact layout leaves out, in words.
    marksCompact: [
      'кольцо вокруг метки — работник в опасной зоне',
      'стрелка у метки — работник идёт к выходу',
      '×3 у метки — группа работников на одном отрезке выработки',
      'линия со стрелками — расчётный маршрут (модель) выбранного объекта или участка инцидента',
      'круг с чертой — новый вход запрещён моделью',
    ],
    otherCodes: 'Остальные коды — при выборе объекта, в плане горизонта и на вкладке «Список»',
  },
  conditions: {
    title: 'Условия сценария (стенд)',
    subtitle: 'что происходит с шахтой',
    closeWorking: 'Закрыть выработку',
    sensorLost: 'Потерять связь с датчиком',
    instability: 'Рост нестабильности',
    choose: 'выберите…',
    none: 'нет активных',
    active: 'Активные условия',
    presets: 'Сценарии с новым прогоном',
    set: 'Задать',
    presetAt: (seconds) => `в ${modelTime(seconds)} модельного времени`,
    undoNote: 'Отмена условия не возвращает людей и не возобновляет работу участка',
    undo: {working_closed: 'Открыть', sensor_lost: 'Вернуть', instability: 'Остановить'},
  },
  actions: {
    title: 'Действия диспетчера',
    subtitle: 'что решает диспетчер',
    zone: 'Участок',
    stop: 'Остановить участок',
    withdraw: 'Вывести персонал участка',
    resume: 'Возобновить работу',
    resumeNote: 'Возобновление работы не возвращает вышедших людей',
    unavailable: 'Недоступно',
  },
  reset: {
    title: 'Прогон',
    button: 'Полный сброс прогона',
    hint: 'с подтверждением',
    dialogTitle: 'Начать новый прогон?',
    dialogText: (run) => `Текущий прогон ${run} будет завершён с пометкой «прерван сбросом» и останется в сравнении`,
    presetDialogTitle: 'Запустить сценарий с новым прогоном?',
    presetDialogText: (run, preset) => `Текущий прогон ${run} будет прерван. Новый прогон начнётся со сценария «${preset}»`,
    confirm: 'Начать новый прогон',
    cancel: 'Отмена',
  },
  pending: {
    title: 'Отправленные команды',
    retry: 'Повторить с тем же идентификатором',
    dismiss: 'Снять ожидание',
    close: 'Закрыть сообщение',
    attempts: (count) => `попыток: ${num(count)}`,
  },
  decision: {
    title: 'Решение',
    noIncident: 'Инцидентов нет. Варианты не предложены',
    noData: 'Нет данных об инциденте и вариантах',
    forecastFor: (seconds) => `Прогноз модели на ${num(seconds)} секунд для заданного сценария`,
    forecastTick: (tick) => `рассчитан на тике${NBSP}${tick}`,
    notPublished: 'Прогноз не опубликован',
    qualityNotPublished: 'полнота прогноза не опубликована',
    forecast: 'прогноз модели',
    actual: 'факт прогона',
    execute: 'Запустить вариант',
    chosen: 'выбран',
    allOutNo: 'не все вышли',
    noLastOut: 'нет: не все вышли',
    nobodyLeft: 'Ни один вариант модели не выводит этих работников',
    noPath: (codes) => `В графе модели нет открытого пути до выхода для ${codes}. Модель не рассчитывает, как выводить этих работников`,
    incomplete: (count) => `Вывод не завершён: ${counted(count, FORMS.worker)} без расчётного маршрута. Это за пределами того, что решает модель`,
    sameGroup: 'Показатели всех вариантов считаются для одной группы: все, кто был под землёй в момент решения',
    downtimeNote: 'суммарный простой участков, не длительность прогона',
    stopKeepsPause: 'Остановка участка не снимает паузу: выберите вывод или наблюдение',
    metric: 'Показатель',
    atEnd: 'на конец расчёта',
    choose: 'Выберите вариант в заголовке таблицы',
    zones: 'участки',
    allZones: 'все участки',
    sharedKey: 'общий для всех вариантов',
    keysDiffer: (keys) => `У вариантов нет общего ключа сравнения (${keys}). Их показатели нельзя сравнивать между собой`,
    keyNotPublished: 'не опубликован',
    confirmTitle: 'Запустить вариант?',
    confirmText: (option, scope) => `${option}. Участки: ${scope}. Модель применит вариант и снимет паузу`,
    factOf: (option) => `Факт прогона: ${option}`,
    tick: (tick) => `тик${NBSP}${tick}`,
  },
  journal: {
    title: 'Журнал событий',
    order: 'модельное время, новые сверху',
    empty: 'Событий нет',
    gap: (from, to) => `Пропущено ${counted(to - from + 1, FORMS.event)}: №${NBSP}${from === to ? from : `${from}–${to}`}`,
    preset: 'сценарий',
    command: 'команда',
    otherRun: 'другой прогон',
  },
  runs: {
    title: 'Завершённые прогоны',
    limit: `Показаны последние ${RUNS_LIMIT} завершённых прогонов`,
    empty: 'Завершённых прогонов нет',
    loading: 'Архив прогонов читается',
    error: 'Архив прогонов не прочитан',
    run: 'Прогон',
    series: 'Данные',
    comparison: (count, key) => `Сравнение: ${count} с ключом ${key}`,
    single: (key) => `Ключ сравнения ${key}: нет сравнимых прогонов`,
    noKey: 'Ключ сравнения не опубликован',
    alone: 'нет сравнимых прогонов',
    incomparable: (reason) => `несравним: ${reason}`,
    interrupted: 'итог неполный, в сравнение не входит',
    unclassified: 'итог не классифицирован, в сравнение не входит',
  },
  dialog: {confirm: 'Подтвердить', cancel: 'Отмена'},
};
