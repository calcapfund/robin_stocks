# Changelog

All notable changes to this fork (`calcap-robin-stocks`) are recorded here.

## 3.4.0.post6

### Added
- `reads.portfolio_history(account_number, span="year")`: an account's value at
  each day's close, from `GET api.robinhood.com/portfolios/historicals/<n>/`
  (`interval=day`, `bounds=regular`), as Robinhood's `equity_historicals` rows.
  Unlike `reads.performance`, these are balances, with deposits and withdrawals
  left in, and they split the account into holdings (`close_market_value`) and
  everything (`close_equity`).

## 3.4.0.post5

### Fixed
- `clients.request_code` ("Text me instead") works for app-approval logins. It
  used `POST /challenge/<id>/replace/`, which Robinhood only allows for a
  challenge that offers an alternate type; an app approval has none, so it
  always failed. It now does what robinhood.com does: it opens the login's
  verification workflow at `identi.robinhood.com/idl/v1/workflow/<id>/` and
  takes the app-approval screen's fallback, which texts a code. `submit_code`
  answers that code the way the code screen asks (through the workflow, or to
  the challenge followed by the workflow's "proceed"), and `finish_login` logs in
  again once the workflow ends approved. If the client approved in the app
  meanwhile, `request_code` returns the login already approved.

### Changed
- `PendingLogin` keeps the verification workflow's ID and, after
  `request_code`, the workflow screen holding the code (`screen`, `block_id`,
  `code_to_workflow`). Older saved values still load; their workflow ID is read
  from the verification page.
- Client sessions may send `PATCH` to identi's workflow path, but only with one
  of the verification actions in `_WORKFLOW_ACTIONS` (open the verification,
  take the approval's fallback, submit or proceed with the texted code). The
  same endpoint takes account-changing actions, such as freezing the account,
  and those stay blocked.

## 3.4.0.post4

### Changed
- Requires Python 3.15 or newer (`python_requires='>=3.15'`), the version
  Calcap's sync service runs. CI tests 3.15 only, and the daily upstream sync
  runs on 3.15.

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
