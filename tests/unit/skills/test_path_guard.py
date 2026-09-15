"""
Unit tests for PathGuard.
Verifies syntax checks, Windows drive letters vs ADS, UNC paths, reserved device names,
ancestor validation, protected locations, extension allowlists, and pre-action checks.
"""

import os
import sys
import tempfile
from pathlib import Path
import pytest

from nova.skills.files.path_guard import (
    PathGuard,
    PathSecurityError,
    OperationType,
    is_reparse_point,
    ALLOWED_OPEN_EXTENSIONS,
    FORBIDDEN_OPEN_EXTENSIONS,
    _get_nova_repo_root,
)


def test_valid_drive_letters_accepted():
    # Valid Windows drive letter prefixes must not be treated as ADS
    PathGuard.validate_syntax(r"C:\Users\John\Documents\file.txt")
    PathGuard.validate_syntax(r"D:/Projects/Nova/README.md")
    PathGuard.validate_syntax(r"c:\temp\log.txt")


def test_alternate_data_stream_rejected():
    with pytest.raises(PathSecurityError, match="ADS"):
        PathGuard.validate_syntax(r"file.txt:stream")

    with pytest.raises(PathSecurityError, match="ADS"):
        PathGuard.validate_syntax(r"C:\Users\John\file.txt:stream")

    with pytest.raises(PathSecurityError, match="ADS"):
        PathGuard.validate_syntax(r"C:\file.txt:stream:extra")


def test_null_bytes_and_control_chars_rejected():
    with pytest.raises(PathSecurityError, match="null byte"):
        PathGuard.validate_syntax("test\0file.txt")

    with pytest.raises(PathSecurityError, match="control character"):
        PathGuard.validate_syntax("test\x07file.txt")

    with pytest.raises(PathSecurityError, match="control character"):
        PathGuard.validate_syntax("test\x1ffile.txt")


def test_unc_paths_rejected():
    with pytest.raises(PathSecurityError, match="UNC network paths are forbidden"):
        PathGuard.validate_syntax(r"\\192.168.1.1\share\secret.txt")

    with pytest.raises(PathSecurityError, match="UNC network paths are forbidden"):
        PathGuard.validate_syntax(r"\\localhost\c$\Windows")

    with pytest.raises(PathSecurityError, match="UNC network paths are forbidden"):
        PathGuard.validate_syntax("//server/share/file.txt")


def test_device_namespaces_rejected():
    with pytest.raises(PathSecurityError, match="Device namespaces are forbidden"):
        PathGuard.validate_syntax(r"\\.\COM1")

    with pytest.raises(PathSecurityError, match="Device namespaces are forbidden"):
        PathGuard.validate_syntax(r"\\?\C:\Windows")


def test_reserved_dos_device_names_rejected():
    for dev in ("CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"):
        with pytest.raises(PathSecurityError, match="reserved DOS device name"):
            PathGuard.validate_syntax(f"C:\\temp\\{dev}")

        with pytest.raises(PathSecurityError, match="reserved DOS device name"):
            PathGuard.validate_syntax(f"C:\\temp\\{dev}.txt")

        with pytest.raises(PathSecurityError, match="reserved DOS device name"):
            PathGuard.validate_syntax(f"C:\\temp\\subfolder\\{dev.lower()}\\file.txt")


def test_protected_system_paths_rejected_for_write_and_delete():
    with pytest.raises(PathSecurityError, match="protected system directory"):
        PathGuard.validate_safe_path(
            r"C:\Windows\System32\cmd.exe",
            operation=OperationType.WRITE,
            allow_nonexistent=True,
        )

    with pytest.raises(PathSecurityError, match="protected system directory"):
        PathGuard.validate_safe_path(
            r"C:\Program Files\App\test.txt",
            operation=OperationType.DELETE,
            allow_nonexistent=True,
        )

    with pytest.raises(PathSecurityError, match="protected system directory"):
        PathGuard.validate_safe_path(
            r"C:\ProgramData\secret.dat",
            operation=OperationType.WRITE,
            allow_nonexistent=True,
        )


def test_drive_root_protected():
    with pytest.raises(PathSecurityError, match="protected system directory"):
        PathGuard.validate_safe_path(
            r"C:\\",
            operation=OperationType.DELETE,
            allow_nonexistent=True,
        )


