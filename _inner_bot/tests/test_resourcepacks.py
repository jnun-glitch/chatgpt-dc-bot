import io
import json
import zipfile

import pytest

from cogs.resourcepacks import _validate_zip


def make_zip(tmp_path, mcmeta, extra_files=None):
    extra_files = extra_files or {}
    path = tmp_path / "pack.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pack.mcmeta", json.dumps(mcmeta))
        for name, data in extra_files.items():
            zf.writestr(name, data)
    return path


def test_missing_pack_version_is_rejected(tmp_path):
    path = make_zip(tmp_path, {"pack": {"description": "No version"}})
    with pytest.raises(ValueError, match="Pack-Version fehlt"):
        _validate_zip(path)


def test_legacy_pack_format_is_accepted(tmp_path):
    path = make_zip(tmp_path, {"pack": {"pack_format": 32, "description": "Legacy"}})
    result = _validate_zip(path)
    assert result["pack_version_min"] == "32.0"
    assert result["pack_version_max"] == "32.0"


def test_modern_min_max_format_is_accepted(tmp_path):
    path = make_zip(tmp_path, {"pack": {"min_format": [74, 0], "max_format": [75, 0]}})
    result = _validate_zip(path)
    assert result["pack_version_min"] == "74.0"
    assert result["pack_version_max"] == "75.0"


def test_missing_pack_mcmeta_is_rejected(tmp_path):
    path = tmp_path / "pack.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("assets/minecraft/test.txt", b"x")
    with pytest.raises(ValueError, match="pack.mcmeta.*fehlt"):
        _validate_zip(path)


def test_zip_slip_is_rejected(tmp_path):
    path = tmp_path / "pack.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 32}}))
        zf.writestr("../outside.txt", b"bad")
    with pytest.raises(ValueError, match="Unsicherer ZIP-Pfad"):
        _validate_zip(path)


def test_bad_json_is_rejected(tmp_path):
    path = tmp_path / "pack.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("pack.mcmeta", b"{not-json")
    with pytest.raises(ValueError, match="ungültiges JSON"):
        _validate_zip(path)
