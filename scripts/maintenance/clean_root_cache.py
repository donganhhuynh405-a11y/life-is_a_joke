#!/usr/bin/env python3
"""
Clean /root Cache Directories
Safely removes cache files from /root to free up disk space
"""

import os
import sys
import subprocess
import shutil


def get_dir_size(path):
    """Get directory size in bytes"""
    try:
        result = subprocess.run(
            ['du', '-sb', path],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0])
    except Exception:
        pass
    return 0


def format_size(bytes_size):
    """Format bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


def clean_cache_directory(cache_dir, dry_run=False):
    """Clean a cache directory"""
    if not os.path.exists(cache_dir):
        print(f"  ⚠️  {cache_dir} does not exist")
        return 0

    size_before = get_dir_size(cache_dir)

    if size_before == 0:
        print(f"  ℹ️  {cache_dir} is already empty")
        return 0

    print(f"  📂 {cache_dir}: {format_size(size_before)}")

    if dry_run:
        print(f"     [DRY RUN] Would delete {format_size(size_before)}")
        return size_before

    try:
        # Remove all contents but keep the directory
        for item in os.listdir(cache_dir):
            item_path = os.path.join(cache_dir, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            except Exception as e:
                print(f"     ⚠️  Could not delete {item}: {e}")

        size_after = get_dir_size(cache_dir)
        freed = size_before - size_after
        print(f"     ✅ Freed {format_size(freed)}")
        return freed

    except Exception as e:
        print(f"     ❌ Error cleaning {cache_dir}: {e}")
        return 0


def main():
    """Main function"""
    print("=" * 60)
    print("🧹 ROOT CACHE CLEANUP")
    print("=" * 60)
    print()

    # Check if running as root
    if os.geteuid() != 0:
        print("⚠️  This script should be run with sudo for full access")
        print()

    # Define cache directories to clean
    cache_dirs = [
        "/root/.cache",
        "/root/.npm",
        "/root/.pip",
        "/root/.local/share/Trash",
    ]

    # Check for dry run
    dry_run = '--dry-run' in sys.argv
    auto_confirm = '--yes' in sys.argv or '-y' in sys.argv

    if dry_run:
        print("🔍 DRY RUN MODE - No files will be deleted")
        print()

    # Analyze what will be cleaned
    print("📊 Analysis:")
    print()
    total_to_free = 0

    for cache_dir in cache_dirs:
        if os.path.exists(cache_dir):
            size = get_dir_size(cache_dir)
            if size > 0:
                print(f"  📂 {cache_dir}: {format_size(size)}")
                total_to_free += size

    print()
    print(f"💾 Total space to free: {format_size(total_to_free)}")
    print()

    if total_to_free == 0:
        print("✅ Nothing to clean!")
        return 0

    # Ask for confirmation
    if not dry_run and not auto_confirm:
        response = input("Proceed with cleanup? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print("❌ Cleanup cancelled")
            return 1

    # Clean caches
    print()
    print("🧹 Cleaning caches...")
    print()

    total_freed = 0
    for cache_dir in cache_dirs:
        freed = clean_cache_directory(cache_dir, dry_run)
        total_freed += freed

    # Additional cleanup
    print()
    print("🧹 Additional cleanup...")
    print()

    # Clean pip cache using pip command
    if not dry_run and shutil.which('pip'):
        print("  🐍 Cleaning pip cache...")
        try:
            subprocess.run(
                ['pip', 'cache', 'purge'],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print("     ✅ Pip cache purged")
        except Exception:
            print("     ⚠️  Could not purge pip cache")

    # Clean npm cache using npm command
    if not dry_run and shutil.which('npm'):
        print("  📦 Cleaning npm cache...")
        try:
            subprocess.run(
                ['npm', 'cache', 'clean', '--force'],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print("     ✅ NPM cache cleaned")
        except Exception:
            print("     ⚠️  Could not clean npm cache")

    # Find and remove core dumps
    print("  💾 Removing core dumps...")
    try:
        result = subprocess.run(
            ['find', '/root', '-name', 'core.*', '-type', 'f'],
            capture_output=True,
            text=True,
            check=False
        )
        core_files = result.stdout.strip().split('\n') if result.stdout.strip() else []

        if core_files and core_files[0]:
            for core_file in core_files:
                if os.path.exists(core_file):
                    size = os.path.getsize(core_file)
                    if not dry_run:
                        os.remove(core_file)
                    print(f"     ✅ Removed {core_file} ({format_size(size)})")
                    total_freed += size
        else:
            print("     ℹ️  No core dumps found")
    except Exception as e:
        print(f"     ⚠️  Could not remove core dumps: {e}")

    # Summary
    print()
    print("=" * 60)
    print("📊 CLEANUP SUMMARY")
    print("=" * 60)
    print()

    if dry_run:
        print(f"💾 Would free: {format_size(total_freed)}")
        print()
        print("Run without --dry-run to actually clean")
    else:
        print(f"✅ Total freed: {format_size(total_freed)}")
        print()
        print("💡 Additional recommendations:")
        print()
        print("  To free even more space, consider:")
        print("  • Remove old venv: sudo rm -rf /root/venv (if not in use)")
        print("  • Remove old installations: sudo rm -rf /root/trading-bot-setup")
        print("  • Clean systemd journal: sudo journalctl --vacuum-size=100M")

    print()
    print("=" * 60)
    print("✅ Cleanup complete!")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n❌ Cleanup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
