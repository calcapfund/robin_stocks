"""Offline checks for the strict account reads (calcap_robin_stocks.robinhood.reads)."""

import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from requests import Response

from calcap_robin_stocks.robinhood import clients, reads
from calcap_robin_stocks.robinhood.clients import PendingLogin, client_session
from tests.test_client_sessions import FakeRobinhood, fake_session, tokens


def query(request):
    return {k: v[0] for k, v in parse_qs(urlsplit(request.url).query).items()}


class Answers:
    """A route handler that gives its answers in turn, then repeats the last."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Statements(FakeRobinhood):
    """Answers a download as if it had been redirected to ``final``."""

    def __init__(self, final, content=b"%PDF-1.4"):
        super().__init__()
        self.final, self.content = final, content

    def send(self, request, **kwargs):
        response = Response()
        response.status_code = 200
        response._content = self.content
        response.url = self.final
        response.request = request
        self.calls.append((request.method, urlsplit(request.url).path, request.headers.get("Authorization"), None))
        return response


class ReadsTestCase(unittest.TestCase):
    def read(self, routes, fn, *args, adapter=None):
        self.adapter = adapter or FakeRobinhood(routes)
        with client_session(tokens("a"), fake_session(self.adapter)):
            return fn(*args)


class TestRequests(ReadsTestCase):
    def test_token_only_goes_to_robinhood(self):
        for fn in (reads.get, reads.download):
            with self.assertRaises(reads.ReadFailed):
                self.read({}, fn, "https://evil.example/collect")
            self.assertEqual(self.adapter.calls, [])

    def test_busy_robinhood_is_retried(self):
        answers = Answers((503, {}), (429, {}), (200, {"ok": True}))
        with mock.patch.object(reads.time, "sleep") as sleep:
            result = self.read({("GET", "/user/"): answers}, reads.get, "https://api.robinhood.com/user/")
        self.assertEqual(result, {"ok": True})
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    def test_robinhood_that_stays_busy_fails(self):
        with mock.patch.object(reads.time, "sleep"):
            with self.assertRaises(reads.ReadFailed):
                self.read({("GET", "/user/"): lambda r: (503, {})}, reads.get, "https://api.robinhood.com/user/")
        self.assertEqual(len(self.adapter.calls), 4)

    def test_rejected_token(self):
        for status in (401, 403):
            with self.assertRaises(reads.Unauthorized):
                self.read({("GET", "/user/"): lambda r: (status, {})}, reads.get, "https://api.robinhood.com/user/")

    def test_other_answers_fail(self):
        with self.assertRaises(reads.ReadFailed):
            self.read({("GET", "/user/"): lambda r: (404, {})}, reads.get, "https://api.robinhood.com/user/")

    def test_lists_follow_every_page(self):
        pages = Answers(
            (200, {"results": [{"id": 1}, None], "next": "https://api.robinhood.com/accounts/?cursor=2"}),
            (200, {"results": [{"id": 2}], "next": None}),
        )
        rows = self.read({("GET", "/accounts/"): pages}, reads.accounts)
        self.assertEqual([r["id"] for r in rows], [1, 2])
        # The first page asks for every kind of account; the next link carries its own query.
        self.assertEqual([query(r) for r in pages.requests], [reads.ACCOUNTS_PARAMS, {"cursor": "2"}])

    def test_endless_lists_fail(self):
        loop = {("GET", "/dividends/"): lambda r: (200, {"results": [], "next": "https://api.robinhood.com/dividends/"})}
        with mock.patch.object(reads, "MAX_PAGES", 3):
            with self.assertRaises(reads.ReadFailed):
                self.read(loop, reads.dividends)
        self.assertEqual(len(self.adapter.calls), 3)

    def test_progress_hears_rows_so_far(self):
        heard = []
        routes = {
            ("GET", "/orders/"): lambda r: (
                200,
                {"results": [{"id": 1}], "next": "https://api.robinhood.com/orders/page2/"},
            ),
            ("GET", "/orders/page2/"): lambda r: (200, {"results": [{"id": 2}, {"id": 3}]}),
        }
        rows = self.read(routes, lambda: reads.stock_orders("5QR1", on_page=heard.append))
        self.assertEqual((len(rows), heard), (3, [1, 3]))


class TestDownload(ReadsTestCase):
    def test_statement_from_robinhood_storage(self):
        adapter = Statements("https://mountain-storage.s3.amazonaws.com/statement.pdf")
        pdf = self.read({}, reads.download, "https://api.robinhood.com/documents/d1/download/", adapter=adapter)
        self.assertEqual(pdf, b"%PDF-1.4")

    def test_download_must_end_at_robinhood_storage(self):
        adapter = Statements("https://evil.example/statement.pdf")
        with self.assertRaisesRegex(reads.ReadFailed, "unexpected host"):
            self.read({}, reads.download, "https://api.robinhood.com/documents/d1/download/", adapter=adapter)

    def test_oversized_download(self):
        adapter = Statements("https://mountain-storage.s3.amazonaws.com/x.pdf", b"x" * 11)
        with mock.patch.object(reads, "MAX_STATEMENT_BYTES", 10):
            with self.assertRaises(reads.ReadFailed):
                self.read({}, reads.download, "https://api.robinhood.com/documents/d1/download/", adapter=adapter)


class TestEndpoints(ReadsTestCase):
    def test_performance_reads_the_returns_line(self):
        def point(label, amount):
            value = {"dollar_value": {"amount": amount}}
            return {"cursor_data": {"label": {"value": label}, "price_chart_data": value}}

        chart = {
            "lines": [
                {"identifier": "benchmark", "segments": [{"points": [point("Jan 2, 2026", "1")]}]},
                {
                    "identifier": "returns",
                    "segments": [
                        {
                            "points": [
                                point("Jan 2, 2026", "100.5"),
                                point("Today", "1"),
                                point("Jan 5, 2026", None),
                                point("Jan 5, 2026", ""),
                            ]
                        },
                        {"points": [point("Jan 6, 2026", "101")]},
                    ],
                },
            ]
        }
        answers = Answers((200, chart))
        points = self.read({("GET", "/portfolio/performance/5QR1"): answers}, reads.performance, "5QR1", "ytd")
        self.assertEqual(points, [("2026-01-02", 100.5), ("2026-01-06", 101.0)])
        self.assertEqual(query(answers.requests[0])["display_span"], "ytd")

    def test_portfolio_history_reads_each_close(self):
        rows = [{"begins_at": "2026-10-30T00:00:00Z", "close_equity": "86618.95", "close_market_value": "73000.00"}]
        answers = Answers((200, {"span": "year", "equity_historicals": rows + [None]}))
        got = self.read({("GET", "/portfolios/historicals/5QR1/"): answers}, reads.portfolio_history, "5QR1")
        self.assertEqual(got, rows)
        self.assertEqual(query(answers.requests[0]), {"interval": "day", "span": "year", "bounds": "regular"})
        self.assertEqual({auth for _, _, auth, _ in self.adapter.calls}, {"Bearer access-a"})

    def test_portfolio_history_failure_raises(self):
        with self.assertRaises(reads.ReadFailed):
            self.read({("GET", "/portfolios/historicals/5QR1/"): lambda r: (404, {})}, reads.portfolio_history, "5QR1")

    def test_quotes_skip_unknown_symbols(self):
        answers = Answers((200, {"results": [{"symbol": "AAPL"}, None]}))
        self.assertEqual(self.read({}, reads.quotes, []), [])
        rows = self.read({("GET", "/quotes/"): answers}, reads.quotes, ["MSFT", "AAPL", "AAPL"])
        self.assertEqual(rows, [{"symbol": "AAPL"}])
        self.assertEqual(query(answers.requests[0])["symbols"], "AAPL,MSFT")

    def test_split_payments_are_asked_for_by_account(self):
        answers = Answers((200, {"results": [{"id": "p1"}]}))
        rows = self.read({("GET", "/corp_actions/v2/split_payments/"): answers}, reads.split_payments, "5QR1")
        self.assertEqual(rows, [{"id": "p1"}])
        self.assertEqual(query(answers.requests[0]), {"account_number": "5QR1"})

    def test_instrument_by_id_or_url(self):
        routes = {("GET", "/instruments/i1/"): lambda r: (200, {"symbol": "AAPL"})}
        self.assertEqual(self.read(routes, reads.instrument, "i1")["symbol"], "AAPL")
        by_url = self.read(routes, reads.instrument, "https://api.robinhood.com/instruments/i1/")
        self.assertEqual(by_url["symbol"], "AAPL")

    def test_trusted_devices(self):
        routes = {("GET", "/devices/"): lambda r: (200, {"results": [{"id": "d1", "device_label": "iPhone"}]})}
        self.assertEqual(self.read(routes, reads.trusted_devices), [{"id": "d1", "device_label": "iPhone"}])
        self.assertEqual({auth for _, _, auth, _ in self.adapter.calls}, {"Bearer access-a"})


class TestVerificationPage(unittest.TestCase):
    def test_returns_the_page_as_sent(self):
        page = {"context": {"sheriff_challenge": {"id": "ch1", "type": "prompt"}}, "type": "prompt"}
        adapter = FakeRobinhood({("GET", "/pathfinder/inquiries/m1/user_view/"): lambda r: (200, page)})
        pending = PendingLogin(device_token="d", machine_id="m1")
        self.assertEqual(clients.verification_page(pending, session=fake_session(adapter)), page)


if __name__ == "__main__":
    unittest.main()
