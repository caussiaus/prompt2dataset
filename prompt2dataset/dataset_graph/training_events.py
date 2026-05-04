"""Re-export trajectory logging from the ``prompt2dataset`` package (canonical: ``prompt2dataset/training_events.py``).

Entrypoints must put the ISF-PEECEE repo root and this app directory on ``sys.path`` first
(see ``app.py`` and ``scripts/*.py``).
"""
from __future__ import annotations

from prompt2dataset.training_events import (
    TrainingEventLogger,
    append_training_event,
    compute_schema_hash,
    merge_training_event_state,
    resolve_training_events_path,
    trajectory_context_from_dataset_state,
)

__all__ = [
    "TrainingEventLogger",
    "append_training_event",
    "compute_schema_hash",
    "merge_training_event_state",
    "resolve_training_events_path",
    "trajectory_context_from_dataset_state",
]
