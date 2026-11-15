"""Scheduled data ingestion and optional manual research training. No order dispatch."""

import argparse
import json
import os
import sys

from investment_engine.hosted_database import application_engine, failure_code
from investment_engine.market_pipeline import ingest_market
from investment_engine.model_training import train_candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--train-models", action="store_true")
    args = parser.parse_args()
    db = None
    try:
        db = application_engine(os.environ.get("PAPER_DATABASE_URL", ""))
        report = ingest_market(db, backfill=args.backfill, limit=args.limit)
        if args.train_models and report["succeeded"]:
            report["training"] = train_candidates(db)
        print(json.dumps(report))
        if os.environ.get("GITHUB_ACTIONS") == "true":
            level = "notice" if report["status"] == "ingested" else "error"
            print(f"::{level} title=Market pipeline result::" + json.dumps(report))
        return 0 if report["status"] == "ingested" else 3
    except Exception as error:
        report = {
            "status": "blocked",
            "reason": failure_code(error),
            "error_type": type(error).__name__,
            "orders_executed": 0,
        }
        print(json.dumps(report))
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::error title=Market pipeline result::" + json.dumps(report))
        return 3
    finally:
        if db is not None:
            db.dispose()


if __name__ == "__main__":
    sys.exit(main())
