from sqlalchemy import select
from sqlalchemy.orm import Session

from investment_engine.broker import RiskRejected
from investment_engine.models import Account, ActionPosting, CorporateAction, Holding, LedgerEntry


def apply_action(session: Session, account_id: str, action_id: str, at: int) -> None:
    account = session.scalar(select(Account).where(Account.id == account_id).with_for_update())
    if session.get(ActionPosting, (account_id, action_id)):
        return
    action = session.get(CorporateAction, action_id)
    if account is None or action is None:
        raise ValueError("Unknown account/action")
    if max(action.published_at, action.received_at, action.effective_at) > at:
        raise RiskRejected("Action not yet available/effective")
    holding = session.get(Holding, (account_id, action.isin))
    quantity = holding.quantity if holding else 0
    delta, cash = 0, 0
    if action.kind == "split":
        if not action.numerator or not action.denominator or action.numerator <= 0:
            raise ValueError("Invalid split ratio")
        new, fractional = divmod(quantity * action.numerator, action.denominator)
        if fractional:
            raise RiskRejected("Fractional entitlement requires verified cash-in-lieu")
        delta = new - quantity
        if holding:
            holding.quantity = new
    elif action.kind == "dividend":
        # effective_at is PAYMENT date; entitlement uses externally verified record-date quantity.
        # Until record-date snapshots exist, block automatic dividends rather than over-credit.
        raise RiskRejected(
            "Dividend entitlement/payment reconciliation requires record-date evidence"
        )
    else:
        raise ValueError("Unsupported corporate action")
    session.add(
        ActionPosting(
            account_id=account_id,
            action_id=action_id,
            isin=action.isin,
            share_delta=delta,
            cash_paise=cash,
            at=at,
        )
    )
    if cash:
        account.cash_paise += cash
        session.add(
            LedgerEntry(
                id=f"action:{account_id}:{action_id}",
                account_id=account_id,
                at=at,
                amount_paise=cash,
                kind="corporate_action",
            )
        )
    session.flush()
