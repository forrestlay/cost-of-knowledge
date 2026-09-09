# AGENTS.md

## Code style

- Use Python type hints where possible.
- In main.py, keep functions close to the relevant UI element.

## Workflow

- Astral uv should always be used to manage the Python project and packages, instead of pip and other tools.
- After changes, check if any variables would be affected by Streamlit's script behaviour and would need to be
  persisted. Prefer using st.session_state to persist variables where possible.
