"""Pure return and annualization calculations for portfolio analysis."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CalculationConfig:
	"""Configuration for return calculations.

	Args:
		trading_days_per_year: Number of trading sessions used for annualization.
		annualization_method: ``log`` for mean log-return annualization or
			``geometric`` for compounded observed daily returns.
		risk_free_rate: Risk-free rate expressed in the configured frequency.
		risk_free_frequency: Frequency of the risk-free rate: annual, quarterly,
			monthly, or daily.
		risk_free_currency: Currency of the supplied risk-free rate.
		include_risk_free_rate: Whether to include risk-free and excess-return
			columns in the annualized summary.
	"""

	trading_days_per_year: int = 252
	annualization_method: str = "log"
	risk_free_rate: float = 0.0
	risk_free_frequency: str = "annual"
	risk_free_currency: str = "USD"
	include_risk_free_rate: bool = True
	risk_free_conversion_method: str = "effective"


def _validate_config(config: CalculationConfig) -> None:
	if config.trading_days_per_year <= 0:
		raise ValueError("trading_days_per_year must be greater than zero.")
	if config.annualization_method not in {"log", "geometric"}:
		raise ValueError("annualization_method must be 'log' or 'geometric'.")
	if config.risk_free_frequency not in {"annual", "quarterly", "monthly", "daily"}:
		raise ValueError(
			"risk_free_frequency must be 'annual', 'quarterly', 'monthly', or 'daily'."
		)
	if not np.isfinite(config.risk_free_rate) or config.risk_free_rate <= -1:
		raise ValueError("risk_free_rate must be finite and greater than -1.")
	if not config.risk_free_currency.strip():
		raise ValueError("risk_free_currency must not be empty.")
	if config.risk_free_conversion_method != "effective":
		raise ValueError("risk_free_conversion_method must be 'effective'.")


def calculate_daily_log_returns(prices: pd.DataFrame) -> pd.DataFrame:
	"""Calculate aligned daily logarithmic returns on a common business calendar.

	Args:
		prices: Clean long-form prices with ``symbol``, ``date``, and
			``adjusted_close`` columns.

	Returns:
		A long-form table reindexed to common weekdays. Missing prices and returns
		remain ``NaN`` during suspensions, so returns never bridge a gap.

	Raises:
		ValueError: If required columns are absent or prices are non-positive.
	"""
	required_columns = {"symbol", "date", "adjusted_close"}
	missing_columns = required_columns.difference(prices.columns)
	if missing_columns:
		raise ValueError(f"Missing required price columns: {sorted(missing_columns)}")
	if prices.empty:
		raise ValueError("Cannot calculate returns from an empty price table.")

	result = prices.copy()
	result["date"] = (
		pd.to_datetime(result["date"], errors="raise", utc=True)
		.dt.tz_convert("Asia/Ho_Chi_Minh")
		.dt.normalize()
		.dt.tz_localize(None)
	)
	result["adjusted_close"] = pd.to_numeric(result["adjusted_close"], errors="raise")
	if (
		result["adjusted_close"].isna().any()
		or not np.isfinite(result["adjusted_close"]).all()
		or (result["adjusted_close"] <= 0).any()
	):
		raise ValueError("adjusted_close values must be finite and greater than zero.")

	result = result.sort_values(["date", "symbol"]).drop_duplicates(
		["symbol", "date"], keep="last"
	)
	wide_prices = result.pivot(index="date", columns="symbol", values="adjusted_close")
	calendar = pd.date_range(wide_prices.index.min(), wide_prices.index.max(), freq="B")
	wide_prices = wide_prices.reindex(calendar)
	previous_prices = wide_prices.shift(1)
	wide_returns = np.log(wide_prices / previous_prices).where(
		wide_prices.notna() & previous_prices.notna()
	)

	long_prices = wide_prices.rename_axis("date").stack(future_stack=True).rename(
		"adjusted_close"
	).reset_index()
	long_returns = wide_returns.rename_axis("date").stack(
		future_stack=True
	).rename("log_return").reset_index()
	return long_prices.merge(long_returns, on=["date", "symbol"], how="left").sort_values(
		["symbol", "date"]
	).reset_index(drop=True)


def annualize_risk_free_rate(config: CalculationConfig) -> float:
	"""Convert the configured periodic simple risk-free rate to an annual rate.

	Args:
		config: Calculation settings containing the rate and its frequency.

	Returns:
		An annualized simple risk-free rate.
	"""
	_validate_config(config)
	periods_per_year = {
		"annual": 1,
		"quarterly": 4,
		"monthly": 12,
		"daily": config.trading_days_per_year,
	}[config.risk_free_frequency]
	return float((1 + config.risk_free_rate) ** periods_per_year - 1)


def annual_to_daily_risk_free_rate(
	annualized_rate: pd.Series | float,
	trading_days_per_year: int,
) -> pd.Series | float:
	"""Convert annual simple rates to effective daily rates.

	Args:
		annualized_rate: Decimal annualized simple rate or rate Series.
		trading_days_per_year: Number of compounding periods per year.

	Returns:
		The effective daily rate using ``(1 + annual_rate) ** (1 / N) - 1``.
	"""
	if trading_days_per_year <= 0:
		raise ValueError("trading_days_per_year must be greater than zero.")
	if isinstance(annualized_rate, pd.Series):
		valid_rates = annualized_rate.dropna()
		if not np.isfinite(valid_rates).all() or (valid_rates <= -1).any():
			raise ValueError("Annualized risk-free rates must be valid and greater than -1.")
		return (1 + annualized_rate) ** (1 / trading_days_per_year) - 1
	if not np.isfinite(annualized_rate) or annualized_rate <= -1:
		raise ValueError("Annualized risk-free rate must be valid and greater than -1.")
	return float((1 + annualized_rate) ** (1 / trading_days_per_year) - 1)


def annual_to_daily_log_risk_free_rate(
	annualized_rate: pd.Series | float,
	trading_days_per_year: int,
) -> pd.Series | float:
	"""Convert annual simple rates to effective daily log rates."""
	daily_simple_rate = annual_to_daily_risk_free_rate(
		annualized_rate, trading_days_per_year
	)
	if isinstance(daily_simple_rate, pd.Series):
		return np.log1p(daily_simple_rate)
	return float(np.log1p(daily_simple_rate))


def align_risk_free_rates(
	log_returns: pd.DataFrame,
	risk_free_rates: pd.DataFrame,
	config: CalculationConfig,
) -> pd.DataFrame:
	"""Align annualized risk-free observations and derive daily rates.

	The latest available observation on or before each equity date is used.

	Args:
		log_returns: Daily equity returns with ``symbol`` and ``date`` columns.
		risk_free_rates: Clean rates with ``date`` and
			``annualized_risk_free_rate`` columns.
		config: Calculation settings.

	Returns:
		The return table with annualized, daily simple, daily log, and excess
		log-return columns. Rates older than seven calendar days are unmatched.
	"""
	required_columns = {"date", "annualized_risk_free_rate"}
	missing_columns = required_columns.difference(risk_free_rates.columns)
	if missing_columns:
		raise ValueError(f"Missing required risk-free columns: {sorted(missing_columns)}")
	if risk_free_rates.empty:
		raise ValueError("Cannot align an empty risk-free-rate table.")

	returns = log_returns.sort_values("date").copy()
	rates = risk_free_rates[["date", "annualized_risk_free_rate"]].copy()
	for frame in (returns, rates):
		frame["date"] = (
			pd.to_datetime(frame["date"], errors="raise", utc=True)
			.dt.tz_convert("Asia/Ho_Chi_Minh")
			.dt.normalize()
			.dt.tz_localize(None)
		)
	rates["annualized_risk_free_rate"] = pd.to_numeric(
		rates["annualized_risk_free_rate"], errors="raise"
	)
	rates = rates.sort_values("date").drop_duplicates("date", keep="last")
	if rates["annualized_risk_free_rate"].isna().any() or (
		rates["annualized_risk_free_rate"] <= -1
	).any():
		raise ValueError("Annualized risk-free rates must be valid and greater than -1.")

	aligned = pd.merge_asof(
		returns,
		rates,
		on="date",
		direction="backward",
		tolerance=pd.Timedelta(days=7),
	)
	aligned_rate = aligned["annualized_risk_free_rate"]
	aligned["daily_risk_free_rate"] = annual_to_daily_risk_free_rate(
		aligned_rate, config.trading_days_per_year
	)
	aligned["daily_log_risk_free_rate"] = annual_to_daily_log_risk_free_rate(
		aligned_rate, config.trading_days_per_year
	)
	aligned["daily_excess_log_return"] = (
		aligned["log_return"] - aligned["daily_log_risk_free_rate"]
	)
	return aligned


def calculate_annualized_returns(
	log_returns: pd.DataFrame,
	config: CalculationConfig,
) -> pd.DataFrame:
	"""Calculate annualized return summaries for each symbol.

	Args:
		log_returns: Output of :func:`calculate_daily_log_returns`.
		config: Annualization and risk-free-rate configuration.

	Returns:
		One row per symbol with annualized return metrics and configured
		risk-free-rate metadata.
	"""
	_validate_config(config)
	if not {"symbol", "log_return"}.issubset(log_returns.columns):
		raise ValueError("log_returns must contain 'symbol' and 'log_return' columns.")
	if log_returns.empty:
		raise ValueError("Cannot annualize an empty return table.")

	valid_returns = log_returns.dropna(subset=["log_return"])
	if valid_returns.empty:
		raise ValueError("At least one non-null log return is required per summary.")

	grouped = valid_returns.groupby("symbol", sort=True)["log_return"]
	mean_log_return = grouped.mean()
	if config.annualization_method == "log":
		annualized_log_return = mean_log_return * config.trading_days_per_year
		annualized_return = np.expm1(annualized_log_return)
	else:
		annualized_return = grouped.apply(
			lambda series: (np.exp(series).prod() ** (
				config.trading_days_per_year / len(series)
			) - 1)
		)
		annualized_log_return = np.log1p(annualized_return)

	summary = pd.DataFrame(
		{
			"symbol": annualized_return.index,
			"mean_daily_log_return": mean_log_return.to_numpy(),
			"annualized_log_return": annualized_log_return.to_numpy(),
			"annualized_return": annualized_return.to_numpy(),
		}
	)
	if config.include_risk_free_rate:
		if "daily_excess_log_return" in log_returns.columns:
			excess_grouped = valid_returns.groupby("symbol", sort=True)[
				"daily_excess_log_return"
			]
			annualized_excess_log_return = (
				excess_grouped.mean() * config.trading_days_per_year
			)
			summary["annualized_excess_log_return"] = (
				annualized_excess_log_return.reindex(summary["symbol"]).to_numpy()
			)
			summary["annualized_excess_return"] = np.expm1(
				summary["annualized_excess_log_return"]
			)
			if "daily_log_risk_free_rate" in log_returns.columns:
				daily_log_rate = valid_returns.groupby("symbol", sort=True)[
					"daily_log_risk_free_rate"
				].mean()
				summary["annualized_risk_free_log_rate"] = (
					daily_log_rate.reindex(summary["symbol"]).to_numpy()
					* config.trading_days_per_year
				)
				summary["annualized_risk_free_rate"] = np.expm1(
					summary["annualized_risk_free_log_rate"]
				)
		else:
			risk_free_rate = annualize_risk_free_rate(config)
			risk_free_log_rate = np.log1p(risk_free_rate)
			summary["annualized_risk_free_log_rate"] = risk_free_log_rate
			summary["annualized_risk_free_rate"] = risk_free_rate
			summary["annualized_excess_log_return"] = (
			summary["annualized_log_return"] - risk_free_log_rate
		)
			summary["annualized_excess_return"] = np.expm1(
				summary["annualized_excess_log_return"]
			)
	return summary


def calculate_returns(
	prices: pd.DataFrame,
	config: CalculationConfig,
	risk_free_rates: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
	"""Calculate daily log returns and annualized summaries.

	Args:
		prices: Clean equity price table.
		config: Return and risk-free-rate configuration.
		risk_free_rates: Optional clean annualized risk-free-rate observations.
	"""
	daily_returns = calculate_daily_log_returns(prices)
	if config.include_risk_free_rate and risk_free_rates is not None:
		daily_returns = align_risk_free_rates(daily_returns, risk_free_rates, config)
	return daily_returns, calculate_annualized_returns(daily_returns, config)
