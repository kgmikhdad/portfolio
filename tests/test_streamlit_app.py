from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from streamlit.testing.v1 import AppTest

from investment_engine.broker import initialize
from investment_engine.models import Base, Feature, Security

ROOT = Path(__file__).resolve().parents[1]


def test_app_reads_backend_features_and_portfolio(tmp_path, monkeypatch):
    db = create_engine("sqlite:///" + str(tmp_path / "app.db"))
    Base.metadata.create_all(db)
    with Session(db) as session, session.begin():
        initialize(session, "paper", 1)
        session.add(Security(isin="INE009A01021", symbol="SYNTHETIC", sector="Test industry"))
        session.flush()
        session.add(
            Feature(
                isin="INE009A01021",
                definition_version="backend-technical-v1",
                as_of=1,
                dataset_hash="synthetic-test",
                values={
                    "last_session": "2026-11-13",
                    "close_inr": 100,
                    "observations": 30,
                    "momentum20": 0.1,
                    "momentum60": None,
                    "momentum120": None,
                    "momentum250": None,
                    "mean_turnover20_inr": 10000000,
                    "trade_approved": False,
                },
            )
        )
    monkeypatch.delenv("PAPER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DASHBOARD_ACCESS_PASSWORD", raising=False)
    monkeypatch.setenv("DATABASE_URL", str(db.url))
    app = AppTest.from_file(str(ROOT / "streamlit_app.py")).run(timeout=30)
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["symbol"] == "SYNTHETIC"
    app.selectbox[0].select("Long · 250 sessions").run()
    assert not app.exception
    assert any("fundamental" in message.value for message in app.info)
    app.sidebar.radio[0].set_value("Paper portfolio").run()
    assert not app.exception
    assert any(metric.label == "NAV" for metric in app.metric)
    assert any("No executed trades" in str(message.value) for message in app.markdown)
    db.dispose()


def test_hosted_data_is_not_accessed_without_password(monkeypatch):
    accessed = []
    monkeypatch.setenv(
        "PAPER_DATABASE_URL",
        "postgresql://user:dummy@aws-0-ap-south-1.pooler.supabase.com:5432/postgres",
    )
    monkeypatch.delenv("DASHBOARD_ACCESS_PASSWORD", raising=False)
    monkeypatch.setattr(
        "investment_engine.hosted_database.application_engine",
        lambda *args, **kwargs: accessed.append(True),
    )
    app = AppTest.from_file(str(ROOT / "streamlit_app.py")).run(timeout=20)
    assert not app.exception and app.error
    assert "DASHBOARD_ACCESS_PASSWORD" in app.error[0].value
    assert not accessed and not app.metric
    monkeypatch.setenv("DASHBOARD_ACCESS_PASSWORD", "private-test-password")
    app = AppTest.from_file(str(ROOT / "streamlit_app.py")).run(timeout=20)
    app.text_input[0].set_value("incorrect 🔒")
    app.button[0].click().run()
    assert not app.exception
    assert "not accepted" in app.error[0].value
    assert not accessed and not app.metric
