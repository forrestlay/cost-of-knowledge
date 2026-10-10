"""Charts of a cost estimate, and the social media card that shares it."""

from typing import TYPE_CHECKING

import drawsvg as draw
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import resvg_py
import streamlit as st

from src.reference_data import RESEARCH_PHASES

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from src.models import BaseActivity, Cost

# Real colours for the phases on the card, as Streamlit's placeholder palette renders near-black outside the app.
# Plotly's Bold palette, darkened (same hue and saturation) to at least 3:1 contrast against every point of the card's
# background gradient, per WCAG 2.2 SC 1.4.11 (non-text contrast). Each also has over 5:1 contrast with the white
# hatching drawn over it.
_PHASE_PALETTE: list[str] = [
    "#7f3c8d",
    "#0c7757",
    "#3969ac",
    "#826301",
    "#ca1951",
    "#4a7230",
    "#9a580b",
    "#00717e",
    "#c21a87",
    "#ce1609",
    "#646958",
]


_HATCH_TILE: int = 16
_HATCH_STYLES: int = 8


def _hatched_fill(colour: str, index: int) -> draw.Pattern | str:
    """Builds a fill of the colour overlaid with a hatching pattern, so categories differ by more than hue.

    Args:
        colour: Base fill colour.
        index: Position of the category. Cycles through solid, diagonal stripes, dots, opposite diagonal stripes,
            horizontal stripes, vertical stripes, crosshatch, and grid styles.

    Returns:
        A solid colour for the first style, otherwise an SVG pattern.
    """
    style: int = index % _HATCH_STYLES
    if style == 0:
        return colour
    tile: int = _HATCH_TILE
    transform: str | None = {1: "rotate(45)", 3: "rotate(-45)", 6: "rotate(45)"}.get(style)
    pattern: draw.Pattern = draw.Pattern(tile, tile, patternTransform=transform)
    pattern.append(draw.Rectangle(0, 0, tile, tile, fill=colour))

    def line(x1: float, y1: float, x2: float, y2: float) -> None:
        pattern.append(draw.Line(x1, y1, x2, y2, stroke="#ffffff", stroke_width=3, stroke_opacity=0.9))

    half: float = tile / 2
    if style in (1, 3, 4):  # diagonal stripes in either direction, then horizontal stripes
        line(0, half, tile, half)
    elif style == 2:  # dots
        pattern.append(draw.Circle(half, half, 2.5, fill="#ffffff", fill_opacity=0.9))
    elif style == 5:  # vertical stripes
        line(half, 0, half, tile)
    elif style == 6:  # diagonal crosshatch
        line(0, half, tile, half)
        line(half, 0, half, tile)
    else:  # square grid
        line(0, half, tile, half)
        line(half, 0, half, tile)
    return pattern


# Placeholder hex values that Streamlit's frontend swaps for its theme's categorical
# colour palette (see streamlit/elements/lib/streamlit_plotly_theme.py). Assigning one
# of these to a category keeps that phase or activity on the same Streamlit colour in
# every chart. Charts with more than 10 categories fall back to px.colors.qualitative.Light24.
STREAMLIT_CATEGORICAL_COLORS: list[str] = [f"#{n:06d}" for n in range(1, 11)]


def build_color_map(names: Sequence[str], palette: Sequence[str] | None = None) -> dict[str, str]:
    """Assigns each distinct name a stable colour so a phase or activity keeps the
    same colour across every chart.

    Args:
        names: Category names, in the order they should claim colours.
        palette: Colours to draw from. Defaults to Streamlit's categorical palette
            when it has enough colours, otherwise px.colors.qualitative.Light24.
    """
    distinct: list[str] = list(dict.fromkeys(names))
    if palette is None:
        palette = (
            STREAMLIT_CATEGORICAL_COLORS
            if len(distinct) <= len(STREAMLIT_CATEGORICAL_COLORS)
            else px.colors.qualitative.Light24
        )
    return {name: palette[i % len(palette)] for i, name in enumerate(distinct)}


# Plotly pattern shapes matching the hatching on the social media card, so categories differ by more than colour
# for colourblind users. The first is solid, and the order follows the card's cycle.
_PATTERN_SHAPES: list[str] = ["", "/", ".", "\\", "-", "|", "x", "+"]
_PATTERN_LINE_COLOUR: str = "#ffffff"


def _pattern_shape(index: int) -> str:
    """The Plotly pattern shape for the category at the position, cycling once the shapes run out."""
    return _PATTERN_SHAPES[index % len(_PATTERN_SHAPES)]


