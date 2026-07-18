"""Read-only Language Server Protocol integration."""

from .bootstrap import get_lsp_manager, install_cli_lsp_extension, shutdown_lsp_managers
from .client import (
    JsonRpcTransport,
    LSPClient,
    LSPError,
    LSPProcessError,
    LSPProtocolError,
    LSPTimeoutError,
)
from .manager import LSPConfigurationError, LSPManager, LanguageServerConfig
from .tools import (
    LSPDefinitionTool,
    LSPDiagnosticsTool,
    LSPHoverTool,
    LSPReferencesTool,
    LSPSymbolsTool,
    register_lsp_tools,
)

__all__ = [
    "JsonRpcTransport",
    "LSPClient",
    "LSPConfigurationError",
    "LSPDefinitionTool",
    "LSPDiagnosticsTool",
    "LSPError",
    "LSPHoverTool",
    "LSPManager",
    "LSPProcessError",
    "LSPProtocolError",
    "LSPReferencesTool",
    "LSPSymbolsTool",
    "LSPTimeoutError",
    "LanguageServerConfig",
    "get_lsp_manager",
    "install_cli_lsp_extension",
    "register_lsp_tools",
    "shutdown_lsp_managers",
]
