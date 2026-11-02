"""Strict reads of one client's account (Calcap addition).

The package's usual helpers print errors and return empty results. Anything
built on a client's data (billing, performance reports) can't use a read that
silently missed something, so here every failure raises: ``Unauthorized`` when
Robinhood rejects the token, ``ReadFailed`` for anything else. Requests only go
to Robinhood's own hosts, are retried briefly when Robinhood is busy, and follow
a list's pages to the end.

Call these inside ``clients.client_session(tokens)``, which supplies the
client's read-only session::

    from calcap_robin_stocks.robinhood import reads
    from calcap_robin_stocks.robinhood.clients import client_session

    with client_session(tokens):
        for row in reads.accounts():
            print(row["account_number"], reads.portfolio_profile(row["account_number"])["equity"])

They return Robinhood's rows as it sends them. Deciding what they mean (which
accounts count, signs, rounding) is the caller's job.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from calcap_robin_stocks.robinhood import urls
from calcap_robin_stocks.robinhood.helper import current_session

#: Hosts a client's token may be sent to.
HOSTS = {"api.robinhood.com", "bonfire.robinhood.com"}
#: Statement downloads redirect from api.robinhood.com to Robinhood's S3 bucket.
#: requests drops the Authorization header when the host changes, so the token
#: isn't sent there.
STATEMENT_HOSTS = {"mountain-storage.s3.amazonaws.com"}
MAX_STATEMENT_BYTES = 10 * 1024 * 1024
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_PAGES = 500

ACCOUNTS_URL = "https://api.robinhood.com/accounts/"
#: Without these, Robinhood leaves out retirement and managed accounts.
ACCOUNTS_PARAMS = {
    "default_to_all_accounts": "true",
    "include_managed": "true",
    "include_multiple_individual": "true",
    "is_default": "false",
}
SWEEPS_URL = "https://api.robinhood.com/accounts/sweeps/"
DEVICES_URL = "https://api.robinhood.com/devices/"


class Unauthorized(Exception):
    """Robinhood rejected the token."""


class ReadFailed(Exception):
    """Robinhood didn't return something that was asked for."""


# ------------------------------------------------------------------- requests


def get(url: str, params: Optional[Dict[str, str]] = None) -> Any:
    """One request's JSON. Retries a busy Robinhood (429 and 5xx) a few times."""
    if urlsplit(url).hostname not in HOSTS:
        raise ReadFailed(f"Refusing to send the client's token to {urlsplit(url).hostname}.")
    for attempt in range(4):
        response = current_session().get(url, params=params)
        if response.status_code in (401, 403):
            raise Unauthorized()
        if response.status_code in RETRY_STATUSES and attempt < 3:
            wait = response.headers.get("Retry-After", "")
            time.sleep(min(10.0, float(wait)) if wait.replace(".", "", 1).isdigit() else 2**attempt)
            continue
        if response.status_code != 200:
            raise ReadFailed(f"Robinhood answered {response.status_code} for {urlsplit(url).path}.")
        return response.json()
    raise ReadFailed(f"Robinhood kept failing for {urlsplit(url).path}.")


def paged(
    url: str, params: Optional[Dict[str, str]] = None, on_page: Optional[Callable[[int], None]] = None
) -> List[dict]:
    """Every page of a list. ``on_page`` hears how many rows have arrived so far."""
    rows: List[dict] = []
    for _ in range(MAX_PAGES):
        page = get(url, params)
        rows.extend(r for r in page.get("results") or [] if isinstance(r, dict))
        if on_page:
            on_page(len(rows))
        url, params = page.get("next"), None
        if not url:
            return rows
    raise ReadFailed(f"More than {MAX_PAGES} pages from {urlsplit(url).path}.")


def download(url: str) -> bytes:
    """A document such as a statement PDF. Starts at Robinhood and may only end at its S3 bucket."""
    if urlsplit(url).hostname not in HOSTS:
        raise ReadFailed(f"Refusing to send the client's token to {urlsplit(url).hostname}.")
    response = current_session().get(url)
    if response.status_code in (401, 403):
        raise Unauthorized()
    final = urlsplit(response.url).hostname
    if final not in HOSTS | STATEMENT_HOSTS:
        raise ReadFailed(f"A statement download ended at an unexpected host: {final}.")
    if response.status_code != 200:
        raise ReadFailed(f"Robinhood answered {response.status_code} for a statement download.")
    if len(response.content) > MAX_STATEMENT_BYTES:
        raise ReadFailed("A statement PDF was larger than expected.")
    return response.content


