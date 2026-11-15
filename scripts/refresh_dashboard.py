"""Refresh the explicitly authorized published Sheet mirror; never write to Google."""

import json
from pathlib import Path

from investment_engine.workbook import refresh

print(json.dumps(refresh(Path(__file__).resolve().parents[1])))