def test_open_extension_validation():
    # Allowed
    for ext in (".txt", ".pdf", ".py", ".docx", ".png", ".jpg", ".csv", ".json", ".log"):
        PathGuard.validate_open_extension(Path(f"test{ext}"))

    # Explicit blacklist
    for ext in (".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".lnk", ".reg", ".msi"):
        with pytest.raises(PathSecurityError, match="Forbidden file type for open"):
            PathGuard.validate_open_extension(Path(f"test{ext}"))

    # Unlisted extension
    with pytest.raises(PathSecurityError, match="not in the safe open allowlist"):
        PathGuard.validate_open_extension(Path("test.unknownextension123"))

    # Missing extension
    with pytest.raises(PathSecurityError, match="without extension"):
        PathGuard.validate_open_extension(Path("no_extension_file"))


def test_safe_path_resolution_and_ancestors(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    target_file = sub / "data.txt"
    target_file.write_text("hello", encoding="utf-8")

    # Valid read
    res = PathGuard.validate_safe_path(str(target_file), operation=OperationType.READ)
    assert res == target_file.resolve()

    # Valid write allow nonexistent
    new_file = sub / "new_data.txt"
    res_new = PathGuard.validate_safe_path(str(new_file), operation=OperationType.WRITE, allow_nonexistent=True)
    assert res_new == new_file.resolve()


def test_pre_action_verification(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("abc", encoding="utf-8")

    # Safe delete pre-action verification
    PathGuard.pre_action_verify_file(f, OperationType.DELETE)

    # Deleting a folder via pre_action_verify_file should be rejected
    sub_dir = tmp_path / "folder"
    sub_dir.mkdir()
    with pytest.raises(PathSecurityError, match="Refusing to delete directory as file"):
        PathGuard.pre_action_verify_file(sub_dir, OperationType.DELETE)


def test_nova_project_root_mutation_rejected():
    nova_root = _get_nova_repo_root()
    assert nova_root is not None
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(nova_root),
            operation=OperationType.WRITE,
            allow_nonexistent=True,
        )
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(nova_root),
            operation=OperationType.DELETE,
            allow_nonexistent=True,
        )


def test_nova_src_mutation_rejected():
    nova_root = _get_nova_repo_root()
    assert nova_root is not None
    src_target = nova_root / "src" / "nova" / "dummy_payload.py"
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(src_target),
            operation=OperationType.WRITE,
            allow_nonexistent=True,
        )


def test_nova_tests_mutation_rejected():
    nova_root = _get_nova_repo_root()
    assert nova_root is not None
    test_target = nova_root / "tests" / "unit" / "test_dummy_payload.py"
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(test_target),
            operation=OperationType.WRITE,
            allow_nonexistent=True,
        )


def test_nova_git_mutation_rejected():
    nova_root = _get_nova_repo_root()
    assert nova_root is not None
    git_target = nova_root / ".git" / "config"
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(git_target),
            operation=OperationType.DELETE,
            allow_nonexistent=True,
        )


def test_nova_backup_not_rejected_for_prefix():
    nova_root = _get_nova_repo_root()
    assert nova_root is not None
    # A path like C:\Users\...\nova_backup must NOT be rejected merely because
    # its name starts with 'nova'
    sibling_backup = nova_root.parent / "nova_backup" / "data.txt"
    res = PathGuard.validate_safe_path(
        str(sibling_backup),
        operation=OperationType.WRITE,
        allow_nonexistent=True,
    )
    assert res == sibling_backup.resolve()


def test_userprofile_ssh_mutation_rejected():
    user_profile = os.environ.get("USERPROFILE") or str(Path.home())
    ssh_file = Path(user_profile) / ".ssh" / "id_rsa"
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(ssh_file),
            operation=OperationType.WRITE,
            allow_nonexistent=True,
        )
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(ssh_file),
            operation=OperationType.DELETE,
            allow_nonexistent=True,
        )


def test_userprofile_aws_mutation_rejected():
    user_profile = os.environ.get("USERPROFILE") or str(Path.home())
    aws_file = Path(user_profile) / ".aws" / "credentials"
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(aws_file),
            operation=OperationType.WRITE,
            allow_nonexistent=True,
        )
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(aws_file),
            operation=OperationType.DELETE,
            allow_nonexistent=True,
        )


def test_appdata_credentials_mutation_rejected():
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    cred_file = Path(appdata) / "Microsoft" / "Credentials" / "target.cred"
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(cred_file),
            operation=OperationType.WRITE,
            allow_nonexistent=True,
        )


def test_appdata_vault_mutation_rejected():
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    vault_file = Path(appdata) / "Microsoft" / "Vault" / "target.vlt"
    with pytest.raises(PathSecurityError, match="protected"):
        PathGuard.validate_safe_path(
            str(vault_file),
            operation=OperationType.DELETE,
            allow_nonexistent=True,
        )

