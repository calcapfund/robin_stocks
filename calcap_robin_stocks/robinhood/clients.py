"""Read several clients' Robinhood accounts from one process (Calcap addition).

The rest of the package keeps a single login in ``globals.SESSION``. Inside
``client_session(tokens)``, every request this package makes on the current
thread or asyncio task uses that client's own session instead, so two clients'
tokens never mix::

    from calcap_robin_stocks.robinhood import get_all_stock_orders
    from calcap_robin_stocks.robinhood.clients import Tokens, client_session

    with client_session(Tokens.from_dict(saved)):
        orders = get_all_stock_orders()

Client sessions are read-only: they refuse any request that could change an
account (orders, transfers, watchlists...) and allow only reads plus the login,
refresh and verification steps.

Logging in is split into steps a web app can drive, without prompts:
``start_login`` -> ``check_login`` or ``submit_code`` -> ``finish_login``. When
an app approval doesn't arrive, ``request_code`` swaps it for a texted (or
emailed) code, like "Text me instead" on robinhood.com; then ``submit_code``.
``refresh_tokens`` renews a session without the client. Nothing here prints a
secret or writes a file; callers store the returned ``Tokens`` themselves.

Each client must keep the same device token for every login and refresh, or
Robinhood treats it as a new device and asks for verification again. A thread
started inside ``client_session`` does not inherit it; enter
``client_session`` again in that thread.
"""

from __future__ import annotations

import base64
import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Iterator, Optional, Union
from urllib.parse import urlsplit

from requests import Response, Session

from calcap_robin_stocks.robinhood.authentication import generate_device_token
from calcap_robin_stocks.robinhood.globals import CLIENT_SESSION, SESSION
from calcap_robin_stocks.robinhood.urls import challenge_url, login_url

CLIENT_ID = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"
TIMEOUT = 20
_HOST = "api.robinhood.com"
_PATHFINDER = "https://api.robinhood.com/pathfinder"

# Requests that aren't reads but change nothing in the account: getting tokens
# and answering Robinhood's device verification.
_AUTH_PATHS = (
    "/oauth2/token/",
    "/pathfinder/user_machine/",
    "/pathfinder/inquiries/",
    "/challenge/",
)
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ReadOnlyViolation(PermissionError):
    """A client session was asked to send a request that could change the account."""


class ReauthenticationRequired(Exception):
    """Robinhood no longer accepts the saved tokens. The client has to log in again."""


class LoginFailed(Exception):
    """Robinhood rejected the login, for example a wrong password or code."""


class AuthenticatorCodeRequired(Exception):
    """The account uses an authenticator app. Call start_login again with mfa_code."""


class LoginNotApproved(Exception):
    """The client hasn't approved the login yet. Check again shortly."""


def is_allowed(method: str, url: str) -> bool:
    """Whether a client session may send this request."""
    if method.upper() in _READ_METHODS:
        return True
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == _HOST and parts.path.startswith(_AUTH_PATHS)


class ReadOnlySession(Session):
    """A requests session that refuses anything but reads and the login steps.

    The check runs in send(), so it also covers redirects.
    """

    def request(self, method, url, *args, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        return super().request(method, url, *args, **kwargs)

    def send(self, request, **kwargs):
        if not is_allowed(request.method, request.url):
            raise ReadOnlyViolation(
                f"{request.method} {urlsplit(request.url).path} was blocked: client sessions are read-only."
            )
        return super().send(request, **kwargs)


def new_session(access_token: Optional[str] = None, token_type: str = "Bearer") -> ReadOnlySession:
    """A fresh read-only session with the package's usual headers and no shared state."""
    session = ReadOnlySession()
    session.headers.clear()
    session.headers.update({k: v for k, v in SESSION.headers.items() if k.lower() != "authorization"})
    if access_token:
        session.headers["Authorization"] = f"{token_type} {access_token}"
    return session


@dataclass(frozen=True)
class Tokens:
    """What to store per client. Never includes the password."""

    access_token: str
    refresh_token: str
    device_token: str
    token_type: str = "Bearer"
    #: A token with Robinhood's "read" scope, which can't trade or move money. Robinhood
    #: returns it with a password login, not with a refresh.
    read_only_token: Optional[str] = None

    @property
    def expires_at(self) -> Optional[float]:
        """Unix time the access token expires, read from the token itself."""
        try:
            part = self.access_token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            return float(claims["exp"])
        except (IndexError, KeyError, TypeError, ValueError):
            return None

    def expires_within(self, seconds: float) -> bool:
        """True if the access token expires within `seconds`, or its expiry can't be read."""
        expires = self.expires_at
        return expires is None or expires - time.time() <= seconds

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Tokens":
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            device_token=data["device_token"],
            token_type=data.get("token_type") or "Bearer",
            read_only_token=data.get("read_only_token"),
        )

    def __repr__(self) -> str:  # keep tokens out of logs and tracebacks
        return f"Tokens(device_token=…{self.device_token[-4:]}, expires_at={self.expires_at})"


