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

Configuration is read from environment variables. The database and
[OIDC authentication settings](https://docs.streamlit.io/develop/concepts/connections/authentication) may also be set in
`.streamlit/secrets.toml`.

| Variable                 | Required                | Description                                                                                                                                         |
|--------------------------|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `EXCHANGE_RATES_API_KEY` | No                      | API key for [exchangeratesapi.io](https://exchangeratesapi.io), used to fetch the latest currency exchange rates daily.                             |
| `DATABASE_TYPE`          | No                      | `none` (the default, saving is disabled), `sqlite` or `mysql`. When a database is set, a "Save to database" button is shown at the end of the page. |
| `DATABASE_URL`           | When `mysql`            | Database to connect to, in the form `mysql://host[:port]/database`. The database must already exist; its tables are created on first use.           |
| `DATABASE_USERNAME`      | When `mysql`            | Username for the MySQL database.                                                                                                                    |
| `DATABASE_PASSWORD`      | When `mysql`            | Password for the MySQL database.                                                                                                                    |
| `DATABASE_SSL_CA`        | No                      | Path to a CA certificate file. When set, the MySQL connection is encrypted and the server's certificate is verified.                                |
| `AUTH_REDIRECT_URI`      | For OIDC authentication | The redirect URL for OIDC authentication. Should be the `BASE_URL/oauth2callback`.                                                                  |
| `COOKIE_SECRET`          | For OIDC authentication | A strong, randomly generated string. Needed for OIDC authentication.                                                                                |
| `GOOGLE_CLIENT_ID`       | Google authentication   | Google OIDC login client ID.                                                                                                                        |
| `GOOGLE_CLIENT_SECRET`   | Google authentication   | Google OIDC login client secret.                                                                                                                    |
| `GOOGLE_METADATA_URL`    | Google authentication   | Google OIDC login metadata url.                                                                                                                     |
| `MSFT_CLIENT_ID`         | Microsoft auth          | Microsoft OIDC login client ID.                                                                                                                     |
| `MSFT_CLIENT_SECRET`     | Microsoft auth          | Microsoft OIDC login client secret.                                                                                                                 |
| `MSFT_METADATA_URL`      | Microsoft auth          | Microsoft OIDC login metadata url.                                                                                                                  |
| `ADMIN_OWNER_EMAIL`      | Recommended for admin   | Email address allowed to become the admin owner. Without it, the first account to log in becomes the owner.                                         |

With `sqlite`, the database is created at `data/cost_of_knowledge.db`.

## Admin

To view the admin page, go to the `BASE_URL/admin` and login with a Google or Microsoft account. OIDC authentication
must be enabled by setting the relevant environment variables or setting the variables in `.streamlit/secrets.toml`.
The owner has admin access and can authorise other users who login to access the admin page. Set `ADMIN_OWNER_EMAIL` to
the owner's email address so that only an account with that verified email can become the owner. If it is not set, the
first account to login becomes the owner, so anyone who reaches `/admin` first on a new deployment could take
ownership.

The admin page displays all data collected by the tool where the user has consented.

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
