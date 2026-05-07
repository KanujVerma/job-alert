from src.adapters.base import BaseAdapter

# Registry populated by each adapter module when imported.
# Phase 1: empty. Phase 2+ adds entries.
ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {}
