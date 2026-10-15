# Team 040 — безопасность подземного рудника

Цифровой двойник условного рудника на OpenEgiz. Диспетчер сравнивает наблюдение,
вывод участка и вывод всей смены при изменении опасности и доступности проходов.
Данные синтетические; физическое обрушение массива не предсказывается.

Замысел команды, статус проверки и ограничения — в [SUBMISSION.md](SUBMISSION.md).

## Running

Requirements (Docker, `make`, Windows/WSL2 setup) are in [OPENEGIZ.md](OPENEGIZ.md) / [OPENEGIZ.ru.md](OPENEGIZ.ru.md).

```bash
sudo apt update && sudo apt install -y git make curl  # prerequisites on clean Ubuntu
make up            # OpenEgiz + симулятор команды + интерфейс
```

На Windows запускайте через WSL2 при работающем Docker Desktop. Требуется не менее
6 ГиБ памяти Docker. Пароли генерируются автоматически в `deploy/compose/.env`;
не удаляйте этот файл отдельно от данных. Первое скачивание образов зависит от сети.
Example Mine запускать не требуется. Внешние API-ключи и Blender для запуска не нужны.

Для проверки перед сдачей выделяйте Docker 8 CPU. При лимите 4 CPU в изолированной
проверке были задержки MQTT/Ditto и таймауты интерфейса; такое ограничение не
считается проверенной конфигурацией команды. Подробный протокол:
[чистый запуск 15 октября](team/research/clean-start.md).

`make up` завершает запуск только после получения полного актуального снимка
шахты через прокси и трёх последовательно растущих номеров публикации. Если
платформа отвечает, но телеметрия не доходит, запуск завершится с понятной ошибкой
готовности Team 040; смотрите `make logs S=team-simulator` и `make logs S=connectivity`.

## What to open

- Grafana: the address and login are printed by `make up`.
- Интерфейс диспетчера: **http://127.0.0.1:8088/**, пароль вводить не требуется.

Если порт занят, задайте `TEAM_UI_PORT=8089` в `deploy/compose/.env` и повторите
`make up`. Для Python smoke-тестов укажите `TEAM_UI_URL=http://127.0.0.1:8089`.
На текущей машине разработки используется 8089, чтобы не занимать порт отдельного
сервера разработки интерфейса.

Выберите пресет роста нестабильности. В модельную секунду 60 прогон остановится
для сравнения вариантов. Выберите вывод всей смены и наблюдайте движение людей.
После горизонта 900 модельных секунд результат попадёт в архив. При x10 это около
90 настенных секунд без учёта нагрузки и задержек. Пресет перекрытого выхода с
участка показывает неполный вывод: `all_out=false`, время выхода всех отсутствует.

Отмена условия не возвращает людей на рабочие места. Полный сброс начинает новый
прогон. После ручного изменения условий факт помечается несравнимым с прогнозом.

```sh
python3 -m unittest team.sim.test_model team.gateway.test_gateway -v
python3 -m unittest team.sim.test_journal team.sim.test_parameters -v
python3 -m team.sim.sensitivity
python3 -m team.sim.comparison --check team/research/comparison.json
python3 -m unittest team.sim.test_comparison -v
python3 -m unittest team.sim.test_scope -v
make smoke
python3 -m team.smoke
python3 -m team.restart_smoke
python3 -m team.edge_smoke
python3 -m team.scope_smoke
make logs S=team-simulator
make down
```

`team.smoke` проверяет действующую платформу, создаёт новый синтетический прогон
команды и исполняет вывод; занимает около двух минут. `make down` сохраняет данные,
а `make clean` удаляет данные всей платформы. Автономные Python-команды на Windows
можно выполнять через `py -3`.

Таблица 12 автономных прогонов и объяснения:
[сравнение действий](team/research/comparison.md). При перекрытии локальный вывод
затрагивает участки работников, чьи справочные маршруты или текущие выработки
перекрыты; общий путь может затронуть несколько участков.

`team.restart_smoke` после полного smoke перезапускает только симулятор команды и
проверяет сохранение прогона и дедупликацию повторного reset. Дополнительные
проверки: `python3 -m team.browser_smoke` (нужен Chrome) и
`python3 -m team.history_smoke` (нужен пакет из `team/sim/requirements.txt`).

Цепочка состояния: симулятор → MQTT → Ditto → прокси → UI. Команда идёт обратно
через live-сообщение Ditto и MQTT; HTTP 202 не означает исполнения. Подробности
расчётов — в [team/sim/README.md](team/sim/README.md).

## Repository contents

| Path | Contents |
|---|---|
| `team/` | Directory for the Team's code. Using it is optional: any part may be changed, including the platform core |
| `SUBMISSION.md` | Description of the Submission: **required** |
| `presentation.pdf` | Presentation: **required**, in the repository root |
| `AGENTS.md`, `CLAUDE.md` | Instructions for your AI agents (Codex, Claude Code and others read them automatically) |
| `examples/mine/` | The Example Mine: shows how a digital mine is built on OpenEgiz. It is not a basis for the Submission |
| `OPENEGIZ.md`, `OPENEGIZ.ru.md` | Documentation of the OpenEgiz platform v1.0.4 |

The Submission is the `main` branch at the moment of the Freeze; other branches are not evaluated.

## License

The Submission is distributed under the MIT license, see [LICENSE](LICENSE). Copyright belongs to the Team: add the line `Copyright (c) 2026 <Team members>` to `LICENSE`.

---

Platform: [aleka07/openegiz](https://github.com/aleka07/openegiz). If the platform was useful to you, support the project with a star on GitHub.
