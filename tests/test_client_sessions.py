"""Offline checks for Calcap's per-client sessions (calcap_robin_stocks.robinhood.clients).

A fake Robinhood answers every request in memory, so no credentials or network are used.
"""

import asyncio
import base64
import json
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit

from requests import Response
from requests.adapters import BaseAdapter

import calcap_robin_stocks.robinhood as rh
from calcap_robin_stocks.robinhood import clients, helper
from calcap_robin_stocks.robinhood.clients import (
    LoginFailed,
    LoginNotApproved,
    PendingLogin,
    ReadOnlyViolation,
    ReauthenticationRequired,
    Tokens,
    client_session,
    is_allowed,
    new_session,
)
from calcap_robin_stocks.robinhood.globals import SESSION


def jwt(exp):
    part = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{part}.signature"


class FakeRobinhood(BaseAdapter):
    """Answers requests from a route table and records everything it was sent."""

    def __init__(self, routes=None):
        super().__init__()
        self.routes = routes or {}
        self.calls = []
        self.lock = threading.Lock()

    def send(self, request, **kwargs):
        path = urlsplit(request.url).path
        with self.lock:
            self.calls.append((request.method, path, request.headers.get("Authorization"), request.body))
        handler = self.routes.get((request.method, path))
        if handler is None:
            # Default: echo who asked, like /user/ returning the account owner.
            status, body = 200, {"authorization": request.headers.get("Authorization"), "results": [], "next": None}
        else:
            status, body = handler(request)
        response = Response()
        response.status_code = status
        response._content = json.dumps(body).encode()
        response.headers["Content-Type"] = "application/json"
        response.url = request.url
        response.request = request
        return response

    def close(self):
        pass


def fake_session(adapter):
    session = new_session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def tokens(name):
    return Tokens(access_token=f"access-{name}", refresh_token=f"refresh-{name}", device_token=f"device-{name}")


