# 🤖 Руководство по запуску обучения ИИ/ML

Это руководство объясняет, **что нужно сделать**, чтобы:

1. запустить полное историческое обучение ИИ/ML на истории каждой криптовалюты;
2. отслеживать прогресс в реальном времени.

---

## Что происходит при обучении

Перед торговлей бот обучает персональную ML-модель для **каждого** торгового символа:

| Этап | Что происходит |
|------|---------------|
| **fetch_data** | Загружается полная история с момента появления монеты на бирже (BTC — с 2017, SOL — с 2020, и т.д.) |
| **training** | Рассчитывается 100+ технических признаков (цена, объём, волатильность, момент, паттерны свечей, режим рынка). Модель обучается на **всех** рыночных ситуациях: бычий тренд, медвежий тренд, боковик, высокая/низкая волатильность |
| **done** | Модель сохраняется на диск и используется для предсказаний |
| **fine-tune** | После каждой закрытой сделки знания пополняются: результат торговли подаётся в модель как новый обучающий пример |

---

## Способ 1 — Автоматически при запуске бота

Обучение запускается **автоматически** при старте бота, если модели ещё не обучены.

```bash
# Поднять стек (включает обучение при первом запуске)
docker compose up -d

# Посмотреть логи обучения
docker compose logs -f trading-bot | grep -E "🎓|📥|✅|❌|epoch"
```

Переменные окружения в `.env`:

```dotenv
# Символы для обучения (через запятую)
TRAINING_SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,DOTUSDT,AVAXUSDT,MATICUSDT

# Таймфрейм обучения
TRAINING_TIMEFRAME=1h

# Директория моделей
MODELS_DIR=/var/lib/trading-bot/models
```

---

## Способ 2 — Запустить обучение вручную (CLI)

```bash
# Зайти в контейнер
docker exec -it trading-bot bash

# Запустить обучение (все символы по умолчанию)
python scripts/run_training.py

# Принудительное переобучение (игнорировать существующие модели)
python scripts/run_training.py --force

# Обучить только конкретные монеты
python scripts/run_training.py --symbols BTCUSDT ETHUSDT SOLUSDT

# Использовать таймфрейм 4h вместо 1h
python scripts/run_training.py --timeframe 4h
```

---

## Способ 3 — Запустить обучение через REST API

```bash
# Запустить обучение (стандартный набор символов)
curl -X POST http://localhost:8080/api/v1/ml/training/start \
     -H "Content-Type: application/json" \
     -d '{"force_retrain": false}'

# Принудительное переобучение конкретных монет
curl -X POST http://localhost:8080/api/v1/ml/training/start \
     -H "Content-Type: application/json" \
     -d '{"force_retrain": true, "symbols": ["BTCUSDT", "ETHUSDT"]}'
```

---

## Отслеживание прогресса

### Вариант A — CLI-дашборд (рекомендуется)

В **отдельном терминале** запустите:

```bash
# Из контейнера
docker exec -it trading-bot python scripts/watch_training.py

# Или напрямую, если src/ доступен
python scripts/watch_training.py

# Обновлять каждые 2 секунды
python scripts/watch_training.py --interval 2

# Один снапшот и выйти
python scripts/watch_training.py --once

# Читать прогресс через API
python scripts/watch_training.py --api http://localhost:8080
```

Вид дашборда:

```
════════════════════════════════════════════════════════════════════════
  🤖  ML TRAINING PROGRESS DASHBOARD
  Refresh #12  •  14:32:07
════════════════════════════════════════════════════════════════════════

  Status:   RUNNING
  Elapsed:  8m 23s

  [████████████████████░░░░░░░░░░░░░░░░░░░░]  40.0%

  Symbols:  4/10  │  ✅ 3  ⏭ 0  ❌ 1
  Current:  SOLUSDT  (training)
  ETA:      12m 30s

  Symbol Results:
  ──────────────────────────────────────────────────────────────────────
  Symbol         Status     Accuracy       F1   Duration
  ──────────────────────────────────────────────────────────────────────
  ✅ ADAUSDT       success      0.623    0.598       142s
  ❌ BNBUSDT       failed          —        —         23s
  ✅ BTCUSDT       success      0.641    0.619       198s
  ✅ ETHUSDT       success      0.629    0.607       175s
  ──────────────────────────────────────────────────────────────────────
```

### Вариант Б — REST API

```bash
# Текущий статус (JSON)
curl http://localhost:8080/api/v1/ml/training/status | python -m json.tool
```

Пример ответа:

```json
{
  "status": "running",
  "symbols_total": 10,
  "symbols_done": 4,
  "progress_pct": 40.0,
  "current_symbol": "SOLUSDT",
  "current_phase": "training",
  "eta_seconds": 750,
  "symbols_successful": 3,
  "symbols_failed": 1,
  "results": {
    "BTCUSDT": { "status": "success", "metrics": { "accuracy": 0.641 } },
    ...
  }
}
```

### Вариант В — Swagger UI

Откройте в браузере:

```
http://localhost:8080/docs
```

Раздел **ML Training** → `GET /api/v1/ml/training/status`

### Вариант Г — Файл прогресса напрямую

```bash
# Читать JSON-файл прогресса
cat /var/lib/trading-bot/training_progress.json | python -m json.tool

# Следить за изменениями
watch -n 3 "cat /var/lib/trading-bot/training_progress.json | python -m json.tool"
```

---

## Сколько времени занимает обучение?

| Символ | Данных | Примерное время |
|--------|--------|----------------|
| BTCUSDT | ~57 000 свечей (с 2017) | 3–5 минут |
| ETHUSDT | ~57 000 свечей (с 2017) | 3–5 минут |
| SOLUSDT | ~30 000 свечей (с 2020) | 2–3 минуты |
| **Все 10 символов** | — | **30–60 минут** |

Время зависит от мощности CPU/GPU сервера.  
При наличии GPU обучение в 5–10 раз быстрее.

---

## Что происходит после обучения

1. Модели сохраняются в `MODELS_DIR` (`/var/lib/trading-bot/models/BTCUSDT/model.pkl` и т.д.)
2. Бот автоматически загружает эти модели и использует их для торговых сигналов
3. После каждой закрытой сделки модель дообучается на новом примере (fine-tuning)
4. Переобучение модели происходит автоматически каждые 7 дней

---

## Ручное переобучение

```bash
# Переобучить все модели (принудительно)
docker exec trading-bot python scripts/run_training.py --force

# Переобучить одну монету
docker exec trading-bot python scripts/run_training.py --symbols BTCUSDT --force
```

---

## Если что-то пошло не так

```bash
# Посмотреть логи обучения
docker compose logs trading-bot | grep -E "ERROR|FAIL|❌"

# Проверить статус через API
curl http://localhost:8080/api/v1/ml/training/status

# Посмотреть файл прогресса
cat /var/lib/trading-bot/training_progress.json
```

Частые проблемы:

| Проблема | Решение |
|----------|---------|
| `Insufficient data` | Биржа вернула мало свечей. Попробуйте снова через 10 минут. |
| `Connection error` | Проверьте доступность API биржи (`BINANCE_API_KEY` в `.env`). |
| Обучение зависло | `docker exec trading-bot kill -9 1` — перезапустит контейнер. |
| Низкая точность модели | Это нормально для первого обучения (0.55–0.65). Со временем дообучение на сделках повысит точность. |
