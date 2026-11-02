Calcap Robin Stocks
==================

Calcap fork of Robin Stocks with transfer pagination and extended filtering.
Distribution: ``calcap-robin-stocks``. Import: ``calcap_robin_stocks``.
This package has not been published to PyPI. Install from this repository::

    uv add "calcap-robin-stocks @ git+https://github.com/calcapfund/robin_stocks.git"

This package is Calcap's only way to Robinhood. Every Robinhood URL, request and
login step lives here, so the Calcap sync service (``calcap_api``) never calls
Robinhood itself; it decides what the answers mean. A new kind of Robinhood
request belongs in this package, with an offline test.

Calcap's additions, under ``calcap_robin_stocks.robinhood``:

- ``clients``: one read-only session per client, so one process can read several
  clients' accounts (``client_session``, ``refresh_tokens``), and logging in as
  steps a web app can drive: ``start_login``, then ``check_login`` (app approval)
  or ``submit_code`` (texted or emailed code), then ``finish_login``.
  ``request_code`` swaps an app approval for a texted code, and
  ``verification_page`` shows where Robinhood's device check stands.
- ``reads``: strict reads of a client's account for anything built on it
  (billing, reports). Unlike the package's usual helpers, which print errors and
  return empty results, every failure raises (``Unauthorized`` or
  ``ReadFailed``), lists are followed to their last page, a busy Robinhood is
  retried, and the token only goes to Robinhood's hosts.

See ``CHANGELOG.md`` for what each version changed and ``UPSTREAM_SYNC.md`` for
how upstream changes are merged in.

Upstream documentation and attribution follow below.

.. image:: docs/source/_static/pics/title.PNG

Robin-Stocks API Library
========================
This library provides a pure Python interface that interacts with the Robinhood API, Gemini API,
and TD Ameritrade API. The code is simple to use, easy to understand, and easy to modify.
With this library, you can view information on stocks, options, and crypto-currencies in real-time, 
create your own robo-investor or trading algorithm, and improve your programming skills.

To join our Slack channel where you can discuss trading and coding, click the link https://join.slack.com/t/robin-stocks/shared_invite/zt-7up2htza-wNSil5YDa3zrAglFFSxRIA

Supported APIs
==============
The supported APIs are Robinhood, Gemini, and TD Ameritrade. For more information about how to use the different APIs, visit the README
documents for `Robinhood Documentation`_, `Gemini Documentation`_, and `TDA Documentation`_.

Below are examples of how to call each of those modules.

>>> import calcap_robin_stocks.robinhood as rh
>>> import calcap_robin_stocks.gemini as gem
>>> import calcap_robin_stocks.tda as tda
>>> # Here are some example calls
>>> gem.get_pubticker("btcusd") # gets ticker information for Bitcoin from Gemini
>>> rh.get_all_open_crypto_orders() # gets all cypto orders from Robinhood
>>> tda.get_price_history("tsla") # get price history from TD Ameritrade 

Contributing
============
If you would like to contribute to this project, follow our contributing guidelines `Here <https://github.com/jmfernandes/robin_stocks/blob/master/contributing.md>`_.

Automatic Testing
^^^^^^^^^^^^^^^^^

If you are contributing to this project and would like to use automatic testing for your changes, you will need to install pytest and pytest-dotenv. To do this type into terminal or command prompt:

>>> pip install pytest
>>> pip install pytest-dotenv

You will also need to fill out all the fields in .test.env. I recommend that you rename the file as .env once you are done adding in all your personal information. After that, you can simply run:

>>> pytest

to run all the tests. If you would like to run specific tests or run all the tests in a specific class then type:

>>> pytest tests/test_robinhood.py -k test_name_apple # runs only the 1 test
>>> pytest tests/test_gemini.py -k TestTrades # runs every test in TestTrades but nothing else

Finally, if you would like the API calls to print out to terminal, then add the -s flag to any of the above pytest calls.


Installing
========================
This fork is installed from GitHub and is not currently published to PyPI::

    uv add "calcap-robin-stocks @ git+https://github.com/calcapfund/robin_stocks.git"

For an editable checkout::

    git clone https://github.com/calcapfund/robin_stocks.git
    cd robin_stocks
    uv venv && uv pip install -e .

Use the renamed Python namespace::

    import calcap_robin_stocks.robinhood as rh

The original ``robin-stocks`` distribution uses ``robin_stocks`` imports.
The two namespaces can coexist in the same Python environment.

List of Functions and Example Usage
===================================

For a complete list of all Robinhood API functions and what the different parameters mean, 
go to `readthedocs.io Robinhood Page <https://robin-stocks.readthedocs.io/en/latest/robinhood.html>`_. If you would like to
see some example code and instructions on how to set up two-factor authorization for Robinhood,
go to the `Robinhood Documentation`_.

For a complete list of all TD Ameritrade API functions and what the different parameters mean, 
go to `readthedocs.io TDA Page <https://robin-stocks.readthedocs.io/en/latest/tda.html>`_. For detailed instructions on 
how to generate API keys for TD Ameritrade and how to use the API, go to the `TDA Documentation`_.

For a complete list of all Gemini API functions and what the different parameters mean, 
go to `readthedocs.io Gemini Page <https://robin-stocks.readthedocs.io/en/latest/gemini.html>`_. For detailed instructions on 
how to generate API keys for Gemini and how to use both the private and public API, go to the `Gemini Documentation`_.

.. _Robinhood Documentation: Robinhood.rst
.. _Gemini Documentation: gemini.rst
.. _TDA Documentation: tda.rst
