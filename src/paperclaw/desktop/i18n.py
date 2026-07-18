"""Desktop browser-host registration for the translation runtime."""

from __future__ import annotations

from typing import Any

_INSTALLED_ATTRIBUTE = "_paperclaw_i18n_extension_installed"


def install_i18n_extension(app_module: Any) -> None:
    """Expose the packaged i18n asset through the protected browser host once."""

    if getattr(app_module, _INSTALLED_ATTRIBUTE, False):
        return
    app_module._BROWSER_ASSETS["/i18n.js"] = (
        "i18n.js",
        "text/javascript; charset=utf-8",
    )
    setattr(app_module, _INSTALLED_ATTRIBUTE, True)


__all__ = ["install_i18n_extension"]
