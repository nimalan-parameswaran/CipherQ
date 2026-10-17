#!/usr/bin/env bash
# ==============================================================================
# CipherQ Disaster Recovery / Restore Script
# Restores:
# 1. Master Key Encryption Key (KEK) via password-protected container
# 2. SQLite database with all user accounts, wrapped DEKs, and metadata
# 3. Encrypted vault ciphertext directory
#
# Usage:
#   sudo bash deployment/scripts/restore.sh /path/to/cipherq_backup_YYYYMMDD_HHMMSS.tar.gz
# Optional env var: CIPHERQ_BACKUP_PASSPHRASE
# ==============================================================================

set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: sudo $0 <path-to-cipherq-backup.tar.gz>" >&2
    exit 1
fi

BACKUP_TAR="$1"
INSTALL_DIR="/opt/cipherq"
RESTORE_ID="restore_$(date +'%Y%m%d_%H%M%S')"
STAGING_DIR="/tmp/${RESTORE_ID}"

if [ ! -f "${BACKUP_TAR}" ]; then
    echo "ERROR: Backup archive ${BACKUP_TAR} does not exist." >&2
    exit 1
fi

echo "=== [1/6] Extracting Backup Archive ==="
mkdir -p "${STAGING_DIR}"
chmod 700 "${STAGING_DIR}"
tar -xzf "${BACKUP_TAR}" -C "${STAGING_DIR}" --strip-components=1

echo "=== [2/6] Verifying Cryptographic Checksums ==="
if [ -f "${STAGING_DIR}/manifest.sha256" ]; then
    (
        cd "${STAGING_DIR}"
        sha256sum -c manifest.sha256
    )
    echo "Integrity verification passed."
else
    echo "WARNING: manifest.sha256 not found in backup. Proceeding with caution."
fi

echo "=== [3/6] Halting CipherQ Service for Restore ==="
systemctl stop cipherq.service || true

echo "=== [4/6] Restoring Master Key (KEK) ==="
KEK_BACKUP="${STAGING_DIR}/cipherq_kek_backup.enc"
if [ -f "${KEK_BACKUP}" ]; then
    if [ -z "${CIPHERQ_BACKUP_PASSPHRASE:-}" ]; then
        echo "Enter passphrase used to encrypt the backup Master Key:"
        read -r -s CIPHERQ_BACKUP_PASSPHRASE
        export CIPHERQ_BACKUP_PASSPHRASE
    fi
    sudo -u cipherq "${INSTALL_DIR}/.venv/bin/python3" -m backend.app.core.key_manager restore --file "${KEK_BACKUP}" --overwrite
    chmod 600 "${INSTALL_DIR}/keys/.vault_master.key"
    echo "Master Key successfully restored and verified with self-test."
else
    echo "WARNING: No encrypted KEK found in backup archive."
fi

echo "=== [5/6] Restoring Database and Encrypted Vault ==="
if [ -f "${STAGING_DIR}/cipherq.db" ]; then
    cp "${STAGING_DIR}/cipherq.db" "${INSTALL_DIR}/data/cipherq.db"
    chmod 600 "${INSTALL_DIR}/data/cipherq.db"
    echo "Restored SQLite database."
fi

if [ -d "${STAGING_DIR}/vault" ]; then
    mkdir -p "${INSTALL_DIR}/data/vault"
    find "${STAGING_DIR}/vault" -maxdepth 1 -name "*.cqenc" -exec cp {} "${INSTALL_DIR}/data/vault/" \;
    RESTORED_COUNT="$(find "${INSTALL_DIR}/data/vault" -name "*.cqenc" | wc -l)"
    echo "Restored ${RESTORED_COUNT} encrypted vault files."
fi

# Ensure correct file permissions
chown -R cipherq:cipherq "${INSTALL_DIR}/data" "${INSTALL_DIR}/keys"
chmod 700 "${INSTALL_DIR}/data" "${INSTALL_DIR}/data/vault" "${INSTALL_DIR}/keys"

# Clean up temporary staging
rm -rf "${STAGING_DIR}"

echo "=== [6/6] Restarting CipherQ Service and Validating ==="
systemctl start cipherq.service
sleep 2

HEALTH_URL="http://127.0.0.1:8000/api/v1/health"
HTTP_STATUS="$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_URL}" || echo "000")"

if [ "${HTTP_STATUS}" -eq 200 ]; then
    echo "SUCCESS: CipherQ restored and healthy (HTTP 200)!"
else
    echo "WARNING: Health check returned HTTP ${HTTP_STATUS}. Check logs: journalctl -u cipherq.service -n 50"
fi

echo "=== Disaster Recovery Restore Completed ==="