class TestIsolation(unittest.TestCase):
    def test_shared_session_is_untouched(self):
        adapter = FakeRobinhood()
        before = dict(SESSION.headers)
        with client_session(tokens("a"), fake_session(adapter)) as session:
            self.assertIs(helper.current_session(), session)
            rh.load_user_profile()
        self.assertIs(helper.current_session(), SESSION)
        self.assertEqual(dict(SESSION.headers), before)
        self.assertNotIn("Authorization", SESSION.headers)

    def test_login_required_functions_run_inside_a_client_session(self):
        adapter = FakeRobinhood()
        with client_session(tokens("a"), fake_session(adapter)):
            profile = rh.load_user_profile()
        self.assertEqual(profile["authorization"], "Bearer access-a")
        with self.assertRaises(Exception):
            rh.load_user_profile()  # outside: still requires the shared login

    def test_parallel_threads_never_mix_tokens(self):
        adapter = FakeRobinhood()
        names = [f"client{i}" for i in range(8)]
        start = threading.Barrier(len(names))
        seen = {name: set() for name in names}

        def work(name):
            with client_session(tokens(name), fake_session(adapter)):
                start.wait()
                for _ in range(40):
                    seen[name].add(rh.load_user_profile()["authorization"])
                    time.sleep(0)

        threads = [threading.Thread(target=work, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for name in names:
            self.assertEqual(seen[name], {f"Bearer access-{name}"})

    def test_parallel_asyncio_tasks_never_mix_tokens(self):
        adapter = FakeRobinhood()

        async def work(name):
            with client_session(tokens(name), fake_session(adapter)):
                results = set()
                for _ in range(20):
                    results.add(rh.load_user_profile()["authorization"])
                    await asyncio.sleep(0)
                return name, results

        async def main():
            return await asyncio.gather(*(work(f"task{i}") for i in range(6)))

        for name, results in asyncio.run(main()):
            self.assertEqual(results, {f"Bearer access-{name}"})

    def test_pagination_stays_on_the_client_session(self):
        adapter = FakeRobinhood(
            {
                ("GET", "/orders/"): lambda r: (
                    200,
                    {"results": [{"id": 1}], "next": "https://api.robinhood.com/orders/page2/"},
                ),
                ("GET", "/orders/page2/"): lambda r: (200, {"results": [{"id": 2}], "next": None}),
            }
        )
        with client_session(tokens("a"), fake_session(adapter)):
            orders = rh.get_all_stock_orders()
        self.assertEqual([o["id"] for o in orders], [1, 2])
        self.assertEqual({auth for _, _, auth, _ in adapter.calls}, {"Bearer access-a"})


class TestReadOnly(unittest.TestCase):
    def test_rules(self):
        self.assertTrue(is_allowed("GET", "https://api.robinhood.com/orders/"))
        self.assertTrue(is_allowed("POST", "https://api.robinhood.com/oauth2/token/"))
        self.assertTrue(is_allowed("POST", "https://api.robinhood.com/challenge/abc/respond/"))
        self.assertFalse(is_allowed("POST", "https://api.robinhood.com/orders/"))
        self.assertFalse(is_allowed("POST", "https://api.robinhood.com/ach/transfers/"))
        self.assertFalse(is_allowed("DELETE", "https://api.robinhood.com/watchlists/x/"))
        self.assertFalse(is_allowed("POST", "https://api.robinhood.com.evil.example/oauth2/token/"))
        self.assertFalse(is_allowed("POST", "http://api.robinhood.com/oauth2/token/"))

    def test_session_refuses_changes_before_sending(self):
        adapter = FakeRobinhood()
        session = fake_session(adapter)
        with self.assertRaises(ReadOnlyViolation):
            session.post("https://api.robinhood.com/orders/", json={"side": "buy"})
        self.assertEqual(adapter.calls, [])

    def test_package_order_and_transfer_functions_send_nothing(self):
        adapter = FakeRobinhood()
        with client_session(tokens("a"), fake_session(adapter)):
            # request_post swallows errors and prints them, so these just return None.
            self.assertIsNone(rh.request_post("https://api.robinhood.com/orders/", {"side": "buy"}))
            self.assertIsNone(
                rh.withdrawl_funds_to_bank_account("https://api.robinhood.com/ach/relationships/x/", 100)
            )
            self.assertIsNone(rh.request_delete("https://api.robinhood.com/watchlists/x/"))
        self.assertEqual([c for c in adapter.calls if c[0] != "GET"], [])

    def test_client_session_requires_read_only(self):
        from requests import Session

        with self.assertRaises(TypeError):
            with client_session(tokens("a"), Session()):
                pass


class TestTokens(unittest.TestCase):
    def test_expiry_from_token(self):
        soon = Tokens(access_token=jwt(time.time() + 3600), refresh_token="r", device_token="d")
        later = Tokens(access_token=jwt(time.time() + 5 * 86400), refresh_token="r", device_token="d")
        self.assertTrue(soon.expires_within(2 * 86400))
        self.assertFalse(later.expires_within(2 * 86400))
        self.assertTrue(Tokens("opaque", "r", "d").expires_within(60))

    def test_round_trip_and_repr_hides_secrets(self):
        t = tokens("a")
        self.assertEqual(Tokens.from_dict(t.to_dict()), t)
        self.assertNotIn("access-a", repr(t))
        self.assertNotIn("refresh-a", repr(t))

    def test_refresh_keeps_device_and_rotates(self):
        def grant(request):
            form = parse_qs(request.body)
            self.assertEqual(form["grant_type"], ["refresh_token"])
            self.assertEqual(form["refresh_token"], ["refresh-a"])
            self.assertEqual(form["device_token"], ["device-a"])
            return 200, {"access_token": "access-new", "refresh_token": "refresh-new", "token_type": "Bearer"}

        adapter = FakeRobinhood({("POST", "/oauth2/token/"): grant})
        new = clients.refresh_tokens(tokens("a"), fake_session(adapter))
        self.assertEqual(
            (new.access_token, new.refresh_token, new.device_token), ("access-new", "refresh-new", "device-a")
        )

    def test_read_only_token_is_used_when_present(self):
        adapter = FakeRobinhood()
        t = Tokens("access-a", "refresh-a", "device-a", read_only_token="read-a")
        with client_session(t, fake_session(adapter)):
            self.assertEqual(rh.load_user_profile()["authorization"], "Bearer read-a")
        self.assertEqual(Tokens.from_dict(t.to_dict()), t)
        self.assertNotIn("read-a", repr(t))

    def test_refresh_drops_the_old_read_only_token(self):
        adapter = FakeRobinhood(
            {("POST", "/oauth2/token/"): lambda r: (200, {"access_token": "access-new", "refresh_token": "refresh-new"})}
        )
        old = Tokens("access-a", "refresh-a", "device-a", read_only_token="read-a")
        self.assertIsNone(clients.refresh_tokens(old, fake_session(adapter)).read_only_token)

    def test_refused_refresh_asks_for_login(self):
        adapter = FakeRobinhood({("POST", "/oauth2/token/"): lambda r: (401, {"detail": "invalid"})})
        with self.assertRaises(ReauthenticationRequired):
            clients.refresh_tokens(tokens("a"), fake_session(adapter))


class TestLoginSteps(unittest.TestCase):
    def setUp(self):
        self.state = {"grants": 0, "challenge": "issued", "workflow": "pending"}

        def password_grant(request):
            form = parse_qs(request.body)
            self.assertEqual(form["device_token"], ["device-fixed"])
            self.state["grants"] += 1
            if self.state["workflow"] != "approved":
                return 403, {"verification_workflow": {"id": "wf1", "workflow_status": "workflow_status_internal_pending"}}
            return 200, {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "token_type": "Bearer",
                "read_only_secondary_access_token": "read-1",
            }

        def respond(request):
            if parse_qs(request.body)["response"] == ["123456"]:
                self.state["challenge"] = "validated"
                return 200, {"status": "validated"}
            return 400, {"status": "failed"}

        def user_view_post(request):
            if self.state["challenge"] == "validated":
                self.state["workflow"] = "approved"
                return 200, {"type_context": {"result": "workflow_status_approved"}}
            return 200, {"verification_workflow": {"workflow_status": "workflow_status_internal_pending"}}

        self.adapter = FakeRobinhood(
            {
                ("POST", "/oauth2/token/"): password_grant,
                ("POST", "/pathfinder/user_machine/"): lambda r: (200, {"id": "machine1"}),
                ("GET", "/pathfinder/inquiries/machine1/user_view/"): lambda r: (
                    200,
                    {"context": {"sheriff_challenge": {"id": "ch1", "type": "sms", "status": self.state["challenge"]}}},
                ),
                ("POST", "/challenge/ch1/respond/"): respond,
                ("POST", "/pathfinder/inquiries/machine1/user_view/"): user_view_post,
            }
        )
        self.session = fake_session(self.adapter)

    def test_sms_flow_without_prompts_or_files(self):
        pending = clients.start_login("client@example.com", "pw", "device-fixed", session=self.session)
        self.assertIsInstance(pending, PendingLogin)
        self.assertEqual((pending.challenge_type, pending.approved), ("sms", False))
        self.assertNotIn("pw", json.dumps(pending.to_dict()))

        with self.assertRaises(LoginNotApproved):
            clients.finish_login(pending, "client@example.com", "pw", session=self.session)
        with self.assertRaises(LoginFailed):
            clients.submit_code(pending, "000000", session=self.session)

        pending = clients.submit_code(PendingLogin.from_dict(pending.to_dict()), "123456", session=self.session)
        self.assertTrue(pending.approved)
        result = clients.finish_login(pending, "client@example.com", "pw", session=self.session)
        self.assertEqual(result, Tokens("access-1", "refresh-1", "device-fixed", read_only_token="read-1"))
        self.assertEqual(self.state["grants"], 2)
        self.assertEqual([c for c in self.adapter.calls if "Authorization" in (c[2] or "")], [])

    def test_prompt_swapped_for_a_texted_code(self):

        def replace_challenge(request):
            self.assertEqual(parse_qs(request.body), {"challenge_type": ["sms"]})
            return 200, {"id": "ch2", "type": "sms", "status": "issued"}

        def respond(request):
            if parse_qs(request.body)["response"] == ["123456"]:
                self.state["challenge"] = "validated"
                return 200, {"status": "validated"}
            return 400, {"status": "failed"}

        self.adapter.routes[("GET", "/pathfinder/inquiries/machine1/user_view/")] = lambda r: (
            200,
            {"context": {"sheriff_challenge": {"id": "ch1", "type": "prompt", "status": "issued"}}},
        )
        self.adapter.routes[("GET", "/push/ch1/get_prompts_status/")] = lambda r: (200, {"challenge_status": "issued"})
        self.adapter.routes[("POST", "/challenge/ch1/replace/")] = replace_challenge
        self.adapter.routes[("POST", "/challenge/ch2/respond/")] = respond

        pending = clients.start_login("client@example.com", "pw", "device-fixed", session=self.session)
        self.assertEqual((pending.challenge_id, pending.challenge_type), ("ch1", "prompt"))
        self.assertFalse(clients.check_login(pending, session=self.session).approved)

        pending = clients.request_code(PendingLogin.from_dict(pending.to_dict()), session=self.session)
        self.assertEqual((pending.challenge_id, pending.challenge_type, pending.approved), ("ch2", "sms", False))
        # The verification page still shows the prompt; checking keeps the texted code.
        self.assertEqual(clients.check_login(pending, session=self.session).challenge_id, "ch2")

        pending = clients.submit_code(pending, "123456", session=self.session)
        result = clients.finish_login(pending, "client@example.com", "pw", session=self.session)
        self.assertEqual(result.access_token, "access-1")

    def test_code_needs_a_challenge(self):
        with self.assertRaises(LoginFailed):
            clients.request_code(PendingLogin(device_token="d", machine_id="m"), session=self.session)
        with self.assertRaises(ValueError):
            clients.request_code(PendingLogin(device_token="d", machine_id="m", challenge_id="c"), "prompt")

    def test_wrong_password(self):
        adapter = FakeRobinhood(
            {("POST", "/oauth2/token/"): lambda r: (400, {"detail": "Unable to log in with provided credentials."})}
        )
        with self.assertRaises(LoginFailed) as caught:
            clients.start_login("client@example.com", "bad", "device-fixed", session=fake_session(adapter))
        self.assertIn("Unable to log in", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
