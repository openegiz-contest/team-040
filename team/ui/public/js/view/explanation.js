// Read-only explanations of published forecasts. No ranking or routing in the UI.
import {incidentOf, labelOf, thingsOfKind} from '../model.js';

const number = (v) => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const list = (v) => Array.isArray(v) ? v : [];
const format = (v) => new Intl.NumberFormat('ru', {maximumFractionDigits: 1}).format(v);
const names = {observe: 'Наблюдать', stop_withdraw_zone: 'Локальный вывод', withdraw_all: 'Вывести всех'};

export function optionExplanation(model, option, options) {
  const v = option.values;
  const kind = option.attrs.option_kind;
  const scope = list(v.scope).filter(x => typeof x === 'string');
  const places = scope.map(x => labelOf(model, x)).join(', ');
  let short = 'Объяснение этого действия пока не задано.';
  if (kind === 'observe') short = 'Приказ о выводе не отдаётся; ограничения модели продолжают действовать.';
  if (kind === 'stop_withdraw_zone') short = scope.length
    ? `Остановка и вывод: ${places}.` : 'Для локального вывода модель не указала участков.';
  if (kind === 'withdraw_all') short = 'Приказ охватывает всю смену; доступность путей не меняется.';

  const reasons = [];
  const incident = incidentOf(model)?.values;
  // Do not explain an old forecast using a new incident.
  if (incident && typeof v.decision_id === 'string' && incident.decision_id === v.decision_id) {
    const codes = new Set();
    for (const zone of scope) for (const reason of list(incident.scope_reasons?.[zone])) {
      if (reason.reason === 'zone_state') for (const cause of list(reason.causes)) {
        if (typeof cause === 'string') codes.add(cause.split(':')[0]);
      }
      else if (reason.reason === 'current_working_closed' || reason.reason === 'reference_route_closed') codes.add('closure');
    }
    if (codes.has('hazard')) reasons.push('В затронутом участке зафиксирован сигнал опасности.');
    if (codes.has('data_lost')) reasons.push('Данные участка потеряны: отсутствие измерений не означает безопасность.');
    if (codes.has('closure')) reasons.push('Перекрытие затрагивает положение работников или их исходный путь к выходу.');
    if (kind === 'stop_withdraw_zone' && scope.length) {
      const outside = thingsOfKind(model, 'zone').filter(z => !scope.includes(z.name));
      if (outside.length) reasons.push(`Приказ не затрагивает: ${outside.map(z => z.label).join(', ')}.`);
    }
  }
  if (number(v.forecast_no_route) && v.forecast_no_route > 0)
    reasons.push(`По прогнозу без маршрута: ${format(v.forecast_no_route)} чел. Сам приказ не создаёт доступный путь.`);
  if (!reasons.length) reasons.push('Дополнительные причины для этого варианта не опубликованы.');

  const peer = options.find(o => o.attrs.option_kind === (kind === 'stop_withdraw_zone' ? 'observe' : 'stop_withdraw_zone'));
  const fields = ['decision_id', 'comparison_key', 'forecast_tick', 'forecast_horizon_s'];
  const comparable = peer && fields.every(k => v[k] !== undefined && v[k] === peer.values[k])
    && typeof v.decision_id === 'string' && v.decision_id.length > 0
    && typeof v.comparison_key === 'string' && v.comparison_key.length > 0
    && number(v.forecast_tick) && number(v.forecast_horizon_s) && v.forecast_horizon_s > 0
    && v.forecast_quality === 'full' && peer.values.forecast_quality === 'full';
  let difference = 'Разница не рассчитана: нужны полные прогнозы из одного состояния и на один срок.';
  if (comparable) {
    const parts = [];
    for (const [metric, label, unit, divisor] of [
      ['out', 'вышедших', 'чел.', 1],
      ['danger_exposure_person_s', 'пребывание в опасной зоне', 'чел.·мин', 60],
      ['production_lost_t', 'недовывоз', 'т', 1],
    ]) {
      const a = v['forecast_' + metric], b = peer.values['forecast_' + metric];
      if (!number(a) || !number(b)) continue;
      const delta = (a - b) / divisor;
      const amount = Math.abs(delta);
      parts.push(delta === 0 ? `${label} — без изменений` : `${label} — на ${amount < 0.1 ? 'менее 0,1' : format(amount)} ${unit} ${delta > 0 ? 'больше' : 'меньше'}`);
    }
    if (parts.length) difference = `Относительно «${names[peer.attrs.option_kind]}»: ${parts.join('; ')}.`;
  }
  return {short, reasons: reasons.join(' '), difference};
}
