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

import streamlit as st

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


def toggletip(trigger: str, tip: str) -> str:
    """Inline HTML for a toggletip: clicking `trigger` shows `tip`, clicking outside it (or pressing Esc) hides it.

    Uses the native HTML Popover API, so no JavaScript is needed. Embed the result in any
    st.markdown(..., unsafe_allow_html=True) string. `trigger` is trusted HTML, `tip` is escaped.
    """
    tip_id = f"tip-{sha1(tip.encode()).hexdigest()[:8]}"
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
