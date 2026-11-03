# CLAUDE.md

Calcap-wide rules (Calcap team, with the private docs repo cloned next to this one): @../calcap-docs/CLAUDE.md

Calcap's fork of [robin_stocks](https://github.com/jmfernandes/robin_stocks), installed as
`calcap-robin-stocks` and imported as `calcap_robin_stocks`. It's the only place Calcap's software
talks to Robinhood. Detailed docs for the team: `../calcap-docs/robinhood-library/`. This file holds
only rules that rarely change.

## Rules

- **Calcap's code** is `calcap_robin_stocks/robinhood/clients.py` (per-client sessions, login steps)
  and `calcap_robin_stocks/robinhood/reads.py` (strict reads), plus small hooks in `globals.py` and
  `helper.py`. Keep changes to upstream files to a minimum, so the daily upstream merge stays clean.
- **Python 3.15+** (CI runs 3.15), the version calcap_api, the only consumer, runs. Calcap's own
  files may use current syntax; leave upstream files' syntax alone so merges stay clean.
- **Client sessions are read-only.** Never widen the allow-list in `clients.py` to a request that can
  change an account.
- **Strict reads raise** (`Unauthorized`, `ReadFailed`) instead of printing and returning empty, and
  send the token only to Robinhood's hosts.
- **Every new request gets an offline test** using the fake Robinhood in
  `tests/test_client_sessions.py`. A new test file must also be added to both workflows
  (`.github/workflows/pythonapp.yml`, `sync-upstream.yml`).
- **Releasing:** bump the version in `setup.py`, add a `CHANGELOG.md` entry, merge to `master`; then
  in calcap_api run `uv lock --upgrade-package calcap-robin-stocks`.
- **This repo is public.** No secrets, client data, account numbers or internal hostnames in code,
  tests, commits or issues.
- Python only through uv.
