# SUBMISSION

<!-- Fill in every section. The AI Jury studies this file together with the code, the Build Report, the presentation and the Stand's interface. Accepted languages: English, Kazakh, Russian. These hint comments may be deleted. -->

## Concept

Первоначальные ответы команды от 13 октября 2026 года, записанные до разработки собственного решения. Замысел уточняется; незаполненные решения ниже не считаются выбранными командой.

**Enterprise:** Подземная рудная шахта, например медная. Основной акцент — устойчивость выработок и доступность выходов. Конкретное реальное предприятие пока не выбрано.

**Users:** Диспетчер смены: видит опасные участки и людей, сравнивает варианты остановки работ и вывода персонала.

**Decision:** Помогать диспетчеру смены сравнивать варианты остановки работ и вывода персонала при опасности, в том числе при возможных обрушениях. Учитывать устойчивость выработок и доступность выходов.

**Why this choice:** Команда выбрала безопасность подземной шахты и хочет создать полезного для отрасли цифрового двойника с отличиями от существующих в Казахстане решений. Отсутствие аналогов пока не установлено и не заявляется как подтверждённый факт.

**Real or fictional:** «Пока что возьмём нереальные данные, а близкие, которые можно найти в открытых источниках». Планируются синтетические данные с обоснованием по открытым источникам. Конкретный реальный аналог шахты, числовые параметры и их источники пока не выбраны.

## Team

<!-- GitHub usernames of the Participants. Other personal data are not required: the repository becomes public after the Freeze (Rules, section 15). -->

| GitHub |
|---|
|  |

## Mine

Первое автономное расчётное ядро находится в `team/sim/`: условная сеть из 12
выработок на двух подземных горизонтах, два выхода, два рабочих участка, два
синтетических датчика и шесть условных работников. Топология одна для расчёта
маршрутов и атрибутов будущих двойников. Создание объектов в работающей платформе
пока не проверено.

<!-- Which part of a mining enterprise the Submission represents (open pit, underground mine, processing plant…), which objects are twins in OpenEgiz, how they are related, and where they are defined in the code. -->

## Modules and What-if Scenarios

<!-- Modules: functions on top of the twin, from the Mine Map or your own. What-if Scenarios: changes of an operating condition that can be run on the Stand without changing the code (close a road, stop equipment…). Only what works on the Stand is taken into account. -->

| Module or What-if Scenario | What it does | How to see it on the Stand | How to undo it (scenarios) |
|---|---|---|---|
|  |  |  |  |

## What works and what does not

На 13 октября 2026 года локально проверено расчётное ядро Python: маршруты,
движение, перекрытие прохода, потеря датчика, прогноз трёх действий из одного
состояния, исполнение выбранного действия, архив и сохранение команд после
перезапуска. Команда проверки: `python3 -m unittest team.sim.test_model -v`.
Автономный эксперимент: `python3 -m team.sim --preset p-instability --option withdraw_all`.

Модель формирует JSON двойников и конверты MQTT, но сетевой сервис публикации,
bootstrap, прокси интерфейса и экспорт истории ещё не реализованы. Сквозная
цепочка MQTT → Ditto → интерфейс не испытана: локальный Docker Engine недоступен.
Интерфейс разрабатывается отдельно и с моделью пока не соединён. Это состояние
разработки, а не заявление о готовом конкурсном стенде.

<!-- What has been verified, what is unfinished, which bugs are known. -->

## Data and Assumptions

Числа первой версии в `team/sim/topology.py` — выбранные настройки демонстрации,
не промышленные измерения и не нормативы. Их происхождение и ограничения
перечислены в `team/sim/README.md`. Обзор открытых источников в
`team/research/safety-sources.md` пока не является калибровкой этих параметров.

<!--
- Synthetic and real data.
- Sources of parameters: equipment data sheets, reference literature, industrial safety regulations, datasets.
- Datasets: source, license, how they are provided (in the repository or downloaded per the README).
Confidential data of organizations and personal data are prohibited.
-->

## Mine visualization

<!-- Address on the Stand, dashboard or scene; what it shows. -->

## Limitations

Нет физического прогноза обрушений. Синтетический индекс нестабильности не является
вероятностью аварии. Пока не моделируются пропускная способность путей, очереди,
уклон и усталость при движении, шахтные подъёмники, сейсмика и резервирование
датчиков. Расчёт не предназначен для принятия решений на действующей шахте.

## Presentation

`presentation.pdf` in the repository root. Video (optional): <link>

---

Platform: OpenEgiz v1.0.4.
