"""server.translate — streaming translation package.

Backward-compat: StreamingTranslator still importable from here so that
any code doing `from server.translate import StreamingTranslator` keeps working.
"""

try:
    from ..translate_legacy import StreamingTranslator  # noqa: F401
except ImportError:
    pass  # top-level import context (benchmarks/tests with server/ on sys.path)
from .streaming_router import StreamingTranslationRouter
from .engines.nllb_engine import NLLBEngine

__all__ = ["StreamingTranslator", "StreamingTranslationRouter", "NLLBEngine"]