def _pattern(shape: str | list[str]) -> dict:
    """Plotly marker pattern drawing white hatching in the given shape(s) over the marker colour."""
    return {"shape": shape, "fgcolor": _PATTERN_LINE_COLOUR, "fillmode": "overlay", "size": 8, "solidity": 0.35}


def costs_dataframe(costs: Sequence[Cost]) -> pd.DataFrame:
    """One row per activity or direct cost, with its name, total cost and phase display name."""
    return pd.DataFrame(
        {
            "Item": [item.get_name() or "Unnamed" for item in costs],
            "Cost": [item.get_total_cost() for item in costs],
            "Phase": [RESEARCH_PHASES[item.get_phase()] for item in costs],
        }
    )


def labour_dataframe(activities: Sequence[BaseActivity], include_hours: bool = True) -> pd.DataFrame:
    """One row per activity, with its name, cost, phase display name and person, and optionally its hours.

    Pass include_hours=False for charts that must not expose the hours of labour, as the data of a chart is sent to
    the browser whether or not the chart displays it.
    """
    data: dict[str, list] = {
        "Activity": [activity.get_name() or "Unnamed" for activity in activities],
        "Cost": [activity.get_total_cost() for activity in activities],
        "Phase": [RESEARCH_PHASES[activity.get_phase()] for activity in activities],
        "Person": [activity.get_person().label for activity in activities],
    }
    if include_hours:
        data["Hours"] = [activity.get_hours() for activity in activities]
    return pd.DataFrame(data)


_LEGEND_ROW_HEIGHT: int = 24


def _legend_below(figure: go.Figure, entries: int, plot_height: int, bottom_margin: int = 0) -> None:
    """Moves the legend of a figure to a single vertical column beneath the plot, for narrow screens.

    The figure is made tall enough for the plot plus one legend row per entry, and the legend is pinned to the bottom
    of the figure.

    Args:
        figure: The figure to modify in place.
        entries: Number of legend entries.
        plot_height: Height in pixels of the plot area above the legend.
        bottom_margin: Extra space in pixels beneath the plot for content such as axis labels.
    """
    legend_height: int = entries * _LEGEND_ROW_HEIGHT + 20
    figure.update_layout(
        height=plot_height + bottom_margin + legend_height,
        showlegend=True,
        legend={
            "orientation": "v",
            "x": 0,
            "xanchor": "left",
            "y": 0,
            "yanchor": "bottom",
            "yref": "container",
        },
        margin={"b": bottom_margin + legend_height},
    )


def costs_pie_chart(
    costs_df: pd.DataFrame,
    names: str,
    phase_color_map: dict[str, str],
    item_color_map: dict[str, str],
    legend_below: bool = False,
    hatching: bool = False,
) -> go.Figure:
    """Pie chart of the total cost, split by phase (names="Phase") or by activity and direct cost (names="Item").

    Pass legend_below=True for narrow screens, to list the legend vertically beneath the pie. Pass hatching=True to
    add patterns to the colours, for colourblind users.
    """
    pie: go.Figure = px.pie(
        costs_df,
        values="Cost",
        names=names,
        color=names,
        color_discrete_map={**phase_color_map, **item_color_map},
        title="Total Cost Breakdown",
    )
    if hatching:
        color_map: dict[str, str] = phase_color_map if names == "Phase" else item_color_map
        positions: dict[str, int] = {name: i for i, name in enumerate(color_map)}
        pie.update_traces(
            marker={"pattern": _pattern([_pattern_shape(positions.get(label, 0)) for label in pie.data[0].labels])}
        )
    if legend_below:
        _legend_below(pie, costs_df[names].nunique(), plot_height=380)
    else:
        pie.update_layout(height=720)
    return pie


