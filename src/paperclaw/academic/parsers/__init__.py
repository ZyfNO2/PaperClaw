"""Built-in paper parsers for the Academic runtime."""

from __future__ import annotations

from .latex_parser import LatexParser
from .markdown_parser import MarkdownParser
from .pymupdf_parser import PyMuPDFParser
from .text_parser import TextParser

__all__ = ["LatexParser", "MarkdownParser", "PyMuPDFParser", "TextParser"]
