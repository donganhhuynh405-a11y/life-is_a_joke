#!/bin/bash
# Скрипт проверки версии кода и обновления бота
# Version Verification and Update Script

set -e

echo "=========================================="
echo "Trading Bot - Version Verification Script"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Find project directory
echo "🔍 Поиск директории проекта..."
PROJECT_DIR=$(find ~ -name "life_is_a_joke" -type d 2>/dev/null | grep -v ".git" | head -1)

if [ -z "$PROJECT_DIR" ]; then
    print_error "Директория проекта не найдена!"
    echo "Попробуйте вручную:"
    echo "  find / -name 'life_is_a_joke' -type d 2>/dev/null"
    exit 1
fi

print_success "Проект найден: $PROJECT_DIR"
cd "$PROJECT_DIR"

echo ""
echo "=========================================="
echo "ПРОВЕРКА ТЕКУЩЕЙ ВЕРСИИ КОДА"
echo "=========================================="

# Check current commit
CURRENT_COMMIT=$(git log --oneline -1 2>/dev/null || echo "ERROR")
echo "📌 Текущий коммит: $CURRENT_COMMIT"

# Expected commit
EXPECTED_COMMIT="fcc1919"
if echo "$CURRENT_COMMIT" | grep -q "$EXPECTED_COMMIT"; then
    print_success "Версия кода ПРАВИЛЬНАЯ"
else
    print_error "Версия кода УСТАРЕВШАЯ! Нужен коммит $EXPECTED_COMMIT"
    NEEDS_UPDATE=1
fi

echo ""
echo "=========================================="
echo "ПРОВЕРКА КРИТИЧЕСКИХ ИСПРАВЛЕНИЙ"
echo "=========================================="

# Check for risk limit checks
RISK_CHECK_COUNT=$(grep -c "CHECK RISK LIMITS FIRST" src/strategies/strategy_manager.py 2>/dev/null || echo "0")
echo "🔒 Проверки лимитов рисков: $RISK_CHECK_COUNT/2"
if [ "$RISK_CHECK_COUNT" = "2" ]; then
    print_success "Проверки лимитов присутствуют"
else
    print_error "Проверки лимитов ОТСУТСТВУЮТ!"
    NEEDS_UPDATE=1
fi

# Check for notification isolation
NOTIF_CHECK_COUNT=$(grep -c "except Exception as notif_error" src/strategies/strategy_manager.py 2>/dev/null || echo "0")
echo "🔔 Изоляция уведомлений: $NOTIF_CHECK_COUNT/4"
if [ "$NOTIF_CHECK_COUNT" = "4" ]; then
    print_success "Уведомления изолированы"
else
    print_error "Уведомления НЕ изолированы!"
    NEEDS_UPDATE=1
fi

# Check for notification error handling
NOTIF_SAFEGUARD=$(grep -c "emoji.*if.*side" src/utils/notifications.py 2>/dev/null || echo "0")
echo "🛡️  Защита уведомлений: найдено $NOTIF_SAFEGUARD проверок"
if [ "$NOTIF_SAFEGUARD" -gt "0" ]; then
    print_success "Защита уведомлений присутствует"
else
    print_error "Защита уведомлений ОТСУТСТВУЕТ!"
    NEEDS_UPDATE=1
fi

echo ""
echo "=========================================="
echo "ПРОВЕРКА ЗАПУЩЕННОГО ПРОЦЕССА"
echo "=========================================="

# Check if bot is running
BOT_PROCESS=$(ps aux | grep -E "python.*main\.py|trading-bot" | grep -v grep || echo "")
if [ -n "$BOT_PROCESS" ]; then
    print_warning "Бот запущен:"
    echo "$BOT_PROCESS"
    echo ""
    print_warning "ВАЖНО: Запущенный бот может использовать СТАРУЮ версию кода!"
else
    print_warning "Бот НЕ запущен (или запущен под systemd)"
fi

# Check systemd service
if systemctl is-active --quiet trading-bot 2>/dev/null; then
    print_warning "Systemd служба активна"
    SERVICE_STATUS=$(systemctl status trading-bot --no-pager -l | head -20)
    echo "$SERVICE_STATUS"
else
    print_warning "Systemd служба не активна"
fi

echo ""
echo "=========================================="
echo "РЕЗУЛЬТАТЫ ПРОВЕРКИ"
echo "=========================================="

