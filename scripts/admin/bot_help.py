#!/usr/bin/env python3
"""
Trading Bot Help Script
Displays all available management commands for the trading bot
"""

import sys

# ANSI color codes


class Colors:
    GREEN = '\033[0;32m'
    BLUE = '\033[0;34m'
    YELLOW = '\033[1;33m'
    CYAN = '\033[0;36m'
    RED = '\033[0;31m'
    MAGENTA = '\033[0;35m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color


def print_header():
    """Print the header"""
    print("=" * 80)
    print(f"{Colors.GREEN}{Colors.BOLD}                   TRADING BOT MANAGEMENT COMMANDS{Colors.NC}")
    print("=" * 80)
    print()


def print_section(title, icon=""):
    """Print a section title"""
    print(f"{Colors.BLUE}{icon} {title}{Colors.NC}")
    print("-" * 80)


def print_command(cmd, description):
    """Print a command with its description"""
    print(f"{Colors.CYAN}{cmd}{Colors.NC}")
    print(f"   {description}")
    print()


def print_service_management():
    """Print service management commands"""
    print_section("BOT SERVICE MANAGEMENT", "📦")

    commands = [
        ("sudo systemctl start trading-bot", "Start the trading bot service"),
        ("sudo systemctl stop trading-bot", "Stop the trading bot service"),
        ("sudo systemctl restart trading-bot", "Restart the trading bot service"),
        ("sudo systemctl status trading-bot", "Check the current status of the bot"),
        ("sudo systemctl enable trading-bot", "Enable bot to start automatically on system boot"),
        ("sudo systemctl disable trading-bot", "Disable bot from starting automatically on system boot"),
    ]

    for cmd, desc in commands:
        print_command(cmd, desc)


def print_logs_monitoring():
    """Print logs and monitoring commands"""
    print_section("LOGS & MONITORING", "📋")

    commands = [
        ("sudo journalctl -u trading-bot -f", "View live logs (press Ctrl+C to exit)"),
        ("sudo journalctl -u trading-bot --since today", "View logs from today"),
        ("sudo journalctl -u trading-bot --since '1 hour ago'", "View logs from the last hour"),
        ("sudo journalctl -u trading-bot -n 100", "View last 100 log lines"),
        ("sudo journalctl -u trading-bot | grep -i 'error\\|warning'", "Filter logs for errors and warnings"),
        ("sudo journalctl -u trading-bot | grep -i 'position\\|pnl\\|close'", "Filter logs for position-related events"),
    ]

    for cmd, desc in commands:
        print_command(cmd, desc)


def print_update_deployment():
    """Print update and deployment commands"""
    print_section("UPDATE & DEPLOYMENT", "🔄")

    commands = [
        ("cd /opt/trading-bot && git pull", "Pull latest changes from repository"),
        ("cd /opt/trading-bot && venv/bin/pip install -r requirements.txt", "Update Python dependencies"),
        ("sudo systemctl restart trading-bot", "Restart bot after updates"),
        ("cd /opt/trading-bot && git status", "Check repository status and changes"),
        ("cd /opt/trading-bot && git log --oneline -10", "View last 10 commits"),
    ]

    for cmd, desc in commands:
        print_command(cmd, desc)


def print_diagnostics():
    """Print diagnostics and debugging commands"""
    print_section("DIAGNOSTICS & DEBUGGING", "🔍")

    commands = [
        ("python3 /opt/trading-bot/scripts/test_ai_system.py", "🤖 Test AI system (commentary, adaptive tactics, ML analyzers)"),
        ("python3 /opt/trading-bot/scripts/analyze_trades.py", "📊 Run full ML performance analysis"),
        ("python3 /opt/trading-bot/scripts/diagnose_positions.py", "Run position diagnostics script"),
        ("python3 /opt/trading-bot/scripts/health_check.py", "Run comprehensive health check"),
        ("sqlite3 /var/lib/trading-bot/trading_bot.db 'SELECT * FROM positions;'", "Query all positions from database"),
        ("sqlite3 /var/lib/trading-bot/trading_bot.db 'SELECT * FROM positions WHERE status=\"open\";'", "Query only open positions"),
        ("sqlite3 /var/lib/trading-bot/trading_bot.db 'SELECT * FROM positions WHERE status=\"closed\" ORDER BY closed_at DESC LIMIT 10;'", "View last 10 closed positions"),
        ("sqlite3 /var/lib/trading-bot/trading_bot.db 'SELECT symbol, COUNT(*), SUM(pnl) FROM positions WHERE status=\"closed\" GROUP BY symbol;'", "View P&L summary by symbol"),
    ]

    for cmd, desc in commands:
        print_command(cmd, desc)


def print_configuration():
    """Print configuration commands"""
    print_section("CONFIGURATION", "⚙️")

    commands = [
        ("nano /opt/trading-bot/.env", "Edit bot configuration (use Ctrl+X to save and exit)"),
        ("cat /opt/trading-bot/.env", "View current configuration"),
        ("cat /opt/trading-bot/.env | grep MAX_", "View position and trade limits"),
        ("cat /opt/trading-bot/.env | grep CONFIDENCE", "View confidence-based sizing settings"),
        ("cat /opt/trading-bot/.env | grep NEWS", "View news analysis settings"),
    ]

    for cmd, desc in commands:
        print_command(cmd, desc)


