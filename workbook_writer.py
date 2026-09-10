"""Excel workbook output functions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping

import pandas as pd


def _normalize_calendar_dates(values: pd.Series) -> pd.Series:
	"""Normalize cached timestamps to Vietnam-local calendar dates."""
	return (
		pd.to_datetime(values, errors="raise", utc=True)
		.dt.tz_convert("Asia/Ho_Chi_Minh")
		.dt.normalize()
		.dt.tz_localize(None)
	)


def _metadata_frame(metadata: Mapping[str, object]) -> pd.DataFrame:
	"""Convert metadata values into the standard workbook table."""
	return pd.DataFrame(
		{
			"property": list(metadata),
			"value": [str(value) for value in metadata.values()],
		}
	)


def write_price_workbook(
	prices: pd.DataFrame,
	output_path: Path,
	metadata: Mapping[str, object],
) -> None:
	"""Write clean adjusted prices and row counts to an Excel workbook.

	Args:
		prices: Clean long-form price data.
		output_path: Destination workbook path.
		metadata: Configuration and source metadata supplied by the orchestrator.
	"""
	counts = prices.groupby("symbol", as_index=False).size().rename(columns={"size": "rows"})
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
		prices.to_excel(writer, sheet_name="Prices", index=False)
		_metadata_frame(metadata).to_excel(writer, sheet_name="Metadata", index=False)
		counts.to_excel(writer, sheet_name="Row Counts", index=False)


def write_returns_workbook(
	daily_returns: pd.DataFrame,
	annualized_returns: pd.DataFrame,
	output_path: Path,
	metadata: Mapping[str, object],
) -> None:
	"""Write calculated daily and annualized returns to a separate workbook.

	Args:
		daily_returns: Return table produced by the calculator module.
		annualized_returns: Summary produced by the calculator module.
		output_path: Destination workbook path.
		metadata: Calculation and source metadata supplied by the orchestrator.
	"""
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
		daily_returns.to_excel(writer, sheet_name="Daily Log Returns", index=False)
		annualized_returns.to_excel(writer, sheet_name="Annualized Returns", index=False)
		_metadata_frame(metadata).to_excel(writer, sheet_name="Metadata", index=False)


def write_risk_free_workbook(
	risk_free_rates: pd.DataFrame,
	output_path: Path,
	metadata: Mapping[str, object],
) -> None:
	"""Write cached annualized risk-free-rate observations to Excel."""
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
		risk_free_rates.to_excel(writer, sheet_name="Risk-Free Rates", index=False)
		_metadata_frame(metadata).to_excel(writer, sheet_name="Metadata", index=False)


def read_price_workbook(input_path: Path) -> pd.DataFrame:
	"""Read and validate the cached ``Prices`` sheet."""
	prices = pd.read_excel(input_path, sheet_name="Prices")
	required_columns = {"symbol", "date", "adjusted_close"}
	missing_columns = required_columns.difference(prices.columns)
	if missing_columns:
		raise ValueError(f"Cached price workbook is missing columns: {sorted(missing_columns)}")
	prices["date"] = _normalize_calendar_dates(prices["date"])
	return prices


def read_risk_free_workbook(input_path: Path) -> pd.DataFrame:
	"""Read and validate cached annualized risk-free-rate observations."""
	risk_free_rates = pd.read_excel(input_path, sheet_name="Risk-Free Rates")
	required_columns = {"date", "annualized_risk_free_rate"}
	missing_columns = required_columns.difference(risk_free_rates.columns)
	if missing_columns:
		raise ValueError(
			f"Cached risk-free workbook is missing columns: {sorted(missing_columns)}"
		)
	risk_free_rates["date"] = _normalize_calendar_dates(risk_free_rates["date"])
	return risk_free_rates


def read_risk_free_workbook_metadata(input_path: Path) -> dict[str, str]:
	"""Read metadata from a cached risk-free-rate workbook."""
	metadata = pd.read_excel(input_path, sheet_name="Metadata")
	if not {"property", "value"}.issubset(metadata.columns):
		raise ValueError("Cached risk-free workbook has invalid metadata columns.")
	return dict(zip(metadata["property"].astype(str), metadata["value"].astype(str)))


def default_metadata(
	base_metadata: Mapping[str, object],
) -> dict[str, object]:
	"""Add the local retrieval timestamp to supplied workbook metadata."""
	metadata = dict(base_metadata)
	metadata["retrieved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
	return metadata