@contextmanager
def client_session(tokens: Tokens, session: Optional[ReadOnlySession] = None) -> Iterator[ReadOnlySession]:
    """Make every request in this block use this client's tokens, read-only."""
    if session is None:
        session = new_session()
        owned = True
    else:
        if not isinstance(session, ReadOnlySession):
            raise TypeError("client_session needs a ReadOnlySession")
        owned = False
    # Prefer the read-scope token: then Robinhood itself refuses changes too.
    session.headers["Authorization"] = f"{tokens.token_type} {tokens.read_only_token or tokens.access_token}"
    marker = CLIENT_SESSION.set(session)
    try:
        yield session
    finally:
        CLIENT_SESSION.reset(marker)
        if owned:
            session.close()


def refresh_tokens(tokens: Tokens, session: Optional[ReadOnlySession] = None) -> Tokens:
    """Get new tokens without the client. Save the result at once: the old refresh token stops working."""
    session = session or new_session()
    response = session.post(
        login_url(),
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": CLIENT_ID,
            "device_token": tokens.device_token,
            "scope": "internal",
            "expires_in": 86400,
        },
    )
    if response.status_code in (400, 401, 403):
        raise ReauthenticationRequired(f"Robinhood refused the refresh ({response.status_code}).")
    response.raise_for_status()
    data = _json(response)
    if not data.get("access_token"):
        raise ReauthenticationRequired("Robinhood asked for a new login or device approval.")
    return replace(
        tokens,
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or tokens.refresh_token,
        token_type=data.get("token_type") or tokens.token_type,
        # The old read-only token expires with the old session, so only keep a new one.
        read_only_token=data.get("read_only_secondary_access_token"),
    )


# ------------------------------------------------------------------- login steps


@dataclass(frozen=True)
class PendingLogin:
    """A login waiting on the client. Safe to keep between web requests: no password or token."""

    device_token: str
    machine_id: str
    challenge_id: Optional[str] = None
    #: "prompt" (approve in the Robinhood app), "sms" or "email" (type the code), or None.
    challenge_type: Optional[str] = None
    approved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PendingLogin":
        return cls(**data)


def start_login(
    username: str,
    password: str,
    device_token: Optional[str] = None,
    mfa_code: Optional[str] = None,
    session: Optional[ReadOnlySession] = None,
) -> Union[Tokens, PendingLogin]:
    """Send the password once. Returns tokens, or a PendingLogin if Robinhood wants the client to verify.

    Pass the client's existing device token when reconnecting so Robinhood recognises the device.
    """
    session = session or new_session()
    device_token = device_token or generate_device_token()
    data = _password_grant(session, username, password, device_token, mfa_code)
    if data.get("access_token"):
        return _tokens(data, device_token)
    if data.get("mfa_required"):
        raise AuthenticatorCodeRequired("Enter the code from the authenticator app.")
    workflow = data.get("verification_workflow") or {}
    if not workflow.get("id"):
        raise LoginFailed(_detail(data) or "Robinhood rejected the login.")
    machine = _json(
        session.post(
            f"{_PATHFINDER}/user_machine/",
            json={"device_id": device_token, "flow": "suv", "input": {"workflow_id": workflow["id"]}},
            headers={"Content-Type": "application/json"},
        )
    )
    if not machine.get("id"):
        raise LoginFailed("Robinhood didn't start device verification.")
    return _read_challenge(session, PendingLogin(device_token=device_token, machine_id=machine["id"]))


