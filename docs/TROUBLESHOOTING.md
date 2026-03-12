# 🔧 РУКОВОДСТВО ПО УСТРАНЕНИЮ НЕПОЛАДОК

---

## 🆘 БЫСТРОЕ ИСПРАВЛЕНИЕ: status=203/EXEC (бот вообще не запускается)

Если в `journalctl` вы видите строку:

```
trading-bot.service: Main process exited, code=exited, status=203/EXEC
```

Это означает, что systemd **не может найти исполняемый файл Python** (обычно потому, что
виртуальное окружение не создано или использует имя `python` вместо `python3`).

### ⚡ Одна команда для исправления

```bash
sudo bash /opt/trading-bot/scripts/fix_exec_error.sh
```

Скрипт автоматически:
1. Диагностирует причину
2. Пересоздаёт виртуальное окружение
3. Устанавливает зависимости
4. Обновляет файл службы (заменяет `python` → `python3`)
5. Перезапускает сервис

### 🔧 Ручное исправление (если скрипт недоступен)

```bash
# 1. Остановить сервис
sudo systemctl stop trading-bot

# 2. Пересоздать виртуальное окружение
cd /opt/trading-bot
sudo python3 -m venv venv
sudo venv/bin/pip install --upgrade pip
sudo venv/bin/pip install -r requirements.txt

# 3. Исправить путь в файле службы (python → python3)
sudo sed -i 's|venv/bin/python |venv/bin/python3 |g' /etc/systemd/system/trading-bot.service
sudo systemctl daemon-reload

# 4. Исправить права доступа
sudo chown -R tradingbot:tradingbot /opt/trading-bot/venv

# 5. Запустить сервис
sudo systemctl start trading-bot
sudo systemctl status trading-bot
```

---

## 🆘 БЫСТРОЕ ИСПРАВЛЕНИЕ: `git pull` завершается с ошибкой "local changes"

Если `git pull` выдаёт:
```
error: Your local changes to the following files would be overwritten by merge:
Please commit your changes or stash them before you merge.
```

### ⚡ Исправление

```bash
# Сохранить локальные изменения в stash и обновить код
cd /opt/trading-bot
git stash push --include-untracked -m "backup before update $(date)"
git pull origin main   # или укажите нужную ветку вместо 'main'

# Затем перезапустить сервис
sudo systemctl restart trading-bot
```

Или используйте готовый скрипт обновления, который делает всё это автоматически:
```bash
sudo bash /opt/trading-bot/scripts/update_bot.sh --branch main
# Замените 'main' на нужную ветку, если вы работаете с другой веткой
```

---

## Ошибка: trading-bot.service: Failed with result 'exit-code'

Эта ошибка означает, что служба не смогла запуститься. Следуйте шагам ниже для диагностики и исправления.

---

## 🔍 ШАГ 1: Проверка логов

### 1.1 Посмотрите подробные логи systemd:
```bash
sudo journalctl -u trading-bot -n 100 --no-pager
```

### 1.2 Проверьте последние ошибки:
```bash
sudo journalctl -u trading-bot -p err --no-pager
```

### 1.3 Следите за логами в реальном времени:
```bash
sudo journalctl -u trading-bot -f
```

---

## 🛠️ ШАГ 2: Проверка основных требований

### 2.1 Проверьте, существует ли пользователь tradingbot:
```bash
id tradingbot
```

**Если ошибка "no such user":**
```bash
sudo useradd -r -s /bin/bash -d /opt/trading-bot tradingbot
```

### 2.2 Проверьте структуру каталогов:
```bash
ls -la /opt/trading-bot/
ls -la /etc/trading-bot/
ls -la /var/log/trading-bot/
ls -la /var/lib/trading-bot/
```

