from __future__ import annotations

from typing import Any

from app.services.parsing import (
    _heading_depth,
    _line_column_metrics,
    _line_spans,
    _looks_like_caption,
    _looks_like_formula,
    _restore_spaces,
    _row_like,
    _rows_aligned,
    _table_line_indexes,
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


def test_caption_hint_matches_figure_and_table_labels() -> None:
    assert _looks_like_caption("Figure 3: Attention weights for each head.")
    assert _looks_like_caption("Table 2: The Transformer achieves better BLEU.")
    assert _looks_like_caption("TABLE 1. Model complexity")
    assert _looks_like_caption("Figure 2 The architecture of the model")
    assert not _looks_like_caption("Table 2 summarizes our results and comparisons.")
    assert not _looks_like_caption("The table 2 rows show a trend.")
    assert not _looks_like_caption("Figures show attention patterns.")


def test_formula_hint_prefers_equation_lines() -> None:
    assert _looks_like_formula("dmodel = 512")
    assert _looks_like_formula("Attention(Q, K, V ) = softmax(QK T /√dk )V")
    assert _looks_like_formula("L = (1/N ) ∑ log p(x)")
    assert not _looks_like_formula(
        "The model achieves 28.4 BLEU on WMT 2014, which is a strong result."
    )
    assert not _looks_like_formula("For the base models, we averaged 5 checkpoints.")


class _FakeTextpage:
    def __init__(self, boxes: list[tuple[float, float, float, float]]) -> None:
        self._boxes = boxes

    def get_charbox(self, index: int) -> Any:
        return self._boxes[index]


def test_line_column_metrics_reports_gap_offset() -> None:
    boxes = [
        (0, 0, 5, 10),
        (5, 0, 10, 10),
        (10, 0, 12, 10),
        (12, 0, 14, 10),
        (30, 0, 35, 10),
        (35, 0, 40, 10),
    ]
    spans = _line_spans("ab  cd")
    metrics = _line_column_metrics(_FakeTextpage(boxes), spans)
    assert metrics == [[(30.0, 4)]]


def test_row_like_rejects_prose_with_soft_wrap_gap() -> None:
    assert _row_like("GNMT + RL 24.6 2.3", [(18.0, 10), (26.0, 16)])
    assert _row_like("Transformer (base model) 27.3", [(28.0, 24)])
    assert not _row_like(
        "Recurrent neural networks, long short-term memory and gated units",
        [(31.0, 18)],
    )
    assert not _row_like("short", [])


def test_table_runs_require_aligned_columns() -> None:
    spans = _line_spans("Model BLEU Params\nGNMT + RL 24.6 2.3\nConvS2S 25.16 9.6")
    metrics = [
        [(120.0, 5), (200.0, 10)],
        [(120.2, 9), (200.1, 14)],
        [(119.9, 7), (200.0, 13)],
    ]
    assert _table_line_indexes(spans, metrics) == {0, 1, 2}

    misaligned = [
        [(120.0, 5), (200.0, 10)],
        [(120.1, 9), (260.0, 14)],
    ]
    assert _table_line_indexes(spans[:2], misaligned) == set()

    prose = _line_spans("first prose line\nsecond prose line")
    assert _table_line_indexes(prose, [[], []]) == set()


def test_rows_aligned_tolerance() -> None:
    assert _rows_aligned([(120.0, 5), (200.0, 10)], [(124.0, 9), (205.0, 14)])
    assert not _rows_aligned([(120.0, 5), (200.0, 10)], [(120.0, 5), (230.0, 14)])
    assert not _rows_aligned([], [(120.0, 5)])