def check_login(pending: PendingLogin, session: Optional[ReadOnlySession] = None) -> PendingLogin:
    """Ask whether the client has approved. Poll every few seconds until `approved`."""
    session = session or new_session()
    if pending.challenge_type is None:
        return _read_challenge(session, pending)
    if pending.challenge_type == "prompt" and pending.challenge_id:
        status = _json(session.get(f"https://{_HOST}/push/{pending.challenge_id}/get_prompts_status/"))
        return replace(pending, approved=status.get("challenge_status") == "validated")
    if pending.challenge_type in _CODE_CHALLENGES and pending.challenge_id:
        # A code is approved through submit_code. The verification page may still show the
        # challenge request_code replaced, so don't read it back over this one.
        return pending
    return _read_challenge(session, pending)


def submit_code(pending: PendingLogin, code: str, session: Optional[ReadOnlySession] = None) -> PendingLogin:
    """Send the code Robinhood texted or emailed the client."""
    if not pending.challenge_id:
        raise LoginFailed("There's no code to answer yet. Check the login again.")
    session = session or new_session()
    result = _json(session.post(challenge_url(pending.challenge_id), data={"response": code}))
    if result.get("status") != "validated":
        raise LoginFailed("Robinhood didn't accept that code.")
    return replace(pending, approved=True)


_CODE_CHALLENGES = ("sms", "email")


def request_code(pending: PendingLogin, method: str = "sms", session: Optional[ReadOnlySession] = None) -> PendingLogin:
    """Have Robinhood text (or email) a code instead of waiting for an app approval.

    What "Text me instead" does on robinhood.com: replace the challenge with one of
    another type. Answer the code with ``submit_code``.
    """
    if method not in _CODE_CHALLENGES:
        raise ValueError(f"method must be one of {_CODE_CHALLENGES}")
    if not pending.challenge_id:
        raise LoginFailed("There's no verification to change yet. Check the login again.")
    session = session or new_session()
    challenge = _json(
        session.post(f"https://{_HOST}/challenge/{pending.challenge_id}/replace/", data={"challenge_type": method})
    )
    if not challenge.get("id"):
        raise LoginFailed(_detail(challenge) or "Robinhood wouldn't send a code.")
    return replace(pending, challenge_id=challenge["id"], challenge_type=challenge.get("type") or method, approved=False)


def finish_login(
    pending: PendingLogin, username: str, password: str, session: Optional[ReadOnlySession] = None
) -> Tokens:
    """After approval, close the verification and log in again with the same device. Returns tokens."""
    session = session or new_session()
    status = _json(
        session.post(
            f"{_PATHFINDER}/inquiries/{pending.machine_id}/user_view/",
            json={"sequence": 0, "user_input": {"status": "continue"}},
            headers={"Content-Type": "application/json"},
        )
    )
    result = (status.get("type_context") or {}).get("result") or (
        (status.get("verification_workflow") or {}).get("workflow_status")
    )
    if result != "workflow_status_approved":
        raise LoginNotApproved("Robinhood hasn't confirmed the approval yet.")
    data = _password_grant(session, username, password, pending.device_token, None)
    if not data.get("access_token"):
        raise LoginFailed(_detail(data) or "Robinhood still wants verification.")
    return _tokens(data, pending.device_token)


# ---------------------------------------------------------------------- helpers


def _password_grant(session, username, password, device_token, mfa_code) -> Dict[str, Any]:
    payload = {
        "client_id": CLIENT_ID,
        "expires_in": 86400,
        "grant_type": "password",
        "password": password,
        "scope": "internal",
        "username": username,
        "device_token": device_token,
        "try_passkeys": False,
        "token_request_path": "/login",
        "create_read_only_secondary_token": True,
    }
    if mfa_code:
        payload["mfa_code"] = mfa_code
    return _json(session.post(login_url(), data=payload))


def _read_challenge(session, pending: PendingLogin) -> PendingLogin:
    view = _json(session.get(f"{_PATHFINDER}/inquiries/{pending.machine_id}/user_view/"))
    challenge = (view.get("context") or {}).get("sheriff_challenge") or {}
    if not challenge:
        return pending
    return replace(
        pending,
        challenge_id=challenge.get("id"),
        challenge_type=challenge.get("type"),
        approved=challenge.get("status") == "validated",
    )


def _tokens(data: Dict[str, Any], device_token: str) -> Tokens:
    return Tokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or "",
        device_token=device_token,
        token_type=data.get("token_type") or "Bearer",
        read_only_token=data.get("read_only_secondary_access_token"),
    )


def _json(response: Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _detail(data: Dict[str, Any]) -> Optional[str]:
    detail = data.get("detail") or data.get("error_description") or data.get("error")
    return str(detail)[:200] if detail else None