**Если каталоги отсутствуют, создайте их:**
```bash
sudo mkdir -p /opt/trading-bot
sudo mkdir -p /etc/trading-bot
sudo mkdir -p /var/log/trading-bot
sudo mkdir -p /var/lib/trading-bot
sudo chown -R tradingbot:tradingbot /opt/trading-bot
sudo chown -R tradingbot:tradingbot /etc/trading-bot
sudo chown -R tradingbot:tradingbot /var/log/trading-bot
sudo chown -R tradingbot:tradingbot /var/lib/trading-bot
```

### 2.3 Проверьте наличие файла .env:
```bash
sudo ls -la /etc/trading-bot/.env
```

**Если файл отсутствует:**
```bash
sudo cp .env.template /etc/trading-bot/.env
sudo chown tradingbot:tradingbot /etc/trading-bot/.env
sudo chmod 600 /etc/trading-bot/.env
```

### 2.4 Проверьте виртуальное окружение Python:
```bash
ls -la /opt/trading-bot/venv/bin/python3
```

**Если отсутствует:**
```bash
cd /opt/trading-bot
sudo python3 -m venv venv
sudo chown -R tradingbot:tradingbot venv
```

### 2.5 Установите зависимости:
```bash
cd /opt/trading-bot
sudo -u tradingbot venv/bin/pip install --upgrade pip
sudo -u tradingbot venv/bin/pip install -r requirements.txt
```

---

## ✅ ШАГ 3: Ручной запуск для диагностики

### 3.1 Переключитесь на пользователя tradingbot и запустите вручную:
```bash
sudo su - tradingbot
cd /opt/trading-bot
source venv/bin/activate
python src/main.py
```

Это покажет точную ошибку!

### 3.2 Распространенные ошибки и решения:

#### ❌ ModuleNotFoundError: No module named 'binance'
**Решение:**
```bash
sudo -u tradingbot /opt/trading-bot/venv/bin/pip install python-binance ccxt pandas numpy python-dotenv fastapi uvicorn
```

#### ❌ PermissionError: [Errno 13] Permission denied: '/var/log/trading-bot'
**Решение:**
```bash
sudo chown -R tradingbot:tradingbot /var/log/trading-bot
sudo chmod 755 /var/log/trading-bot
```

#### ❌ FileNotFoundError: [Errno 2] No such file or directory: '/etc/trading-bot/.env'
**Решение:**
```bash
sudo cp /opt/trading-bot/.env.template /etc/trading-bot/.env
sudo nano /etc/trading-bot/.env  # Настройте параметры
sudo chown tradingbot:tradingbot /etc/trading-bot/.env
sudo chmod 600 /etc/trading-bot/.env
```

#### ❌ binance.exceptions.BinanceAPIException: Invalid API-key
**Решение:**
```bash
sudo nano /etc/trading-bot/.env
```
Проверьте:
- `EXCHANGE_API_KEY` и `EXCHANGE_API_SECRET` правильные
- Если используете testnet: `EXCHANGE_TESTNET=true`
- API ключи активированы на бирже
- IP сервера добавлен в whitelist (если настроен)

#### ❌ Cannot connect to exchange
**Решение:**
```bash
# Проверьте интернет-соединение
curl -I https://api.binance.com/api/v3/ping

# Проверьте для Bybit
curl -I https://api-testnet.bybit.com/v5/market/time

# Проверьте настройки файрволла
sudo ufw status
```

#### ❌ Database is locked
**Решение:**
```bash
sudo rm /var/lib/trading-bot/trading_bot.db-journal
sudo chown tradingbot:tradingbot /var/lib/trading-bot/trading_bot.db
sudo chmod 644 /var/lib/trading-bot/trading_bot.db
```

---

## 🔧 ШАГ 4: Проверка файла службы systemd

### 4.1 Просмотрите конфигурацию службы:
```bash
sudo cat /etc/systemd/system/trading-bot.service
```

### 4.2 Проверьте, что пути правильные:
```bash
grep -E "(ExecStart|WorkingDirectory|EnvironmentFile)" /etc/systemd/system/trading-bot.service
```

