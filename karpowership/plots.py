"""
Charts built with matplotlib. Every function returns a matplotlib ``Figure``;
the app shows it with ``st.pyplot`` and the notebook displays it directly.

All charts share the same simple style: one main colour, light grid, no box.
Downtime periods are shaded: red = outage, blue = maintenance, orange = idle.
"""

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter, StrMethodFormatter

MAIN_COLOR = "#1f3b57"
GREY = "#9a9a9a"
EVENT_COLORS = {"Outage": "#d93b3b", "Maintenance": "#2f6fce", "Idle": "#e8a33d"}

plt.rcParams.update({"font.size": 10, "axes.titlesize": 13, "axes.titleweight": "bold",
                     "axes.spines.top": False, "axes.spines.right": False})


def new_chart(title, ylabel="", height=3.6):
    """
    An empty chart with the common style.

    Parameters
    ----------
    title : str
    ylabel : str, optional
    height : float, optional
        Height in inches (the width is always 10).

    Returns
    -------
    (matplotlib.figure.Figure, matplotlib.axes.Axes)
    """
    fig, ax = plt.subplots(figsize=(10, height))
    ax.set_title(title, loc="left")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color="#e5e5e5")
    ax.set_axisbelow(True)
    return fig, ax


def readable_dates(ax):
    """Short date labels on the x axis (e.g. 2025, Apr, Jul)."""
    locator = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def shade_downtime(ax, events, min_days=1):
    """Shade each downtime period and add a small legend for the types shown."""
    shown = set()
    for _, event in events[events["days"] >= min_days].iterrows():
        color = EVENT_COLORS.get(event["type"], GREY)
        ax.axvspan(event["start"], event["end"], color=color, alpha=0.18, linewidth=0)
        shown.add(event["type"])
    if shown:
        handles = [Patch(color=EVENT_COLORS[kind], alpha=0.4, label=kind) for kind in sorted(shown)]
        ax.legend(handles=handles, loc="lower right", bbox_to_anchor=(1, 1), frameon=False, ncol=len(handles))


def monthly_bars(monthly, column, title, ylabel):
    """
    One bar per month (e.g. energy produced by the fleet).

    Parameters
    ----------
    monthly : pandas.DataFrame
        Columns ``month`` and ``column``.
    column, title, ylabel : str
    """
    fig, ax = new_chart(title, ylabel)
    ax.bar(monthly["month"], monthly[column], width=25, color=MAIN_COLOR)
    ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    readable_dates(ax)
    return fig


def monthly_line(monthly, column, title, events, percent=False):
    """
    One line over the months, with the long downtimes (14+ days) shaded.

    Parameters
    ----------
    monthly : pandas.DataFrame
        Columns ``month`` and ``column``.
    column, title : str
    events : pandas.DataFrame
        Table returned by ``alerts.downtime_events``.
    percent : bool, optional
        Show the y axis as a percentage.
    """
    fig, ax = new_chart(title)
    ax.plot(monthly["month"], monthly[column], color=MAIN_COLOR, marker="o", markersize=4)
    shade_downtime(ax, events, min_days=14)
    if percent:
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    readable_dates(ax)
    return fig


def availability_heatmap(wide):
    """
    Availability of each ship in each month: dark cells are months with downtime.

    Parameters
    ----------
    wide : pandas.DataFrame
        One row per ship, one column per month (see ``data.monthly_table``).
    """
    fig, ax = new_chart("Availability per ship and month", height=0.45 * len(wide) + 1.4)
    ax.grid(False)
    image = ax.imshow(wide.to_numpy(), aspect="auto", cmap="Greys_r", vmin=0, vmax=1)
    ax.set_yticks(range(len(wide)), wide.index)
    months = list(wide.columns)
    ticks = [i for i, month in enumerate(months) if month.month in (1, 7)]
    ax.set_xticks(ticks, [months[i].strftime("%b %Y") for i in ticks])
    fig.colorbar(image, ax=ax, format=PercentFormatter(1.0), fraction=0.03)
    return fig


def ship_bars(table, column, title, number_format="{:,.0f}"):
    """
    Horizontal bars, one per ship, sorted from highest to lowest, with the value written.

    Parameters
    ----------
    table : pandas.DataFrame
        Columns ``ship_name`` and ``column``.
    column, title : str
    number_format : str, optional
        How to write the values, e.g. ``"{:.1%}"``.
    """
    table = table.sort_values(column)
    fig, ax = new_chart(title, height=0.4 * len(table) + 1.2)
    ax.grid(False)
    bars = ax.barh(table["ship_name"], table[column], color=MAIN_COLOR)
    ax.bar_label(bars, labels=[number_format.format(v) for v in table[column]], padding=4)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    return fig


def efficiency_boxplot(daily):
    """
    Spread of daily efficiency for each ship (operating days only).

    The box holds the middle 50 % of the days, the line in the box is the median.
    """
    days = daily[(daily["status"] == "operating") & daily["mwh_per_ton"].notna()]
    ships = sorted(days["ship_name"].unique())
    fig, ax = new_chart("Daily efficiency per ship", "MWh per tonne")
    ax.boxplot([days.loc[days["ship_name"] == ship, "mwh_per_ton"] for ship in ships],
               tick_labels=ships, showfliers=False,
               medianprops={"color": MAIN_COLOR, "linewidth": 2})
    return fig


def seasonal_line(profile):
    """Average capacity factor in each calendar month (``analysis.seasonal_profile``)."""
    fig, ax = new_chart("Seasonal pattern: average capacity factor by month")
    ax.plot(profile["month"], profile["capacity_factor"], color=MAIN_COLOR, marker="o")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    return fig


def daily_production(ship_days, events):
    """Daily production of one ship, with its downtime periods shaded."""
    fig, ax = new_chart("Daily production", "MWh")
    ax.fill_between(ship_days["date"], ship_days["production_mwh"].fillna(0), color=MAIN_COLOR, linewidth=0)
    shade_downtime(ax, events)
    readable_dates(ax)
    return fig


def efficiency_vs_normal(check, events):
    """
    Efficiency of one ship compared with its normal level.

    Grey dots: daily efficiency. Blue line: last 7 days. Dashed line: normal
    level. Red triangles: alert days (more than 4 % below normal).

    Parameters
    ----------
    check : pandas.DataFrame
        Rows of ``alerts.efficiency_check`` for one ship.
    events : pandas.DataFrame
        Downtime periods of the same ship.
    """
    # One row per calendar day, so the lines break during downtime instead of jumping across it.
    check = check.set_index("date").asfreq("D").reset_index()

    fig, ax = new_chart("Efficiency compared with normal", "MWh per tonne")
    ax.scatter(check["date"], check["mwh_per_ton"], s=6, color=GREY, alpha=0.5)
    ax.plot(check["date"], check["normal"], color="#333333", linestyle="--", linewidth=1)
    ax.plot(check["date"], check["recent"], color=MAIN_COLOR, linewidth=1.5)
    alert_days = check[check["alert"].eq(True)]
    ax.scatter(alert_days["date"], alert_days["recent"], marker="v", s=30, color="#d93b3b", zorder=3)
    shade_downtime(ax, events)
    readable_dates(ax)
    return fig
