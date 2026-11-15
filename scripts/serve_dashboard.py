"""Local read-only dashboard with portfolio API. No write/trade endpoints."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sqlalchemy import select

from investment_engine.db import engine, transaction
from investment_engine.models import Order
from investment_engine.operations import portfolio_report
from investment_engine.settings import settings

ROOT = Path(__file__).resolve().parents[1]
DB = engine(settings().database_url.get_secret_value())


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        files = {
            "/": (ROOT / "dashboard/index.html", "text/html; charset=utf-8"),
            "/index.html": (ROOT / "dashboard/index.html", "text/html; charset=utf-8"),
            "/data/workbook/workbook_snapshot.xlsx": (
                ROOT / "data/workbook/workbook_snapshot.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        }
        if path == "/api/portfolio":
            try:
                report = portfolio_report(DB, "paper", int(time.time()))
                with transaction(DB) as session:
                    orders = session.scalars(
                        select(Order)
                        .where(Order.account_id == "paper")
                        .order_by(Order.executed_at.desc())
                        .limit(100)
                    ).all()
                    report["executions"] = [
                        {
                            "id": o.id,
                            "isin": o.isin,
                            "side": o.side,
                            "quantity": o.quantity,
                            "price_paise": o.price_paise,
                            "executed_at": o.executed_at,
                        }
                        for o in orders
                    ]
                body = json.dumps(report).encode()
                self.send_response(200)
            except Exception:
                body = b'{"status":"unavailable","message":"Paper database unavailable"}'
                self.send_response(503)
            self.send_header("Content-Type", "application/json")
        elif path in files:
            file, content_type = files[path]
            body = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
        else:
            self.send_error(404)
            return
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("Private local dashboard: http://127.0.0.1:8765", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
