"""Streamlit interface elements shared by the pages.

Copyright 2026 Nurul Alam, Ben Lay

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import html
from hashlib import sha1
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from collections.abc import Sequence

TOGGLETIP_BORDER = "color-mix(in srgb, currentColor 25%, transparent)"


def theme_color(option: str, light_default: str, dark_default: str) -> str:
    """Colour of a Streamlit theme option (e.g. "primaryColor") for the active light/dark theme.

    Streamlit does not expose its theme as CSS variables outside of custom components, so read it from the theme
    config instead: the [theme.light] / [theme.dark] section first, then [theme], then the given Streamlit default.
    The theme type is only inferred by Streamlit, so it can be wrong for the first run or just after a theme change.
    """
    theme_type = "dark" if st.context.theme.type == "dark" else "light"
    configured = st.get_option(f"theme.{theme_type}.{option}") or st.get_option(f"theme.{option}")
    return str(configured or (dark_default if theme_type == "dark" else light_default))


def primary_fill_styles() -> None:
    """Adds the CSS that keeps labels on primary-coloured fills (e.g. primary buttons) readable. Call it once per run.

    Streamlit always uses white for these labels, which is too faint on the dark theme's light orange primary colour,
    so in the dark theme they use the background colour instead.
    """
    if st.context.theme.type != "dark":
        return
    label_color = theme_color("backgroundColor", "#ffffff", "#0e1117")
    st.html(
        f"""
    <style>
    :is([data-testid^="stBaseButton-primary"], [data-testid^="stBaseLinkButton-primary"]),
    :is([data-testid^="stBaseButton-primary"], [data-testid^="stBaseLinkButton-primary"]) * {{
        color: {label_color} !important;
    }}
    </style>
    """
    )


def toggletip(trigger: str, tip: str, key: str | None = None) -> str:
    """Inline HTML for a toggletip: clicking `trigger` shows `tip`, clicking outside it (or pressing Esc) hides it.

    Uses the native HTML Popover API, so no JavaScript is needed. Embed the result in any
    st.markdown(..., unsafe_allow_html=True) string. `trigger` is trusted HTML, `tip` is escaped.

    Identical tips share an id unless given distinct `key`s, so pass one whenever the same tip appears more than once.
    """
    tip_id = f"tip-{sha1((key if key is not None else tip).encode()).hexdigest()[:8]}"
    # Each tip gets its own CSS anchor name so the popover is positioned next to its own trigger.
    return (
        f'<button type="button" class="toggletip-btn" popovertarget="{tip_id}" style="anchor-name: --{tip_id}">'
        f"{trigger}</button>"
        f'<span id="{tip_id}" popover class="toggletip" style="position-anchor: --{tip_id}">{html.escape(tip)}</span>'
    )


def toggletip_styles() -> None:
    """Adds the CSS of toggletips to the page. Call it once on each page that shows toggletips, before any are shown."""
    st.html(
        f"""
    <style>
    .toggletip-btn {{
        all: unset;
        cursor: pointer;
        color: {theme_color("primaryColor", "#ff4b4b", "#ff4b4b")};
    }}
    .toggletip {{
        max-width: 22rem;
        padding: 0.6rem 0.8rem;
        border-radius: 0.5rem;
        border: 1px solid {theme_color("borderColor", TOGGLETIP_BORDER, TOGGLETIP_BORDER)};
        background: {theme_color("secondaryBackgroundColor", "#f0f2f6", "#262730")};
        color: inherit;
        font: inherit;
        font-size: 0.875rem;
    }}
    /* Browsers without anchor positioning keep the default centred popover. */
    @supports (anchor-name: --a) {{
        .toggletip {{
            inset: auto;
            margin: 0.3rem 0 0;
            top: anchor(bottom);
            left: anchor(left);
            position-try-fallbacks: flip-block, flip-inline, flip-block flip-inline;
        }}
    }}
    </style>
    """
    )


# Streamlit's default categorical chart colours for the light and dark themes, which the charts give the phases in the
# order of RESEARCH_PHASES.
DEFAULT_CHART_COLORS: dict[str, list[str]] = {
    "light": ["#0068c9", "#83c9ff", "#ff2b2b", "#ffabab"],
    "dark": ["#83c9ff", "#0068c9", "#ffabab", "#ff2b2b"],
}
# Colour of the researchers' rows, which are not in the charts.
RESEARCHER_COLOR = "#8f6bc2"


def chart_colors() -> list[str]:
    """Categorical chart colours of the active theme, as the charts show them."""
    theme_type = "dark" if st.context.theme.type == "dark" else "light"
    configured = st.get_option(f"theme.{theme_type}.chartCategoricalColors") or st.get_option(
        "theme.chartCategoricalColors"
    )
    return list(configured or DEFAULT_CHART_COLORS[theme_type])


def colored_container_key(name: str, unique: str) -> str:
    """Key of a container coloured by `row_styles`. `name` is "researcher" or a phase key."""
    return f"row-{name}-{unique}"


def row_styles(phases: Sequence[str]) -> None:
    """Adds the CSS that colours the containers made with `colored_container_key`. Call it once per run, before any
    are shown.

    Each phase's rows use the colour of the phase in the charts as their border. The background and text are mixes of
    that colour with the page's white or black, so the text stays readable whatever the chart colour is.

    Args:
        phases: Phase keys, in the order the charts give them colours.
    """
    dark = st.context.theme.type == "dark"
    background_mix, text_mix = ("black", "white") if dark else ("white", "black")
    background_share, text_share = (28, 30) if dark else (16, 38)
    colors = chart_colors()
    row_colors = {"researcher": RESEARCHER_COLOR} | {phase: colors[i % len(colors)] for i, phase in enumerate(phases)}
    rules = "\n".join(
        f'[class*="st-key-row-{name}-"] {{ background-color: color-mix(in srgb, {color} {background_share}%, '
        f"{background_mix}) !important; border-color: {color} !important; "
        f"color: color-mix(in srgb, {color} {text_share}%, {text_mix}) !important; }}\n"
        f'[class*="st-key-row-{name}-"] :is(p, span, label, li) '
        f"{{ color: color-mix(in srgb, {color} {text_share}%, {text_mix}) !important; }}"
        for name, color in row_colors.items()
    )
    st.html(f"<style>\n{rules}\n</style>")
