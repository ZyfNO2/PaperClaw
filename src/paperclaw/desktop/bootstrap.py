"""Desktop bootstrap that installs optional UI extensions before launch."""

from __future__ import annotations

from paperclaw.desktop import app

<<<<<<< HEAD
from .provider_config import install_provider_extension

install_provider_extension(app)
=======
from .native_workspace import install_native_workspace_extension
from .provider_config import install_provider_extension

install_provider_extension(app)
install_native_workspace_extension(app)
>>>>>>> 77ef8ea


def main(argv: list[str] | None = None) -> int:
    return app.main(argv)
