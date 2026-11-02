# Changelog

All notable changes to this fork (`calcap-robin-stocks`) are recorded here.

## 3.4.0.post3

Calcap's sync service now reaches Robinhood only through this package.

### Added
- `robinhood.reads`: strict reads of a client's account for billing and
  reports. Every failure raises (`Unauthorized` when Robinhood rejects the token,
  `ReadFailed` otherwise); lists are read to their last page; 429 and 5xx answers
  are retried briefly; the token is only sent to `api.robinhood.com` and
  `bonfire.robinhood.com`, and statement downloads may only end at Robinhood's S3
  bucket. Readers: `user_email`, `accounts` (retirement and managed accounts
  included), `portfolio_profile`, `performance` (the performance chart's
  "returns" line as dated values), `positions`, `quotes`, `stock_orders`,
  `unified_transfers`, `dividends`, `sweeps`, `split_payments` (by account),
  `instrument`, `documents`, `download`, `historicals` and `trusted_devices`
  (`/devices/`, the app's Security > Devices list).
- `clients.request_code`: swaps a login's app approval for a texted (or emailed)
  code, as "Text me instead" does on robinhood.com
  (`POST /challenge/<id>/replace/`).
- `clients.verification_page`: Robinhood's device-verification page for a login
  in progress, for diagnosing one that stalls.

### Fixed
- The daily upstream sync was skipped after the repository moved to the
  `calcapfund` organization; it now runs there.

## 3.4.0.post2

Endpoint refresh after a live audit of the Robinhood web app (2026-10). Every
added endpoint was verified against a real signed-in session; nothing was removed
on suspicion alone.

### Removed
- `robinhood.urls.phoenix_url` and `robinhood.account.load_phoenix_account` —
  `phoenix.robinhood.com` no longer completes a TLS handshake. Use
  `load_unified_accounts()` instead (see below).

### Added — accounts & portfolio
- `load_unified_accounts()` — unified cash/buying-power per account
  (`bonfire.robinhood.com/accounts/unified/`, the live replacement for phoenix).
- `get_portfolio_performance(account_number=None)` — daily portfolio performance
  chart data (`bonfire…/portfolio/performance/<account>`).
- `get_interest_rate()` — current cash-sweep interest rates
  (`/accounts/sweeps/interest/`).

### Added — transfers & corporate actions
- `get_crypto_transfers()` — crypto deposit/withdrawal history.
- `get_acats_transfers()` / `get_asset_transfers()` — ACATS broker-to-broker
  transfers (`/acats/` and `nimbus/v1/asset_transfers`).
- `get_split_payments()` — stock-split payments applied to the account.
- `get_adr_fees()` — ADR fees charged to the account.
- `get_drip_enrollment(account_number=None)` — DRIP enrollment status.
- `get_retirement_history()` — retirement (IRA) activity history.
- `get_rhy_accounts()` — Robinhood cash/spending accounts.

### Added — market data
- `get_marketdata_fundamentals(inputSymbols)` — richer fundamentals from
  `/marketdata/fundamentals/` (trading stats plus company profile).

### Added — orders
- `get_combo_orders()` — combo/multi-leg orders.
- `get_advanced_orders()` — advanced orders (trailing stops, recurring, …).

### Tests
- New offline suite `tests/test_new_endpoints.py` (URL builders, request wiring,
  info-filtering, exports) and a credential-gated live suite
  `tests/test_new_endpoints_live.py`.
