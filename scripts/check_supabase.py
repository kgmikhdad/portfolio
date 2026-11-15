"""Run only through a securely injected database binding; print safe status fields."""

import json
import os
import sys

from investment_engine.hosted_database import check_connection, endpoint_diagnostics, failure_code


def main() -> int:
    secret = os.environ.get("PAPER_DATABASE_URL", "")
    diagnostics: dict[str, bool] = {}
    try:
        expected_host = os.environ.get("SUPABASE_EXPECTED_HOST", "")
        if expected_host:
            diagnostics = endpoint_diagnostics(secret, expected_host)
        report = {**check_connection(secret), **diagnostics}
        print(json.dumps(report))
        return 0
    except Exception as error:
        report = {
            **diagnostics,
            "status": "blocked",
            "secret_present": bool(secret),
            "reason": failure_code(error),
            "schema_changes": False,
            "trades_executed": 0,
        }
        print(json.dumps(report))
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::error title=Supabase readiness check::" + json.dumps(report))
        return 3


if __name__ == "__main__":
    sys.exit(main())
