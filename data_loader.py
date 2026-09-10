"""Yahoo Finance data ingestion and cleaning utilities."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class DownloadConfig:
	"""Configuration for downloading and cleaning historical prices.

	Args:
		start_date: Inclusive first date retained in the output.
		end_date: Inclusive last date retained in the output.
		yahoo_end_date: Exclusive Yahoo Finance end date.
		interval: Yahoo Finance history interval.
		auto_adjust: Whether Yahoo adjusts OHLC prices.
		actions: Whether Yahoo includes corporate actions.
		append_vietnam_suffix: Whether to append ``.VN`` to symbols.
		price_column_candidates: Accepted adjusted-close column names.
	"""

	start_date: str
	end_date: str
	yahoo_end_date: str
	interval: str = "1d"
	auto_adjust: bool = False
	actions: bool = False
	append_vietnam_suffix: bool = True
	price_column_candidates: tuple[str, ...] = (
		"adj close",
		"adjusted close",
		"adjusted_close",
		"adj_close",
	)


@dataclass(frozen=True)
class RiskFreeConfig:
	"""Configuration for downloading an annualized risk-free-rate series.

	Args:
		symbol: Yahoo Finance symbol for the risk-free instrument.
		start_date: Inclusive first date retained in the output.
		end_date: Inclusive last date retained in the output.
		yahoo_end_date: Exclusive Yahoo Finance end date.
		interval: Yahoo Finance history interval.
		quote_column_candidates: Accepted annualized quote column names.
		quote_is_percentage: Whether Yahoo quotes values such as ``4.25`` for
			4.25 percent rather than decimal ``0.0425``.
	"""

	symbol: str = "^IRX"
	start_date: str = "2021-01-01"
	end_date: str = "2025-12-31"
	yahoo_end_date: str = "2026-01-01"
	interval: str = "1d"
	quote_column_candidates: tuple[str, ...] = (
		"close",
		"adj close",
		"adjusted close",
		"adjusted_close",
	)
	quote_is_percentage: bool = True


def yfinance_version() -> str:
	"""Return the installed yfinance version, or ``unknown`` if unavailable."""
	try:
		return version("yfinance")
	except PackageNotFoundError:
		return "unknown"


def normalize_symbol(symbol: str, append_vietnam_suffix: bool = True) -> str:
	"""Normalize a ticker and optionally append Yahoo's Vietnam suffix.

	Args:
		symbol: User-provided ticker symbol.
		append_vietnam_suffix: Whether to append ``.VN`` when absent.

	Returns:
		An uppercase, whitespace-trimmed Yahoo Finance symbol.
	"""
	normalized = symbol.strip().upper()
	if not normalized:
		raise ValueError("Ticker symbols must not be empty.")
	if append_vietnam_suffix and not normalized.endswith(".VN"):
		return f"{normalized}.VN"
	return normalized


def download_symbol(symbol: str, config: DownloadConfig) -> pd.DataFrame:
	"""Download one symbol's historical data from Yahoo Finance.

	Args:
		symbol: User-facing ticker symbol.
		config: Download and cleaning configuration.

	Returns:
		The raw Yahoo Finance history DataFrame.

	Raises:
		RuntimeError: If yfinance is not installed.
		ValueError: If Yahoo returns no usable data.
	"""
	try:
		import yfinance as yf
	except ImportError as error:
		raise RuntimeError(
			"yfinance is not installed. Run: python -m pip install -r requirements.txt"
		) from error

	yahoo_symbol = normalize_symbol(symbol, config.append_vietnam_suffix)
	data = yf.Ticker(yahoo_symbol).history(
		start=config.start_date,
		end=config.yahoo_end_date,
		interval=config.interval,
		auto_adjust=config.auto_adjust,
		actions=config.actions,
	)
	if not isinstance(data, pd.DataFrame) or data.empty:
		raise ValueError(f"No data returned for {symbol} ({yahoo_symbol}).")
	return data


def _find_column(columns: pd.Index, candidates: tuple[str, ...]) -> str | None:
	normalized = {str(column).strip().lower(): str(column) for column in columns}
	for candidate in candidates:
		if str(candidate).strip().lower() in normalized:
			return normalized[str(candidate).strip().lower()]
	return None


def _normalize_calendar_dates(values: pd.Series) -> pd.Series:
	"""Convert timestamps to Vietnam-local calendar dates without mixed timezones."""
	return (
		pd.to_datetime(values, errors="coerce", utc=True)
		.dt.tz_convert("Asia/Ho_Chi_Minh")
		.dt.normalize()
		.dt.tz_localize(None)
	)


def normalize_prices(symbol: str, data: pd.DataFrame, config: DownloadConfig) -> pd.DataFrame:
	"""Clean one raw Yahoo response into a standard long-form price table.

	Args:
		symbol: User-facing ticker symbol.
		data: Raw DataFrame returned by Yahoo Finance.
		config: Date range and price-column configuration.

	Returns:
		A DataFrame with ``symbol``, ``date``, and ``adjusted_close`` columns.

	Raises:
		ValueError: If the response lacks required data or columns.
	"""
	adjusted_column = _find_column(data.columns, config.price_column_candidates)
	if adjusted_column is None:
		raise ValueError(
			f"{symbol}: Yahoo response has no adjusted-close column. "
			"Raw 'Close' was not used as a substitute."
		)

	prices = data[[adjusted_column]].rename(columns={adjusted_column: "adjusted_close"})
	prices = prices.reset_index()
	date_column = _find_column(prices.columns, ("date", "datetime"))
	if date_column is None:
		raise ValueError(f"{symbol}: Yahoo response has no date index.")

	prices = prices.rename(columns={date_column: "date"})
	prices["date"] = _normalize_calendar_dates(prices["date"])
	prices["adjusted_close"] = pd.to_numeric(prices["adjusted_close"], errors="coerce")
	prices = prices.dropna(subset=["date", "adjusted_close"])
	prices = prices[
		(prices["date"] >= pd.Timestamp(config.start_date))
		& (prices["date"] <= pd.Timestamp(config.end_date))
	]
	prices = prices.sort_values("date").drop_duplicates(subset=["date"], keep="last")
	if prices.empty:
		raise ValueError(f"{symbol}: no valid adjusted-close rows in the requested period.")

	prices.insert(0, "symbol", symbol.strip().upper())
	return prices.reset_index(drop=True)


def load_symbol(symbol: str, config: DownloadConfig) -> pd.DataFrame:
	"""Download and clean one symbol using the supplied configuration."""
	return normalize_prices(symbol, download_symbol(symbol, config), config)


def load_prices(symbols: tuple[str, ...] | list[str], config: DownloadConfig) -> pd.DataFrame:
	"""Download and combine clean prices for multiple symbols.

	Args:
		symbols: Ticker symbols to download.
		config: Shared download and cleaning configuration.

	Returns:
		A sorted long-form DataFrame containing all requested symbols.

	The function prints a warning for each failed symbol and raises only when
	all requested symbols fail.
		ValueError: If no symbols are supplied.
	"""
	normalized_symbols = tuple(symbol.strip().upper() for symbol in symbols if symbol.strip())
	if not normalized_symbols:
		raise ValueError("At least one ticker symbol is required.")

	loaded: list[pd.DataFrame] = []
	failures: list[str] = []
	for symbol in normalized_symbols:
		try:
			loaded.append(load_symbol(symbol, config))
		except Exception as error:
			failure = f"{symbol}: {error}"
			failures.append(failure)
			print(f"Warning: skipping ticker {failure}")

	if not loaded:
		details = "\n".join(f"- {failure}" for failure in failures)
		raise RuntimeError(f"No ticker data loaded successfully:\n{details}")
	return pd.concat(loaded, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)


def download_risk_free_rate(config: RiskFreeConfig) -> pd.DataFrame:
	"""Download the configured annualized risk-free-rate series from Yahoo.

	Args:
		config: Risk-free symbol, date, and quote configuration.

	Returns:
		The raw Yahoo Finance history DataFrame.

	Raises:
		RuntimeError: If yfinance is not installed.
		ValueError: If Yahoo returns no usable data.
	"""
	try:
		import yfinance as yf
	except ImportError as error:
		raise RuntimeError(
			"yfinance is not installed. Run: python -m pip install -r requirements.txt"
		) from error

	data = yf.Ticker(config.symbol).history(
		start=config.start_date,
		end=config.yahoo_end_date,
		interval=config.interval,
		auto_adjust=False,
		actions=False,
	)
	if not isinstance(data, pd.DataFrame) or data.empty:
		raise ValueError(f"No data returned for risk-free symbol {config.symbol}.")
	return data


def normalize_risk_free_rate(
	data: pd.DataFrame,
	config: RiskFreeConfig,
) -> pd.DataFrame:
	"""Clean Yahoo's annualized risk-free quote into a standard rate table.

	Args:
		data: Raw Yahoo Finance history for the configured risk-free symbol.
		config: Quote-column, date-range, and percentage interpretation settings.

	Returns:
		A DataFrame with ``date``, ``annualized_risk_free_rate``, and
		``source_symbol`` columns. Rates are decimal values.

	Raises:
		ValueError: If required columns are missing or no valid rows remain.
	"""
	quote_column = _find_column(data.columns, config.quote_column_candidates)
	if quote_column is None:
		raise ValueError(
			f"{config.symbol}: Yahoo response has no configured risk-free quote column."
		)

	rate = data[[quote_column]].rename(columns={quote_column: "annualized_risk_free_rate"})
	rate = rate.reset_index()
	date_column = _find_column(rate.columns, ("date", "datetime"))
	if date_column is None:
		raise ValueError(f"{config.symbol}: Yahoo response has no date index.")

	rate = rate.rename(columns={date_column: "date"})
	rate["date"] = _normalize_calendar_dates(rate["date"])
	rate["annualized_risk_free_rate"] = pd.to_numeric(
		rate["annualized_risk_free_rate"], errors="coerce"
	)
	if config.quote_is_percentage:
		rate["annualized_risk_free_rate"] = rate["annualized_risk_free_rate"] / 100

	rate = rate.dropna(subset=["date", "annualized_risk_free_rate"])
	rate = rate[
		(rate["date"] >= pd.Timestamp(config.start_date))
		& (rate["date"] <= pd.Timestamp(config.end_date))
	]
	rate = rate.sort_values("date").drop_duplicates(subset=["date"], keep="last")
	if rate.empty:
		raise ValueError(f"{config.symbol}: no valid risk-free rows in the requested period.")
	if (rate["annualized_risk_free_rate"] <= -1).any():
		raise ValueError("Annualized risk-free rates must be greater than -1.")

	rate.insert(0, "source_symbol", config.symbol)
	return rate.reset_index(drop=True)


def load_risk_free_rate(config: RiskFreeConfig) -> pd.DataFrame:
	"""Download and clean the configured risk-free-rate series."""
	return normalize_risk_free_rate(download_risk_free_rate(config), config)


# Kept available for callers that need to inspect forwarded Yahoo options.
def yahoo_history_options(config: DownloadConfig) -> dict[str, Any]:
	"""Return the configured options used for a Yahoo history request."""
	return {
		"start": config.start_date,
		"end": config.yahoo_end_date,
		"interval": config.interval,
		"auto_adjust": config.auto_adjust,
		"actions": config.actions,
	}