def labour_sunburst_chart(
    labour_df: pd.DataFrame,
    phase_color_map: dict[str, str],
    total_cost: float,
    currency_code: str,
    legend_below: bool = False,
    hatching: bool = False,
) -> go.Figure:
    """Sunburst of the cost of labour by phase, person and activity, labelled as a percentage of total_cost.

    Pass legend_below=True for narrow screens, to list the legend vertically beneath the sunburst. Pass hatching=True
    to add patterns to the colours, for colourblind users.
    """
    sunburst: go.Figure = px.sunburst(
        labour_df,
        path=["Phase", "Person", "Activity"],
        values="Cost",
        color="Phase",
        labels={"Cost": f"Cost ({currency_code})"},
        color_discrete_map=phase_color_map,
        title="Cost of Labor Breakdown by Phase, Role and Activity",
    )
    # Label each segment with its cost as a percentage of the overall total cost.
    # total_cost includes direct costs, which are not shown in this sunburst, so
    # the percentages of the top-level segments will not sum to 100%.
    node_costs: list[float] = list(sunburst.data[0].values)
    sunburst.data[0].text = [f"{(cost / total_cost * 100):.1f}%" if total_cost else "0.0%" for cost in node_costs]
    sunburst.data[0].texttemplate = "%{label}<br>%{text}"
    # Each node shares its phase's colour, so the colour tells which phase's pattern the node takes.
    if hatching:
        shape_by_colour: dict[str, str] = {
            colour: _pattern_shape(i) for i, colour in enumerate(phase_color_map.values())
        }
        sunburst.data[0].marker.pattern = _pattern(
            [shape_by_colour.get(colour, "") for colour in sunburst.data[0].marker.colors]
        )
    # Sunburst traces cannot show a legend, so add an invisible placeholder trace per phase to create
    # legend entries. The legend takes up the same space as the pie chart's legend, aligning the two charts.
    # Bar traces are used as scatter markers cannot show patterns.
    for i, phase in enumerate(phase_color_map):
        if phase not in set(labour_df["Phase"]):
            continue
        sunburst.add_trace(
            go.Bar(
                x=[None],
                y=[None],
                marker={
                    "color": phase_color_map[phase],
                    **({"pattern": _pattern(_pattern_shape(i))} if hatching else {}),
                },
                name=phase,
                hoverinfo="skip",
            )
        )
    sunburst.update_xaxes(visible=False)
    sunburst.update_yaxes(visible=False)
    sunburst.update_layout(height=720, showlegend=True, legend={"itemclick": False, "itemdoubleclick": False})
    if legend_below:
        _legend_below(sunburst, labour_df["Phase"].nunique(), plot_height=380)
    return sunburst


def labour_bar_chart(
    labour_df: pd.DataFrame,
    measure: str,
    title: str,
    phase_color_map: dict[str, str],
    currency_code: str,
    currency_prefix: str,
    legend_below: bool = False,
    hatching: bool = False,
) -> go.Figure:
    """Bar chart of each labour activity's cost (measure="Cost") or hours (measure="Hours"), coloured by phase.

    The cost and hours of every researcher in an activity are added together, so each activity is a single bar.
    Pass legend_below=True for narrow screens, to list the legend vertically beneath the chart. Pass hatching=True to
    add patterns to the colours, for colourblind users.
    """
    totals_df: pd.DataFrame = labour_df.groupby(["Activity", "Phase"], as_index=False, sort=False)[[measure]].sum()
    chart: go.Figure = px.bar(
        totals_df,
        x="Activity",
        y=measure,
        color="Phase",
        color_discrete_map=phase_color_map,
        title=title,
        text_auto=True,
        labels={"Cost": f"Cost ({currency_code})"},
    )
    if hatching:
        positions: dict[str, int] = {name: i for i, name in enumerate(phase_color_map)}
        chart.for_each_trace(
            lambda trace: trace.update(marker={"pattern": _pattern(_pattern_shape(positions.get(trace.name, 0)))})
        )
    if measure == "Cost":
        chart.update_traces(texttemplate=f"{currency_prefix}%{{y:,.2f}}", textposition="outside")
        chart.update_yaxes(tickprefix=currency_prefix)
    else:
        chart.update_traces(texttemplate="%{y:.1f} hours", textposition="outside")
    if legend_below:
        # The bottom margin leaves room for the rotated activity names between the plot and the legend.
        _legend_below(chart, totals_df["Phase"].nunique(), plot_height=380, bottom_margin=140)
    return chart


def _join_list(items: Sequence[str]) -> str:
    """Joins items into a list for alt text, e.g. "A; B; and C".

    Semicolons separate the items, as formatted amounts contain commas.
    """
    if len(items) <= 1:
        return "".join(items)
    return "; ".join(items[:-1]) + f"; and {items[-1]}"


def _plural(count: int, noun: str, plural: str | None = None) -> str:
    """Formats a count with its noun, e.g. "1 phase" or "3 phases", taking ``plural`` for irregular nouns."""
    return f"{count} {noun if count == 1 else plural or f'{noun}s'}"


