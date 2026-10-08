"""Page describing the Cost of Knowledge Calculator, at BASE-URL/about.

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

import streamlit as st

from src.ui import CALCULATOR_PAGE

with st.sidebar:
    st.page_link(CALCULATOR_PAGE, icon=":material/calculate:")

st.title("About the Cost of Knowledge Calculator")
st.markdown(
    """
    Every journal article starts as public investment: researcher time, university resources, grant funding.
    By the time it reaches a publisher, more than 95% of the cost has typically already been paid <link to blog post>.

    This tool enables faculty to quantify the public and institutional investment that underpins their work
    (primarily in the form of their own labor) using a costing model described in this companion publication <link>
    — and to compare that with publisher investment. Through this comparison, this resource raises important
    questions about who contributes what, who controls the final publication, and who profits most <link to
    profitability report>.
    """
)

st.divider()
st.markdown(
    """
    :small[:material/copyright: Copyright 2026 Alam, Andrew, Baker, Coupe, Koh,
    Lay, Loh, and Tanima.
    :material/license: The content on this website is subject to the [Creative Commons Attribution 4.0
    International License](https://creativecommons.org/licenses/by/4.0/).]

    :small[[Privacy Policy](https://sparcopen.org/privacy-policy/) •
    [Github](https://github.com/forrestlay/cost-of-knowledge)]
    """,
    text_alignment="center",
)

if "tool_version" in st.session_state:
    st.markdown(f":small[Tool version: v{st.session_state['tool_version']}]", text_alignment="center")
