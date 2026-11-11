"""Offline tests for the endpoints added/removed after the 2026-10 web-app audit.

No network or credentials: ``request_get`` (and, where needed, ``id_for_stock`` and
``load_account_profile``) are patched, so these only check that each function targets
the right URL with the right dataType/payload and threads ``info`` through
``filter_data`` correctly. The endpoints themselves were verified live against a real
signed-in session when they were added.
"""

import unittest
from unittest.mock import patch

import calcap_robin_stocks.robinhood as rh
from calcap_robin_stocks.robinhood import account, orders, stocks, urls
from calcap_robin_stocks.robinhood.helper import set_login_state


class TestEndpointUrls(unittest.TestCase):
    """The URL builders are pure functions; assert their exact output."""

    def test_unified_accounts_url(self):
        self.assertEqual(urls.unified_accounts_url(),
                         'https://bonfire.robinhood.com/accounts/unified/')

    def test_portfolio_performance_url(self):
        self.assertEqual(urls.portfolio_performance_url('5RY12345'),
                         'https://bonfire.robinhood.com/portfolio/performance/5RY12345')

    def test_interest_rate_url(self):
        self.assertEqual(urls.interest_rate_url(),
                         'https://api.robinhood.com/accounts/sweeps/interest/')

    def test_acats_url(self):
        self.assertEqual(urls.acats_url(), 'https://api.robinhood.com/acats/')

    def test_marketdata_fundamentals_url(self):
        self.assertEqual(urls.marketdata_fundamentals_url(),
                         'https://api.robinhood.com/marketdata/fundamentals/')

    def test_dead_phoenix_url_removed(self):
        # phoenix.robinhood.com no longer completes a TLS handshake; the builder is gone.
        self.assertFalse(hasattr(urls, 'phoenix_url'))

    def test_dead_urls_removed(self):
        # Robinhood answers 404 for these with a signed-in session (2026-11-11).
        for name in ('portfolis_historicals_url', 'popularity_url', 'wiretransfers_url',
                     'get_100_most_popular_url', 'movers_top_url', 'market_category_url'):
            self.assertFalse(hasattr(urls, name), name)
        self.assertEqual(urls.notifications_url(), 'https://api.robinhood.com/notifications/devices/')


class TestExports(unittest.TestCase):
    """The package's public surface reflects the add/remove."""

    def test_new_functions_exported(self):
        for name in ('load_unified_accounts', 'get_interest_rate',
                     'get_acats_transfers', 'get_portfolio_performance',
                     'get_marketdata_fundamentals'):
            self.assertTrue(hasattr(rh, name), name)

    def test_removed_function_not_exported(self):
        for name in ('load_phoenix_account', 'get_historical_portfolio', 'get_latest_notification',
                     'get_wire_transfers', 'get_top_100', 'get_top_movers',
                     'get_all_stocks_from_market_tag'):
            self.assertFalse(hasattr(rh, name), name)


