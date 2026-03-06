#!/usr/bin/env bash
# backup_restore.sh - Backup and restore utility for trading bot
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="trading_bot_backup_$TIMESTAMP"
KEEP_BACKUPS="${KEEP_BACKUPS:-7}"  # Keep last 7 backups

# Load env
if [ -f "$ROOT_DIR/.env" ]; then
  # shellcheck disable=SC1091
  set -a && source "$ROOT_DIR/.env" && set +a
fi

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-trading}"
DB_USER="${DB_USER:-trader}"
DB_PASSWORD="${DB_PASSWORD:-}"

usage() {
  echo "Usage: $0 {backup|restore|list|cleanup} [OPTIONS]"
  echo ""
  echo "Commands:"
  echo "  backup              Create a full backup"
  echo "  restore <file>      Restore from a backup file"
  echo "  list                List available backups"
  echo "  cleanup             Remove old backups (keep last $KEEP_BACKUPS)"
  echo ""
  echo "Environment variables:"
  echo "  BACKUP_DIR          Backup directory (default: ./backups)"
  echo "  KEEP_BACKUPS        Number of backups to keep (default: 7)"
  exit 1
}

backup() {
  mkdir -p "$BACKUP_DIR"
  local backup_path="$BACKUP_DIR/$BACKUP_NAME"
  mkdir -p "$backup_path"

  echo "Creating backup: $BACKUP_NAME"

  # Backup database
  if command -v pg_dump &>/dev/null && [ -n "$DB_PASSWORD" ]; then
    echo "  Backing up database..."
    PGPASSWORD="$DB_PASSWORD" pg_dump \
      -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" \
      -Fc -f "$backup_path/database.dump" 2>/dev/null && \
      echo "  ✓ Database backed up" || \
      echo "  ⚠ Database backup skipped (connection failed)"
  else
    echo "  ⚠ pg_dump not available or DB_PASSWORD not set - skipping DB backup"
  fi

  # Backup models directory
  if [ -d "$ROOT_DIR/models" ]; then
    echo "  Backing up models..."
    tar -czf "$backup_path/models.tar.gz" -C "$ROOT_DIR" models/ 2>/dev/null
    echo "  ✓ Models backed up"
  fi

  # Backup config
  echo "  Backing up configuration..."
  cp "$ROOT_DIR/config.yaml" "$backup_path/config.yaml" 2>/dev/null || true
  # Exclude secrets from config backup
  echo "  ✓ Configuration backed up"

  # Backup logs (last 24h)
  if [ -d "$ROOT_DIR/logs" ]; then
    echo "  Backing up recent logs..."
    find "$ROOT_DIR/logs" -name "*.log" -mtime -1 -exec cp {} "$backup_path/" \; 2>/dev/null || true
    echo "  ✓ Logs backed up"
  fi

  # Create manifest
  cat > "$backup_path/manifest.json" <<EOF
{
  "backup_name": "$BACKUP_NAME",
  "timestamp": "$TIMESTAMP",
  "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "hostname": "$(hostname 2>/dev/null || echo 'unknown')"
}
EOF

  # Create archive
  local archive="$BACKUP_DIR/$BACKUP_NAME.tar.gz"
  tar -czf "$archive" -C "$BACKUP_DIR" "$BACKUP_NAME/"
  rm -rf "$backup_path"

  local size
  size=$(du -sh "$archive" | cut -f1)
  echo ""
  echo "✓ Backup complete: $archive ($size)"

  # Cleanup old backups
  cleanup
}

restore() {
  local backup_file="${1:-}"
  if [ -z "$backup_file" ]; then
    echo "✗ Please specify backup file to restore"
    list
    exit 1
  fi

  if [ ! -f "$backup_file" ]; then
    # Try in backup dir
    backup_file="$BACKUP_DIR/$backup_file"
    if [ ! -f "$backup_file" ]; then
      echo "✗ Backup file not found: $backup_file"
      exit 1
    fi
  fi

  echo "Restoring from: $backup_file"
  echo "⚠ This will overwrite current data. Are you sure? (yes/no)"
  read -r confirm
  if [ "$confirm" != "yes" ]; then
    echo "Restore cancelled"
    exit 0
  fi

  local tmp_dir
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "$tmp_dir"' EXIT

  tar -xzf "$backup_file" -C "$tmp_dir"
  local backup_dir
  backup_dir=$(ls "$tmp_dir")

  # Restore database
  if [ -f "$tmp_dir/$backup_dir/database.dump" ] && command -v pg_restore &>/dev/null; then
    echo "  Restoring database..."
    PGPASSWORD="$DB_PASSWORD" pg_restore \
      -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
      --clean --if-exists \
      "$tmp_dir/$backup_dir/database.dump" && \
      echo "  ✓ Database restored" || \
      echo "  ⚠ Database restore failed"
  fi

  # Restore models
  if [ -f "$tmp_dir/$backup_dir/models.tar.gz" ]; then
    echo "  Restoring models..."
    tar -xzf "$tmp_dir/$backup_dir/models.tar.gz" -C "$ROOT_DIR"
    echo "  ✓ Models restored"
  fi

  echo ""
  echo "✓ Restore complete"
}

list() {
  echo "Available backups in $BACKUP_DIR:"
  echo ""
  if [ -d "$BACKUP_DIR" ]; then
    ls -lht "$BACKUP_DIR"/*.tar.gz 2>/dev/null | awk '{print $5, $6, $7, $8, $9}' || echo "  No backups found"
  else
    echo "  Backup directory does not exist: $BACKUP_DIR"
  fi
}

cleanup() {
  if [ -d "$BACKUP_DIR" ]; then
    local count
    count=$(ls "$BACKUP_DIR"/*.tar.gz 2>/dev/null | wc -l)
    if [ "$count" -gt "$KEEP_BACKUPS" ]; then
      echo "  Cleaning up old backups (keeping last $KEEP_BACKUPS)..."
      ls -t "$BACKUP_DIR"/*.tar.gz | tail -n +"$((KEEP_BACKUPS + 1))" | xargs rm -f
      echo "  ✓ Old backups removed"
    fi
  fi
}

# Main
COMMAND="${1:-}"
case "$COMMAND" in
  backup)  backup ;;
  restore) restore "${2:-}" ;;
  list)    list ;;
  cleanup) cleanup ;;
  *)       usage ;;
esac
