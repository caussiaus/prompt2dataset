from __future__ import annotations

from prompt2dataset.utils.retrieval import annealed_reorder_blocks


def test_annealed_reorder_preserves_length():
    blocks = [{"chunk_id": str(i), "text": "x" * (100 + i * 10)} for i in range(5)]
    out = annealed_reorder_blocks(blocks, steps=20, seed=42)
    assert len(out) == len(blocks)
    assert {b["chunk_id"] for b in out} == {b["chunk_id"] for b in blocks}


def test_annealed_zero_steps_noop():
    b = [{"chunk_id": "a", "text": "hi"}]
    assert annealed_reorder_blocks(b, steps=0) == b
