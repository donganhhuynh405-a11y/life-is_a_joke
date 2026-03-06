#!/usr/bin/env python3
"""
Trading Bot - Administration Tool
Main administration tool with interactive menu for bot management.
"""

import os
import sys
import argparse
import subprocess
import time
from pathlib import Path
from datetime import datetime
import signal

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class Colors:
    """ANSI color codes"""
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    CYAN = '\033[0;36m'
    MAGENTA = '\033[0;35m'
    BOLD = '\033[1m'
    NC = '\033[0m'


def print_info(message):
    """Print info message"""
    print(f"{Colors.BLUE}[INFO]{Colors.NC} {message}")


def print_success(message):
    """Print success message"""
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {message}")


def print_warning(message):
    """Print warning message"""
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {message}")


def print_error(message):
    """Print error message"""
    print(f"{Colors.RED}[ERROR]{Colors.NC} {message}")


def run_command(cmd, show_output=True, check=True):
    """
    Run shell command and return output.

    SECURITY NOTE: This function uses shell=True for convenience with internal
    commands. All user input passed to this function MUST be sanitized first.
    """
    try:
        if show_output:
            result = subprocess.run(cmd, shell=True, text=True, check=check)
            return result.returncode == 0
        else:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)
            return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        if show_output:
            print_error(f"Command failed: {e}")
        return None if not show_output else False


