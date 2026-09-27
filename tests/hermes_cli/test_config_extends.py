"""Regression tests for profile configuration inheritance via `extends:` directive."""

import os
from pathlib import Path
from unittest.mock import patch
import pytest

from hermes_cli import config as config_mod
from hermes_cli.config import (
    load_config,
    read_raw_config,
    read_raw_config_readonly,
    save_config,
    set_config_value,
    unset_config_value,
    show_config,
)
from hermes_cli.config_effective import load_user_config_effective
from hermes_cli.profiles import create_profile


@pytest.fixture(autouse=True)
def clear_caches():
    config_mod._CONFIG_EXTENDED_PATHS.clear()
    config_mod._LOAD_CONFIG_CACHE.clear()
    config_mod._RAW_CONFIG_CACHE.clear()
    from hermes_cli.config_effective import _EFFECTIVE_CACHE
    _EFFECTIVE_CACHE.clear()
    yield
    config_mod._CONFIG_EXTENDED_PATHS.clear()
    config_mod._LOAD_CONFIG_CACHE.clear()
    config_mod._RAW_CONFIG_CACHE.clear()
    _EFFECTIVE_CACHE.clear()


def test_single_extends_relative(tmp_path):
    """Test extending a base config file via a relative path."""
    base_file = tmp_path / "base.yaml"
    base_file.write_text(
        "model:\n"
        "  default: base-model-4\n"
        "terminal:\n"
        "  backend: docker\n"
        "  timeout: 45\n",
        encoding="utf-8",
    )

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(
        "extends: ../base.yaml\n"
        "terminal:\n"
        "  timeout: 90\n",
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        cfg = load_config()
        assert cfg["model"]["default"] == "base-model-4"
        assert cfg["terminal"]["backend"] == "docker"
        assert cfg["terminal"]["timeout"] == 90

        # read_raw_config also resolves extends
        raw = read_raw_config()
        assert raw["model"]["default"] == "base-model-4"
        assert raw["terminal"]["backend"] == "docker"
        assert raw["terminal"]["timeout"] == 90
        assert raw["extends"] == "../base.yaml"

        # load_user_config_effective resolves extends
        effective = load_user_config_effective()
        assert effective["model"]["default"] == "base-model-4"
        assert effective["terminal"]["backend"] == "docker"
        assert effective["terminal"]["timeout"] == 90


def test_single_extends_absolute_and_tilde(tmp_path):
    """Test extending via absolute and tilde paths."""
    base_file = tmp_path / "base.yaml"
    base_file.write_text("model:\n  default: base-model-abs\n", encoding="utf-8")

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(f"extends: {base_file}\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        cfg = load_config()
        assert cfg["model"]["default"] == "base-model-abs"


def test_multiple_extends(tmp_path):
    """Test multiple base files specified as a list, merged in order."""
    base1 = tmp_path / "base1.yaml"
    base1.write_text(
        "model:\n"
        "  default: model-1\n"
        "terminal:\n"
        "  backend: local\n"
        "  timeout: 30\n",
        encoding="utf-8",
    )

    base2 = tmp_path / "base2.yaml"
    base2.write_text(
        "model:\n"
        "  default: model-2\n"  # overrides base1
        "agent:\n"
        "  max_turns: 50\n",
        encoding="utf-8",
    )

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(
        "extends:\n"
        "  - ../base1.yaml\n"
        "  - ../base2.yaml\n"
        "terminal:\n"
        "  timeout: 100\n",  # overrides base1
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        cfg = load_config()
        assert cfg["model"]["default"] == "model-2"
        assert cfg["agent"]["max_turns"] == 50
        assert cfg["terminal"]["backend"] == "local"
        assert cfg["terminal"]["timeout"] == 100


def test_chained_extends(tmp_path):
    """Test chained extends: grandchild -> child -> base."""
    root_base = tmp_path / "root.yaml"
    root_base.write_text("model:\n  default: root-model\ntimezone: UTC\n", encoding="utf-8")

    mid_base = tmp_path / "mid.yaml"
    mid_base.write_text("extends: ./root.yaml\nterminal:\n  backend: docker\n", encoding="utf-8")

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text("extends: ../mid.yaml\nmodel:\n  default: leaf-model\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        cfg = load_config()
        assert cfg["timezone"] == "UTC"
        assert cfg["terminal"]["backend"] == "docker"
        assert cfg["model"]["default"] == "leaf-model"


def test_circular_extends_detection(tmp_path):
    """Test that circular inheritance is detected and fails closed."""
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text(f"extends: {b}\n", encoding="utf-8")
    b.write_text(f"extends: {a}\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path)}):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(f"extends: {a}\n", encoding="utf-8")

        # load_config catches exception and yields FailedConfigRead
        res = load_config()
        assert isinstance(res, config_mod.FailedConfigRead)
        assert isinstance(res.read_error, ValueError)
        assert "Circular config inheritance" in str(res.read_error)


def test_missing_extended_file_fails_closed(tmp_path):
    """Test that an unresolvable extends path fails closed."""
    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text("extends: /nonexistent/path/missing.yaml\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        res = load_config()
        assert isinstance(res, config_mod.FailedConfigRead)
        assert isinstance(res.read_error, FileNotFoundError)


def test_live_cache_invalidation(tmp_path):
    """Test that modifying a base file on disk invalidates the cache immediately."""
    base_file = tmp_path / "base.yaml"
    base_file.write_text("model:\n  default: initial-model\n", encoding="utf-8")

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(f"extends: {base_file}\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        cfg1 = load_config()
        assert cfg1["model"]["default"] == "initial-model"

        # Cache hit identity
        cfg_ro = config_mod.load_config_readonly()
        assert cfg_ro["model"]["default"] == "initial-model"

        # Update base file with new mtime
        new_mtime = base_file.stat().st_mtime_ns + 1_000_000_000
        base_file.write_text("model:\n  default: updated-model\n", encoding="utf-8")
        os.utime(base_file, ns=(new_mtime, new_mtime))

        # Next call to load_config must immediately reflect the update
        cfg2 = load_config()
        assert cfg2["model"]["default"] == "updated-model"

        # read_raw_config also sees update
        raw = read_raw_config()
        assert raw["model"]["default"] == "updated-model"

        # load_user_config_effective also sees update
        effective = load_user_config_effective()
        assert effective["model"]["default"] == "updated-model"


def test_save_config_anti_flattening(tmp_path):
    """Test that save_config does not write base settings into the profile's config.yaml."""
    base_file = tmp_path / "base.yaml"
    base_file.write_text(
        "model:\n"
        "  default: base-model-shared\n"
        "terminal:\n"
        "  backend: docker\n"
        "  timeout: 60\n",
        encoding="utf-8",
    )

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(
        f"extends: {base_file}\n"
        "terminal:\n"
        "  timeout: 120\n",
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        loaded = load_config()
        assert loaded["model"]["default"] == "base-model-shared"
        assert loaded["terminal"]["backend"] == "docker"
        assert loaded["terminal"]["timeout"] == 120

        # Save the fully loaded config back
        save_config(loaded)

        # Inspect on-disk content: extends and timeout: 120 must be present,
        # but model.default and terminal.backend must NOT be flattened into this file!
        saved_text = cfg_file.read_text(encoding="utf-8")
        assert f"extends: {base_file}" in saved_text
        assert "timeout: 120" in saved_text
        assert "base-model-shared" not in saved_text
        assert "docker" not in saved_text


def test_config_set_and_unset_overrides(tmp_path):
    """Test hermes config set and unset with extends."""
    base_file = tmp_path / "base.yaml"
    base_file.write_text(
        "model:\n"
        "  default: shared-model\n"
        "terminal:\n"
        "  timeout: 30\n",
        encoding="utf-8",
    )

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(f"extends: {base_file}\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        assert load_config()["terminal"]["timeout"] == 30

        # Set an override
        set_config_value("terminal.timeout", "80")

        # Verify on-disk file: has extends and timeout: 80
        raw_text = cfg_file.read_text(encoding="utf-8")
        assert f"extends: {base_file}" in raw_text
        assert "80" in raw_text
        assert "shared-model" not in raw_text

        # Verify load_config sees 80
        assert load_config()["terminal"]["timeout"] == 80

        # Unset the override
        unset_config_value("terminal.timeout")

        # Verify it reverts back to base value 30
        assert load_config()["terminal"]["timeout"] == 30
        assert f"extends: {base_file}" in cfg_file.read_text(encoding="utf-8")


def test_profile_create_extends(tmp_path):
    """Test create_profile with extends parameter."""
    profiles_root = tmp_path / "profiles"
    profiles_root.mkdir()
    base_file = tmp_path / "base.yaml"
    base_file.write_text("model:\n  default: company-model\n", encoding="utf-8")

    with patch("hermes_cli.profiles._get_profiles_root", return_value=profiles_root):
        pdir = create_profile("worker", extends=str(base_file))
        assert pdir.exists()
        cfg_file = pdir / "config.yaml"
        assert cfg_file.exists()
        assert f"extends: {base_file}" in cfg_file.read_text(encoding="utf-8")

        # Cloning with extends must be rejected
        with pytest.raises(ValueError, match="--extends cannot be combined"):
            create_profile("invalid", clone_from="worker", clone_config=True, extends=str(base_file))


def test_show_config_displays_extends(tmp_path, capsys):
    """Test that show_config prints the Extends path."""
    base_file = tmp_path / "shared_base.yaml"
    base_file.write_text("model:\n  default: base-model\n", encoding="utf-8")

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(f"extends: {base_file}\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        show_config()
        captured = capsys.readouterr().out
        assert "Extends:" in captured
        assert str(base_file) in captured


def test_remove_extends_cache_stability(tmp_path):
    """Removing extends must not corrupt the cache signature or crash subsequent load_config() calls."""
    base_file = tmp_path / "base.yaml"
    base_file.write_text("model:\n  default: base-model\n", encoding="utf-8")

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(f"extends: {base_file}\nterminal:\n  timeout: 45\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        # 1. Load with extends
        cfg1 = load_config()
        assert cfg1["model"]["default"] == "base-model"
        assert cfg1["terminal"]["timeout"] == 45

        # 2. Hand-edit: remove the extends line
        new_mtime = cfg_file.stat().st_mtime_ns + 1_000_000_000
        cfg_file.write_text("terminal:\n  timeout: 60\n", encoding="utf-8")
        os.utime(cfg_file, ns=(new_mtime, new_mtime))

        # 1st reload after edit
        cfg2 = load_config()
        assert cfg2["terminal"]["timeout"] == 60
        # 2nd reload (cache hit path - previously crashed with AttributeError: 'int' object has no attribute 'items')
        cfg3 = load_config()
        assert cfg3["terminal"]["timeout"] == 60

        # Also test unset_config_value("extends") path
        cfg_file.write_text(f"extends: {base_file}\nterminal:\n  timeout: 75\n", encoding="utf-8")
        assert load_config()["model"]["default"] == "base-model"

        unset_config_value("extends")
        # Multiple loads after unset
        assert load_config()["terminal"]["timeout"] == 75
        assert load_config()["terminal"]["timeout"] == 75


def test_save_config_refuses_when_base_unresolvable(tmp_path):
    """save_config must refuse to save (fail closed) if extended base config cannot be resolved."""
    base_file = tmp_path / "base.yaml"
    base_file.write_text("model:\n  default: custom-shared\n", encoding="utf-8")

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(f"extends: {base_file}\nterminal:\n  timeout: 50\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
        loaded = load_config()
        assert loaded["model"]["default"] == "custom-shared"

        # Delete base file so it becomes unresolvable
        base_file.unlink()

        # Saving must fail closed rather than falling back and flattening custom-shared into child
        with pytest.raises(RuntimeError, match="extended base configuration could not be resolved"):
            save_config(loaded)


def test_create_profile_validates_extends_and_quotes(tmp_path, monkeypatch):
    """create_profile validates extends file existence/readability, resolves relative paths against CWD to absolute, and safely dumps YAML scalars with special chars."""
    profiles_root = tmp_path / "profiles"
    profiles_root.mkdir()

    with patch("hermes_cli.profiles._get_profiles_root", return_value=profiles_root):
        # Non-existent base file must fail immediately at create time
        with pytest.raises(FileNotFoundError, match="Extended config file not found"):
            create_profile("fail_prof", extends=str(tmp_path / "nonexistent.yaml"))

        # Relative path from CWD must be resolved to absolute path so profile config loads anywhere
        monkeypatch.chdir(tmp_path)
        rel_base = tmp_path / "cwd_base.yaml"
        rel_base.write_text("model:\n  default: cwd-rel-model\n", encoding="utf-8")
        pdir_rel = create_profile("rel_prof", extends="cwd_base.yaml")
        # Ensure it seeded the resolved absolute path
        rel_cfg_text = (pdir_rel / "config.yaml").read_text(encoding="utf-8")
        assert f"extends: {rel_base.resolve()}" in rel_cfg_text
        with patch.dict(os.environ, {"HERMES_HOME": str(pdir_rel)}):
            assert load_config()["model"]["default"] == "cwd-rel-model"

        # Unreadable file must raise PermissionError
        unreadable = tmp_path / "unreadable.yaml"
        unreadable.write_text("model:\n  default: secret\n", encoding="utf-8")
        unreadable.chmod(0o000)
        try:
            with pytest.raises(PermissionError, match="Extended config file is not readable"):
                create_profile("unreadable_prof", extends=str(unreadable))
        finally:
            unreadable.chmod(0o644)

        # Base file with special chars in path
        special_dir = tmp_path / "dir:with#chars[1]"
        special_dir.mkdir()
        special_base = special_dir / "base.yaml"
        special_base.write_text("model:\n  default: special-model\n", encoding="utf-8")

        pdir = create_profile("special_prof", extends=str(special_base))
        cfg_file = pdir / "config.yaml"
        assert cfg_file.exists()

        # Verify YAML is valid and loads correctly
        with patch.dict(os.environ, {"HERMES_HOME": str(pdir)}):
            loaded = load_config()
            assert loaded["model"]["default"] == "special-model"


def test_base_config_env_var_expansion(tmp_path):
    """Environment variables inside base config values are properly expanded."""
    base_file = tmp_path / "base.yaml"
    base_file.write_text("model:\n  default: ${BASE_TEST_MODEL}\n", encoding="utf-8")

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    cfg_file = profile_home / "config.yaml"
    cfg_file.write_text(f"extends: {base_file}\n", encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(profile_home), "BASE_TEST_MODEL": "expanded-model-val"}):
        cfg = load_config()
        assert cfg["model"]["default"] == "expanded-model-val"