class TestAccountFunctions(unittest.TestCase):
    def setUp(self):
        set_login_state(True)

    def tearDown(self):
        set_login_state(False)

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_load_unified_accounts(self, mock_get):
        rows = [{'account_number': 'A', 'account_buying_power': {'amount': '1.00'}},
                {'account_number': 'B', 'account_buying_power': {'amount': '2.00'}}]
        mock_get.return_value = rows
        self.assertEqual(account.load_unified_accounts(), rows)
        mock_get.assert_called_once_with(
            'https://bonfire.robinhood.com/accounts/unified/', 'results')

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_load_unified_accounts_info_filter(self, mock_get):
        mock_get.return_value = [{'account_number': 'A'}, {'account_number': 'B'}]
        # list + single field -> list of that field's values
        self.assertEqual(account.load_unified_accounts(info='account_number'), ['A', 'B'])

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_get_interest_rate(self, mock_get):
        mock_get.return_value = {'interest_rate': '0.0400', 'gold_interest_rate': '0.0450'}
        self.assertEqual(account.get_interest_rate()['interest_rate'], '0.0400')
        mock_get.assert_called_once_with(
            'https://api.robinhood.com/accounts/sweeps/interest/', 'regular')
        # dict + single field -> that field's value
        mock_get.return_value = {'interest_rate': '0.0400'}
        self.assertEqual(account.get_interest_rate(info='interest_rate'), '0.0400')

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_get_acats_transfers(self, mock_get):
        mock_get.return_value = [{'id': 'x', 'state': 'complete'}]
        self.assertEqual(account.get_acats_transfers(), [{'id': 'x', 'state': 'complete'}])
        mock_get.assert_called_once_with('https://api.robinhood.com/acats/', 'pagination')

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_get_portfolio_performance_explicit_account(self, mock_get):
        mock_get.return_value = {'id': 'perf', 'lines': []}
        account.get_portfolio_performance(account_number='5RY12345')
        mock_get.assert_called_once_with(
            'https://bonfire.robinhood.com/portfolio/performance/5RY12345', 'regular')

    @patch('calcap_robin_stocks.robinhood.account.load_account_profile', return_value='DEF999')
    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_get_portfolio_performance_default_account(self, mock_get, mock_profile):
        mock_get.return_value = {'id': 'perf'}
        account.get_portfolio_performance()
        mock_profile.assert_called_once_with(info='account_number')
        mock_get.assert_called_once_with(
            'https://bonfire.robinhood.com/portfolio/performance/DEF999', 'regular')


class TestMarketdataFundamentals(unittest.TestCase):
    def setUp(self):
        set_login_state(True)

    def tearDown(self):
        set_login_state(False)

    @patch('calcap_robin_stocks.robinhood.stocks.request_get')
    @patch('calcap_robin_stocks.robinhood.stocks.id_for_stock', return_value='INST-ID-1')
    def test_resolves_symbol_and_tags_result(self, mock_id, mock_get):
        mock_get.return_value = [{'open': '10.0', 'high': '11.0'}]
        out = stocks.get_marketdata_fundamentals('AAPL')
        mock_id.assert_called_once_with('AAPL')
        mock_get.assert_called_once_with(
            'https://api.robinhood.com/marketdata/fundamentals/',
            'results', {'ids': 'INST-ID-1'})
        self.assertEqual(out[0]['symbol'], 'AAPL')

    @patch('calcap_robin_stocks.robinhood.stocks.request_get')
    @patch('calcap_robin_stocks.robinhood.stocks.id_for_stock', return_value=None)
    def test_unresolvable_symbol_short_circuits(self, mock_id, mock_get):
        # No valid instrument ids -> no request is made.
        self.assertEqual(stocks.get_marketdata_fundamentals('NOTREAL'), [None])
        mock_get.assert_not_called()


class TestTier12Urls(unittest.TestCase):
    """URL builders for the Tier 1 + Tier 2 batch."""

    ZERO_ARG = {
        'crypto_transfers_url': 'https://bonfire.robinhood.com/crypto/transfers/history/',
        'asset_transfers_url': 'https://api.robinhood.com/nimbus/v1/asset_transfers',
        'split_payments_url': 'https://api.robinhood.com/corp_actions/v2/split_payments/',
        'adr_fees_url': 'https://api.robinhood.com/corp_actions/adr_fees/',
        'retirement_history_url': 'https://bonfire.robinhood.com/retirement/history/',
        'rhy_accounts_url': 'https://bonfire.robinhood.com/rhy/accounts/',
        'combo_orders_url': 'https://api.robinhood.com/combo/orders/',
        'advanced_orders_url': 'https://api.robinhood.com/accounts/v1/orders/advanced_orders/',
    }

    def test_zero_arg_builders(self):
        for name, expected in self.ZERO_ARG.items():
            self.assertEqual(getattr(urls, name)(), expected, name)

    def test_drip_enrollment_url(self):
        self.assertEqual(urls.drip_enrollment_url('5RY12345'),
                         'https://api.robinhood.com/corp_actions/drip/enrollment/5RY12345/')


class TestTier12Exports(unittest.TestCase):
    def test_new_functions_exported(self):
        for name in ('get_crypto_transfers', 'get_asset_transfers', 'get_split_payments',
                     'get_adr_fees', 'get_drip_enrollment', 'get_retirement_history',
                     'get_rhy_accounts', 'get_combo_orders', 'get_advanced_orders'):
            self.assertTrue(hasattr(rh, name), name)


