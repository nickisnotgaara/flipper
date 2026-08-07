"""packages.flipper_db.sources — SourceParser implementations.

Each module in this package implements the
:class:`packages.flipper_db.parser_types.SourceParser` protocol for one
data source (cian, domclick, winners, ...).

The pipeline (``packages.flipper_db.pipeline``) consumes these
implementations and never touches source-specific code. To add a new
source, drop a new file here implementing the protocol — no pipeline
changes needed.

To register a new source in the generic ``run_pipeline`` CLI
(``scripts/run_pipeline.py --source <name>``), add the source class to
``packages.flipper_db.SOURCES`` registry.
"""
from .cian import CianSource
from .domclick import DomclickSource

__all__ = ["CianSource", "DomclickSource"]