def costs_pie_chart_alt_text(costs_df: pd.DataFrame, names: str, format_currency: Callable[[float], str]) -> str:
    """Builds alt text for ``costs_pie_chart``, listing each slice's cost and share, largest first.

    Args:
        costs_df: The data of the chart, from ``costs_dataframe``.
        names: The column the pie is split by, "Phase" or "Item".
        format_currency: Formats an amount as a string in the chosen country's currency.
    """
    by_phase: bool = names == "Phase"
    title: str = f'Pie chart "Total Cost Breakdown" by {"phase" if by_phase else "activity and direct cost"}.'
    totals: pd.Series = costs_df.groupby(names, sort=False)["Cost"].sum().sort_values(ascending=False)
    totals = totals[totals > 0]
    total: float = float(totals.sum())
    if total <= 0:
        return f"{title} There are no costs to show."
    slices: list[str] = [
        f"{name}: {format_currency(cost)} ({cost / total * 100:.0f}%)" for name, cost in totals.items()
    ]
    noun_count: str = (
        _plural(len(slices), "phase")
        if by_phase
        else _plural(len(slices), "activity and direct cost", "activities and direct costs")
    )
    return (
        f"{title} The total cost of {format_currency(total)} is split across {noun_count}, largest first: "
        f"{_join_list(slices)}."
    )


def labour_sunburst_chart_alt_text(
    labour_df: pd.DataFrame, total_cost: float, format_currency: Callable[[float], str]
) -> str:
    """Builds alt text for ``labour_sunburst_chart``, listing each phase's cost of labour and the people within it.

    The activities in the outer ring are left out to keep the text short; the labour bar chart lists them.

    Args:
        labour_df: The data of the chart, from ``labour_dataframe``.
        total_cost: The total cost of the paper, which the chart's percentages are of.
        format_currency: Formats an amount as a string in the chosen country's currency.
    """
    title: str = 'Sunburst chart "Cost of Labor Breakdown by Phase, Role and Activity".'
    labour_df = labour_df[labour_df["Cost"] > 0]
    if labour_df.empty:
        return f"{title} There are no labor costs to show."

    def share(cost: float) -> str:
        return f"{cost / total_cost * 100:.1f}%" if total_cost else "0.0%"

    phases: list[str] = []
    for phase, phase_df in labour_df.groupby("Phase", sort=False):
        phase_cost: float = float(phase_df["Cost"].sum())
        people: pd.Series = phase_df.groupby("Person", sort=False)["Cost"].sum().sort_values(ascending=False)
        people_text: str = ", ".join(f"{person} {format_currency(cost)}" for person, cost in people.items())
        phases.append(f"{phase}: {format_currency(phase_cost)} ({share(phase_cost)}), by {people_text}")
    labour_cost: float = float(labour_df["Cost"].sum())
    return (
        f"{title} The inner ring splits the cost of labor, {format_currency(labour_cost)} ({share(labour_cost)} of "
        f"the total cost of {format_currency(total_cost)}), across {_plural(len(phases), 'phase')}; the middle ring "
        f"splits each phase by person, and the outer ring by activity. {_join_list(phases)}."
    )


def labour_bar_chart_alt_text(
    labour_df: pd.DataFrame, measure: str, title: str, format_currency: Callable[[float], str]
) -> str:
    """Builds alt text for ``labour_bar_chart``, listing each activity's bar in order.

    Args:
        labour_df: The data of the chart, from ``labour_dataframe``.
        measure: The measure the bars show, "Cost" or "Hours".
        title: The title of the chart.
        format_currency: Formats an amount as a string in the chosen country's currency.
    """
    totals_df: pd.DataFrame = labour_df.groupby(["Activity", "Phase"], as_index=False, sort=False)[[measure]].sum()
    chart: str = f'Bar chart "{title}" of the {measure.lower()} of each labor activity, colored by phase.'
    if totals_df.empty:
        return f"{chart} There are no labor activities to show."
    bars: list[str] = [
        f"{activity} ({phase}): " + (format_currency(value) if measure == "Cost" else f"{value:,.1f} hours")
        for activity, phase, value in zip(totals_df["Activity"], totals_df["Phase"], totals_df[measure], strict=True)
    ]
    return f"{chart} {_plural(len(bars), 'activity', 'activities')}: {_join_list(bars)}."


