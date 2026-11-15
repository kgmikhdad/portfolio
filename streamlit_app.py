"""Atlas: read-only Supabase research dashboard. No training/ingestion runs on page visits."""

import hashlib
import hmac
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Community Cloud can install hashed dependencies without building the local project.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from investment_engine.dashboard_data import dashboard_data, price_history
from investment_engine.db import engine
from investment_engine.hosted_database import application_engine
from investment_engine.settings import settings


def export_csv(frame):
    safe = frame.map(
        lambda value: (
            "'" + value
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r"))
            else value
        )
    )
    return safe.to_csv(index=False)


st.set_page_config(page_title="Atlas · Backend research", page_icon="📈", layout="wide")
st.markdown(
    """<style>.stApp{background:#f6f7f4}h1,h2,h3{color:#193e32}
[data-testid=stMetric]{background:white;padding:18px;border:1px solid #e0e6dc;border-radius:10px}
.block-container{padding-top:2rem}div[data-testid=stSidebar]{background:#eaf0e8}</style>""",
    unsafe_allow_html=True,
)


def secret(name):
    value = os.environ.get(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, ""))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return ""


uri = secret("PAPER_DATABASE_URL")
access_password = secret("DASHBOARD_ACCESS_PASSWORD")
if uri:
    if not access_password:
        st.error(
            "Set DASHBOARD_ACCESS_PASSWORD in the app's private Secrets before accessing Supabase."
        )
        st.stop()
    if not st.session_state.get("authenticated", False):
        st.title("Atlas · Private research workspace")
        entered = st.text_input("Dashboard access password", type="password")
        if st.button("Unlock dashboard"):
            if hmac.compare_digest(entered.encode(), access_password.encode()):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Password not accepted.")
        st.stop()
else:
    st.info(
        "Local development database. Configure PAPER_DATABASE_URL and DASHBOARD_ACCESS_PASSWORD "
        "in private app Secrets to connect the hosted account."
    )


@st.cache_resource
def database(_uri, connection_id):
    return (
        application_engine(_uri, read_only=True)
        if _uri
        else engine(settings().database_url.get_secret_value())
    )


@st.cache_data(ttl=300, show_spinner=False)
def load_dashboard(connection_id):
    return dashboard_data(database(uri, connection_id))


@st.cache_data(ttl=300, show_spinner=False)
def load_prices(connection_id, isin):
    return price_history(database(uri, connection_id), isin)


st.sidebar.title("ATLAS")
st.sidebar.caption("Backend investment research · INR")
view = st.sidebar.radio("View", ["Research", "Paper portfolio", "Prices", "Models", "Operations"])
st.sidebar.caption("Research data comes from PostgreSQL, not Google Sheet screening scores.")
if st.sidebar.button("Refresh database view"):
    st.cache_data.clear()
if uri and st.sidebar.button("Lock dashboard"):
    st.session_state.authenticated = False
    st.rerun()


