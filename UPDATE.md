# Обновление бота — применение исправления контейнера

## Что было исправлено

### 1. `container_name: trading-bot` в `docker-compose.yml`

Без этого поля Docker Compose автоматически назначает контейнеру имя вроде
`trading-bot_bot_1` (v1) или `trading-bot-bot-1` (v2), из-за чего `docker exec -it trading-bot …` завершается ошибкой:

```
Error response from daemon: No such container: trading-bot
```

### 2. CPU-only PyTorch и TensorFlow CPU в `Dockerfile` / `requirements.txt`

`pip install torch` на Linux по умолчанию скачивает wheel с CUDA-библиотеками
(nvidia-cublas-cu12, nvidia-cudnn-cu12, nvidia-nccl-cu12, triton и др.) — это **~2.5 ГБ дополнительно**.

`pip install tensorflow` на Linux начиная с версии 2.15 устанавливает `cuda-bindings` и
`cuda-pathfinder` — это ещё **~150–300 МБ** даже на CPU-сервере.

На сервере без видеокарты все эти библиотеки не нужны, и Docker build завершался ошибкой:

```
ERROR: Could not install packages due to an OSError: [Errno 28] No space left on device
```

**Исправления:**

- `requirements.txt`: заменено `tensorflow>=2.15.0` → `tensorflow-cpu>=2.15.0`  
  (CPU-only вариант TensorFlow, не устанавливает CUDA-зависимости)
- `Dockerfile`: torch устанавливается из CPU-only wheel-индекса PyTorch **перед** основным
  `pip install -r requirements.txt`. Поскольку ограничение `torch>=2.6.0` уже выполнено,
  pip не перекачивает CUDA-вариант. Аналогично для `tensorflow-cpu`.

### 3. Неверный путь `prometheus.yml` в `docker-compose.yml`

Сервис Prometheus использовал монтирование:

```yaml
- ./prometheus.yml:/etc/prometheus/prometheus.yml
```

Файл `prometheus.yml` **не существует в корне** репозитория — он находится в
`deployment/monitoring/prometheus.yml`. Docker Compose, не найдя файл по указанному пути,
создавал вместо него **папку**, из-за чего монтирование завершалось ошибкой:

```
mount ... not a directory: Are you trying to mount a directory onto a file (or vice-versa)?
```

**Исправление:** путь обновлён до `./deployment/monitoring/prometheus.yml`.

### 4. Конфликт порта Redis (6379) в `docker-compose.yml`

Сервис Redis публиковал порт `6379:6379` на хосте. Если на сервере уже запущен другой
Redis (или осталась предыдущая версия контейнера), это завершалось ошибкой:

```
failed to bind host port for 0.0.0.0:6379: address already in use
```

Публикация порта на хосте **не нужна**: торговый бот подключается к Redis через внутреннюю
сеть Docker (`redis://redis:6379/0`). Внешний доступ к Redis также небезопасен.

**Исправление:** блок `ports: ["6379:6379"]` удалён из сервиса `redis`.

### 5. Контейнер `trading-bot` в цикле перезапуска после старта стека

После успешного запуска всех контейнеров сам бот немедленно завершался с ошибкой и Docker
перезапускал его снова и снова. Причин несколько.

#### 5а. Состояние гонки: PostgreSQL не успевает инициализироваться

`depends_on: [redis, postgres]` гарантирует только **запуск контейнера**, но не готовность
сервиса внутри. PostgreSQL требует нескольких секунд на инициализацию хранилища и начало приёма
соединений. Бот стартовал раньше и падал с ошибкой подключения.

**Исправление:** добавлены `healthcheck` для `postgres` (`pg_isready`) и `redis`
(`redis-cli ping`); в `depends_on` для сервиса `bot` теперь используется
`condition: service_healthy`, что гарантирует готовность БД перед стартом бота.

#### 5б. Docker HEALTHCHECK завершался до инициализации бота

`--start-period=5s` было слишком коротким: за 5 секунд бот не успевал подключиться к бирже
и базе данных. Docker начинал считать контейнер нездоровым раньше времени.

**Исправление:** `--start-period` увеличен до `60s`.

#### 5в. Port 8001 (Prometheus) никогда не открывался

Dockerfile проверяет порт 8001 командой `socket.create_connection`, но класс `HealthMonitor`
(который запускает Prometheus HTTP-сервер на порту 8001) никогда не инициализировался и не
запускался из `bot.py`.

**Исправление:** в `TradingBot.__init__` добавлена инициализация `HealthMonitor`, а в
`TradingBot.start()` добавлен вызов `_start_health_monitor_background()` — аналогично
тому, как уже запускаются агрегатор новостей и ML-обучение в фоновых потоках.

#### 5г. Отсутствие файла `.env` — нет API-ключей → немедленный крах

Файл `.env` находится в `.gitignore` и не копируется в образ командой `COPY . .`. Если
пользователь не создал `.env` вручную перед первым запуском, контейнер стартует без
каких-либо API-ключей биржи. В этом случае:

