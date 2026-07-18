from __future__ import annotations

from types import SimpleNamespace

from paperclaw.desktop.contracts import DesktopPublicError
from paperclaw.desktop.product_extension import install_product_extension


class _API:
    def __init__(self, controller, *, existing: str = "kept") -> None:
        self.controller = controller
        self.existing = existing


class _Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def _result(self, name: str, *args: object):
        self.calls.append((name, args))
        return {"ok": True, "method": name, "args": list(args)}

    def get_overview(self, *args):
        return self._result("get_overview", *args)

    def get_capabilities(self, *args):
        return self._result("get_capabilities", *args)

    def get_project_status(self, *args):
        return self._result("get_project_status", *args)

    def refresh_project_index(self, *args):
        return self._result("refresh_project_index", *args)

    def list_artifacts(self, *args):
        return self._result("list_artifacts", *args)

    def get_artifact(self, *args):
        return self._result("get_artifact", *args)

    def export_artifact(self, *args):
        return self._result("export_artifact", *args)


class _ErrorService(_Service):
    def get_overview(self, *_args):
        raise DesktopPublicError("project_invalid", "Project is invalid.")

    def get_project_status(self, *_args):
        raise RuntimeError("private details must not escape")


def _module():
    return SimpleNamespace(
        DesktopAPI=type("DesktopAPI", (_API,), {}),
        _BROWSER_API_ARITY={"get_state": (0, 0)},
        _BROWSER_ASSETS={"/app.js": ("app.js", "text/javascript")},
    )


def test_product_extension_installs_methods_assets_and_preserves_init_kwargs() -> None:
    module = _module()
    install_product_extension(module)
    service = _Service()
    api = module.DesktopAPI("controller", existing="custom", product_service=service)

    assert api.controller == "controller"
    assert api.existing == "custom"
    assert api.get_product_overview("/workspace")["method"] == "get_overview"
    assert api.get_capabilities("foundation", "desktop")["method"] == "get_capabilities"
    assert api.get_project_status("/workspace")["method"] == "get_project_status"
    assert api.refresh_project_index("/workspace")["method"] == "refresh_project_index"
    assert api.list_artifacts("/workspace", {"limit": 10})["method"] == "list_artifacts"
    assert api.get_artifact("/workspace", "artifact-1")["method"] == "get_artifact"
    assert api.export_artifact("/workspace", "artifact-1")["method"] == "export_artifact"

    assert module._BROWSER_API_ARITY["get_product_overview"] == (1, 1)
    assert module._BROWSER_API_ARITY["export_artifact"] == (2, 5)
    assert module._BROWSER_ASSETS["/product.js"][0] == "product.js"
    assert module._BROWSER_ASSETS["/product.css"][0] == "product.css"


def test_product_extension_is_idempotent() -> None:
    module = _module()
    install_product_extension(module)
    installed_init = module.DesktopAPI.__init__
    install_product_extension(module)
    assert module.DesktopAPI.__init__ is installed_init


def test_product_extension_returns_public_errors_only() -> None:
    module = _module()
    install_product_extension(module)
    api = module.DesktopAPI(None, product_service=_ErrorService())

    public = api.get_product_overview("/workspace")
    assert public == {
        "ok": False,
        "error_code": "project_invalid",
        "error_message": "Project is invalid.",
    }
    unexpected = api.get_project_status("/workspace")
    assert unexpected == {
        "ok": False,
        "error_code": "runtime_error",
        "error_message": "Desktop product operation failed.",
    }
    assert "private details" not in str(unexpected)
