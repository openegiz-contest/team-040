// Every user-visible string of the 3D stage (view/stage.js and js/scene3d/).
// Pure: no DOM. Codes of the platform are named with the vocabularies and
// formatters of text.js, so the stage and the other views say the same thing.

import {counted, FORMS, num} from './text.js';

/** «Участок Г» -> «Г»: the zone named after «участка» (any other label is kept whole). */
const zoneShort = (label) => String(label).replace(/^Участок\s+/u, '');

export const STAGE = {
  region: 'Сцена рудника',
  modeGroup: 'Вид сцены',
  mode: {'3d': '3D', scheme: 'Схема'},
  modeHint: {'3d': 'Трёхмерная модель рудника', scheme: 'Схема в SVG: работает без графического ускорителя'},
  quality: 'Качество',
  qualityName: {high: 'высокое', low: 'облегчённое'},
  qualityAuto: (name) => `${name} (авто)`,
  qualityHint: 'Облегчённое: без сглаживания и ламп, проще материалы',
  explode: 'Разнести',
  explodeHint: 'Разнести горизонты: расстояние между плитами (клавиша E)',
  explodeToggle: 'Разнести или сблизить горизонты (клавиша E)',
  overview: 'Общий вид',
  levels: 'Горизонт',
  levelPick: 'Горизонт: все',
  settings: 'Настройки',
  keysTitle: 'Управление камерой',
  keyList: [
    ['мышь', 'перетаскивание — повернуть, с правой кнопкой или Shift — сдвинуть, колесо — приблизить'],
    ['← → ↑ ↓', 'повернуть'],
    ['Shift + стрелки', 'сдвинуть'],
    ['+ / −', 'приблизить, отдалить'],
    ['Home', 'общий вид'],
    ['PageUp / PageDown', 'следующий, предыдущий горизонт'],
    ['E', 'разнести или сблизить горизонты'],
    ['Esc', 'снять выбор'],
    ['двойной щелчок', 'показать объект крупно'],
    ['Tab', 'подписи объектов; Enter выбирает'],
  ],
  /** Art mode (one orthographic view of the illustrated mine): pan and zoom only. */
  keyListArt: [
    ['мышь', 'перетаскивание — сдвинуть, колесо — приблизить к указателю'],
    ['два пальца', 'развести — приблизить, вести — сдвинуть'],
    ['← → ↑ ↓', 'сдвинуть'],
    ['+ / −', 'приблизить, отдалить (до ×4)'],
    ['Home', 'общий вид'],
    ['PageUp / PageDown', 'следующий, предыдущий горизонт'],
    ['Esc', 'снять выбор'],
    ['двойной щелчок', 'показать объект крупно'],
    ['Tab', 'подписи объектов; Enter выбирает'],
  ],
  loading: '3D-модель загружается…',
  notice: {
    'no-webgl': 'WebGL 2 недоступен в этом браузере — показана схема',
    slow: '3D на этом устройстве работает медленно — показана схема',
    'context-lost': 'Графический контекст потерян — показана схема. 3D вернётся, когда браузер его восстановит',
    'load-failed': '3D-модель не загрузилась — показана схема',
  },
  backTo3d: 'Вернуть 3D',
  retry3d: 'Попробовать 3D снова',
};

export const SCENE = {
  canvas: (parts) => `Трёхмерная модель рудника. ${parts.join('. ')}. Камера: стрелки, Shift и стрелки, плюс и минус, Home. Подписи объектов — кнопки, полный перечень — вкладка «Список»`,
  canvasArt: (parts) => `Рисованный разрез рудника. ${parts.join('. ')}. Камера: стрелки — сдвиг, плюс и минус — приближение, Home — общий вид. Подписи объектов — кнопки, полный перечень — вкладка «Список»`,
  levelsCount: (count) => `Горизонтов: ${num(count)}`,
  workingsCount: (count) => `выработок: ${num(count)}`,
  workersShown: (count) => `работников на модели: ${num(count)} (по опубликованным положениям)`,
  inDanger: (count) => `в опасных зонах: ${num(count)}`,
  noRoute: (count) => `без расчётного маршрута: ${num(count)}`,
  problems: (count) => `объектов в особом состоянии: ${num(count)}`,
  noState: 'состояние не получено',
  north: 'С',
  scaleAt: 'у центра вида',
  vertical: (factor) => (Math.abs(factor - 1) < 0.05 ? 'вертикаль в масштабе плана' : `вертикаль ×${num(factor, 1)}`),
  notToScale: 'толщина плит и ширина выработок условные',
  /** The rock around the slabs (scene3d/environment.js) is decoration, not data. */
  massifNote: 'массив — оформление',
  oldData: 'Показаны последние полученные данные, движение остановлено',
  grouped: (count) => `×${num(count)}`,
  /** The published number of people of a zone, after its state on its tag. */
  people: (count) => `${num(count)} чел.`,
  group: (count) => `группа: ${counted(count, FORMS.worker)} на одном отрезке`,
  inDangerZone: 'в опасной зоне',
  noSensors: 'без датчиков',
  lastKnownShort: 'последнее известное: опасно',
  workers: (count) => `под землёй на модели: ${num(count)}`,
  between: (kind, code) => `${kind} ${code}`,
  levelsSpan: (upper, lower) => `${upper} — ${lower}`,
  /** The tooltip of a zone's loader: the zone's published work state; the machine itself is not in the model. */
  loaderTitle: (zone, words) => `Символ работы участка ${zoneShort(zone)}: ${words} (данные модели)`,
  loaderNote: (factor) => `Техника в модели не описана · ПДМ показана увеличенной ×${num(factor, 1)}`,
  loaderUnknown: 'работа участка не опубликована',
  /** The sign of a loader whose zone has no published work state. */
  loaderQuestion: 'работа: ?',
  decorNote: (factor, people) => `ПДМ — символ работы участка, ×${num(factor, 1)}${people ? `; фигуры людей ×${num(people, 1)}` : ''}`,
  /** People out at an exit, after its name on its label. */
  exitOut: (count) => `вышли ${num(count)}`,
  noPosition: (codes) => `Без опубликованного положения: ${codes}`,
  /** A loader of the model (equipment twin): «ПДМ-Г · везёт руду · участок Г (данные модели)». */
  machineTitle: (code, words, zone) => `${code} · ${words}${zone ? ` · участок ${zoneShort(zone)}` : ''} (данные модели)`,
  machineStill: {parked: 'стоит', stopped: 'остановлена'},
  machineWorking: 'работает',
  machineUnknown: 'состояние не опубликовано',
  machineLoad: (loaded) => (loaded ? 'в ковше руда' : 'ковш пуст'),
  machineNote: (factor) => `Положение и состояние — по публикации модели · ПДМ показана увеличенной ×${num(factor, 1)}`,
  /** The sign of a loader that does not work: stopped with its zone, or without a published state. */
  machineSign: {stopped: 'остановлена', unknown: 'ПДМ: ?'},
  /** The notes of the illustrated mine (art mode with the art's GLB): what is to scale and what is decoration. */
  artVertical: (factor) => `вертикаль ×${num(factor, 1)}; выработки нарисованы шире настоящих`,
  artDecor: 'порода, крепь, лампы, оборудование, самосвал и буровая — оформление',
  artFigures: (machine, people) => `машины ×${num(machine, 1)} настоящих, фигуры людей ×${num(people, 1)}; ПДМ показывает только работу своего участка`,
  decorEquipment: (factor, people) => `ПДМ — по данным модели, ×${num(factor, 1)}; фигуры людей ×${num(people, 1)}`,
};
