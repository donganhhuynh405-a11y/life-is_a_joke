#!/bin/bash
#
# Update .env file with missing parameters from .env.template
# This script safely adds new configuration parameters to existing .env files
#

# Exit on error, but allow arithmetic operations to return non-zero
set -e
set +e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Обновление файла .env с новыми параметрами                   ║${NC}"
echo -e "${BLUE}║       Update .env file with new parameters                         ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Default paths
DEFAULT_ENV_FILE="/etc/trading-bot/.env"
TEMPLATE_FILE="/opt/trading-bot/.env.template"

# Allow custom paths
ENV_FILE="${1:-$DEFAULT_ENV_FILE}"

# Check if .env file exists
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}❌ Файл .env не найден: $ENV_FILE${NC}"
    echo -e "${YELLOW}Создайте .env файл из шаблона:${NC}"
    echo "   cp $TEMPLATE_FILE $ENV_FILE"
    exit 1
fi

# Check if template exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo -e "${RED}❌ Файл .env.template не найден: $TEMPLATE_FILE${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Найден .env файл: $ENV_FILE${NC}"
echo -e "${GREEN}✅ Найден .env.template: $TEMPLATE_FILE${NC}"
echo ""

# Create backup
BACKUP_FILE="${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
echo -e "${YELLOW}📦 Создаём резервную копию...${NC}"
sudo cp "$ENV_FILE" "$BACKUP_FILE"
echo -e "${GREEN}✅ Резервная копия: $BACKUP_FILE${NC}"
echo ""

# Parameters to add/update
echo -e "${BLUE}🔍 Проверяем отсутствующие параметры...${NC}"
echo ""

# List of new parameters with their default values and descriptions
declare -A NEW_PARAMS
NEW_PARAMS["NOTIFICATION_LANGUAGE"]="en"
NEW_PARAMS["USE_CONFIDENCE_SIZING"]="true"
NEW_PARAMS["MIN_POSITION_SIZE_PCT"]="0.5"
NEW_PARAMS["MAX_POSITION_SIZE_PCT"]="5.0"
NEW_PARAMS["TRADE_WITH_TREND_ONLY"]="false"
NEW_PARAMS["MIN_TREND_STRENGTH"]="0.3"
NEW_PARAMS["MIN_ADX_VALUE"]="20"
NEW_PARAMS["DAILY_PROFIT_TARGET"]="100"
NEW_PARAMS["WEEKLY_PROFIT_TARGET"]="500"
NEW_PARAMS["MONTHLY_PROFIT_TARGET"]="2000"
NEW_PARAMS["STOP_ON_DAILY_TARGET"]="false"
NEW_PARAMS["NOTIFY_ON_TARGET_REACHED"]="true"

ADDED_COUNT=0
SKIPPED_COUNT=0

# Create temporary file for new parameters
TEMP_FILE=$(mktemp)

# Check and collect missing parameters
for param in "${!NEW_PARAMS[@]}"; do
    if ! grep -q "^${param}=" "$ENV_FILE"; then
        echo -e "${YELLOW}➕ Добавляем: $param=${NEW_PARAMS[$param]}${NC}"
        echo "${param}=${NEW_PARAMS[$param]}" >> "$TEMP_FILE"
        ((ADDED_COUNT++))
    else
        echo -e "${GREEN}✓ Уже существует: $param${NC}"
        ((SKIPPED_COUNT++))
    fi
done

# Add all new parameters at once
if [ $ADDED_COUNT -gt 0 ]; then
    echo "" | sudo tee -a "$ENV_FILE" > /dev/null
    echo "# ============================================================================" | sudo tee -a "$ENV_FILE" > /dev/null
    echo "# NEW PARAMETERS (added automatically on $(date +%Y-%m-%d))" | sudo tee -a "$ENV_FILE" > /dev/null
    echo "# ============================================================================" | sudo tee -a "$ENV_FILE" > /dev/null
    cat "$TEMP_FILE" | sudo tee -a "$ENV_FILE" > /dev/null
fi

# Clean up
rm -f "$TEMP_FILE"

echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Обновление завершено!${NC}"
echo ""
echo -e "${GREEN}📊 Статистика:${NC}"
echo -e "   Добавлено параметров: ${ADDED_COUNT}"
echo -e "   Уже существовало: ${SKIPPED_COUNT}"
echo ""
echo -e "${YELLOW}📝 Важные новые параметры:${NC}"
echo ""
echo -e "${BLUE}1. NOTIFICATION_LANGUAGE${NC} - Язык уведомлений"
echo -e "   Поддерживаемые языки: en, zh, es, hi, ar, bn, pt, ru, ja, de, fr, tr, ko, it, vi, th, pl, uk, nl, id"
echo -e "   Текущее значение: ${NEW_PARAMS[NOTIFICATION_LANGUAGE]}"
echo ""
echo -e "${BLUE}2. USE_CONFIDENCE_SIZING${NC} - Адаптивный размер позиций"
echo -e "   Динамически регулирует размер позиции в зависимости от уверенности сигнала"
echo -e "   Текущее значение: ${NEW_PARAMS[USE_CONFIDENCE_SIZING]}"
echo ""
echo -e "${BLUE}3. TRADE_WITH_TREND_ONLY${NC} - Торговля только по тренду"
echo -e "   Открывает позиции только когда они совпадают с трендом"
echo -e "   Текущее значение: ${NEW_PARAMS[TRADE_WITH_TREND_ONLY]}"
echo ""
echo -e "${YELLOW}💡 Для изменения параметров:${NC}"
echo "   sudo nano $ENV_FILE"
echo ""
echo -e "${YELLOW}🔄 Для применения изменений:${NC}"
echo "   sudo systemctl restart trading-bot"
echo ""
echo -e "${YELLOW}📖 Полная документация:${NC}"
echo "   /opt/trading-bot/BOT_CONFIGURATION_GUIDE.md"
echo ""
echo -e "${GREEN}✅ Готово!${NC}"
echo ""
