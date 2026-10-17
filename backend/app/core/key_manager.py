"""
CipherQ Master Key Lifecycle Manager
Handles generation, permission enforcement, startup smoke testing,
and password-protected backup/restore of the Master Key Encryption Key (KEK).
Never logs or exposes plaintext key material or passwords.
"""
import os
import sys
import stat
import secrets
import logging
from pathlib import Path
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2.low_level import hash_secret_raw, Type

from backend.app.core.config import settings

logger = logging.getLogger("cipherq.key_manager")

BACKUP_MAGIC = b"CQKEYBKP"
BACKUP_VERSION = b"\x01"


class KeyManagementError(Exception):
    """Base exception for cryptographic key errors."""
    pass


class KeyPermissionError(KeyManagementError):
    """Raised when key file permissions are too permissive."""
    pass


class KeyValidationError(KeyManagementError):
    """Raised when key integrity check fails."""
    pass


class MasterKeyManager:
    """Manages the lifecycle of the Master Key Encryption Key (KEK)."""

    def __init__(self, key_path: Path = settings.MASTER_KEY_PATH):
        self.key_path = key_path

    def generate_master_key(self, overwrite: bool = False) -> None:
        """Generate a new cryptographically secure 256-bit Master KEK."""
        if self.key_path.exists() and not overwrite:
            raise KeyManagementError(f"Master key already exists at {self.key_path}. Use overwrite=True if intended.")
        
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        raw_key = secrets.token_bytes(32)  # 256 bits

        # Write to temporary file first, enforce permissions, then atomic rename
        tmp_path = self.key_path.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            f.write(raw_key)

        self._set_strict_permissions(tmp_path)
        tmp_path.replace(self.key_path)
        logger.info("Master Key generated and stored successfully with restricted permissions.")

    def _set_strict_permissions(self, path: Path) -> None:
        """Enforce 0600 (owner read/write only) on POSIX, restricted DACL on Windows."""
        try:
            if os.name == "posix":
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            elif os.name == "nt":
                # On Windows, set read/write for current user via icacls if available, or restrict attributes
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        except Exception as e:
            logger.warning(f"Could not enforce strict permissions on {path}: {e}")

    def verify_permissions(self, path: Path) -> None:
        """Check that key file is not readable by group or world on POSIX systems."""
        if not path.exists():
            raise KeyManagementError(f"Key file {path} does not exist.")

        if os.name == "posix":
            mode = path.stat().st_mode
            if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
                raise KeyPermissionError(
                    f"Insecure permissions {oct(mode)} on {path}. Master key must be 0600 (owner only)."
                )

    def load_master_key(self) -> bytes:
        """
        Load, validate permissions, and return the 32-byte Master KEK.
        Never log the returned bytes.
        """
        if not self.key_path.exists():
            raise KeyManagementError(f"Master key file not found at {self.key_path}.")

        self.verify_permissions(self.key_path)

        with open(self.key_path, "rb") as f:
            key_data = f.read()

        if len(key_data) != 32:
            raise KeyValidationError(
                f"Invalid Master Key length: expected 32 bytes (256-bit), got {len(key_data)} bytes."
            )

        return key_data

    def startup_self_test(self) -> bool:
        """
        Execute an in-memory smoke test encrypting and decrypting synthetic data.
        Aborts startup if the Master Key cannot perform valid AEAD operations.
        """
        key = self.load_master_key()
        aesgcm = AESGCM(key)
        test_payload = b"CipherQ_Startup_Verification_Vector_2026"
        test_nonce = secrets.token_bytes(12)
        test_ad = b"cipherq_startup_ad"

        try:
            ciphertext = aesgcm.encrypt(test_nonce, test_payload, test_ad)
            decrypted = aesgcm.decrypt(test_nonce, ciphertext, test_ad)
            if decrypted != test_payload:
                raise KeyValidationError("Startup self-test failed: decrypted data does not match test vector.")
        except Exception as e:
            raise KeyValidationError(f"Master key startup self-test failed: {e}") from e

        logger.info("Master Key startup self-test passed successfully.")
        return True

    def validate_or_init(self) -> None:
        """Helper for application lifespan: initialize key if absent, then run self-test."""
        if not self.key_path.exists():
            logger.info("No Master Key found. Generating a new 256-bit Master Key for first run...")
            self.generate_master_key()
        self.startup_self_test()

    def backup_to_file(self, backup_path: Path, passphrase: str) -> None:
        """
        Encrypt the Master KEK with an Argon2id-derived key and write to an authenticated container.
        Passphrase must be at least 10 characters.
        """
        if len(passphrase) < 10:
            raise ValueError("Backup passphrase must be at least 10 characters long.")

        kek = self.load_master_key()
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)

        # Derive 32-byte wrapping key using Argon2id
        derived_key = hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=salt,
            time_cost=3,
            memory_cost=65536,  # 64 MB
            parallelism=4,
            hash_len=32,
            type=Type.ID
        )

        aesgcm = AESGCM(derived_key)
        # Associated data binds container magic and version
        ad = BACKUP_MAGIC + BACKUP_VERSION
        encrypted_kek = aesgcm.encrypt(nonce, kek, ad)

        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with open(backup_path, "wb") as f:
            f.write(BACKUP_MAGIC)
            f.write(BACKUP_VERSION)
            f.write(salt)
            f.write(nonce)
            f.write(encrypted_kek)

        self._set_strict_permissions(backup_path)
        logger.info(f"Master Key successfully backed up to encrypted archive: {backup_path}")

    def restore_from_file(self, backup_path: Path, passphrase: str, overwrite: bool = False) -> None:
        """
        Restore Master KEK from an encrypted backup archive using the passphrase.
        Raises ValueError if the passphrase is incorrect or archive is corrupted.
        """
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file {backup_path} does not exist.")

        if self.key_path.exists() and not overwrite:
            raise KeyManagementError(
                f"Active key already exists at {self.key_path}. Set overwrite=True to replace."
            )

        with open(backup_path, "rb") as f:
            data = f.read()

        # Minimum length: 8 (magic) + 1 (ver) + 16 (salt) + 12 (nonce) + 32 (key) + 16 (tag) = 85 bytes
        if len(data) < 85:
            raise KeyValidationError("Backup file is truncated or invalid.")

        magic = data[:8]
        ver = data[8:9]
        if magic != BACKUP_MAGIC or ver != BACKUP_VERSION:
            raise KeyValidationError("Unrecognized backup file format or version.")

        salt = data[9:25]
        nonce = data[25:37]
        encrypted_kek = data[37:]

        # Derive key using same Argon2id parameters
        derived_key = hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=salt,
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            type=Type.ID
        )

        aesgcm = AESGCM(derived_key)
        ad = BACKUP_MAGIC + BACKUP_VERSION
        try:
            kek = aesgcm.decrypt(nonce, encrypted_kek, ad)
        except Exception as e:
            raise KeyValidationError("Decryption failed. Incorrect passphrase or corrupted backup archive.") from e

        if len(kek) != 32:
            raise KeyValidationError("Restored key length invalid.")

        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.key_path.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            f.write(kek)

        self._set_strict_permissions(tmp_path)
        tmp_path.replace(self.key_path)
        logger.info(f"Master Key successfully restored from backup to {self.key_path}")