if [ "$NEEDS_UPDATE" = "1" ]; then
    print_error "КОД УСТАРЕЛ - ТРЕБУЕТСЯ ОБНОВЛЕНИЕ!"
    echo ""
    echo "Выполните следующие команды для обновления:"
    echo ""
    echo "1. Остановите бота:"
    echo "   sudo systemctl stop trading-bot"
    echo ""
    echo "2. Обновите код:"
    echo "   cd $PROJECT_DIR"
    echo "   git fetch origin"
    echo "   git checkout main"
    echo "   git pull origin main"
    echo ""
    echo "3. Проверьте обновление:"
    echo "   git log --oneline -1"
    echo "   # Должно быть: fcc1919 Fix position/trade limits"
    echo ""
    echo "4. Проверьте наличие исправлений:"
    echo "   grep -c 'CHECK RISK LIMITS FIRST' src/strategies/strategy_manager.py"
    echo "   # Должно вывести: 2"
    echo ""
    echo "5. Запустите бота:"
    echo "   sudo systemctl start trading-bot"
    echo ""
    echo "6. Проверьте логи:"
    echo "   sudo journalctl -u trading-bot -f"
    echo ""
    
    read -p "Выполнить автоматическое обновление сейчас? (yes/no): " CONFIRM
    if [ "$CONFIRM" = "yes" ] || [ "$CONFIRM" = "y" ]; then
        echo ""
        echo "=========================================="
        echo "АВТОМАТИЧЕСКОЕ ОБНОВЛЕНИЕ"
        echo "=========================================="
        
        echo "⏸️  Останавливаем бота..."
        sudo systemctl stop trading-bot || print_warning "Не удалось остановить службу (возможно, не запущена)"
        
        echo "📥 Обновляем код..."
        git fetch origin
        git checkout main
        git pull origin main
        
        echo "✅ Проверяем обновление..."
        UPDATED_COMMIT=$(git log --oneline -1)
        echo "Новый коммит: $UPDATED_COMMIT"
        
        RISK_CHECK=$(grep -c "CHECK RISK LIMITS FIRST" src/strategies/strategy_manager.py)
        NOTIF_CHECK=$(grep -c "except Exception as notif_error" src/strategies/strategy_manager.py)
        
        echo "Проверки лимитов: $RISK_CHECK/2"
        echo "Изоляция уведомлений: $NOTIF_CHECK/4"
        
        if [ "$RISK_CHECK" = "2" ] && [ "$NOTIF_CHECK" = "4" ]; then
            print_success "Код обновлён успешно!"
            
            echo "▶️  Запускаем бота..."
            sudo systemctl start trading-bot
            
            echo ""
            print_success "ОБНОВЛЕНИЕ ЗАВЕРШЕНО!"
            echo ""
            echo "Проверьте логи:"
            echo "  sudo journalctl -u trading-bot -f"
            echo ""
            echo "В логах должны быть сообщения о проверке лимитов:"
            echo "  ✅ INFO - Available currencies: [...]"
            echo "  ✅ INFO - Non-zero balances: {...}"
            echo "  ✅ WARNING - Skipping BUY: Position limits reached (при превышении)"
        else
            print_error "Обновление не применилось правильно!"
            print_warning "Проверьте вручную"
        fi
    else
        print_warning "Автоматическое обновление отменено"
    fi
else
    print_success "КОД АКТУАЛЬНЫЙ!"
    echo ""
    echo "Все исправления присутствуют:"
    echo "  ✅ Проверки лимитов рисков (MAX_POSITIONS, MAX_DAILY_TRADES)"
    echo "  ✅ Изоляция уведомлений Telegram"
    echo "  ✅ Защита от ошибок конвертации float"
    echo ""
    print_warning "Если проблемы всё ещё есть, перезапустите бота:"
    echo "  sudo systemctl restart trading-bot"
    echo ""
    echo "И проверьте логи:"
    echo "  sudo journalctl -u trading-bot -f | grep -E 'Position limits|Daily limits|notification'"
fi

echo ""
echo "=========================================="
echo "ПРОВЕРКА КОНФИГУРАЦИИ"
echo "=========================================="

if [ -f ".env" ]; then
    echo "📝 Файл .env найден"
    MAX_POS=$(grep MAX_OPEN_POSITIONS .env 2>/dev/null || echo "NOT FOUND")
    MAX_TRADES=$(grep MAX_DAILY_TRADES .env 2>/dev/null || echo "NOT FOUND")
    echo "  MAX_OPEN_POSITIONS: $MAX_POS"
    echo "  MAX_DAILY_TRADES: $MAX_TRADES"
else
    print_warning "Файл .env не найден"
    echo "Проверьте переменные окружения systemd:"
    echo "  sudo systemctl show trading-bot | grep MAX"
fi

echo ""
echo "=========================================="
echo "ДОПОЛНИТЕЛЬНАЯ ДИАГНОСТИКА"
echo "=========================================="

# Check database for open positions
if [ -f "/var/lib/trading-bot/trading_bot.db" ]; then
    OPEN_POS=$(sqlite3 /var/lib/trading-bot/trading_bot.db "SELECT COUNT(*) FROM positions WHERE status='open';" 2>/dev/null || echo "ERROR")
    echo "🗄️  Открытых позиций в БД: $OPEN_POS"
    if [ "$OPEN_POS" != "ERROR" ] && [ "$OPEN_POS" -gt 20 ]; then
        print_error "Слишком много открытых позиций ($OPEN_POS)!"
        print_warning "Это означает, что бот работал БЕЗ проверок лимитов"
        print_warning "После обновления новые позиции НЕ будут открываться до закрытия существующих"
    fi
else
    print_warning "База данных не найдена в /var/lib/trading-bot/trading_bot.db"
fi

# Recent log check
echo ""
echo "📜 Последние логи (30 строк):"
sudo journalctl -u trading-bot --no-pager -n 30 2>/dev/null || echo "Логи недоступны"

echo ""
echo "=========================================="
echo "ЗАВЕРШЕНИЕ"
echo "=========================================="
echo ""