1. `Config.validate()` возвращает `False` (API-ключи пусты)
2. `TradingBot.__init__` выбрасывает `ValueError("Invalid configuration")`
3. `main()` перехватывает исключение и вызывает `sys.exit(1)`
4. Docker немедленно перезапускает контейнер — получается бесконечный цикл

**Исправление (четыре изменения):**

- **`src/core/config.py`** — `validate()` больше не требует API-ключей, когда
  `TRADING_ENABLED=false`. Бот может работать в режиме мониторинга без подключения к бирже.

- **`src/core/bot.py`** — подключение к бирже теперь необязательно, когда
  `TRADING_ENABLED=false`. Если соединение не устанавливается, бот переходит в режим
  только-мониторинга, а не падает. Аналогично, вызов `get_account()` при старте защищён
  обработкой исключений при отключённом трейдинге.

- **`src/main.py`** — перед `sys.exit(1)` добавлена задержка 30 секунд. Это даёт Docker
  время для применения политики перезапуска с экспоненциальной задержкой, а не мгновенный
  перезапуск, который исчерпывал лимит попыток.

- **`docker-compose.yml`** — добавлена переменная `TRADING_ENABLED=${TRADING_ENABLED:-false}`
  как безопасное значение по умолчанию для сервиса `bot`. Если в `.env` не указано иное,
  бот стартует без торговли. Это позволяет запустить стек и проверить его работу ещё до
  настройки реальных API-ключей.

---

## Требования к дисковому пространству

| Компонент | До исправления (CUDA) | После исправления (CPU) |
|---|---|---|
| torch | ~2.5 ГБ | ~200 МБ |
| tensorflow | ~400 МБ + CUDA-stubs | ~200 МБ |
| **Итого экономия** | | **~2.5 ГБ** |

Минимум свободного места для сборки образа: **3 ГБ**.

Проверить место на диске:
```bash
df -h /var/lib/docker
```

Очистить кэш Docker при нехватке места:
```bash
docker system prune -f
```

---

## Определение версии Docker Compose

На сервере используется **Docker Compose v1** (отдельный бинарник `docker-compose`).  
Команда `docker compose` (без дефиса) — это плагин Docker Compose **v2**, которого на сервере нет.

```bash
# Проверить, какая версия установлена
docker-compose --version   # v1: "docker-compose version 1.x.x"
docker compose version     # v2: "Docker Compose version v2.x.x"
```

---

## Команды для обновления сервера

Выполните на сервере от имени root (из директории `/opt/trading-bot`):

```bash
cd /opt/trading-bot

# 0. Убедиться, что достаточно места на диске
df -h /var/lib/docker
# Если мало — очистить кэш Docker
docker system prune -f

# 1. Получить изменения из ветки с исправлением
git fetch origin
git stash push -u                      # сохранить локальные правки (если есть)
git checkout copilot/fix-bot-error-and-update-scripts
git pull origin copilot/fix-bot-error-and-update-scripts

# 2. Пересобрать и перезапустить стек (Docker Compose v1)
docker-compose down
docker-compose up -d --build

# 3. Проверить, что контейнер запустился с правильным именем
docker ps --format "table {{.Names}}\t{{.Status}}"
# Ожидаемый вывод: trading-bot   Up N seconds
```

> **Если сейчас контейнер называется `trading-bot_bot_1`** (старое автоматическое имя), то
> после `docker-compose down && docker-compose up -d --build` он будет пересоздан с именем
> `trading-bot` благодаря `container_name: trading-bot` в `docker-compose.yml`.

### Быстрая проверка после запуска

```bash
# Войти в контейнер
docker exec -it trading-bot bash

# Запустить обучение
docker exec -it trading-bot python scripts/run_training.py

# Принудительное переобучение
docker exec -it trading-bot python scripts/run_training.py --force

# Следить за прогрессом (в отдельном терминале)
docker exec -it trading-bot python scripts/watch_training.py
```

---

## Альтернатива — скрипт обновления (для systemd-установки)

Если бот запущен через systemd (а не Docker Compose), используйте:

```bash
cd /opt/trading-bot
sudo bash scripts/update_bot.sh --branch copilot/fix-bot-error-and-update-scripts
```

Скрипт автоматически:
- сохранит локальные изменения (`git stash`),
- переключится на нужную ветку и выполнит `git pull`,
- обновит зависимости Python,
- перезапустит сервис `trading-bot`.

---

## Просмотр логов

```bash
# Логи через docker-compose (используется имя сервиса — bot, не имя контейнера)
docker-compose logs -f bot

# Или напрямую через docker (используется имя контейнера — trading-bot)
docker logs -f trading-bot

# Фильтр по обучению
docker logs trading-bot 2>&1 | grep -E "🎓|📥|✅|❌|epoch|ERROR"
```
