from __future__ import annotations

from app.services.parsing import (
    _heading_depth,
    _line_spans,
    _restore_spaces,
    _update_sections,
)


def test_heading_depth_and_section_stack() -> None:
    assert _heading_depth("1 Introduction") == 1
    assert _heading_depth("3.2 Attention") == 2
    assert _heading_depth("3.2.1 Scaled Dot-Product Attention") == 3
    stack: list[tuple[int, str]] = []
    assert _update_sections(stack, "3 Model Architecture") == ["3 Model Architecture"]
    assert _update_sections(stack, "3.1 Encoder") == [
        "3 Model Architecture",
        "3.1 Encoder",
    ]
    assert _update_sections(stack, "4 Training") == ["4 Training"]


def test_line_spans_keep_offsets() -> None:
    spans = _line_spans("alpha\r\nbeta\ngamma")
    assert [text for text, _start, _end in spans] == ["alpha", "beta", "gamma"]
    assert spans[1][1] == 7
    assert spans[2][1] == 12


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