def find_bot_process():
    """Find bot process by name"""
    try:
        result = subprocess.run(
            ['pgrep', '-', 'python.*main.py|python.*telegram_bot.py'],
            capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.stdout.strip() else None
    except Exception:
        return None


def get_bot_status():
    """Get bot status"""
    pid = find_bot_process()
    if pid:
        return True, pid
    return False, None


def start_bot():
    """Start the trading bot"""
    print_info("Starting trading bot...")

    is_running, pid = get_bot_status()
    if is_running:
        print_warning(f"Bot is already running (PID: {pid})")
        return

    # Check which bot file exists
    project_root = Path(__file__).parent.parent
    main_py = project_root / "src" / "main.py"
    telegram_py = project_root / "telegram_bot.py"

    if main_py.exists():
        cmd = f"cd {project_root} && nohup python3 src/main.py > logs/bot.log 2>&1 &"
    elif telegram_py.exists():
        cmd = f"cd {project_root} && nohup python3 telegram_bot.py > logs/bot.log 2>&1 &"
    else:
        print_error("Bot main file not found!")
        return

    # Create logs directory if it doesn't exist
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    if run_command(cmd):
        time.sleep(2)
        is_running, pid = get_bot_status()
        if is_running:
            print_success(f"Bot started successfully (PID: {pid})")
        else:
            print_error("Failed to start bot")
    else:
        print_error("Failed to execute start command")


def stop_bot():
    """Stop the trading bot"""
    print_info("Stopping trading bot...")

    is_running, pid = get_bot_status()
    if not is_running:
        print_warning("Bot is not running")
        return

    # Send SIGTERM for graceful shutdown
    try:
        os.kill(int(pid), signal.SIGTERM)
        time.sleep(2)

        # Check if still running
        is_running, _ = get_bot_status()
        if is_running:
            print_warning("Bot didn't stop gracefully, sending SIGKILL...")
            os.kill(int(pid), signal.SIGKILL)
            time.sleep(1)

        print_success("Bot stopped successfully")
    except Exception as e:
        print_error(f"Failed to stop bot: {e}")


def restart_bot():
    """Restart the trading bot"""
    print_info("Restarting trading bot...")
    stop_bot()
    time.sleep(2)
    start_bot()


def bot_status():
    """Show bot status"""
    print_info("Checking bot status...")
    is_running, pid = get_bot_status()

    if is_running:
        print_success(f"Bot is running (PID: {pid})")

        # Get additional info
        try:
            import psutil
            p = psutil.Process(int(pid))
            cpu = p.cpu_percent(interval=1)
            mem = p.memory_info().rss / 1024 / 1024
            uptime = datetime.now() - datetime.fromtimestamp(p.create_time())

            print(f"  CPU: {cpu:.1f}%")
            print(f"  Memory: {mem:.1f} MB")
            print(f"  Uptime: {uptime}")
        except (ImportError, psutil.NoSuchProcess, ValueError):
            pass
    else:
        print_warning("Bot is not running")


def enable_bot():
    """Enable bot to start on system boot"""
    print_info("Enabling bot autostart...")
    # This would typically add to systemd or crontab
    print_warning("Autostart configuration requires manual setup")
    print("Add to crontab: @reboot cd /path/to/bot && python3 src/main.py")


def disable_bot():
    """Disable bot autostart"""
    print_info("Disabling bot autostart...")
    print_warning("Remove from crontab or systemd manually")


def update_bot():
    """Update bot from git repository"""
    print_info("Updating bot from repository...")

    project_root = Path(__file__).parent.parent

    # Check if git repo
    if not (project_root / ".git").exists():
        print_error("Not a git repository!")
        return

    # Stash local changes
    print_info("Stashing local changes...")
    run_command(f"cd {project_root} && git stash")

    # Pull latest
    print_info("Pulling latest changes...")
    if run_command(f"cd {project_root} && git pull"):
        print_success("Repository updated")

        # Update dependencies
        print_info("Installing dependencies...")
        if run_command(f"cd {project_root} && pip3 install -q -r requirements.txt"):
            print_success("Dependencies updated")

            # Restart bot
            print_info("Restarting bot...")
            restart_bot()
        else:
            print_error("Failed to update dependencies")
    else:
        print_error("Failed to pull updates")


def change_git_source():
    """Change git repository source"""
    print_info("Change Git Repository Source")
    print()

    current_remote = run_command("git remote get-url origin", show_output=False)
    if current_remote:
        print(f"Current remote: {Colors.CYAN}{current_remote}{Colors.NC}")

    print()
    new_url = input("Enter new repository URL (or press Enter to cancel): ").strip()

    if not new_url:
        print_warning("Operation cancelled")
        return

    # Basic URL validation
    if not (new_url.startswith('https://') or new_url.startswith('git@')):
        print_error("Invalid URL format. Must start with https:// or git@")
        return

    # Use subprocess with list arguments for safety
    try:
        subprocess.run(['git', 'remote', 'set-url', 'origin', new_url],
                       capture_output=True, text=True, check=True)
        print_success("Repository URL updated")
        new_remote = run_command("git remote get-url origin", show_output=False)
        print(f"New remote: {Colors.CYAN}{new_remote}{Colors.NC}")
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to update repository URL: {e}")


def view_logs(live=False, lines=50, search=None):
    """View bot logs"""
    project_root = Path(__file__).parent.parent
    log_file = project_root / "logs" / "bot.log"

    if not log_file.exists():
        print_error("Log file not found!")
        return

    if live:
        print_info("Viewing live logs (Ctrl+C to stop)...")
        print("=" * 80)
        run_command(f"tail -f {log_file}")
    elif search:
        # Sanitize search term for shell safety
        safe_search = search.replace("'", "'\\''")
        print_info(f"Searching for: {search}")
        print("=" * 80)
        run_command(f"grep --color=always -i '{safe_search}' {log_file} | tail -n {lines}")
    else:
        print_info(f"Showing last {lines} lines...")
        print("=" * 80)
        run_command(f"tail -n {lines} {log_file}")


def quick_diagnostics():
    """Run quick diagnostics"""
    print_info("Running quick diagnostics...")
    print("=" * 80)

    # Bot status
    print(f"\n{Colors.BOLD}Bot Status:{Colors.NC}")
    is_running, pid = get_bot_status()
    status = f"{
        Colors.GREEN}Running{
        Colors.NC}" if is_running else f"{
            Colors.RED}Stopped{
                Colors.NC}"
    print(f"  Status: {status}")
    if pid:
        print(f"  PID: {pid}")

    # Disk space
    print(f"\n{Colors.BOLD}Disk Space:{Colors.NC}")
    run_command("df -h / | tail -1")

    # Memory
    print(f"\n{Colors.BOLD}Memory:{Colors.NC}")
    run_command("free -h | grep Mem")

    # Recent errors in log
    print(f"\n{Colors.BOLD}Recent Errors:{Colors.NC}")
    project_root = Path(__file__).parent.parent
    log_file = project_root / "logs" / "bot.log"
    if log_file.exists():
        run_command(f"grep -i error {log_file} | tail -5")
    else:
        print("  No log file found")


def edit_config():
    """Edit configuration file"""
    print_info("Opening configuration editor...")

    project_root = Path(__file__).parent.parent
    config_file = project_root / "config.yaml"

    if not config_file.exists():
        print_error("Configuration file not found!")
        return

    editor = os.environ.get('EDITOR', 'nano')
    run_command(f"{editor} {config_file}")