def hours_per_person_chart_alt_text(hours_per_person_df: pd.DataFrame) -> str:
    """Builds alt text for the bar chart of the hours of labour per person, listing each person's bar in order.

    Args:
        hours_per_person_df: The data of the chart, with "Person" and "Hours" columns.
    """
    chart: str = 'Bar chart "Hours of Labor per Person".'
    if hours_per_person_df.empty:
        return f"{chart} There are no people to show."
    bars: list[str] = [
        f"{person}: {hours:,.1f} hours"
        for person, hours in zip(hours_per_person_df["Person"], hours_per_person_df["Hours"], strict=True)
    ]
    return f"{chart} {_plural(len(bars), 'person', 'people')}: {_join_list(bars)}."


# Arial is the intended face; the generic fallback lets the PNG renderer substitute a metric-compatible font
# (Liberation Sans, installed in the Docker image) on hosts without Arial.
SOCIAL_MEDIA_FONT: str = "Arial, sans-serif"


def _wrap_text(text: str, max_chars: int) -> list[str]:
    """Greedily wraps text into lines of at most ``max_chars`` characters.

    drawsvg does no line wrapping of its own, so long project titles are split
    here before being handed to a multi-line ``draw.Text``.
    """
    words: list[str] = text.split()
    lines: list[str] = []
    current: str = ""
    for word in words:
        candidate: str = f"{current} {word}".strip()
        if not current or len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


# Blurb of the social-media card, beginning the sentence that the headline continues.
SOCIAL_MEDIA_BLURB: str = "Using the Cost of Knowledge calculator, I estimated that"

# Headline of the social-media card, continuing the blurb and leading into the total cost below it.
SOCIAL_MEDIA_HEADLINE: str = "The public and institutional investment in my peer-reviewed journal article is"

# Legend label of the publisher investment on the social-media card's bar chart.
SOCIAL_MEDIA_PUBLISHER_LABEL: str = "Estimated publisher investment"

# Heading of the research phases in the social-media card's legend.
SOCIAL_MEDIA_PHASES_HEADING: str = "What public and institutional investment funded"


def _social_media_breakdown(phase_costs: dict[str, float], publishing_costs: float) -> dict[str, float]:
    """The segments of the social-media card's bar chart: the cost of each research phase, then the publisher
    investment if the publishing costs are included."""
    if publishing_costs <= 0:
        return dict(phase_costs)
    return {**phase_costs, SOCIAL_MEDIA_PUBLISHER_LABEL: publishing_costs}


def _wrap_parts(parts: list[str], separator: str, max_chars: int) -> list[str]:
    """Greedily packs parts into lines of at most ``max_chars`` characters, joining parts on a line with ``separator``.

    A part only starts a new line if it does not fit on the current one, and a part too long for a line of its own is
    word-wrapped, the parts after it continuing on its last line.
    """
    lines: list[str] = []
    current: str = ""
    for part in parts:
        candidate: str = f"{current}{separator}{part}" if current else part
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        wrapped: list[str] = _wrap_text(part, max_chars)
        lines.extend(wrapped[:-1])
        current = wrapped[-1]
    if current:
        lines.append(current)
    return lines or [""]


def _social_media_subtitle_parts(
    project_field: str, researchers: int, country: str, international_collaborators: bool
) -> list[str]:
    """The parts of the social-media card's subtitle: the field of research, the number of researchers and
    contributors, then where they are.

    The field of research is left out if there is none. Where they are is "International" for projects with
    international collaborators, otherwise the country, and is left out if there is no country.
    """
    parts: list[str] = [project_field.strip()] if project_field.strip() else []
    parts.append("1 researcher" if researchers == 1 else f"{researchers:,} researchers and contributors")
    place: str = "International" if international_collaborators else country.strip()
    if place:
        parts.append(place)
    return parts


