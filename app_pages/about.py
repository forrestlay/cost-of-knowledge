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
st.markdown("About the Cost of Knowledge Calculator.")