class TestTier12AccountFunctions(unittest.TestCase):
    def setUp(self):
        set_login_state(True)

    def tearDown(self):
        set_login_state(False)

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_crypto_transfers(self, mock_get):
        mock_get.return_value = [{'id': 't1'}]
        self.assertEqual(account.get_crypto_transfers(), [{'id': 't1'}])
        mock_get.assert_called_once_with(
            'https://bonfire.robinhood.com/crypto/transfers/history/', 'pagination')

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_asset_transfers(self, mock_get):
        mock_get.return_value = {'assetTransferRecord': [], 'nextCursor': None, 'previousCursor': None}
        out = account.get_asset_transfers()
        mock_get.assert_called_once_with(
            'https://api.robinhood.com/nimbus/v1/asset_transfers', 'regular')
        self.assertIn('assetTransferRecord', out)

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_split_payments(self, mock_get):
        mock_get.return_value = [{'id': 's1', 'state': 'paid'}, {'id': 's2', 'state': 'paid'}]
        self.assertEqual(account.get_split_payments(info='state'), ['paid', 'paid'])
        mock_get.assert_called_once_with(
            'https://api.robinhood.com/corp_actions/v2/split_payments/', 'pagination')

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_adr_fees(self, mock_get):
        mock_get.return_value = []
        self.assertEqual(account.get_adr_fees(), [])
        mock_get.assert_called_once_with(
            'https://api.robinhood.com/corp_actions/adr_fees/', 'pagination')

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_retirement_history_uses_results_not_pagination(self, mock_get):
        # bonfire's response has no "next" key; 'pagination' would KeyError, so we use 'results'.
        mock_get.return_value = []
        account.get_retirement_history()
        mock_get.assert_called_once_with(
            'https://bonfire.robinhood.com/retirement/history/', 'results')

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_rhy_accounts(self, mock_get):
        mock_get.return_value = []
        account.get_rhy_accounts()
        mock_get.assert_called_once_with('https://bonfire.robinhood.com/rhy/accounts/', 'results')

    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_drip_enrollment_explicit_account(self, mock_get):
        mock_get.return_value = {'drip_enrolled': True}
        self.assertTrue(account.get_drip_enrollment(account_number='5RY12345',
                                                    info='drip_enrolled'))
        mock_get.assert_called_once_with(
            'https://api.robinhood.com/corp_actions/drip/enrollment/5RY12345/', 'regular')

    @patch('calcap_robin_stocks.robinhood.account.load_account_profile', return_value='DEF999')
    @patch('calcap_robin_stocks.robinhood.account.request_get')
    def test_drip_enrollment_default_account(self, mock_get, mock_profile):
        mock_get.return_value = {'drip_enrolled': False}
        account.get_drip_enrollment()
        mock_profile.assert_called_once_with(info='account_number')
        mock_get.assert_called_once_with(
            'https://api.robinhood.com/corp_actions/drip/enrollment/DEF999/', 'regular')


class TestOrderReadFunctions(unittest.TestCase):
    def setUp(self):
        set_login_state(True)

    def tearDown(self):
        set_login_state(False)

    @patch('calcap_robin_stocks.robinhood.orders.request_get')
    def test_combo_orders(self, mock_get):
        mock_get.return_value = [{'id': 'c1'}]
        self.assertEqual(orders.get_combo_orders(), [{'id': 'c1'}])
        mock_get.assert_called_once_with('https://api.robinhood.com/combo/orders/', 'pagination')

    @patch('calcap_robin_stocks.robinhood.orders.request_get')
    def test_advanced_orders(self, mock_get):
        mock_get.return_value = [{'id': 'a1'}]
        self.assertEqual(orders.get_advanced_orders(), [{'id': 'a1'}])
        mock_get.assert_called_once_with(
            'https://api.robinhood.com/accounts/v1/orders/advanced_orders/', 'pagination')


if __name__ == '__main__':
    unittest.main()