def create_social_media_svg(
    country: str,
    international_collaborators: bool,
    project_field: str,
    researchers: int,
    total_cost: float,
    phase_costs: dict[str, float],
    publishing_costs: float,
    format_currency: Callable[[float], str],
    version: str | None = None,
) -> draw.Drawing:
    """Builds a portrait social-media card summarising a cost estimate.

    The cost breakdown is drawn as a plain SVG stacked bar (no Plotly/Kaleido),
    so the card renders identically wherever the SVG is displayed.

    Args:
        country: Display name of the researcher's country.
        international_collaborators: Whether the project has collaborators from other countries; shows "International"
            in place of the country.
        project_field: Name of the Field of Research group the project sits in, shown before the researchers and
            country, or "" to leave it out.
        researchers: Number of researchers and contributors the user added, counting each person's quantity, but not
            the peer reviewer or journal editor.
        total_cost: Estimated public and institutional investment in the chosen country's currency, leaving out the
            publishing costs.
        phase_costs: Cost in the chosen country's currency per research phase, keyed by phase display name, leaving out
            the publishing costs.
        publishing_costs: The publisher investment in the chosen country's currency, shown as the last segment of the
            bar chart, or 0 to leave it out.
        format_currency: Formats an amount as a string in the chosen country's currency.
        version: Version of the tool that produced the estimate (e.g. "0.1.2"), shown in the bottom-left corner, or
            None to leave it out.
    """
    width: int = 1080
    height: int = 1360
    margin: int = 72
    # Text colours meet WCAG AA contrast (4.5:1) against every point of the background gradient: ink 8.6:1, muted
    # 4.6:1, accent 4.6:1.
    ink: str = "#16263a"
    muted: str = "#3f5064"
    accent: str = "#961c47"

    image: draw.Drawing = draw.Drawing(width, height, id_prefix="socmed")

    # Background
    gradient = draw.LinearGradient(200, 0, 800, height)
    gradient.add_stop(0, "lightskyblue")
    gradient.add_stop(1, "lightsteelblue")
    image.append(draw.Rectangle(0, 0, width, height, fill=gradient))

    # Eyebrow
    image.append(
        draw.Text(
            "THE COST OF KNOWLEDGE",
            30,
            margin,
            110,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
            font_weight="bold",
            letter_spacing=4,
        )
    )

    # Blurb, beginning the sentence that the headline continues.
    image.append(
        draw.Text(
            SOCIAL_MEDIA_BLURB,
            28,
            margin,
            162,
            fill=ink,
            font_family=SOCIAL_MEDIA_FONT,
        )
    )

    # Vertical layout. The headline, total and subtitle flow down from the blurb, then the divider, breakdown and
    # legend, while the call to action and footer are anchored to the bottom of the card. The
    # space left over, which depends on the number of phases and wrapped lines, is shared between the gaps above the
    # total, above the divider and below the legend.
    headline_size: int = 52
    headline_line_height: float = 1.2
    headline_lines: list[str] = _wrap_text(SOCIAL_MEDIA_HEADLINE, 31)
    # The first baseline sits a fixed gap below the blurb.
    headline_top: float = 196 + headline_size * 0.8
    headline_bottom: float = headline_top + headline_size * headline_line_height * (len(headline_lines) - 1)

    breakdown: dict[str, float] = _social_media_breakdown(phase_costs, publishing_costs)
    phase_names: list[str] = list(breakdown.keys())
    breakdown_total: float = sum(breakdown.values())
    visible_phases: list[str] = [name for name in phase_names if breakdown[name] > 0] or phase_names
    # From the last headline baseline to the total's baseline, and from the total's baseline to the subtitle's.
    headline_total_gap: float = 110
    total_size: int = 88
    total_subtitle_gap: float = 76

    subtitle_size: int = 34
    subtitle_line_height: float = 1.2
    # The field of research, researchers and country share a line where they fit, wrapping onto more lines if not.
    subtitle_lines: list[str] = _wrap_parts(
        _social_media_subtitle_parts(project_field, researchers, country, international_collaborators), " · ", 58
    )
    subtitle_block_h: float = subtitle_size * subtitle_line_height * (len(subtitle_lines) - 1)
    # From the last subtitle baseline to the divider, and from the divider to the top of the bar.
    subtitle_divider_gap: float = 46
    divider_bar_gap: float = 52

    bar_h: int = 88
    legend_row_h: int = 48
    legend_font: int = 28
    # The research phases' heading, if any phase is shown, takes the place of the first legend row's baseline, the
    # rows following a gap below it. Text has no swatch reaching above it, so the heading sits closer to the bar.
    phases_heading: bool = any(name != SOCIAL_MEDIA_PUBLISHER_LABEL for name in visible_phases)
    bar_legend_gap: float = 56 if phases_heading else 70
    heading_legend_gap: float = 48 if phases_heading else 0
    # The least space from the last legend baseline to the call to action's baseline.
    legend_cta_gap: float = 100
    # Extra space before the publisher investment's legend row, which a dashed line sets apart from the research
    # phases above it.
    publisher_separated: bool = SOCIAL_MEDIA_PUBLISHER_LABEL in visible_phases and len(visible_phases) > 1
    publisher_gap: float = 24 if publisher_separated else 0

    # Bottom-anchored call to action's baseline.
    cta_y: float = height - 108
    cta_size: int = 28
    content_limit: float = cta_y - legend_cta_gap

    content_bottom: float = (
        headline_bottom
        + headline_total_gap
        + total_subtitle_gap
        + subtitle_block_h
        + subtitle_divider_gap
        + divider_bar_gap
        + bar_h
        + bar_legend_gap
        + heading_legend_gap
        + (len(visible_phases) - 1) * legend_row_h
        + publisher_gap
    )
    slack: float = max(0.0, content_limit - content_bottom)
    total_y: float = headline_bottom + headline_total_gap + slack / 3
    subtitle_y: float = total_y + total_subtitle_gap
    divider_y: float = subtitle_y + subtitle_block_h + subtitle_divider_gap + slack / 3
    bar_y: float = divider_y + divider_bar_gap
    heading_y: float = bar_y + bar_h + bar_legend_gap
    legend_first_y: float = heading_y + heading_legend_gap

    # Headline
    image.append(
        draw.Text(
            headline_lines,
            headline_size,
            margin,
            headline_top,
            fill=ink,
            font_family=SOCIAL_MEDIA_FONT,
            font_weight="bold",
            line_height=headline_line_height,
        )
    )

    # Total cost, answering the headline.
    image.append(
        draw.Text(
            format_currency(total_cost),
            total_size,
            margin,
            total_y,
            fill=ink,
            font_family=SOCIAL_MEDIA_FONT,
            font_weight="bold",
        )
    )

    image.append(
        draw.Text(
            subtitle_lines,
            subtitle_size,
            margin,
            subtitle_y,
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
            line_height=subtitle_line_height,
        )
    )
    image.append(
        draw.Line(
            margin,
            divider_y,
            width - margin,
            divider_y,
            stroke="#ffffff",
            stroke_width=2,
            stroke_opacity=0.6,
        )
    )

    # Cost breakdown by phase, drawn as a plain SVG stacked bar so no charting library is needed. Streamlit's
    # placeholder palette renders near-black outside the app, so choose real colours here, one stable colour per phase.
    palette: dict[str, str] = {
        name: _PHASE_PALETTE[i % len(_PHASE_PALETTE)] for i, name in enumerate(dict.fromkeys(phase_names))
    }
    fills: dict[str, draw.Pattern | str] = {
        name: _hatched_fill(palette[name], i) for i, name in enumerate(dict.fromkeys(phase_names))
    }
    bar_x: int = margin
    bar_w: int = width - 2 * margin
    if breakdown_total > 0:
        cursor: float = bar_x
        for name in phase_names:
            segment: float = bar_w * (breakdown[name] / breakdown_total)
            if segment <= 0:
                continue
            image.append(draw.Rectangle(cursor, bar_y, segment, bar_h, fill=fills[name]))
            cursor += segment
    else:
        image.append(draw.Rectangle(bar_x, bar_y, bar_w, bar_h, fill="#ffffff", fill_opacity=0.4))
    image.append(
        draw.Rectangle(
            bar_x,
            bar_y,
            bar_w,
            bar_h,
            rx=10,
            fill="none",
            # Ink rather than white, so the bar's edge has 3:1 contrast against the background.
            stroke=ink,
            stroke_width=3,
        )
    )

    if phases_heading:
        image.append(
            draw.Text(
                SOCIAL_MEDIA_PHASES_HEADING,
                legend_font,
                margin,
                heading_y,
                fill=ink,
                font_family=SOCIAL_MEDIA_FONT,
                font_weight="bold",
            )
        )

    # Legend: one row per phase that has a cost, the publisher investment set apart below a dashed line.
    row_index: int = 0
    for name in phase_names:
        amount: float = breakdown[name]
        if amount <= 0:
            continue
        row_y: float = legend_first_y + row_index * legend_row_h
        if name == SOCIAL_MEDIA_PUBLISHER_LABEL and publisher_separated:
            row_y += publisher_gap
            # Midway between the swatches of the rows above and below.
            separator_y: float = row_y - (legend_row_h + publisher_gap) / 2 - 8
            image.append(
                draw.Line(
                    margin,
                    separator_y,
                    width - margin,
                    separator_y,
                    stroke=muted,
                    stroke_width=2,
                    stroke_dasharray="8 8",
                )
            )
        share: float = amount / breakdown_total * 100 if breakdown_total else 0.0
        image.append(draw.Rectangle(margin, row_y - 24, 32, 32, rx=7, fill=fills[name]))
        image.append(
            draw.Text(
                name,
                legend_font,
                margin + 48,
                row_y,
                fill=ink,
                font_family=SOCIAL_MEDIA_FONT,
            )
        )
        image.append(
            draw.Text(
                f"{format_currency(amount)}  ({share:.0f}%)",
                legend_font,
                width - margin,
                row_y,
                fill=muted,
                text_anchor="end",
                font_family=SOCIAL_MEDIA_FONT,
            )
        )
        row_index += 1

    image.append(
        draw.Text(
            "Estimate your own Cost of Knowledge at https://costofknowledge.org.",
            cta_size,
            width / 2,
            cta_y,
            text_anchor="middle",
            fill=accent,
            font_weight="bold",
            font_family=SOCIAL_MEDIA_FONT,
        )
    )
    # Credit, with the authors on their own line below.
    image.append(
        draw.Text(
            ["The University of Sydney and SPARC.", "Alam, Andrew, Baker, Coupe, Koh, Lay, Loh, and Tanima 2026."],
            24,
            width - margin,
            height - 64,
            text_anchor="end",
            fill=muted,
            font_family=SOCIAL_MEDIA_FONT,
            line_height=28 / 24,
        )
    )
    if version is not None:
        # Aligned with the last line of the credit.
        image.append(
            draw.Text(
                f"Version {version}",
                14,
                margin,
                height - 36,
                fill=muted,
                font_family=SOCIAL_MEDIA_FONT,
            )
        )
    return image


