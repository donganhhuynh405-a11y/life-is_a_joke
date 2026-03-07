# Обновление бота — применение исправления контейнера

## Что было исправлено

### 1. `container_name: trading-bot` в `docker-compose.yml`

Без этого поля Docker Compose автоматически назначает контейнеру имя вроде
`trading-bot_bot_1` (v1) или `trading-bot-bot-1` (v2), из-за чего `docker exec -it trading-bot …` завершается ошибкой:

```
Error response from daemon: No such container: trading-bot
```

### 2. CPU-only PyTorch в `Dockerfile`

`pip install torch` на Linux по умолчанию скачивает wheel с CUDA-библиотеками
(nvidia-cublas-cu12, nvidia-cudnn-cu12, nvidia-nccl-cu12 и др.) — это **~2.5 ГБ дополнительно**.
На сервере без видеокарты эти библиотеки не нужны, и Docker build завершался ошибкой:

```
ERROR: Could not install packages due to an OSError: [Errno 28] No space left on device
```

Теперь `Dockerfile` устанавливает torch из CPU-only wheel-индекса PyTorch **до** основного
`pip install -r requirements.txt`. Поскольку ограничение `torch>=2.6.0` уже выполнено,
pip не перекачивает CUDA-вариант.

---

## Требования к дисковому пространству

| Вариант torch | Размер (installed) |
|---|---|
| PyPI (CUDA, по умолчанию) | ~2.5 ГБ |
| CPU-only (после исправления) | ~200 МБ |

Минимум свободного места для сборки образа: **3 ГБ** (CPU-only torch).

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