@st.fragment(run_every="300s")
def render_dashboard():
    if uri and not st.session_state.get("authenticated", False):
        st.stop()
    try:
        connection_id = hashlib.sha256(
            (uri or settings().database_url.get_secret_value()).encode()
        ).hexdigest()
        data = load_dashboard(connection_id)
    except Exception:
        st.error(
            "Database unavailable. Check the private database binding and connection workflow. "
            "No private connection details are displayed."
        )
        st.stop()
    st.title("Investment research, from the backend")
    st.caption(
        ("Supabase · " if uri else "Local database · ") + "Read-only · auto-refresh every 5 minutes"
    )
    columns = st.columns(4)
    for column, label, value in zip(
        columns,
        ["Reference securities", "Stored price records", "Latest price session", "Portfolio cash"],
        [
            data["security_count"],
            data["bar_count"],
            data["latest_session"] or "No data",
            f"₹{data['portfolio']['cash_paise'] / 100:,.2f}",
        ],
        strict=True,
    ):
        column.metric(label, value)
    st.warning(
        "Research and experimental forecasts are not approved investment decisions. "
        "Index eligibility, fundamentals and strategy validation remain incomplete; "
        "the paper account emergency stop remains active."
    )
    if view == "Research":
        st.subheader("Independent price-based research")
        st.caption(
            "Calculated from genuine Yahoo history stored in the backend. "
            "No workbook scores or arbitrary target returns are copied here."
        )
        horizon = st.selectbox(
            "Holding-horizon research",
            [
                "Swing · 20 sessions",
                "Position · 60 sessions",
                "Medium · 120 sessions",
                "Long · 250 sessions",
            ],
        )
        length = int(horizon.split("·")[1].strip().split()[0])
        rows = data["research"]
        if not rows:
            st.info("No backend features yet. Run the Market data pipeline in GitHub Actions.")
        else:
            frame = pd.DataFrame(rows)
            query = st.text_input("Search ticker")
            industries = sorted(frame["industry"].dropna().unique())
            industry = st.selectbox(
                "Industry (source classification unverified)", ["All", *industries]
            )
            if query:
                frame = frame[frame["symbol"].str.contains(query, case=False, regex=False)]
            if industry != "All":
                frame = frame[frame["industry"] == industry]
            key = f"momentum{length}"
            frame["momentum_percent"] = pd.to_numeric(frame[key], errors="coerce") * 100
            frame = frame.sort_values("momentum_percent", ascending=False, na_position="last")
            frame["research_state"] = frame["momentum_percent"].apply(
                lambda value: (
                    "Insufficient history"
                    if pd.isna(value)
                    else "Positive momentum · unapproved"
                    if value > 0
                    else "Weak momentum · unapproved"
                )
            )
            if length == 250:
                st.info(
                    "Long-term fundamental investment recommendations remain blocked. "
                    "The table shows price momentum only."
                )
            display = frame[
                [
                    "symbol",
                    "industry",
                    "last_session",
                    "close_inr",
                    "observations",
                    "momentum_percent",
                    "mean_turnover20_inr",
                    "research_state",
                ]
            ]
            st.dataframe(
                display,
                hide_index=True,
                width="stretch",
                column_config={
                    "symbol": "Stock",
                    "industry": "Industry",
                    "last_session": "Price date",
                    "close_inr": st.column_config.NumberColumn("Close (INR)", format="%.2f"),
                    "observations": "Feature sessions",
                    "research_state": "Research status",
                    "momentum_percent": st.column_config.NumberColumn(
                        "Momentum (%)", format="%.2f"
                    ),
                    "mean_turnover20_inr": st.column_config.NumberColumn(
                        "20-session mean turnover (INR)"
                    ),
                },
            )
            st.download_button(
                "Download filtered research CSV",
                export_csv(display),
                "backend-research.csv",
                "text/csv",
            )
    elif view == "Paper portfolio":
        report = data["portfolio"]
        st.subheader("Persistent paper ledger")
        st.caption(
            "This is the backend account, separate from the workbook's ₹10,00,000 model setting."
        )
        st.metric(
            "NAV",
            f"₹{report['nav_paise'] / 100:,.2f}"
            if report["nav_paise"] is not None
            else "Fresh position marks required",
        )
        st.write("Holdings", report["holdings"] or "No holdings")
        st.write("Simulated executions", report["executions"] or "No executed trades")
        st.write("Realized P&L (INR)", report["realized_pnl_paise"] / 100)
        st.write("Fees (INR)", report["transaction_fees_paise"] / 100)
    elif view == "Prices":
        symbols = {r["symbol"]: r["isin"] for r in data["research"]}
        if not symbols:
            st.info("No ingested price series available yet.")
        else:
            selected = st.selectbox("Stock", sorted(symbols))
            frame = pd.DataFrame(load_prices(connection_id, symbols[selected]))
            if not frame.empty:
                frame["date"] = pd.to_datetime(frame["date"])
                st.line_chart(frame.set_index("date")[["close_inr", "adjusted_close_inr"]])
                st.caption(
                    "Yahoo history is split-adjusted; adjusted close also reflects dividends. "
                    "This is a retrospective vendor data vintage, not historical execution prices."
                )
                st.dataframe(frame.tail(300), hide_index=True, width="stretch")
                st.download_button(
                    "Download stored price series",
                    export_csv(frame),
                    selected + "-prices.csv",
                    "text/csv",
                )
    elif view == "Models":
        st.subheader("Experimental model registry")
        if not data["experiments"]:
            st.info("No candidate models are registered yet. No ML/RL recommendation is displayed.")
        else:
            forecasts = pd.DataFrame(data["predictions"])
            if not forecasts.empty:
                forecasts["experimental_return_percent"] = forecasts["estimate"] * 100
                forecasts["residual_scale_percent"] = forecasts["uncertainty"] * 100
                forecasts["forecast_time_IST"] = pd.to_datetime(
                    forecasts["as_of"], unit="s", utc=True
                ).dt.tz_convert("Asia/Kolkata")
                st.dataframe(
                    forecasts[
                        [
                            "symbol",
                            "horizon",
                            "experimental_return_percent",
                            "residual_scale_percent",
                            "forecast_time_IST",
                            "status",
                        ]
                    ],
                    hide_index=True,
                    width="stretch",
                )
            st.caption(
                "Forecasts are price-only research estimates. Residual scale is not a "
                "calibrated probability or guaranteed return; no model is approved for trading."
            )
            for experiment in data["experiments"]:
                with st.expander(experiment["model_kind"] + " · " + experiment["status"]):
                    parameters = experiment.get("parameters", {})
                    if parameters.get("feature_names") and parameters.get("coefficients"):
                        weights = pd.DataFrame(
                            {
                                "Price factor": parameters["feature_names"],
                                "Standardized coefficient": parameters["coefficients"],
                            }
                        )
                        st.bar_chart(weights.set_index("Price factor"))
                        st.caption(
                            "Learned price-factor associations, not causal effects or "
                            "fundamental/valuation factor weights."
                        )
                    st.json(experiment)
        st.caption(
            "Model promotion requires independent validation and prospective paper evidence."
        )
    else:
        st.subheader("Ingestion and data quality")
        st.json(data["last_ingestion"] or {"status": "No ingestion job recorded"})
        st.info(
            "The official factsheet reports 204 constituents; the source workbook lists 203. "
            "The current research universe is not verified historical index membership. "
            "HFCL is NSE series BE (delivery-only), explicitly flagged in reference configuration."
        )
        st.write(
            "Automated data workflow",
            "16:15 Asia/Kolkata on weekdays; GitHub schedules are best-effort",
        )
        st.write("Approved models", "None")
        st.write("Real-money execution", "Disabled")
        st.write("Model training schedule", "Manual only")
        st.caption(
            "Original workbook remains available in the separate downloadable workbook mirror."
        )


render_dashboard()
