## Project Architecture and Coding Rules

This is a quantitative investment management project for Vietnam equities, with a focus on VN30-style liquid large-cap stocks and the 2021-2025 analysis period. The project separates configuration, data ingestion, financial calculations, and output serialization.

## 1. Module Responsibilities

### `main.py`: Configuration and Orchestration

`main.py` is the central entry point and may contain:

- Editable symbols, dates, output paths, and pipeline options.
- `DownloadConfig` and `CalculationConfig` construction.
- `RUN_DATA_LOADING` and `RUN_CALCULATIONS` execution switches.
- Calls that chain the project modules.
- Metadata assembly from configured values.

`main.py` must not contain:

- `pandas` or `numpy` data transformations.
- `yfinance` calls.
- Financial formulas or return calculations.
- Excel writer construction or workbook serialization.
- Business logic that belongs in another module.

All download and calculation assumptions must be changeable from the configuration section in `main.py` without editing reusable modules.

When `RUN_DATA_LOADING` is false, `main.py` must read the cached price and risk-free workbooks and must not call Yahoo Finance. When `RUN_CALCULATIONS` is false, it must stop after caching downloaded inputs.

### `data_loader.py`: Data Ingestion

This module owns all Yahoo Finance ingestion and price cleaning. It must:

- Use `yfinance` to download historical prices.
- Accept explicit `DownloadConfig` values from `main.py`.
- Support configurable date range, interval, adjustment/action flags, symbol suffix behavior, and accepted price columns.
- Normalize symbols and dates consistently.
- Handle missing values, invalid numeric values, duplicate dates, empty responses, and missing adjusted-close columns explicitly.
- Return clean long-form pandas data with `symbol`, `date`, and `adjusted_close` columns.
- Download the configured US 3-month Treasury series, normally Yahoo symbol `^IRX`, through a separate `RiskFreeConfig`.
- Interpret the Yahoo `^IRX` quote as an annualized percentage by default and return a decimal `annualized_risk_free_rate`.

### `return_calculator.py`: Financial Mathematics

This module owns pure, network-free financial calculations. It must:

- Accept clean data from `data_loader.py`.
- Calculate daily log returns using:

  $$
  r_t = \ln\left(\frac{P_t}{P_{t-1}}\right)
  $$

- Calculate annualized returns using the configurable `trading_days_per_year` value, defaulting to 252.
- Support the configured annualization method.
- Validate required columns and reject non-positive prices.
- Convert the configured risk-free rate according to its frequency and preserve its currency metadata.
- Convert annualized T-Bill rates to effective daily rates with
  `daily_rate = (1 + annual_rate) ** (1 / trading_days_per_year) - 1`.
- Align the latest available T-Bill observation on or before each equity date.
- Include `annualized_risk_free_rate`, `daily_risk_free_rate`, and `daily_excess_log_return` in daily return output.
- Remain independently unit-testable without network or Excel access.

### `workbook_writer.py`: Output Serialization

This module owns all Excel output. It must:

- Write the clean price workbook with `Prices`, `Metadata`, and `Row Counts` sheets.
- Write calculated results to a separate returns workbook.
- Write and read cached equity prices and T-Bill observations without downloading or recalculating them.
- Include daily log returns, annualized returns, and configured risk-free-rate metadata in the returns workbook.
- Accept already-calculated DataFrames and never recalculate financial values.
- Create parent directories as needed and use `openpyxl` through pandas.

## 2. Configuration Contract

The editable configuration in `main.py` controls:

- Symbols and inclusive analysis dates.
- Yahoo Finance end date, interval, `auto_adjust`, and `actions` settings.
- Vietnam ticker suffix behavior and adjusted-price column candidates.
- Price and returns workbook paths.
- T-Bill cache path, source symbol, quote-column candidates, and percentage interpretation.
- Whether data loading and calculation stages run in the current execution.
- Trading days per year and annualization method.
- Risk-free-rate source, frequency, currency, daily conversion method, and whether it is included in summaries.

The default risk-free-rate currency is USD because the project requires the US 3-month T-Bill assumption. Analysts must document the FX and country-risk implications when comparing that rate with VND-denominated assets.

## 3. Coding Standards

- Use strict type hints and Google-style docstrings for public functions and classes.
- Use pandas and numpy for tabular data and financial mathematics.
- Keep functions modular, deterministic where possible, and independently testable.
- Use precise financial terminology such as `risk_free_rate`, `expected_return`, `volatility`, `log_returns`, and `annualized_return`.
- Do not hard-code downloaded market data or unsupported financial assumptions.
- Keep unrelated refactors out of changes for a specific workflow.

The returns workbook must remain separate from the input caches. Its daily sheet must contain the equity `log_return` plus the aligned annualized and daily risk-free rates and `daily_excess_log_return`.

## 4. Domain Context

- Target market: Vietnam Stock Market, especially VN30-style liquid large-cap equities.
- Default analysis horizon: 2021-01-01 through 2025-12-31.
- Ultimate objective: portfolio optimization using risk-adjusted return, especially the Sharpe ratio.
- Future Sharpe-ratio work must explain covariance, diversification, volatility, and the treatment of the USD risk-free rate for VND assets.

