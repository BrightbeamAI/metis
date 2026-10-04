"""Capture connectors: records from workplace systems become observations, and whispers reach
workers in the tools they already use (Slack and Microsoft Teams)."""
from .mapping import (
    MappedObservation,
    SourceMapping,
    load_mappings,
    map_records,
    read_records,
)

__all__ = ["MappedObservation", "SourceMapping", "load_mappings", "map_records", "read_records"]
