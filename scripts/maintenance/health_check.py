#!/usr/bin/env python3
"""
Trading Bot - System Health Check Script
Performs comprehensive health checks on the trading bot system.
"""

import os
import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime

# Try to import psutil (optional dependency)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("⚠️  Warning: psutil not installed. System resource checks will be skipped.")
    print("   Install with: pip install psutil")
    print()


class Colors:
    """ANSI color codes"""
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'


class HealthChecker:
    """Health check manager"""

    def __init__(self):
        self.checks_passed = 0
        self.checks_failed = 0
        self.checks_warning = 0
        self.results = []

    def print_header(self):
        """Print header"""
        print("=" * 70)
        print("Trading Bot - System Health Check")
        print("=" * 70)
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

    def print_section(self, title):
        """Print section header"""
        print(f"\n{Colors.BLUE}{'=' * 70}{Colors.NC}")
        print(f"{Colors.BLUE}{title}{Colors.NC}")
        print(f"{Colors.BLUE}{'=' * 70}{Colors.NC}")

    def check_pass(self, name, message):
        """Record passed check"""
        self.checks_passed += 1
        self.results.append(("PASS", name, message))
        print(f"{Colors.GREEN}✓{Colors.NC} {name}: {message}")

    def check_fail(self, name, message):
        """Record failed check"""
        self.checks_failed += 1
        self.results.append(("FAIL", name, message))
        print(f"{Colors.RED}✗{Colors.NC} {name}: {message}")

    def check_warn(self, name, message):
        """Record warning"""
        self.checks_warning += 1
        self.results.append(("WARN", name, message))
        print(f"{Colors.YELLOW}⚠{Colors.NC} {name}: {message}")

    def check_system_resources(self):
        """Check system resource usage"""
        self.print_section("System Resources")

        if not PSUTIL_AVAILABLE:
            self.check_warn("System Resources", "psutil not installed - skipping resource checks")
            self.check_warn("Installation", "Run: pip install psutil")
            return

        # CPU usage
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent < 80:
                self.check_pass("CPU Usage", f"{cpu_percent}%")
            elif cpu_percent < 90:
                self.check_warn("CPU Usage", f"{cpu_percent}% (High)")
            else:
                self.check_fail("CPU Usage", f"{cpu_percent}% (Critical)")
        except Exception as e:
            self.check_fail("CPU Usage", f"Error: {str(e)}")

        # Memory usage
        try:
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_available_gb = memory.available / (1024**3)

            if memory_percent < 80:
                self.check_pass(
                    "Memory Usage", f"{memory_percent}% ({
                        memory_available_gb:.2f}GB available)")
            elif memory_percent < 90:
                self.check_warn(
                    "Memory Usage", f"{memory_percent}% ({
                        memory_available_gb:.2f}GB available)")
            else:
                self.check_fail(
                    "Memory Usage", f"{memory_percent}% ({
                        memory_available_gb:.2f}GB available)")
        except Exception as e:
            self.check_fail("Memory Usage", f"Error: {str(e)}")

        # Disk usage
        try:
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            disk_free_gb = disk.free / (1024**3)

            if disk_percent < 80:
                self.check_pass("Disk Usage", f"{disk_percent}% ({disk_free_gb:.2f}GB free)")
            elif disk_percent < 90:
                self.check_warn("Disk Usage", f"{disk_percent}% ({disk_free_gb:.2f}GB free)")
            else:
                self.check_fail("Disk Usage", f"{disk_percent}% ({disk_free_gb:.2f}GB free)")
        except Exception as e:
            self.check_fail("Disk Usage", f"Error: {str(e)}")

    def check_directories(self):
        """Check required directories exist"""
        self.print_section("Directory Structure")

        required_dirs = {
            'APP_DIR': os.environ.get('APP_DIR', '/opt/trading-bot'),
            'DATA_DIR': os.environ.get('DATA_DIR', '/var/lib/trading-bot'),
            'LOG_DIR': os.environ.get('LOG_DIR', '/var/log/trading-bot'),
            'BACKUP_DIR': os.environ.get('BACKUP_DIR', '/var/backups/trading-bot'),
            'CONFIG_DIR': os.environ.get('CONFIG_DIR', '/etc/trading-bot'),
        }

        for name, path in required_dirs.items():
            if os.path.isdir(path):
                # Check permissions
                if os.access(path, os.R_OK | os.W_OK):
                    self.check_pass(name, f"{path} (readable/writable)")
                else:
                    self.check_warn(name, f"{path} (insufficient permissions)")
            else:
                self.check_fail(name, f"{path} (not found)")

    def check_configuration(self):
        """Check configuration files"""
        self.print_section("Configuration")

        config_dir = os.environ.get('CONFIG_DIR', '/etc/trading-bot')
        env_file = os.path.join(config_dir, '.env')

        if os.path.isfile(env_file):
            # Check file permissions (should be 600 for security)
            stat_info = os.stat(env_file)
            mode = oct(stat_info.st_mode)[-3:]

            if mode == '600':
                self.check_pass("Environment File", f"{env_file} (secure permissions)")
            else:
                self.check_warn("Environment File", f"{env_file} (insecure permissions: {mode})")

            # Check for required variables
            required_vars = ['BINANCE_API_KEY', 'BINANCE_API_SECRET']
            with open(env_file, 'r') as f:
                content = f.read()
                for var in required_vars:
                    pattern = f"{var}="
                    if pattern in content:
                        # Extract the value after the = sign
                        lines = content.split('\n')
                        for line in lines:
                            if line.startswith(pattern):
                                value = line[len(pattern):].strip()
                                if value and not value.startswith('your_'):
                                    self.check_pass(f"Config: {var}", "Set")
                                else:
                                    self.check_warn(f"Config: {var}", "Not configured")
                                break
                    else:
                        self.check_warn(f"Config: {var}", "Not found")
        else:
            self.check_fail("Environment File", f"{env_file} (not found)")

    def check_database(self):
        """Check database connectivity"""
        self.print_section("Database")

        db_type = os.environ.get('DB_TYPE', 'sqlite')

        if db_type == 'sqlite':
            db_path = os.environ.get('DB_PATH', '/var/lib/trading-bot/trading_bot.db')

            if os.path.isfile(db_path):
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    conn.close()

                    # Check file size
                    size_mb = os.path.getsize(db_path) / (1024**2)
                    self.check_pass("SQLite Database", f"{db_path} ({size_mb:.2f}MB)")
                except Exception as e:
                    self.check_fail("SQLite Database", f"Error: {str(e)}")
            else:
                self.check_warn("SQLite Database", f"{db_path} (not found - will be created)")
        else:
            self.check_warn("Database", f"Type: {db_type} (check not implemented)")

    def check_logs(self):
        """Check log files"""
        self.print_section("Logging")

        log_dir = os.environ.get('LOG_DIR', '/var/log/trading-bot')

        if os.path.isdir(log_dir):
            log_files = list(Path(log_dir).glob('*.log'))

            if log_files:
                total_size = sum(f.stat().st_size for f in log_files) / (1024**2)
                self.check_pass("Log Files", f"{len(log_files)} file(s), {total_size:.2f}MB total")

                # Check most recent log
                if log_files:
                    recent_log = max(log_files, key=lambda f: f.stat().st_mtime)
                    age_hours = (time.time() - recent_log.stat().st_mtime) / 3600

                    if age_hours < 24:
                        self.check_pass(
                            "Recent Activity", f"Last log update: {
                                age_hours:.1f} hours ago")
                    else:
                        self.check_warn(
                            "Recent Activity", f"Last log update: {
                                age_hours:.1f} hours ago")
            else:
                self.check_warn("Log Files", "No log files found")
        else:
            self.check_fail("Log Directory", f"{log_dir} (not found)")

    def check_processes(self):
        """Check running processes"""
        self.print_section("Processes")

        app_name = os.environ.get('APP_NAME', 'trading-bot')
        found = False

        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if app_name in cmdline or 'trading' in cmdline.lower():
                    cpu = proc.cpu_percent(interval=0.1)
                    mem = proc.memory_info().rss / (1024**2)
                    self.check_pass(f"Process {proc.info['pid']}",
                                    f"CPU: {cpu:.1f}%, Memory: {mem:.1f}MB")
                    found = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not found:
            self.check_warn("Application Process", "Not running")

    def check_network(self):
        """Check network connectivity"""
        self.print_section("Network")

        # Check network interfaces
        interfaces = psutil.net_if_addrs()
        active_interfaces = [iface for iface in interfaces.keys() if iface != 'lo']

        if active_interfaces:
            self.check_pass("Network Interfaces", f"{len(active_interfaces)} active")
        else:
            self.check_fail("Network Interfaces", "No active interfaces found")

        # Check network connectivity
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            self.check_pass("Internet Connectivity", "OK")
        except OSError:
            self.check_fail("Internet Connectivity", "No connection")

    def check_backups(self):
        """Check backup status"""
        self.print_section("Backups")

        backup_dir = os.environ.get('BACKUP_DIR', '/var/backups/trading-bot')

        if os.path.isdir(backup_dir):
            backup_files = list(Path(backup_dir).glob('*.tar.gz'))

            if backup_files:
                most_recent = max(backup_files, key=lambda f: f.stat().st_mtime)
                age_hours = (time.time() - most_recent.stat().st_mtime) / 3600

                if age_hours < 24:
                    self.check_pass(
                        "Latest Backup", f"{
                            most_recent.name} ({
                            age_hours:.1f} hours old)")
                elif age_hours < 72:
                    self.check_warn(
                        "Latest Backup", f"{
                            most_recent.name} ({
                            age_hours:.1f} hours old)")
                else:
                    self.check_fail(
                        "Latest Backup", f"{
                            most_recent.name} ({
                            age_hours:.1f} hours old)")

                total_size = sum(f.stat().st_size for f in backup_files) / (1024**3)
                self.check_pass(
                    "Backup Files", f"{
                        len(backup_files)} file(s), {
                        total_size:.2f}GB total")
            else:
                self.check_warn("Backups", "No backups found")
        else:
            self.check_fail("Backup Directory", f"{backup_dir} (not found)")

    def print_summary(self):
        """Print health check summary"""
        print()
        print("=" * 70)
        print("Health Check Summary")
        print("=" * 70)

        total = self.checks_passed + self.checks_failed + self.checks_warning

        print(f"{Colors.GREEN}Passed:{Colors.NC}  {self.checks_passed}/{total}")
        print(f"{Colors.YELLOW}Warnings:{Colors.NC} {self.checks_warning}/{total}")
        print(f"{Colors.RED}Failed:{Colors.NC}  {self.checks_failed}/{total}")
        print()

        if self.checks_failed == 0 and self.checks_warning == 0:
            print(f"{Colors.GREEN}System Status: HEALTHY{Colors.NC}")
            return 0
        elif self.checks_failed == 0:
            print(f"{Colors.YELLOW}System Status: HEALTHY (with warnings){Colors.NC}")
            return 0
        else:
            print(f"{Colors.RED}System Status: UNHEALTHY{Colors.NC}")
            return 1

    def run_all_checks(self):
        """Run all health checks"""
        self.print_header()

        try:
            self.check_system_resources()
            self.check_directories()
            self.check_configuration()
            self.check_database()
            self.check_logs()
            self.check_processes()
            self.check_network()
            self.check_backups()
        except Exception as e:
            print(f"\n{Colors.RED}Error running health checks: {str(e)}{Colors.NC}")
            return 1

        return self.print_summary()


def main():
    """Main entry point"""
    checker = HealthChecker()
    exit_code = checker.run_all_checks()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
