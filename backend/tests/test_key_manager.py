"""
Unit Tests for Master Key Lifecycle Manager
Tests generation, self-test verification, corruption rejection, and encrypted backup/restore.
"""
import pytest
from pathlib import Path

from backend.app.core.key_manager import (
    MasterKeyManager,
    KeyValidationError,
    KeyManagementError
)

def test_generate_and_load_master_key(temp_dir):
    """Verify Master Key is strictly 32 bytes (256 bits)."""
    key_path = temp_dir / ".test_key.key"
    mgr = MasterKeyManager(key_path=key_path)
    mgr.generate_master_key()

    assert key_path.exists()
    loaded_key = mgr.load_master_key()
    assert isinstance(loaded_key, bytes)
    assert len(loaded_key) == 32

def test_startup_self_test_success(test_key_manager):
    """Verify in-memory AEAD self-test passes on a valid key."""
    assert test_key_manager.startup_self_test() is True


def test_startup_self_test_fails_on_corrupt_key(temp_dir):
    """Verify self-test fails hard if the key file is truncated or corrupted."""
    key_path = temp_dir / ".corrupt.key"
    with open(key_path, "wb") as f:
        f.write(b"too_short_key_bytes")  # 19 bytes, invalid

    key_path.chmod(0o600)
    mgr = MasterKeyManager(key_path=key_path)
    with pytest.raises(KeyValidationError) as exc:
        mgr.load_master_key()
    assert "Invalid Master Key length" in str(exc.value)

def test_backup_and_restore_success(temp_dir, test_key_manager):
    """Verify key backup and recovery roundtrip with Argon2id passphrase."""
    backup_file = temp_dir / "backup.enc"
    passphrase = "CorrectSecurePassphrase2026!"

    original_key = test_key_manager.load_master_key()
    test_key_manager.backup_to_file(backup_file, passphrase)
    assert backup_file.exists()

    # Create a new manager targeting a new path and restore into it
    restore_path = temp_dir / ".restored_key.key"
    new_mgr = MasterKeyManager(key_path=restore_path)
    new_mgr.restore_from_file(backup_file, passphrase)

    restored_key = new_mgr.load_master_key()
    assert restored_key == original_key
    assert new_mgr.startup_self_test() is True

def test_restore_fails_with_incorrect_passphrase(temp_dir, test_key_manager):
    """Verify restore fails and raises KeyValidationError when given wrong passphrase."""
    backup_file = temp_dir / "backup.enc"
    test_key_manager.backup_to_file(backup_file, "ValidPassphrase12345!")

    restore_path = temp_dir / ".wrong_pw.key"
    new_mgr = MasterKeyManager(key_path=restore_path)

    with pytest.raises(KeyValidationError) as exc:
        new_mgr.restore_from_file(backup_file, "WrongIncorrectPassword999!")

    assert "Decryption failed" in str(exc.value)
    assert not restore_path.exists()  # Ensure corrupt key is never written

def test_backup_rejects_short_passphrase(temp_dir, test_key_manager):
    """Verify backup rejects passwords under 10 characters."""
    backup_file = temp_dir / "backup.enc"
    with pytest.raises(ValueError) as exc:
        test_key_manager.backup_to_file(backup_file, "short")
    assert "at least 10 characters" in str(exc.value)
