"""
Environment variable helpers
"""

import os


def strip_comment(value: str) -> str:
    """Strip an inline shell comment from an environment-variable value.

    ``systemd``'s ``EnvironmentFile=`` directive does **not** remove inline
    ``# …`` comments from unquoted values.  If the ``.env`` file was copied
    verbatim from ``.env.template`` it may contain lines such as::

        EXCHANGE_ID=bybit   # binance, kraken, coinbase, bybit, etc.

    The process then receives the literal string
    ``'bybit   # binance, kraken, coinbase, bybit, etc.'``, which breaks
    any code that uses the value as a Python identifier (e.g.
    ``getattr(ccxt, exchange_id)``), a ``float()``/``int()`` conversion, or
    a boolean comparison.

    This helper removes everything from the first ``#`` character onward
    and strips surrounding whitespace.  It is safe to call on any config
    field that does **not** legitimately contain ``#`` (numeric, boolean,
    exchange IDs, strategy names, log levels, …).  Do **not** use it for
    free-form secret strings such as API keys, passwords, or bearer tokens
    where ``#`` could theoretically be a valid character.

    Args:
        value: Raw string value from an environment variable (may be None).

    Returns:
        Value with any trailing shell comment removed and whitespace stripped.
    """
    if value is None or '#' not in value:
        return (value or '').strip()
    return value[:value.index('#')].strip()


def getenv(key: str, default: str = '') -> str:
    """Return ``os.getenv(key, default)`` with any inline shell comment stripped.

    Convenience wrapper around :func:`strip_comment` for use wherever an
    environment variable feeds into Python identifier lookup, numeric
    conversion, boolean comparison, or a similar context where trailing
    comments would cause a runtime error.

    Args:
        key: Environment variable name.
        default: Value to use when the variable is not set.

    Returns:
        Stripped value, never ``None``.
    """
    return strip_comment(os.getenv(key, default))
