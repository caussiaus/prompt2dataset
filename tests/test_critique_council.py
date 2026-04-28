"""Unit tests for validation-council vote agreement (no LLM)."""
from __future__ import annotations

from prompt2dataset.dataset_graph import critique_council


def test_vote_agreement_unanimous():
    assert critique_council._vote_agreement(["ok", "ok", "ok"]) == 1.0


def test_vote_agreement_split():
    assert critique_council._vote_agreement(["good", "ok", "ok"]) == 2 / 3


def test_vote_agreement_two_way():
    assert critique_council._vote_agreement(["needs_work", "ok"]) == 0.5


def test_vote_agreement_ignores_garbage():
    assert critique_council._vote_agreement(["needs_work", "badlabel", "needs_work"]) == 1.0


def test_prompt2dataset_config_council_defaults():
    from prompt2dataset.utils.prompt2dataset_settings import Prompt2DatasetConfig

    c = Prompt2DatasetConfig.defaults()
    assert c.critique_council_enabled is False
    assert c.critique_council_reviewer_count == 2
    assert len(c.critique_council_reviewer_temperatures_list()) == 2