def print_database():
    """Print database management commands"""
    print_section("DATABASE MANAGEMENT", "📊")

    commands = [
        ("sqlite3 /var/lib/trading-bot/trading_bot.db", "Open database interactive shell (type .exit to quit)"),
        ("sqlite3 /var/lib/trading-bot/trading_bot.db '.schema'", "View database schema"),
        ("sqlite3 /var/lib/trading-bot/trading_bot.db 'PRAGMA table_info(positions);'", "View positions table structure"),
        ("sqlite3 /var/lib/trading-bot/trading_bot.db '.backup /tmp/trading_bot_backup.db'", "Create database backup"),
        ("python3 /opt/trading-bot/scripts/reset_daily_limit.py --status", "Check current daily trade limit status"),
        ("python3 /opt/trading-bot/scripts/reset_daily_limit.py", "Reset daily trade counter (allows more trading today)"),
    ]

    for cmd, desc in commands:
        print_command(cmd, desc)


def print_maintenance():
    """Print maintenance commands"""
    print_section("MAINTENANCE", "🧹")

    commands = [
        ("sudo find /opt/trading-bot -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null", "Clean Python cache files"),
        ("python3 /opt/trading-bot/scripts/cleanup_old_data.py", "Clean old data from database"),
        ("python3 /opt/trading-bot/scripts/optimize_database.py", "Optimize database for better performance"),
        ("sudo python3 /opt/trading-bot/scripts/clean_root_cache.py", "Clean /root cache to free disk space"),
        ("df -h /opt/trading-bot", "Check disk space usage"),
    ]

    for cmd, desc in commands:
        print_command(cmd, desc)


def print_troubleshooting():
    """Print troubleshooting commands"""
    print_section("TROUBLESHOOTING", "🆘")

    commands = [
        ("sudo systemctl daemon-reload", "Reload systemd configuration if service file changed"),
        ("sudo systemctl reset-failed trading-bot", "Reset failed state if service won't start"),
        ("journalctl -xe", "View system logs for recent errors"),
        ("ps aux | grep trading", "Check if bot process is running"),
        ("cd /opt/trading-bot && rm -rf venv && python3 -m venv venv", "Recreate virtual environment if broken"),
        ("cd /opt/trading-bot && venv/bin/pip install -r requirements.txt", "Reinstall all dependencies"),
    ]

    for cmd, desc in commands:
        print_command(cmd, desc)


def print_quick_recipes():
    """Print quick recipe commands"""
    print_section("QUICK RECIPES", "💡")

    print(f"{Colors.YELLOW}Full update and restart:{Colors.NC}")
    print("   cd /opt/trading-bot && git pull && venv/bin/pip install -r requirements.txt && sudo systemctl restart trading-bot")
    print()

    print(f"{Colors.YELLOW}Test AI system:{Colors.NC}")
    print("   python3 /opt/trading-bot/scripts/test_ai_system.py")
    print()

    print(f"{Colors.YELLOW}View today's P&L:{Colors.NC}")
    print("   sqlite3 /var/lib/trading-bot/trading_bot.db \"SELECT COALESCE(SUM(pnl), 0) FROM positions WHERE status='closed' AND DATE(closed_at) = DATE('now', 'localtime');\"")
    print()

    print(f"{Colors.YELLOW}Count open positions:{Colors.NC}")
    print("   sqlite3 /var/lib/trading-bot/trading_bot.db \"SELECT COUNT(*) FROM positions WHERE status='open';\"")
    print()

    print(f"{Colors.YELLOW}Watch live trading activity:{Colors.NC}")
    print("   sudo journalctl -u trading-bot -f | grep -i 'signal\\|position\\|buy\\|sell'")
    print()

    print(f"{Colors.YELLOW}Watch AI activity:{Colors.NC}")
    print("   sudo journalctl -u trading-bot -f | grep -i 'AI\\|adaptive\\|commentary'")
    print()

    print(f"{Colors.YELLOW}Watch news analysis:{Colors.NC}")
    print("   sudo journalctl -u trading-bot -f | grep -i 'news\\|sentiment'")
    print()

    print(f"{Colors.YELLOW}Emergency stop:{Colors.NC}")
    print("   sudo systemctl stop trading-bot")
    print()


def print_footer():
    """Print the footer"""
    print("=" * 80)
    print(f"{Colors.GREEN}For more help, visit the repository or check РУКОВОДСТВО.md{Colors.NC}")
    print("=" * 80)
    print()


def main():
    """Main function"""
    # Clear screen (optional)
    # os.system('clear')

    print_header()
    print_service_management()
    print_logs_monitoring()
    print_update_deployment()
    print_diagnostics()
    print_configuration()
    print_database()
    print_maintenance()
    print_troubleshooting()
    print_quick_recipes()
    print_footer()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.NC}")
        sys.exit(0)
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.NC}", file=sys.stderr)
        sys.exit(1)
