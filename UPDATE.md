# Обновление бота — применение исправления контейнера

## Что было исправлено

В `docker-compose.yml` добавлено `container_name: trading-bot`.  
Без этого поля Docker Compose назначает контейнеру автоматическое имя вроде `life-is_a_joke-bot-1`,
из-за чего `docker exec -it trading-bot …` завершается ошибкой:

```
Error response from daemon: No such container: trading-bot
```

---

## Команды для обновления сервера

Выполните на сервере от имени root (из директории `/opt/trading-bot`):

```bash
cd /opt/trading-bot

# 1. Получить изменения из ветки с исправлением
git fetch origin
git stash push -u                      # сохранить локальные правки (если есть)
git checkout copilot/fix-bot-error-and-update-scripts
git pull origin copilot/fix-bot-error-and-update-scripts

# 2. Пересобрать и перезапустить стек
docker compose down
docker compose up -d --build

# 3. Проверить, что контейнер запустился с правильным именем
docker ps --format "table {{.Names}}\t{{.Status}}"
# Ожидаемый вывод: trading-bot   Up N seconds
```

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
# Логи контейнера (Docker Compose)
docker compose logs -f trading-bot

# Фильтр по обучению
docker compose logs trading-bot | grep -E "🎓|📥|✅|❌|epoch|ERROR"
```
