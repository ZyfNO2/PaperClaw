from types import SimpleNamespace

import pytest

from paperclaw.desktop.app import _folder_dialog_type


def test_folder_dialog_type_supports_pywebview_5_and_6() -> None:
    legacy = SimpleNamespace(FOLDER_DIALOG="legacy-folder")
    modern = SimpleNamespace(
        FileDialog=SimpleNamespace(FOLDER="modern-folder"),
        FOLDER_DIALOG="legacy-folder",
    )
    assert _folder_dialog_type(legacy) == "legacy-folder"
    assert _folder_dialog_type(modern) == "modern-folder"


def test_folder_dialog_type_fails_closed_for_unknown_api() -> None:
    with pytest.raises(RuntimeError, match="folder dialog API"):
        _folder_dialog_type(SimpleNamespace())
