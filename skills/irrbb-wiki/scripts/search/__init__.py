"""Agentic search package for the IRRBB Wiki.

Three workflows feed a shared approval queue:
- polling: scheduled scans of registered sources
- discovery: bounded web search for new sources matching topics of interest
- targeted: on-demand research for a specific event or announcement

Nothing is auto-ingested. All items pass through `inbox/` for human approval
before being handed to the existing `research.py` ingest pipeline.

See references/agentic-search.md in the skill for the full design.
"""

__version__ = "0.1.0"
