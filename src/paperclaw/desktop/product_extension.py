"""Install product-foundation methods and static assets into the Desktop host."""

from __future__ import annotations

from typing import Any

from .contracts import DesktopPublicError
from .product_service import DesktopProductService

_MARKER = "_paperclaw_product_extension"


def install_product_extension(app_module: Any) -> None:
    """Extend DesktopAPI without moving product logic into the UI layer."""
    if getattr(app_module, _MARKER, False):
        return

    app_module._BROWSER_API_ARITY.update(
        {
            "get_product_overview": (1, 1),
            "get_capabilities": (0, 2),
            "get_project_status": (1, 1),
            "refresh_project_index": (1, 1),
            "list_artifacts": (1, 2),
            "get_artifact": (2, 2),
            "export_artifact": (2, 5),
        }
    )
    app_module._BROWSER_ASSETS.update(
        {
            "/product.css": ("product.css", "text/css; charset=utf-8"),
            "/product.js": ("product.js", "text/javascript; charset=utf-8"),
        }
    )

    api_type = app_module.DesktopAPI
    original_init = api_type.__init__

    def product_init(self, controller, *args, **kwargs):
        product_service = kwargs.pop("product_service", None)
        original_init(self, controller, *args, **kwargs)
        self._product_service = product_service or DesktopProductService()

    def invoke(self, method_name: str, *args: object) -> dict[str, object]:
        try:
            method = getattr(self._product_service, method_name)
            return method(*args)
        except DesktopPublicError as exc:
            return exc.to_public_dict()
        except Exception:
            return DesktopPublicError(
                "runtime_error",
                "Desktop product operation failed.",
            ).to_public_dict()

    def get_product_overview(self, workspace: str) -> dict[str, object]:
        return invoke(self, "get_overview", workspace)

    def get_capabilities(
        self,
        maturity: str | None = None,
        surface: str | None = None,
    ) -> dict[str, object]:
        return invoke(self, "get_capabilities", maturity, surface)

    def get_project_status(self, workspace: str) -> dict[str, object]:
        return invoke(self, "get_project_status", workspace)

    def refresh_project_index(self, workspace: str) -> dict[str, object]:
        return invoke(self, "refresh_project_index", workspace)

    def list_artifacts(
        self,
        workspace: str,
        filters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return invoke(self, "list_artifacts", workspace, filters)

    def get_artifact(self, workspace: str, artifact_id: str) -> dict[str, object]:
        return invoke(self, "get_artifact", workspace, artifact_id)

    def export_artifact(
        self,
        workspace: str,
        artifact_id: str,
        relative_path: str | None = None,
        revision_number: int | None = None,
        overwrite: bool = False,
    ) -> dict[str, object]:
        return invoke(
            self,
            "export_artifact",
            workspace,
            artifact_id,
            relative_path,
            revision_number,
            overwrite,
        )

    api_type.__init__ = product_init
    api_type.get_product_overview = get_product_overview
    api_type.get_capabilities = get_capabilities
    api_type.get_project_status = get_project_status
    api_type.refresh_project_index = refresh_project_index
    api_type.list_artifacts = list_artifacts
    api_type.get_artifact = get_artifact
    api_type.export_artifact = export_artifact
    setattr(app_module, _MARKER, True)


__all__ = ["install_product_extension"]
