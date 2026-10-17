#!/usr/bin/env bash
# ==============================================================================
# CipherQ Automated Deployment Script
# Target: Debian 12 (Bookworm) / Arduino UNO Q (ARM Cortex-A53, 4GB RAM, 32GB eMMC)
#
# Usage:
#   sudo bash deployment/scripts/deploy.sh
# ==============================================================================

set -euo pipefail

CIPHERQ_USER="cipherq"
CIPHERQ_GROUP="cipherq"
INSTALL_DIR="/opt/cipherq"
CONFIG_DIR="/etc/cipherq"
LOG_DIR="/var/log/cipherq"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== [1/8] Checking Environment and Privileges ==="
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: deploy.sh must be executed with root privileges (sudo)." >&2
    exit 1
fi

# Detect architecture and OS
ARCH="$(uname -m)"
OS_NAME="unknown"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME="${ID} ${VERSION_ID}"
fi
echo "Host OS: ${OS_NAME}"
echo "Architecture: ${ARCH}"

echo "=== [2/8] Installing Required System Packages ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    sqlite3 \
    nginx \
    curl \
    openssl \
    libffi-dev \
    libssl-dev \
    build-essential

echo "=== [3/8] Provisioning Dedicated Service Account and Directories ==="
if ! id -u "${CIPHERQ_USER}" >/dev/null 2>&1; then
    useradd -r -s /usr/sbin/nologin -d "${INSTALL_DIR}" -c "CipherQ Vault Daemon" "${CIPHERQ_USER}"
    echo "Created system user '${CIPHERQ_USER}'."
else
    echo "System user '${CIPHERQ_USER}' already exists."
fi

mkdir -p "${INSTALL_DIR}/data/vault/orphans"
mkdir -p "${INSTALL_DIR}/keys"
mkdir -p "${INSTALL_DIR}/backups"
mkdir -p "${CONFIG_DIR}"
mkdir -p "${LOG_DIR}"

# Restrictive filesystem permissions
chmod 750 "${INSTALL_DIR}"
chmod 700 "${INSTALL_DIR}/data"
chmod 700 "${INSTALL_DIR}/data/vault"
chmod 700 "${INSTALL_DIR}/data/vault/orphans"
chmod 700 "${INSTALL_DIR}/keys"
chmod 700 "${INSTALL_DIR}/backups"
chmod 750 "${CONFIG_DIR}"
chmod 755 "${LOG_DIR}"

echo "=== [4/8] Installing Application Files ==="
# Synchronize backend, frontend, and deployment assets
cp -r "${REPO_ROOT}/backend" "${INSTALL_DIR}/"
cp -r "${REPO_ROOT}/frontend" "${INSTALL_DIR}/"

# Setup Python Virtual Environment
if [ ! -d "${INSTALL_DIR}/.venv" ]; then
    echo "Creating Python virtual environment at ${INSTALL_DIR}/.venv..."
    python3 -m venv "${INSTALL_DIR}/.venv"
fi

echo "Installing/updating Python dependencies..."
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip setuptools wheel
"${INSTALL_DIR}/.venv/bin/pip" install -r "${INSTALL_DIR}/backend/requirements.txt"

echo "=== [5/8] Configuring Environment and Master KEK ==="
if [ ! -f "${CONFIG_DIR}/cipherq.env" ]; then
    echo "Creating production environment file from template..."
    cp "${REPO_ROOT}/deployment/env/.env.example" "${CONFIG_DIR}/cipherq.env"
    
    # Generate secure random admin token
    ADMIN_HEX="$(openssl rand -hex 32)"
    sed -i "s/REPLACE_WITH_SECURE_RANDOM_HEX_64_CHARS/${ADMIN_HEX}/" "${CONFIG_DIR}/cipherq.env"
    echo "Generated random 256-bit ADMIN_TOKEN in ${CONFIG_DIR}/cipherq.env"
fi

chmod 600 "${CONFIG_DIR}/cipherq.env"
chown -R "${CIPHERQ_USER}:${CIPHERQ_GROUP}" "${INSTALL_DIR}" "${CONFIG_DIR}" "${LOG_DIR}"

# Initialize Master KEK if not present
MASTER_KEY="${INSTALL_DIR}/keys/.vault_master.key"
if [ ! -f "${MASTER_KEY}" ]; then
    echo "Initializing new 256-bit Master Key Encryption Key (KEK)..."
    sudo -u "${CIPHERQ_USER}" env PYTHONPATH="${INSTALL_DIR}" "${INSTALL_DIR}/.venv/bin/python3" -m backend.app.core.key_manager generate
fi
chmod 600 "${MASTER_KEY}"

# Validate Master Key with in-memory self-test
echo "Running Master Key startup self-test..."
sudo -u "${CIPHERQ_USER}" env PYTHONPATH="${INSTALL_DIR}" "${INSTALL_DIR}/.venv/bin/python3" -m backend.app.core.key_manager validate

echo "=== [6/8] Configuring Systemd Unit ==="
cp "${REPO_ROOT}/deployment/systemd/cipherq.service" /etc/systemd/system/cipherq.service
systemctl daemon-reload
systemctl enable cipherq.service
systemctl restart cipherq.service

echo "=== [7/8] Configuring Nginx Reverse Proxy & TLS Stub ==="
# Ensure SSL directory exists
mkdir -p /etc/ssl/certs /etc/ssl/private

# Generate bootstrap self-signed certificate if none exists
if [ ! -f /etc/ssl/certs/cipherq.crt ] || [ ! -f /etc/ssl/private/cipherq.key ]; then
    echo "Generating temporary self-signed TLS certificate for bootstrap (replace with mkcert or real CA)..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/ssl/private/cipherq.key \
        -out /etc/ssl/certs/cipherq.crt \
        -subj "/CN=cipherq.local/O=CipherQ/C=US" >/dev/null 2>&1
    chmod 600 /etc/ssl/private/cipherq.key
fi

cp "${REPO_ROOT}/deployment/nginx/cipherq.conf" /etc/nginx/sites-available/cipherq.conf
ln -sf /etc/nginx/sites-available/cipherq.conf /etc/nginx/sites-enabled/cipherq.conf

# Remove default nginx welcome site if present
rm -f /etc/nginx/sites-enabled/default

# Verify nginx config and reload
nginx -t
systemctl restart nginx

echo "=== [8/8] Verifying Service Health ==="
sleep 2
HEALTH_URL="http://127.0.0.1:8000/api/v1/health"
HTTP_STATUS="$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_URL}" || echo "000")"

if [ "${HTTP_STATUS}" -eq 200 ]; then
    echo "SUCCESS: CipherQ service is healthy and responding (HTTP 200)!"
    echo "Backend:  http://127.0.0.1:8000 (Internal loopback only)"
    echo "Nginx:    https://cipherq.local (LAN Reverse Proxy with TLS)"
    echo "Logs:     journalctl -u cipherq.service -f"
else
    echo "WARNING: Service check returned HTTP ${HTTP_STATUS}. Inspect logs with: journalctl -u cipherq.service -n 50"
fi

echo "=== Deployment Completed Successfully ==="
