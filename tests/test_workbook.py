import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from investment_engine.workbook import normalized_signals, parse_grid, write_xlsx


def test_published_grid_preserves_columns_and_ignores_row_headers():
    document = (
        '<table class="waffle"><tr><th>1</th><td>A</td><td colspan="2">B</td>'
        "<td>&lt;script&gt;untrusted&lt;/script&gt;</td></tr></table>"
    )
    assert parse_grid(document) == [["A", "B", "", "<script>untrusted</script>"]]
    with pytest.raises(ValueError, match="grid"):
        parse_grid("<html>Sign in</html>")


def test_signal_contract_cannot_silently_change():
    headers = [
        "Ticker",
        "Company",
        "Industry",
        "Swing /100",
        "Swing decision",
        "Position /100",
        "Position decision",
        "Long-Term /100",
        "Long-Term decision",
    ]
    rows = [
        headers,
        [
            "TEST",
            "Test company",
            "IT",
            "80",
            "WATCH",
            "90",
            "BUY CANDIDATE",
            "",
            "NEEDS FUNDAMENTALS",
        ],
    ]
    assert normalized_signals(rows)[0]["Position /100"] == "90"
    with pytest.raises(ValueError, match="Duplicate"):
        normalized_signals(rows + [rows[1]])
    with pytest.raises(ValueError, match="headers"):
        normalized_signals([["different layout"]])


def test_xlsx_does_not_execute_published_formulas(tmp_path):
    data = {
        "fetched_at": "2026-11-15T00:00:00+00:00",
        "source_url": "https://example.test",
        "tabs": [
            {
                "name": "Signals",
                "rows": [["Ticker", "Expression"], ["TEST", '=HYPERLINK("https://evil.test")']],
            }
        ],
    }
    file = tmp_path / "copy.xlsx"
    write_xlsx(data, file)
    workbook = load_workbook(file, data_only=False)
    assert workbook["Signals"]["B2"].data_type == "s"
    assert "Snapshot provenance" in workbook.sheetnames


def test_committed_snapshot_matches_excel_and_dashboard():
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "data/workbook/current.json").read_text())
    assert len(data["tabs"]) == 10
    assert len(data["signals"]) > 0
    assert len({row["Ticker"] for row in data["signals"]}) == len(data["signals"])
    workbook = load_workbook(root / "data/workbook/workbook_snapshot.xlsx", read_only=True)
    assert set(tab["name"] for tab in data["tabs"]).issubset(workbook.sheetnames)
    page = (root / "dashboard/index.html").read_text()
    assert "__SNAPSHOT_JSON__" not in page
    assert "existing heuristic signals; unvalidated" in page
    for tab in data["tabs"]:
        assert workbook[tab["name"]].max_row == len(tab["rows"])
