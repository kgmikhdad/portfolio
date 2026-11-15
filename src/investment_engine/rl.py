"""Experimental Gymnasium environment using the same deterministic paper risk engine.

No trained policy is shipped. Daily bars supply simulated next-open fills only; the agent
observes preceding-session PIT features. Use an archived, bias-reviewed dataset before
research; synthetic fixtures validate code, never investment performance.
"""

from typing import Any, Literal

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session

from investment_engine.actions import apply_action
from investment_engine.broker import (
    Costs,
    Proposal,
    Quote,
    RiskRejected,
    execute,
    initialize,
    reconcile,
)
from investment_engine.data import point_in_time_bars
from investment_engine.db import engine, transaction
from investment_engine.features import technical
from investment_engine.models import (
    Account,
    Bar,
    Base,
    CorporateAction,
    Holding,
    MarketSession,
    Membership,
    Security,
)
from investment_engine.settings import Settings


class PortfolioEnv(gym.Env[NDArray[np.float32], np.int64]):
    metadata = {"render_modes": []}

    def __init__(self, source: Session, days: list[str], dataset_label: str) -> None:
        super().__init__()
        if len(days) < 2 or days != sorted(set(days)) or not dataset_label:
            raise ValueError("Explicit labeled dataset and sorted session dates required")
        self.days, self.dataset_label = days, dataset_label
        self.records: list[tuple[type[Base], list[dict[str, Any]]]] = []
        for model in (Security, Membership, MarketSession, Bar, CorporateAction):
            rows = [
                {c.name: getattr(row, c.name) for c in model.__table__.columns}
                for row in source.scalars(select(model))
            ]
            self.records.append((model, rows))
        self.isins = sorted(row["isin"] for row in self.records[0][1])
        if not self.isins:
            raise ValueError("Security master required")
        # 0=cash/hold; per security: buy, increase, reduce, exit.
        self.action_space = spaces.Discrete(1 + 4 * len(self.isins))
        # cash fraction, drawdown, then weight / momentum / volatility / holding days per security.
        self.observation_space = spaces.Box(-np.inf, np.inf, (2 + 5 * len(self.isins),), np.float32)
        self.db = engine("sqlite:///:memory:")
        self.index = 1
        self.nav = 10000000
        self.peak = self.nav
        self.costs = Costs()
        self.done = False
        self.held_since: dict[str, int] = {}

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[NDArray[np.float32], dict[str, Any]]:
        super().reset(seed=seed)
        self.db.dispose()
        self.db = engine("sqlite:///:memory:")
        Base.metadata.create_all(self.db)
        with transaction(self.db) as session:
            for model, records in self.records:
                session.add_all(model(**row) for row in records)
                session.flush()
            for day in self.days:
                market = session.get(MarketSession, day)
                if market is None or not market.verified:
                    raise ValueError("Verified session calendar required")
            account = initialize(session, "rl-research", 0)
            account.stopped = False
        self.index, self.nav, self.peak, self.done = 1, 10000000, 10000000, False
        self.held_since = {}
        return self._observation(), {"dataset_label": self.dataset_label, "status": "experimental"}

    def _observation(self) -> NDArray[np.float32]:
        with transaction(self.db) as session:
            previous = session.get(
                MarketSession, self.days[min(self.index - 1, len(self.days) - 1)]
            )
            assert previous is not None
            cutoff = previous.closes_at + 300
            account = session.get(Account, "rl-research")
            assert account is not None
            values = [account.cash_paise / self.nav, 1 - self.nav / self.peak]
            for isin in self.isins:
                bars = point_in_time_bars(session, isin, cutoff)
                holding = session.get(Holding, (account.id, isin))
                quantity = holding.quantity if holding else 0
                # Missing observations are zero-filled only alongside a trade-blocking history gate.
                features = technical([float(b.close_paise) for b in bars]) if bars else {}
                values.extend(
                    [
                        quantity * bars[-1].close_paise / self.nav if bars else 0.0,
                        features.get("momentum20") or 0.0,
                        features.get("volatility20") or 0.0,
                        float(self.index - self.held_since.get(isin, self.index)),
                        float(len(bars) >= 21),
                    ]
                )
        return np.asarray(values, dtype=np.float32)

    def step(
        self, action: int | np.int64
    ) -> tuple[NDArray[np.float32], float, bool, bool, dict[str, Any]]:
        if self.done:
            raise RuntimeError("Reset after episode termination")
        if not self.action_space.contains(action):
            raise ValueError("Invalid action")
        reason, turnover = "hold_or_cash", 0
        with transaction(self.db) as session:
            market = session.get(MarketSession, self.days[self.index])
            previous = session.get(MarketSession, self.days[self.index - 1])
            assert market is not None and previous is not None
            cutoff = previous.closes_at + 300
            for corporate_action in session.scalars(
                select(CorporateAction).where(
                    CorporateAction.effective_at > previous.opens_at,
                    CorporateAction.effective_at <= market.opens_at,
                )
            ):
                apply_action(session, "rl-research", corporate_action.id, market.opens_at)
            rows = session.scalars(select(Bar).where(Bar.day == market.day)).all()
            if len({b.isin for b in rows}) != len(rows):
                raise ValueError("Ambiguous fill sources/revisions")
            by_isin = {b.isin: b for b in rows}
            quotes = {
                isin: Quote(
                    isin,
                    b.open_paise,
                    market.opens_at,
                    market.opens_at,
                    "simulated-next-open:" + b.source,
                )
                for isin, b in by_isin.items()
            }
            if action:
                asset, operation = divmod(int(action) - 1, 4)
                isin = self.isins[asset]
                bars = point_in_time_bars(session, isin, cutoff)
                holding = session.get(Holding, ("rl-research", isin))
                held = holding.quantity if holding else 0
                if isin not in quotes or len(bars) < 21:
                    reason = "blocked_missing_history_or_fill"
                elif session.scalar(
                    select(CorporateAction.id).where(
                        CorporateAction.isin == isin, CorporateAction.effective_at <= cutoff
                    )
                ):
                    reason = "blocked_action_normalization"
                else:
                    side: Literal["buy", "sell"] = "buy" if operation < 2 else "sell"
                    quantity = (
                        int(self.nav * 0.02) // quotes[isin].price_paise
                        if operation < 2
                        else max(1, held // 2)
                        if operation == 2
                        else held
                    )
                    proposal = Proposal(
                        f"rl:{market.day}",
                        "rl-research",
                        isin,
                        side,
                        quantity,
                        cutoff,
                        market.opens_at,
                        "experimental RL action",
                    )
                    try:
                        order = execute(
                            session, proposal, quotes, Settings(emergency_stop=False), self.costs
                        )
                        reason = "simulated_fill"
                        turnover = order.price_paise * quantity
                        if not held and side == "buy":
                            self.held_since[isin] = self.index
                        if side == "sell" and quantity == held:
                            self.held_since.pop(isin, None)
                    except RiskRejected as error:
                        reason = str(error)
            account = session.get(Account, "rl-research")
            assert account is not None
            holdings = session.scalars(
                select(Holding).where(Holding.account_id == account.id, Holding.quantity > 0)
            ).all()
            if any(h.isin not in by_isin for h in holdings):
                raise ValueError("Missing valuation; episode blocked")
            next_nav = account.cash_paise + sum(
                h.quantity * by_isin[h.isin].close_paise for h in holdings
            )
            if next_nav <= 0:
                raise RuntimeError("Invalid NAV")
            weights = [h.quantity * by_isin[h.isin].close_paise / next_nav for h in holdings]
            next_peak = max(self.peak, next_nav)
            drawdown_increase = max(0.0, (1 - next_nav / next_peak) - (1 - self.nav / self.peak))
            reward = float(
                np.log(next_nav / self.nav)
                - 0.1 * drawdown_increase
                - 0.001 * turnover / self.nav
                - 0.0001 * sum(w * w for w in weights)
            )
            self.nav, self.peak = next_nav, next_peak
            reconcile(session, account.id)
        self.index += 1
        self.done = self.index >= len(self.days)
        return (
            self._observation(),
            reward,
            self.done,
            False,
            {
                "reason": reason,
                "nav_paise": self.nav,
                "status": "experimental",
                "dataset_label": self.dataset_label,
            },
        )

    def close(self) -> None:
        self.db.dispose()
