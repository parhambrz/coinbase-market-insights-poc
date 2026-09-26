from rich.console import Console
from rich.table import Table

from coinbase_insights.output.models import InsightResult
from coinbase_insights.output.ndjson import result_to_dict


def render_console(result: InsightResult, *, console: Console | None = None) -> None:
    destination = Console() if console is None else console
    values = result_to_dict(result)
    table = Table(title=f"Coinbase Insights: {values['product_id']}")
    table.add_column("Metric")
    table.add_column("Value", overflow="fold")
    for key in (
        "as_of",
        "feed_status",
        "reason",
        "data_age_ms",
        "highest_bid",
        "lowest_ask",
        "current_spread",
        "max_spread_since_start",
        "average_mid_price",
        "forecast_60s",
        "average_absolute_error",
    ):
        table.add_row(key, _display(values[key]))
    destination.print(table)


def _display(value: object) -> str:
    return "unavailable" if value is None else str(value)