Должно быть:
```
WorkingDirectory=/opt/trading-bot
EnvironmentFile=/etc/trading-bot/.env
ExecStart=/opt/trading-bot/venv/bin/python3 /opt/trading-bot/src/main.py
```

### 4.3 Если файл службы неправильный, исправьте (или запустите fix_exec_error.sh):
```bash
sudo bash /opt/trading-bot/scripts/fix_exec_error.sh
# или вручную:
sudo sed -i 's|venv/bin/python |venv/bin/python3 |g' /etc/systemd/system/trading-bot.service
sudo systemctl daemon-reload
```

### 4.4 Перезагрузите systemd:
```bash
sudo systemctl daemon-reload
```

---

## 🚀 ШАГ 5: Перезапуск службы

### 5.1 Остановите службу (если запущена):
```bash
sudo systemctl stop trading-bot
```

### 5.2 Проверьте статус:
```bash
sudo systemctl status trading-bot
```

### 5.3 Запустите службу:
```bash
sudo systemctl start trading-bot
```

### 5.4 Проверьте статус снова:
```bash
sudo systemctl status trading-bot
```

### 5.5 Если все работает, включите автозапуск:
```bash
sudo systemctl enable trading-bot
```

---

## 📋 ШАГ 6: Комплексная проверка

### Выполните все проверки одной командой:
```bash
# Создайте скрипт проверки
cat > /tmp/check_bot.sh << 'EOF'
#!/bin/bash
echo "=== Проверка пользователя ==="
id tradingbot

echo -e "\n=== Проверка каталогов ==="
ls -ld /opt/trading-bot /etc/trading-bot /var/log/trading-bot /var/lib/trading-bot

echo -e "\n=== Проверка .env файла ==="
sudo ls -l /etc/trading-bot/.env

echo -e "\n=== Проверка виртуального окружения ==="
ls -l /opt/trading-bot/venv/bin/python3

echo -e "\n=== Проверка установленных пакетов ==="
/opt/trading-bot/venv/bin/pip list | grep -E "(binance|ccxt|pandas|numpy)"

echo -e "\n=== Проверка прав доступа ==="
sudo -u tradingbot test -r /etc/trading-bot/.env && echo "✓ .env читаемый" || echo "✗ .env не читаемый"
sudo -u tradingbot test -w /var/log/trading-bot && echo "✓ Логи записываемые" || echo "✗ Логи не записываемые"
sudo -u tradingbot test -w /var/lib/trading-bot && echo "✓ БД записываемая" || echo "✗ БД не записываемая"

echo -e "\n=== Статус службы ==="
sudo systemctl status trading-bot --no-pager

echo -e "\n=== Последние 20 строк логов ==="
sudo journalctl -u trading-bot -n 20 --no-pager
EOF

chmod +x /tmp/check_bot.sh
bash /tmp/check_bot.sh
```

---

## 🆘 ШАГ 7: Быстрое исправление (если все остальное не помогло)

### Полная переустановка:

```bash
#!/bin/bash
# Остановите службу
sudo systemctl stop trading-bot

# Сохраните конфигурацию
sudo cp /etc/trading-bot/.env /tmp/env_backup

# Удалите старые файлы
sudo rm -rf /opt/trading-bot/*

# Скопируйте файлы проекта
sudo cp -r ~/trading-bot-setup/life_is_a_joke/* /opt/trading-bot/

# Восстановите .env
sudo cp /tmp/env_backup /etc/trading-bot/.env

# Создайте виртуальное окружение
cd /opt/trading-bot
sudo python3 -m venv venv

# Установите зависимости
sudo -u tradingbot venv/bin/pip install --upgrade pip
sudo -u tradingbot venv/bin/pip install -r requirements.txt

# Исправьте права доступа
sudo chown -R tradingbot:tradingbot /opt/trading-bot
sudo chown -R tradingbot:tradingbot /etc/trading-bot
sudo chown -R tradingbot:tradingbot /var/log/trading-bot
sudo chown -R tradingbot:tradingbot /var/lib/trading-bot

# Перезагрузите systemd
sudo systemctl daemon-reload

# Запустите службу
sudo systemctl start trading-bot

# Проверьте статус
sudo systemctl status trading-bot
```