def interactive_menu():
    """Display interactive menu"""
    while True:
        os.system('clear' if os.name != 'nt' else 'cls')

        print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 70}{Colors.NC}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'Trading Bot - Administration Tool':^70}{Colors.NC}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 70}{Colors.NC}")

        # Show current status
        is_running, pid = get_bot_status()
        status = f"{
            Colors.GREEN}RUNNING{
            Colors.NC}" if is_running else f"{
            Colors.RED}STOPPED{
                Colors.NC}"
        print(f"\nCurrent Status: {status}")
        if pid:
            print(f"Process ID: {pid}")
        print()

        print(f"{Colors.BOLD}Bot Management:{Colors.NC}")
        print(f"  {Colors.GREEN}1{Colors.NC}. Start bot")
        print(f"  {Colors.YELLOW}2{Colors.NC}. Stop bot")
        print(f"  {Colors.CYAN}3{Colors.NC}. Restart bot")
        print(f"  {Colors.BLUE}4{Colors.NC}. Bot status")
        print(f"  {Colors.MAGENTA}5{Colors.NC}. Enable autostart")
        print(f"  {Colors.MAGENTA}6{Colors.NC}. Disable autostart")

        print(f"\n{Colors.BOLD}Updates & Configuration:{Colors.NC}")
        print(f"  {Colors.GREEN}7{Colors.NC}. Update bot (git pull & restart)")
        print(f"  {Colors.CYAN}8{Colors.NC}. Change git repository")
        print(f"  {Colors.BLUE}9{Colors.NC}. Edit configuration")

        print(f"\n{Colors.BOLD}Logs & Diagnostics:{Colors.NC}")
        print(f"  {Colors.GREEN}10{Colors.NC}. View live logs")
        print(f"  {Colors.CYAN}11{Colors.NC}. View last N lines")
        print(f"  {Colors.BLUE}12{Colors.NC}. Search logs")
        print(f"  {Colors.MAGENTA}13{Colors.NC}. Quick diagnostics")

        print(f"\n  {Colors.RED}0{Colors.NC}. Exit")
        print()

        choice = input(f"{Colors.BOLD}Select option: {Colors.NC}").strip()

        if choice == '1':
            start_bot()
            input("\nPress Enter to continue...")
        elif choice == '2':
            stop_bot()
            input("\nPress Enter to continue...")
        elif choice == '3':
            restart_bot()
            input("\nPress Enter to continue...")
        elif choice == '4':
            bot_status()
            input("\nPress Enter to continue...")
        elif choice == '5':
            enable_bot()
            input("\nPress Enter to continue...")
        elif choice == '6':
            disable_bot()
            input("\nPress Enter to continue...")
        elif choice == '7':
            update_bot()
            input("\nPress Enter to continue...")
        elif choice == '8':
            change_git_source()
            input("\nPress Enter to continue...")
        elif choice == '9':
            edit_config()
        elif choice == '10':
            try:
                view_logs(live=True)
            except KeyboardInterrupt:
                print("\n")
        elif choice == '11':
            lines = input("Number of lines (default 50): ").strip() or "50"
            view_logs(lines=int(lines))
            input("\nPress Enter to continue...")
        elif choice == '12':
            search = input("Search term: ").strip()
            if search:
                view_logs(search=search)
                input("\nPress Enter to continue...")
        elif choice == '13':
            quick_diagnostics()
            input("\nPress Enter to continue...")
        elif choice == '0':
            print_info("Goodbye!")
            break
        else:
            print_error("Invalid option!")
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(
        description='Trading Bot Administration Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Interactive menu
  %(prog)s --start            # Start bot
  %(prog)s --stop             # Stop bot
  %(prog)s --restart          # Restart bot
  %(prog)s --status           # Show status
  %(prog)s --update           # Update bot
  %(prog)s --logs             # View logs
  %(prog)s --logs --live      # Live log stream
  %(prog)s --logs --lines 100 # Last 100 lines
  %(prog)s --logs --search ERROR  # Search logs
        """
    )

    parser.add_argument('--start', action='store_true', help='Start the bot')
    parser.add_argument('--stop', action='store_true', help='Stop the bot')
    parser.add_argument('--restart', action='store_true', help='Restart the bot')
    parser.add_argument('--status', action='store_true', help='Show bot status')
    parser.add_argument('--enable', action='store_true', help='Enable autostart')
    parser.add_argument('--disable', action='store_true', help='Disable autostart')
    parser.add_argument('--update', action='store_true', help='Update bot from git')
    parser.add_argument('--logs', action='store_true', help='View logs')
    parser.add_argument('--live', action='store_true', help='View live logs')
    parser.add_argument('--lines', type=int, default=50, help='Number of log lines to show')
    parser.add_argument('--search', type=str, help='Search term in logs')
    parser.add_argument('--diagnostics', action='store_true', help='Run quick diagnostics')
    parser.add_argument('--config', action='store_true', help='Edit configuration')

    args = parser.parse_args()

    # If no arguments, show interactive menu
    if len(sys.argv) == 1:
        interactive_menu()
        return

    # Execute commands
    if args.start:
        start_bot()
    elif args.stop:
        stop_bot()
    elif args.restart:
        restart_bot()
    elif args.status:
        bot_status()
    elif args.enable:
        enable_bot()
    elif args.disable:
        disable_bot()
    elif args.update:
        update_bot()
    elif args.logs:
        view_logs(live=args.live, lines=args.lines, search=args.search)
    elif args.diagnostics:
        quick_diagnostics()
    elif args.config:
        edit_config()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Operation cancelled by user{Colors.NC}")
        sys.exit(0)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)
