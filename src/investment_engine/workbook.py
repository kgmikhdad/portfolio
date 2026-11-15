"""Read-only published-workbook mirror and generated, self-contained research dashboard."""

import hashlib
import io
import json
import re
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from lxml import html
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

PUBLISHED = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTFz2DtV1qZI8WLqAxgTr_mPJSK9EjrpKM3Ua3KOFqlbxVu6VPKaAJ2Q7HvvdSM5_q5tmPX8mMlcAci/pubhtml"
)


def parse_grid(document: str) -> list[list[str]]:
    tree = html.fromstring(document)
    tables = tree.xpath('//table[contains(concat(" ", normalize-space(@class), " "), " waffle ")]')
    if not tables:
        raise ValueError("Published sheet contains no readable grid")
    rows: list[list[str]] = []
    for tr in tables[0].xpath(".//tr"):
        row: list[str] = []
        for td in tr.xpath("./td"):
            row.append(td.text_content().strip())
            row.extend([""] * (int(td.get("colspan", "1")) - 1))
        if any(row):
            rows.append(row)
    if not rows:
        raise ValueError("Empty published grid")
    return rows


def normalized_signals(rows: list[list[str]]) -> list[dict[str, str]]:
    header_index = next((i for i, row in enumerate(rows) if "Swing /100" in row), None)
    if header_index is None:
        raise ValueError("Expected versioned Signals headers not found")
    headers = rows[header_index]
    required = {
        "Ticker",
        "Company",
        "Industry",
        "Swing /100",
        "Swing decision",
        "Position /100",
        "Position decision",
        "Long-Term /100",
        "Long-Term decision",
    }
    if not required.issubset(headers):
        raise ValueError("Signals data contract changed")
    records = []
    seen = set()
    for row in rows[header_index + 1 :]:
        record = {name: row[i] if i < len(row) else "" for i, name in enumerate(headers) if name}
        ticker = record.get("Ticker", "")
        if not ticker:
            continue
        if ticker in seen:
            raise ValueError("Duplicate signal ticker")
        seen.add(ticker)
        records.append(record)
    if not records:
        raise ValueError("No stock records")
    return records


def write_xlsx(snapshot: dict[str, Any], path: Path) -> None:
    book = Workbook()
    book.remove(book.active)
    for tab in snapshot["tabs"]:
        sheet = book.create_sheet(tab["name"][:31])
        for row in tab["rows"]:
            sheet.append(row)
        # Preserve published display values as text; never execute imported formulas.
        for cells in sheet:
            for cell in cells:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="173E38")
        sheet.freeze_panes = "C2"
        for cells in sheet.columns:
            maximum = max((len(str(cell.value or "")) for cell in cells), default=12)
            sheet.column_dimensions[cells[0].column_letter].width = min(48, max(14, maximum + 2))
    metadata = book.create_sheet("Snapshot provenance")
    metadata.append(["Published values only", "Original Google formulas are not exported"])
    metadata.append(["Retrieved at UTC", snapshot["fetched_at"]])
    metadata.append(["Source", snapshot["source_url"]])
    metadata.append(["Interpretation", "Existing heuristic signals; no trained/approved model"])
    book.save(path)


def refresh(root: Path, published_url: str = PUBLISHED) -> dict[str, Any]:
    if urlsplit(published_url).hostname != "docs.google.com":
        raise ValueError("Expected authorized published Google workbook")
    with httpx.Client(timeout=40, follow_redirects=True) as client:
        response = client.get(published_url)
        response.raise_for_status()
        menu = re.findall(
            r'items.push\(\{name: "([^"]+)", pageUrl: "[^"]+", gid: "(-?\d+)"', response.text
        )
        if not menu or len({name for name, _ in menu}) != len(menu):
            raise ValueError("Published sheet menu missing/ambiguous")

        def fetch(item: tuple[str, str]) -> tuple[dict[str, Any], str]:
            name, gid = item
            page = client.get(published_url + "/sheet", params={"headers": "false", "gid": gid})
            page.raise_for_status()
            return {
                "name": name,
                "gid": gid,
                "rows": parse_grid(page.text),
                "source_sha256": hashlib.sha256(page.content).hexdigest(),
            }, page.text

        with ThreadPoolExecutor(max_workers=3) as pool:
            fetched = list(pool.map(fetch, menu))
    tabs = [tab for tab, _ in fetched]
    names = {tab["name"] for tab in tabs}
    if not {"Signals", "Constituents", "Dashboard", "Controls", "Fundamentals"}.issubset(names):
        raise ValueError("Required source tabs missing; last snapshot preserved")
    signals = normalized_signals(next(tab["rows"] for tab in tabs if tab["name"] == "Signals"))
    snapshot = {
        "schema_version": "1",
        "fetched_at": datetime.now(UTC).isoformat(),
        "source_url": published_url,
        "source_type": "published_google_sheet_values",
        "signal_status": "existing heuristic signals; unvalidated",
        "model_status": "no trained or approved model",
        "tabs": tabs,
        "signals": signals,
    }
    destination = root / "data" / "workbook"
    destination.mkdir(parents=True, exist_ok=True)
    template = root / "dashboard" / "template.html"
    encoded = json.dumps(snapshot, ensure_ascii=False).replace("<", "\\u003c")
    page = template.read_text().replace("__SNAPSHOT_JSON__", encoded)
    # Download/parse/validate every tab before replacing any current snapshot.
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        staging = Path(temporary)
        (staging / "current.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
        write_xlsx(snapshot, staging / "workbook_snapshot.xlsx")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
            for tab, source_html in fetched:
                zipped.writestr(f"{tab['gid']}.html", source_html)
            zipped.writestr("source-menu.html", response.text)
            zipped.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "fetched_at": snapshot["fetched_at"],
                        "source_url": published_url,
                        "tabs": [{k: v for k, v in tab.items() if k != "rows"} for tab in tabs],
                    },
                    indent=2,
                ),
            )
        (staging / "published_source.zip").write_bytes(archive.getvalue())
        for file in staging.iterdir():
            file.replace(destination / file.name)
    (root / "dashboard" / "index.html").write_text(page)
    return {"tabs": len(tabs), "stocks": len(signals), "fetched_at": snapshot["fetched_at"]}
