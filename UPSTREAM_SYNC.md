# Keeping this fork current

The Sync upstream GitHub Action checks `jmfernandes/robin_stocks`'s `master`
branch daily at 12:23 UTC, and can also be run manually from the Actions tab.
GitHub may delay scheduled runs or disable schedules after 60 days without
repository activity; re-enable the workflow in Actions if necessary.

It merges upstream into this fork's `master`, installs the merged package,
and runs `tests/test_fork_compatibility.py` before pushing. It never resets
the fork or force-pushes. Existing custom commits remain in history.
Git follows the package directory rename when merging upstream additions.
New upstream Python files and imports are adapted from `robin_stocks` to
`calcap_robin_stocks` by `tools/normalize_upstream.py`. Namespace collisions
stop the run for manual resolution.

A merge conflict, failed test, or rejected push stops the workflow without
changing the remote branch. Review failed runs in Actions, resolve conflicts
locally, run the offline checks, and push the resolution. Changes that Git can
merge automatically may still require review; these checks cover Calcap's
custom filtering, transfer pagination, per-client sessions and strict reads, not
all Robinhood API behavior.

Local check (no brokerage credentials or API access required):

```sh
python -m unittest discover -s tests -p test_fork_compatibility.py -v
python -m unittest discover -s tests -p test_client_sessions.py -v
python -m unittest discover -s tests -p test_reads.py -v
```

## Per-client sessions

`calcap_robin_stocks/robinhood/clients.py` lets one process read several
clients' accounts. Its module docstring explains how to use it. It needs only
two small hooks in upstream files, so merges rarely touch it:

- `globals.py` defines `CLIENT_SESSION`, a `ContextVar` holding the active
  client's session.
- `helper.py` sends every request through `current_session()`, and
  `login_required` accepts an active client session.

If an upstream merge adds a new direct `SESSION.get`/`post`/`delete` in
`helper.py`, change it to `current_session()`. Otherwise those requests would
use the shared login instead of the client's. `test_client_sessions.py` checks
that clients stay separate and that client sessions refuse anything but reads
and login steps.

## Strict reads

`calcap_robin_stocks/robinhood/reads.py` is what Calcap's sync service reads
clients' accounts with. It is new code, not a change to upstream's, so merges
don't touch it. It builds URLs with `urls.py`; if upstream renames or removes a
URL function it uses, `test_reads.py` fails.

## Using an update in Calcap

`calcap_api` installs this package from `master`, pinned to a commit in its
`uv.lock`, so a merge here changes nothing there by itself. In `calcap_api`, run
`uv lock --upgrade-package calcap-robin-stocks`, run its tests, and commit the
lock file.