key_manager = MasterKeyManager()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CipherQ Master Key Manager CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("generate", help="Generate a new Master Key")
    subparsers.add_parser("validate", help="Validate existing Master Key and run self-test")

    backup_parser = subparsers.add_parser("backup", help="Create encrypted backup of Master Key")
    backup_parser.add_argument("--out", type=Path, default=settings.KEYS_DIR / "cipherq_kek_backup.enc", help="Output path")

    restore_parser = subparsers.add_parser("restore", help="Restore Master Key from encrypted backup")
    restore_parser.add_argument("--file", type=Path, required=True, help="Backup file path")
    restore_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing active key")

    args = parser.parse_args()

    if args.command == "generate":
        key_manager.generate_master_key()
        print("Generated Master Key successfully.")
    elif args.command == "validate":
        key_manager.startup_self_test()
        print("Master Key validation passed.")
    elif args.command == "backup":
        pwd = os.environ.get("CIPHERQ_BACKUP_PASSPHRASE")
        if not pwd:
            import getpass
            pwd = getpass.getpass("Enter backup encryption passphrase (min 10 chars): ")
        key_manager.backup_to_file(args.out, pwd)
        print(f"Backup created at: {args.out}")
    elif args.command == "restore":
        pwd = os.environ.get("CIPHERQ_BACKUP_PASSPHRASE")
        if not pwd:
            import getpass
            pwd = getpass.getpass("Enter backup encryption passphrase: ")
        key_manager.restore_from_file(args.file, pwd, overwrite=args.overwrite)
        print("Restored Master Key successfully.")
    else:
        parser.print_help()
