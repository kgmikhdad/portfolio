"""Validate hosted read-only app views using an ephemeral, unlogged test login."""

import json
import os
import secrets
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

from investment_engine.dashboard_data import dashboard_data
from investment_engine.hosted_database import application_engine


def main() -> int:
    if not os.environ.get("PAPER_DATABASE_URL"):
        print("::error title=Hosted dashboard verification::Missing private database binding")
        return 3
    os.environ["DASHBOARD_ACCESS_PASSWORD"] = secrets.token_urlsafe(32)
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"))
        app.run(timeout=90)
        if app.exception or not app.text_input:
            raise RuntimeError("login_view_not_ready")
        app.text_input[0].set_value(os.environ["DASHBOARD_ACCESS_PASSWORD"])
        app.button[0].click().run(timeout=90)
        if app.exception or len(app.metric) < 4:
            raise RuntimeError("database_view_not_ready")
        for view in ("Paper portfolio", "Prices", "Models", "Operations"):
            app.sidebar.radio[0].set_value(view).run(timeout=90)
            if app.exception:
                raise RuntimeError("dashboard_view_validation_failed")
        db = application_engine(os.environ["PAPER_DATABASE_URL"], read_only=True)
        try:
            snapshot = dashboard_data(db)
        finally:
            db.dispose()
        last = snapshot["last_ingestion"] or {}
        report = {
            "price_records": snapshot["bar_count"],
            "reference_securities": snapshot["security_count"],
            "securities_with_research": len(snapshot["research"]),
            "latest_price_session": snapshot["latest_session"],
            "model_versions": len(snapshot["experiments"]),
            "latest_forecasts": len(snapshot["predictions"]),
            "last_ingestion_status": last.get("status"),
            "last_ingestion_succeeded": last.get("details", {}).get("succeeded"),
            "last_ingestion_requested": last.get("details", {}).get("requested"),
            "status": "passed",
            "source": "supabase",
            "private_login": "verified",
            "views_checked": 5,
            "database_access": "read_only",
            "orders_executed": 0,
        }
        print(json.dumps(report))
        print("::notice title=Hosted dashboard verification::" + json.dumps(report))
        return 0
    except Exception:
        print(
            "::error title=Hosted dashboard verification::App view validation failed; "
            "private exception details suppressed"
        )
        return 3
    finally:
        os.environ.pop("DASHBOARD_ACCESS_PASSWORD", None)


if __name__ == "__main__":
    sys.exit(main())