# ---------------------------------------------------------------------- reads


def user_email() -> str:
    """The login's email. Also checks the token works."""
    return get(urls.user_profile_url()).get("email") or ""


def accounts() -> List[dict]:
    """Every brokerage account, retirement and managed ones included, closed ones too."""
    return paged(ACCOUNTS_URL, ACCOUNTS_PARAMS)


def portfolio_profile(account_number: str) -> dict:
    """An account's current value: ``equity`` (everything) and ``market_value`` (holdings)."""
    return get(urls.portfolio_profile_url(account_number) + "/")


def performance(account_number: str, span: str) -> List[Tuple[str, float]]:
    """``(day, dollar value)`` from Robinhood's own performance chart for an account.

    ``span`` is ``"ytd"``, ``"year"`` or ``"all"``. These are the "returns" line's
    points: the account's value with deposits and withdrawals taken out. Each
    point is dated by its label, which on the coarse ``"all"`` span is the first
    day of the interval it covers.
    """
    chart = get(
        urls.portfolio_performance_url(account_number),
        {
            "chart_style": "PERFORMANCE",
            "chart_type": "historical_portfolio",
            "display_currency": "USD",
            "display_span": span,
            "include_all_hours": "true",
        },
    )
    points = []
    for line in chart.get("lines") or []:
        if line.get("identifier") != "returns":
            continue
        for segment in line.get("segments") or []:
            for point in segment.get("points") or []:
                cursor = point.get("cursor_data") or {}
                day = _chart_day(cursor)
                amount = ((cursor.get("price_chart_data") or {}).get("dollar_value") or {}).get("amount")
                try:
                    value = float(amount)
                except (TypeError, ValueError):
                    continue
                if day:
                    points.append((day, value))
    return points


def _chart_day(cursor: dict) -> Optional[str]:
    label = (cursor.get("label") or {}).get("value")
    try:
        return datetime.strptime(label, "%b %d, %Y").date().isoformat()
    except (TypeError, ValueError):
        return None


def positions(account_number: str) -> List[dict]:
    """An account's positions, without the ones Robinhood keeps at zero."""
    return paged(urls.positions_url(account_number), {"nonzero": "true"})


def quotes(symbols: Iterable[str]) -> List[dict]:
    """Latest quotes. Robinhood answers ``None`` for a symbol it doesn't know; those are left out."""
    symbols = sorted(set(symbols))
    if not symbols:
        return []
    return [q for q in get(urls.quotes_url(), {"symbols": ",".join(symbols)}).get("results") or [] if q]


def stock_orders(
    account_number: str, since: Optional[str] = None, on_page: Optional[Callable[[int], None]] = None
) -> List[dict]:
    """An account's stock orders in every state, from ``since`` (``"YYYY-MM-DD"``) if given."""
    return paged(urls.orders_url(account_number=account_number, start_date=since), on_page=on_page)


def unified_transfers() -> List[dict]:
    """Every deposit and withdrawal, from bank and between accounts, in every state."""
    return paged(urls.unifiedtransfers_url())


def dividends() -> List[dict]:
    """Every dividend, in every state, across the login's accounts."""
    return paged(urls.dividends_url())


def sweeps() -> List[dict]:
    """Cash sweep entries, including the interest paid on cash (``reason: "interest_payment"``)."""
    return paged(SWEEPS_URL)


def split_payments(account_number: str) -> List[dict]:
    """Shares given or taken in stock splits. Each account must be asked for by number:
    without one, only the individual account's come back."""
    return paged(urls.split_payments_url(), {"account_number": account_number})


def instrument(instrument: str) -> dict:
    """An instrument, by its URL (as orders and dividends link to it) or its ID."""
    if not instrument.startswith("https://"):
        instrument = f"{urls.instruments_url()}{instrument}/"
    return get(instrument)


def documents() -> List[dict]:
    """Every document: statements (``type: "account_statement"``), tax forms, confirms."""
    return paged(urls.documents_url())


def historicals(symbols: Iterable[str], span: str, interval: str = "day", bounds: str = "regular") -> List[dict]:
    """Price history for several symbols at once, one result per symbol."""
    data = get(
        urls.historicals_url(),
        {"symbols": ",".join(symbols), "interval": interval, "span": span, "bounds": bounds},
    )
    return [r for r in data.get("results") or [] if r]


def trusted_devices() -> List[dict]:
    """The devices signed in to the account, as the app's Security > Devices screen lists them."""
    return paged(DEVICES_URL)
