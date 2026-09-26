"""Configure and orchestrate the quantitative investment data pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_loader import (
	DownloadConfig,
	RiskFreeConfig,
	load_prices,
	load_risk_free_rate,
	normalize_symbol,
	yfinance_version,
)
from return_calculator import CalculationConfig, calculate_returns
from workbook_writer import (
	default_metadata,
	read_price_workbook,
	read_risk_free_workbook,
	read_risk_free_workbook_metadata,
	write_price_workbook,
	write_returns_workbook,
	write_risk_free_workbook,
)


# Edit this section before running the pipeline.
RUN_DATA_LOADING = True
RUN_CALCULATIONS = True

SYMBOLS = ("^VNI", "VNM", "GAS", "BMP", "HPG", "FPT", "BVH", "VCB", "PVD", "VJC", "SSI", "DHG")
START_DATE = "2020-12-28"
END_DATE = "2025-12-31"
RISK_FREE_START_DATE = "2020-12-01"
YAHOO_END_DATE = "2026-01-01"
YAHOO_INTERVAL = "1d"
YAHOO_AUTO_ADJUST = False
YAHOO_ACTIONS = False
APPEND_VIETNAM_SUFFIX = True
PRICE_COLUMN_CANDIDATES = ("adj close", "adjusted close", "adjusted_close", "adj_close")

TRADING_DAYS_PER_YEAR = 250
ANNUALIZATION_METHOD = "log"
RISK_FREE_RATE = 0.0
RISK_FREE_FREQUENCY = "annual"
RISK_FREE_CURRENCY = "USD"
INCLUDE_RISK_FREE_RATE = True

PRICE_OUTPUT_FILE = Path("adjusted_close_prices.xlsx")
RISK_FREE_OUTPUT_FILE = Path("us_3m_tbill_rates.xlsx")
RETURNS_OUTPUT_FILE = Path("calculated_returns.xlsx")
RISK_FREE_SYMBOL = "^IRX"
RISK_FREE_QUOTE_COLUMN_CANDIDATES = ("close", "adj close", "adjusted close")
RISK_FREE_QUOTE_IS_PERCENTAGE = True


DOWNLOAD_CONFIG = DownloadConfig(
	start_date=START_DATE,
	end_date=END_DATE,
	yahoo_end_date=YAHOO_END_DATE,
	interval=YAHOO_INTERVAL,
	auto_adjust=YAHOO_AUTO_ADJUST,
	actions=YAHOO_ACTIONS,
	append_vietnam_suffix=APPEND_VIETNAM_SUFFIX,
	price_column_candidates=PRICE_COLUMN_CANDIDATES,
)

RISK_FREE_CONFIG = RiskFreeConfig(
	symbol=RISK_FREE_SYMBOL,
	start_date=RISK_FREE_START_DATE,
	end_date=END_DATE,
	yahoo_end_date=YAHOO_END_DATE,
	interval=YAHOO_INTERVAL,
	quote_column_candidates=RISK_FREE_QUOTE_COLUMN_CANDIDATES,
	quote_is_percentage=RISK_FREE_QUOTE_IS_PERCENTAGE,
)

CALCULATION_CONFIG = CalculationConfig(
	trading_days_per_year=TRADING_DAYS_PER_YEAR,
	annualization_method=ANNUALIZATION_METHOD,
	risk_free_rate=RISK_FREE_RATE,
	risk_free_frequency=RISK_FREE_FREQUENCY,
	risk_free_currency=RISK_FREE_CURRENCY,
	include_risk_free_rate=INCLUDE_RISK_FREE_RATE,
)


def _has_risk_free_coverage(prices: Any, risk_free_rates: Any) -> bool:
	"""Return whether rates include an observation before the first equity date."""
	if prices.empty or risk_free_rates.empty:
		return False
	return risk_free_rates["date"].min() <= prices["date"].min()


def _validate_risk_free_coverage(prices: Any, risk_free_rates: Any) -> None:
	"""Raise a diagnostic when rates cannot cover the equity dates."""
	if _has_risk_free_coverage(prices, risk_free_rates):
		return
	price_min = prices["date"].min() if not prices.empty else "unavailable"
	rate_min = risk_free_rates["date"].min() if not risk_free_rates.empty else "unavailable"
	raise ValueError(
		"Risk-free cache has no observation on or before the first equity date. "
		f"First equity date: {price_min}; first risk-free date: {rate_min}. "
		"Regenerate the risk-free cache with the configured lookback."
	)


def main() -> None:
	"""Run the configured loading and calculation stages independently or together."""
	if not RUN_DATA_LOADING and not RUN_CALCULATIONS:
		raise ValueError("Enable RUN_DATA_LOADING, RUN_CALCULATIONS, or both.")

	symbols = tuple(
		normalize_symbol(symbol, append_vietnam_suffix=False)
		for symbol in SYMBOLS
		if symbol.strip()
	)
	if not symbols:
		raise ValueError("SYMBOLS must contain at least one ticker.")

	if not RUN_DATA_LOADING:
		if not PRICE_OUTPUT_FILE.exists():
			raise FileNotFoundError(f"Cached price workbook not found: {PRICE_OUTPUT_FILE}")
		if not RISK_FREE_OUTPUT_FILE.exists():
			raise FileNotFoundError(
				f"Cached risk-free workbook not found: {RISK_FREE_OUTPUT_FILE}"
			)
		prices = read_price_workbook(PRICE_OUTPUT_FILE)
		risk_free_rates = read_risk_free_workbook(RISK_FREE_OUTPUT_FILE)
	else:
		prices = load_prices(symbols, DOWNLOAD_CONFIG)
		cache_metadata = default_metadata(
			{
				"source": "Yahoo Finance Ticker.history (adjusted close)",
				"yfinance_version": yfinance_version(),
				"start_date": START_DATE,
				"end_date": END_DATE,
				"symbols": ", ".join(prices["symbol"].drop_duplicates().sort_values()),
				"yahoo_symbols": ", ".join(
					normalize_symbol(symbol, APPEND_VIETNAM_SUFFIX) for symbol in symbols
				),
				"interval": YAHOO_INTERVAL,
				"auto_adjust": YAHOO_AUTO_ADJUST,
				"actions": YAHOO_ACTIONS,
			}
		)
		write_price_workbook(prices, PRICE_OUTPUT_FILE, cache_metadata)

		expected_risk_free_metadata = {
			"start_date": RISK_FREE_START_DATE,
			"end_date": END_DATE,
			"interval": YAHOO_INTERVAL,
			"risk_free_symbol": RISK_FREE_SYMBOL,
			"risk_free_quote_is_percentage": RISK_FREE_QUOTE_IS_PERCENTAGE,
		}
		cache_hit = False
		if RISK_FREE_OUTPUT_FILE.exists():
			try:
				cached_metadata = read_risk_free_workbook_metadata(RISK_FREE_OUTPUT_FILE)
				cache_hit = all(
					cached_metadata.get(key) == str(value)
					for key, value in expected_risk_free_metadata.items()
				)
				if cache_hit:
					risk_free_rates = read_risk_free_workbook(RISK_FREE_OUTPUT_FILE)
					cache_hit = _has_risk_free_coverage(prices, risk_free_rates)
			except (OSError, ValueError, KeyError):
				cache_hit = False

		if not cache_hit:
			risk_free_rates = load_risk_free_rate(RISK_FREE_CONFIG)
			write_risk_free_workbook(
				risk_free_rates,
				RISK_FREE_OUTPUT_FILE,
				{
					**cache_metadata,
					"start_date": RISK_FREE_START_DATE,
					"risk_free_symbol": RISK_FREE_SYMBOL,
					"risk_free_quote_is_percentage": RISK_FREE_QUOTE_IS_PERCENTAGE,
				},
			)

	_validate_risk_free_coverage(prices, risk_free_rates)

	if not RUN_CALCULATIONS:
		print("Loaded and cached price and risk-free data.")
		return

	daily_returns, annualized_returns = calculate_returns(
		prices,
		CALCULATION_CONFIG,
		risk_free_rates,
	)

	metadata = default_metadata(
		{
			"source": "Yahoo Finance Ticker.history (adjusted close)",
			"yfinance_version": yfinance_version(),
			"start_date": START_DATE,
			"end_date": END_DATE,
			"symbols": ", ".join(
				prices["symbol"].drop_duplicates().sort_values()
			),
			"yahoo_symbols": ", ".join(
				normalize_symbol(symbol, APPEND_VIETNAM_SUFFIX) for symbol in symbols
			),
			"interval": YAHOO_INTERVAL,
			"auto_adjust": YAHOO_AUTO_ADJUST,
			"actions": YAHOO_ACTIONS,
			"trading_days_per_year": TRADING_DAYS_PER_YEAR,
			"annualization_method": ANNUALIZATION_METHOD,
			"risk_free_rate": RISK_FREE_RATE,
			"risk_free_frequency": RISK_FREE_FREQUENCY,
			"risk_free_currency": RISK_FREE_CURRENCY,
			"include_risk_free_rate": INCLUDE_RISK_FREE_RATE,
			"risk_free_symbol": RISK_FREE_SYMBOL,
			"risk_free_start_date": RISK_FREE_START_DATE,
			"risk_free_quote_is_percentage": RISK_FREE_QUOTE_IS_PERCENTAGE,
			"risk_free_conversion_method": "effective",
			"FX_Risk_Warning": "US T-Bill 3M is used as Rf per project constraints. VND/USD FX Premium is NOT adjusted in this raw data. Manual adjustment required in Excel.",
			"execution_data_loading": RUN_DATA_LOADING,
			"execution_calculations": RUN_CALCULATIONS,
		}
	)

	write_returns_workbook(
		daily_returns,
		annualized_returns,
		RETURNS_OUTPUT_FILE,
		metadata,
	)
	print(
		f"Exported {len(daily_returns):,} return rows for "
		f"{daily_returns['symbol'].nunique():,} ticker(s)."
	)


if __name__ == "__main__":
	main()
