# Cost of Knowledge Visualisation Tool

The Cost of Knowledge Visualisation Tool, allows an academic to estimate the total cost of producing
and publishing an academic research article.

This repository is part of the Cost of Knowledge research project conducted by academics from The University of Sydney
School of Accounting, Governance and Regulation in collaboration with [SPARC](https://sparcopen.org).
Cost of Knowledge Project Team: Nurul Alam, Jane Andrew, Max BAker, Janine Coupe, Tai-Joo Koh, Ben Lay,
Chang-yuan Loh, Farzana Tanima
Primary tool contributors: Nurul Alam, Ben Lay

## Tool details

The Cost of Knowledge Tool is developed using [Streamlit](https://streamlit.io), and requires Python 3.14 or greater
to run.

## Testing the tool

Running this streamlit application is best done with [Astral UV](https://github.com/astral-sh/uv). To run the streamlit
app locally, use `uv run streamlit run ./main.py` in the terminal.

## Deploying the tool

This tool can be deployed as a Docker image, run `docker build -t streamlit` to build the image.

This tool uses the [exchangeratesapi.io API](https://exchangeratesapi.io) to fetch the latest currency exchange rates
daily. Pass an API key as an `EXCHANGE_RATES_API_KEY` environment variable to enable this.

Calculator inputs can be saved to a database by setting `DATABASE_TYPE` in `.streamlit/secrets.toml` or as an
environment variable. It may be `none` (the default, saving is disabled), `sqlite` or `mysql`. When a database is set, a
"Save to database" button is shown at the end of the page.

- `sqlite` creates the database at `data/cost_of_knowledge.db`.
- `mysql` connects to the database set by `DATABASE_URL`, in the form `mysql://host[:port]/database`, with the
  `DATABASE_USERNAME` and `DATABASE_PASSWORD` settings, which are also read from `.streamlit/secrets.toml` or environment
  variables. The database must already exist, and its tables are created on first use.

## Attributions

Country data and flag assets sourced from [lipis/flag-icons](https://github.com/lipis/flag-icons).

## LLM Use Disclosure

LLMs were used to assist with the coding of this tool. Specifically, LLMs were used to generate the initial proof of
concept, which was used as the basis for manual development of the tool, before LLM assistant was used again to
implement certain features (beginning with commit 8cfd02835d2c14a01154de5b1352fc696af23bb7).

## License

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
