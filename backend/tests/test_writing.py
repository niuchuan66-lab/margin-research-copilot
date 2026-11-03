from __future__ import annotations

import pytest

from app.services.writing import csv_to_chart, render_figure


def test_csv_to_chart_builds_one_axis_series() -> None:
    csv_text = "year,accuracy,latency\n2023,0.81,120\n2024,0.85,110\n2025,0.88,95\n"
    chart = csv_to_chart(csv_text, "Model quality")
    assert chart.columns == ["year", "accuracy", "latency"]
    assert chart.option["xAxis"]["type"] == "category"
    assert chart.option["xAxis"]["data"] == ["2023", "2024", "2025"]
    assert len(chart.option["series"]) == 2
    assert chart.caption.startswith("图 1.")
    assert "accuracy" in chart.caption


def test_csv_to_chart_supports_bar_and_radar() -> None:
    csv_text = "model,accuracy,latency\nA,0.81,120\nB,0.85,110\nC,0.88,95\n"
    bar = csv_to_chart(csv_text, "Model quality", "bar")
    assert bar.option["series"][0]["type"] == "bar"
    assert bar.option["xAxis"]["boundaryGap"] is True
    assert "柱状图" in bar.caption

    radar = csv_to_chart(csv_text, "Model quality", "radar")
    assert radar.option["series"][0]["type"] == "radar"
    assert len(radar.option["radar"]["indicator"]) == 2
    assert len(radar.option["series"][0]["data"]) == 3


def test_csv_to_chart_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="不支持"):
        csv_to_chart("x,y\n1,2\n", "bad", "pie")


def test_mermaid_passthrough_and_wrap() -> None:
    passthrough = render_figure("mermaid", "flowchart LR\n  A --> B")
    assert passthrough.code.startswith("flowchart")

    wrapped = render_figure("mermaid", "Idea to experiment")
    assert wrapped.code.startswith("flowchart LR")
    assert "Idea to experiment" in wrapped.code
