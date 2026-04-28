"""prompt2dataset — PDF→structured dataset engine (ISF-PEECEE).

Claude Code / external pipelines: put **ISF-PEECEE** on ``sys.path``, then::

    from prompt2dataset import build_dataset_graph, DatasetState
    from prompt2dataset.utils.config import get_settings
"""

from .dataset_graph.graph import build_dataset_graph
from .dataset_graph.state import DatasetState
from .training_events import (
    TrainingEventLogger,
    append_training_event,
    compute_schema_hash,
    merge_training_event_state,
    resolve_training_events_path,
    trajectory_context_from_dataset_state,
)

__all__ = [
    "build_dataset_graph",
    "DatasetState",
    "TrainingEventLogger",
    "append_training_event",
    "compute_schema_hash",
    "merge_training_event_state",
    "resolve_training_events_path",
    "trajectory_context_from_dataset_state",
]
