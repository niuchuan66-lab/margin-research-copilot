from __future__ import annotations

from app.services.parsing import _restore_spaces


def test_restore_spaces_splits_concatenated_content() -> None:
    assert _restore_spaces("AttentionIsAllYouNeed") == "Attention Is All You Need"
    assert "dominant sequence" in _restore_spaces(
        "The dominantsequence transductionmodelsarebasedoncomplexrecurrent or"
    )
    assert "parallel iz able" in _restore_spaces("more parallel iz able")


def test_restore_spaces_keeps_names_and_emails() -> None:
    assert _restore_spaces("AshishVaswani*") == "AshishVaswani*"
    assert _restore_spaces("llion@google.com") == "llion@google.com"
    assert _restore_spaces("NVIDIA") == "NVIDIA"
