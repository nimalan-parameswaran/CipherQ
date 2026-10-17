#!/usr/bin/env bash
# ==============================================================================
# CipherQ Coordinated Backup Script
# Performs an atomic, skew-resistant backup of:
# 1. SQLite database (using atomic VACUUM INTO)
# 2. Encrypted Master Key Encryption Key (KEK container)
# 3. Encrypted vault ciphertext directory (/opt/cipherq/data/vault/*.cqenc)
#
# Usage:
#   sudo bash deployment/scripts/backup.sh [/path/to/backup/destination]
# Optional env var: CIPHERQ_BACKUP_PASSPHRASE
# ==============================================================================

set -euo pipefail

INSTALL_DIR="/opt/cipherq"
DEFAULT_BACKUP_DIR="${INSTALL_DIR}/backups"
BACKUP_DEST="${1:-${DEFAULT_BACKUP_DIR}}"
TIMESTAMP="$(date +'%Y%m%d_%H%M%S')"
BACKUP_ID="cipherq_backup_${TIMESTAMP}"
STAGING_DIR="/tmp/${BACKUP_ID}"
FINAL_TAR="${BACKUP_DEST}/${BACKUP_ID}.tar.gz"

echo "=== [1/5] Initializing CipherQ Backup (${BACKUP_ID}) ==="
mkdir -p "${BACKUP_DEST}"
mkdir -p "${STAGING_DIR}/vault"
chmod 700 "${STAGING_DIR}"

# 1. Atomic SQLite Snapshot
echo "Creating transactionally consistent SQLite snapshot..."
DB_PATH="${INSTALL_DIR}/data/cipherq.db"
if [ -f "${DB_PATH}" ]; then
    # SQLite VACUUM INTO creates an atomic, read-consistent copy of the database
    sqlite3 "${DB_PATH}" "VACUUM INTO '${STAGING_DIR}/cipherq.db';"
    echo "SQLite database safely snapshotted."
else
    echo "WARNING: SQLite database not found at ${DB_PATH}. Skipping DB backup."
fi

# 2. Encrypted Master Key Export
echo "Exporting encrypted Master Key (KEK)..."
KEK_BACKUP_PATH="${STAGING_DIR}/cipherq_kek_backup.enc"
if [ -z "${CIPHERQ_BACKUP_PASSPHRASE:-}" ]; then
    echo "Enter passphrase to encrypt the Master Key backup (min 10 characters):"
    read -r -s CIPHERQ_BACKUP_PASSPHRASE
    export CIPHERQ_BACKUP_PASSPHRASE
fi

if [ ${#CIPHERQ_BACKUP_PASSPHRASE} -lt 10 ]; then
    echo "ERROR: Backup passphrase must be at least 10 characters." >&2
    rm -rf "${STAGING_DIR}"
    exit 1
fi

sudo -u cipherq env PYTHONPATH="${INSTALL_DIR}" CIPHERQ_BACKUP_PASSPHRASE="${CIPHERQ_BACKUP_PASSPHRASE}" "${INSTALL_DIR}/.venv/bin/python3" -m backend.app.core.key_manager backup --out "${KEK_BACKUP_PATH}"
echo "Encrypted Master Key backup written."

# 3. Vault Ciphertext Snapshot
echo "Copying encrypted vault files..."
VAULT_DIR="${INSTALL_DIR}/data/vault"
if [ -d "${VAULT_DIR}" ]; then
    # Use rsync or cp to copy active .cqenc files
    find "${VAULT_DIR}" -maxdepth 1 -name "*.cqenc" -exec cp {} "${STAGING_DIR}/vault/" \;
    FILE_COUNT="$(find "${STAGING_DIR}/vault" -name "*.cqenc" | wc -l)"
    echo "Archived ${FILE_COUNT} encrypted vault files."
fi

# 4. Generate SHA256 Integrity Manifest
echo "Generating cryptographic checksum manifest..."
(
    cd "${STAGING_DIR}"
    find . -type f ! -name "manifest.sha256" -exec sha256sum {} + > manifest.sha256
)

# 5. Archive and Compress
echo "Creating compressed backup archive at ${FINAL_TAR}..."
tar -czf "${FINAL_TAR}" -C "/tmp" "${BACKUP_ID}"
chmod 600 "${FINAL_TAR}"
chown cipherq:cipherq "${FINAL_TAR}"

# Clean up staging directory
rm -rf "${STAGING_DIR}"

echo "=== Backup Completed Successfully ==="
echo "Archive: ${FINAL_TAR}"
echo "Size:    $(du -h "${FINAL_TAR}" | cut -f1)"
