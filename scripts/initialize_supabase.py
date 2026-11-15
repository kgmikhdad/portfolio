"""Manual deployment entry point. No connection strings or raw exceptions in output."""

import json
import os
import sys

from investment_engine.hosted_database import failure_code
from investment_engine.hosted_setup import HostedSetupError, initialize_supabase


def main() -> int:
    try:
        report = initialize_supabase(os.environ.get("PAPER_DATABASE_URL", ""))
        print(json.dumps(report))
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::notice title=Supabase initialization verified::" + json.dumps(report))
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, HostedSetupError) else failure_code(error)
        report = {
            "status": "blocked",
            "reason": reason,
            "trades_executed": 0,
            "schedules_enabled": False,
        }
        print(json.dumps(report))
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::error title=Supabase initialization blocked::" + json.dumps(report))
        return 3


if __name__ == "__main__":
    sys.exit(main())
