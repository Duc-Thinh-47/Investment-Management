"""Excel workbook output functions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
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


def _excel_sheet_name(prefix: str, metric: str, used_names: set[str]) -> str:
	"""Create a unique Excel-safe worksheet name."""
	base_name = re.sub(r"[\\/*?:\[\]]", "_", f"{prefix} - {metric}")[:31]
	if not base_name:
		base_name = "Results"
	name = base_name
	suffix = 1
	while name in used_names:
		suffix_text = f"_{suffix}"
		name = f"{base_name[:31 - len(suffix_text)]}{suffix_text}"
		suffix += 1
	used_names.add(name)
	return name


def _daily_metric_frame(
	daily_returns: pd.DataFrame,
	metric: str,
) -> pd.DataFrame:
	"""Pivot one daily result metric to dates by ticker."""
	required_columns = {"date", "symbol", metric}
	missing_columns = required_columns.difference(daily_returns.columns)
	if missing_columns:
		raise ValueError(
			f"Daily returns are missing columns: {sorted(missing_columns)}"
		)
	if daily_returns.duplicated(["date", "symbol"]).any():
		raise ValueError("Daily returns contain duplicate date/symbol observations.")

	return (
		daily_returns.pivot(index="date", columns="symbol", values=metric)
		.reset_index()
		.rename_axis(columns=None)
	)


def _annualized_metric_frame(
	annualized_returns: pd.DataFrame,
	metric: str,
) -> pd.DataFrame:
	"""Orient one annualized result metric horizontally by ticker."""
	required_columns = {"symbol", metric}
	missing_columns = required_columns.difference(annualized_returns.columns)
	if missing_columns:
		raise ValueError(
			f"Annualized returns are missing columns: {sorted(missing_columns)}"
		)
	if annualized_returns["symbol"].duplicated().any():
		raise ValueError("Annualized returns contain duplicate symbols.")

	return pd.DataFrame(
		[[metric, *annualized_returns[metric].tolist()]],
		columns=["metric", *annualized_returns["symbol"].tolist()],
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
		used_names: set[str] = set()
		daily_metrics = [
			column for column in daily_returns.columns if column not in {"date", "symbol"}
		]
		annualized_metrics = [
			column for column in annualized_returns.columns if column != "symbol"
		]
		if not daily_metrics and not annualized_metrics:
			raise ValueError("No calculated result columns are available to write.")

		for metric in daily_metrics:
			_daily_metric_frame(daily_returns, metric).to_excel(
				writer,
				sheet_name=_excel_sheet_name("Daily", metric, used_names),
				index=False,
			)
		for metric in annualized_metrics:
			_annualized_metric_frame(annualized_returns, metric).to_excel(
				writer,
				sheet_name=_excel_sheet_name("Annualized", metric, used_names),
				index=False,
			)
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