---

## 📊 ШАГ 8: Проверка после исправления

### 8.1 Служба должна быть активной:
```bash
sudo systemctl is-active trading-bot
# Должно вывести: active
```

### 8.2 Проверьте логи:
```bash
sudo journalctl -u trading-bot -n 50 --no-pager
```

Должны увидеть:
```
Trading Bot - Starting
Configuration loaded: Trading Bot
Trading enabled: true/false
Connected to binance/bybit/etc...
```

### 8.3 Проверьте файл лога:
```bash
sudo tail -f /var/log/trading-bot/trading-bot.log
```

---

## 🎯 Дополнительные команды для диагностики

### Проверка сетевого подключения к биржам:
```bash
# Binance
curl https://api.binance.com/api/v3/ping
curl https://testnet.binance.vision/api/v3/ping  # Testnet

# Bybit
curl https://api.bybit.com/v5/market/time
curl https://api-testnet.bybit.com/v5/market/time  # Testnet

# Kraken
curl https://api.kraken.com/0/public/Time

# Coinbase
curl https://api.exchange.coinbase.com/time
```

### Проверка использования ресурсов:
```bash
# CPU и память
top -u tradingbot

# Процессы
ps aux | grep trading-bot

# Открытые файлы
sudo lsof -u tradingbot
```

### Проверка портов (если используется API):
```bash
sudo netstat -tulpn | grep python
```

---

## 📝 Контрольный список перед запуском

- [ ] Пользователь `tradingbot` создан
- [ ] Все каталоги созданы и принадлежат `tradingbot`
- [ ] Файл `.env` существует и настроен правильно
- [ ] API ключи валидны и активны
- [ ] Виртуальное окружение создано
- [ ] Все зависимости установлены
- [ ] Права доступа установлены правильно
- [ ] Файл службы systemd правильный
- [ ] Интернет-соединение работает
- [ ] Файрволл не блокирует исходящие соединения

---

## 🆘 Если ничего не помогло

### Свяжитесь с поддержкой, предоставив:

1. **Вывод проверки:**
```bash
bash /tmp/check_bot.sh > /tmp/bot_diagnostic.txt 2>&1
cat /tmp/bot_diagnostic.txt
```

2. **Логи systemd:**
```bash
sudo journalctl -u trading-bot -n 200 --no-pager > /tmp/systemd_logs.txt
cat /tmp/systemd_logs.txt
```

3. **Конфигурация (без секретов):**
```bash
sudo cat /etc/trading-bot/.env | grep -v "SECRET\|KEY" > /tmp/config_safe.txt
cat /tmp/config_safe.txt
```

4. **Информация о системе:**
```bash
uname -a
python3 --version
cat /etc/os-release
```

---

## 💡 Полезные советы

### Режим отладки
Добавьте в `/etc/trading-bot/.env`:
```bash
LOG_LEVEL=DEBUG
```

### Запуск в тестовом режиме
```bash
TRADING_ENABLED=false
EXCHANGE_TESTNET=true
```

### Мониторинг в реальном времени
```bash
# Окно 1: Логи systemd
sudo journalctl -u trading-bot -f

# Окно 2: Файловые логи
sudo tail -f /var/log/trading-bot/trading-bot.log

# Окно 3: Ошибки
sudo tail -f /var/log/trading-bot/error.log
```

---

Удачи! Если следуете всем шагам, бот должен запуститься успешно! 🚀
# 🆘 Помощь по боту

## Как вызвать меню с подсказками

### Команда для вызова справки:

```bash
bash ~/trading-bot-setup/life_is_a_joke/scripts/bot_help.sh
```

или короче:

```bash
~/trading-bot-setup/life_is_a_joke/scripts/bot_help.sh
```

или если вы находитесь в директории репозитория:

```bash
./scripts/bot_help.sh
```

---

## 📋 Быстрые команды

### Самые частые команды:

```bash
# Посмотреть статус бота
sudo systemctl status trading-bot

# Посмотреть логи в реальном времени
sudo journalctl -u trading-bot -f

# Перезапустить бота
sudo systemctl restart trading-bot

# Обновить бота
sudo ~/trading-bot-setup/life_is_a_joke/scripts/update_bot.sh

# Диагностика позиций
python3 ~/trading-bot-setup/life_is_a_joke/scripts/diagnose_positions.py

# Проверить здоровье бота
python3 ~/trading-bot-setup/life_is_a_joke/scripts/health_check.py
```

---

## 🎯 Что показывает меню справки

Меню `bot_help.sh` содержит разделы:

1. **📦 Управление сервисом** - запуск, остановка, перезапуск бота
2. **📋 Логи и мониторинг** - просмотр логов разными способами
3. **🔄 Обновление** - команды для обновления бота
4. **🔍 Диагностика** - тестирование и проверка системы
5. **⚙️ Конфигурация** - просмотр и редактирование настроек
6. **📊 База данных** - работа с SQLite базой
7. **🧹 Обслуживание** - очистка и техподдержка
8. **🆘 Решение проблем** - устранение неисправностей
9. **💡 Быстрые рецепты** - готовые команды для частых задач

---

## 🔖 Добавить алиас для быстрого вызова

Чтобы вызывать справку просто командой `bot-help`, добавьте в `~/.bashrc`:

```bash
echo "alias bot-help='bash ~/trading-bot-setup/life_is_a_joke/scripts/bot_help.sh'" >> ~/.bashrc
source ~/.bashrc
```

После этого просто используйте:

```bash
bot-help
```

---

## 📚 Другие полезные скрипты

В директории `scripts/` есть и другие полезные скрипты:

```bash
# Установка и обновление
./scripts/install.sh                 # Установка зависимостей
./scripts/quick_install.sh           # Быстрая установка
./scripts/update_bot.sh              # Обновление бота
./scripts/download_update.sh         # Скачать обновление

# Диагностика
./scripts/health_check.py            # Проверка здоровья
./scripts/test_connectivity.py       # Тест соединения с биржей
./scripts/diagnose_positions.py      # Диагностика позиций
./scripts/test_ai_system.py          # Тест AI системы

# Анализ
./scripts/analyze_trades.py          # Анализ сделок
./scripts/generate_weekly_report.py  # Генерация отчётов

# Управление
./scripts/reset_daily_limit.py       # Сброс дневного лимита
./scripts/setup_environment.py       # Настройка окружения
./scripts/quick_start.py             # Быстрый старт
```

---

## 🆘 Экстренная помощь

### Бот не работает?

1. **Проверьте статус:**
   ```bash
   sudo systemctl status trading-bot
   ```

2. **Посмотрите логи:**
   ```bash
   sudo journalctl -u trading-bot -n 50
   ```

3. **Перезапустите:**
   ```bash
   sudo systemctl restart trading-bot
   ```

4. **Вызовите полную справку:**
   ```bash
   ~/trading-bot-setup/life_is_a_joke/scripts/bot_help.sh
   ```

---

## 📞 Дополнительная документация

- [README.md](README.md) - Основная документация
- [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) - Руководство по настройке
- [TREND_ANALYSIS_GUIDE.md](TREND_ANALYSIS_GUIDE.md) - Анализ трендов
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Решение проблем
- [QUICK_START_UPDATE.md](QUICK_START_UPDATE.md) - Обновление
- [UBUNTU_INSTALL.md](UBUNTU_INSTALL.md) - Установка на Ubuntu

---

**💡 Совет:** Добавьте эту страницу в закладки браузера или сохраните команду вызова справки!

**Команда для запоминания:**
```bash
~/trading-bot-setup/life_is_a_joke/scripts/bot_help.sh
```