def create_social_media_image_alt_text(
    country: str,
    international_collaborators: bool,
    project_field: str,
    researchers: int,
    total_cost: float,
    phase_costs: dict[str, float],
    publishing_costs: float,
    format_currency: Callable[[float], str],
    version: str | None = None,
) -> str:
    """Builds alt text for the social-media card from ``create_social_media_svg``.

    Repeats the card's text in reading order and describes the stacked bar as the share of the cost taken by each
    phase, so the card is accessible to screen-reader users. Takes the same arguments as ``create_social_media_svg``.
    """
    subtitle: str = ", ".join(
        _social_media_subtitle_parts(project_field, researchers, country, international_collaborators)
    )

    sentences: list[str] = [
        'An infographic intended for sharing on social media, titled "The Cost of Knowledge".',
        "The text of the infographic is as follows: ",
        f"{SOCIAL_MEDIA_BLURB} {SOCIAL_MEDIA_HEADLINE} {format_currency(total_cost)}.",
        f"{subtitle}.",
    ]

    breakdown: dict[str, float] = _social_media_breakdown(phase_costs, publishing_costs)
    breakdown_total: float = sum(breakdown.values())
    phase_shares: list[str] = [
        f"{name}: {format_currency(amount)} ({amount / breakdown_total * 100:.0f}%)"
        for name, amount in breakdown.items()
        if amount > 0
    ]
    if breakdown_total > 0 and phase_shares:
        researched_phases: int = sum(1 for amount in phase_costs.values() if amount > 0)
        split: str = _plural(researched_phases, "research phase")
        if publishing_costs > 0:
            split = f"{split} and the publisher investment" if researched_phases else "the publisher investment"
        legend: str = f', with a legend headed "{SOCIAL_MEDIA_PHASES_HEADING}",' if researched_phases else ""
        sentences.append(
            f"A horizontal stacked bar chart{legend} splits the cost across {split}, from left to right: "
            f"{_join_list(phase_shares)}."
        )
    else:
        sentences.append("An empty bar chart, as no research phase has a cost.")

    sentences.append("Estimate your own Cost of Knowledge at https://costofknowledge.org.")
    sentences.append("The University of Sydney and SPARC. Alam, Andrew, Baker, Coupe, Koh, Lay, Loh, and Tanima 2026.")
    if version is not None:
        sentences.append(f"Version {version}.")
    return " ".join(sentences)


@st.cache_data(show_spinner=False)
def social_media_svg_to_png(svg: str) -> bytes:
    """Rasterises the social-media card for platforms that do not accept SVG uploads (e.g. LinkedIn, X, Facebook).

    Cached on the SVG markup, so the card is only re-rendered when its content changes.
    """
    return resvg_py.svg_to_bytes(svg_string=svg, sans_serif_family="Liberation Sans")
