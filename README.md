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

Configuration is read from environment variables listed below. The database and
[OIDC authentication settings](https://docs.streamlit.io/develop/concepts/connections/authentication) may also be set in
`.streamlit/secrets.toml`, refer to the linked Streamlit documentation for the format of secrets.toml.

| Variable                 | Required                | Description                                                                                                                                         |
|--------------------------|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `EXCHANGE_RATES_API_KEY` | No                      | API key for [exchangeratesapi.io](https://exchangeratesapi.io), used to fetch the latest currency exchange rates daily.                             |
| `DATABASE_TYPE`          | No                      | `none` (the default, saving is disabled), `sqlite` or `mysql`. When a database is set, a "Save to database" button is shown at the end of the page. |
| `DATABASE_URL`           | When `mysql`            | Database to connect to, in the form `mysql://host[:port]/database`. The database must already exist; its tables are created on first use.           |
| `DATABASE_USERNAME`      | When `mysql`            | Username for the MySQL database.                                                                                                                    |
| `DATABASE_PASSWORD`      | When `mysql`            | Password for the MySQL database.                                                                                                                    |
| `DATABASE_SSL_CA`        | No                      | Contents of the CA certificate (PEM), not a file path. Encrypts and verifies the MySQL connection. See below.                                       |
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

### MySQL SSL certificate

`DATABASE_SSL_CA` is the certificate itself (the full `-----BEGIN CERTIFICATE-----` ... `-----END CERTIFICATE-----`
text). In `secrets.toml`, use a multi-line string:

```toml
DATABASE_SSL_CA = """
-----BEGIN CERTIFICATE-----
...
-----END CERTIFICATE-----
"""
```

If `DATABASE_SSL_CA` is not set, the app looks for the certificate in `.streamlit/database_ca.pem` and uses it if the
file exists. If neither is present, the MySQL connection is not encrypted. When a certificate is used, the server's
certificate and hostname are verified against it.

### Running the Docker image

```shell
docker run -d \
  --name cost-of-knowledge \
  -p 8501:8501 \
  -v "$(pwd)/.streamlit:/app/.streamlit:ro" \
  -e EXCHANGE_RATES_API_KEY=your_api_key \
  ghcr.io/forrestlay/paper-cost-simulator:latest
```

In PowerShell, replace `$(pwd)` with `${PWD}`, and use a backtick (`` ` ``) instead of `\` for line continuation.

To use `sqlite` for saving, also set `-e DATABASE_TYPE=sqlite` and mount a volume at `/app/data` so the database
persists when the container is recreated, e.g. `-v costofknowledge/data:/app/data`.

The app is then available at <http://localhost:8501>.

Each time the container starts, it runs any database migrations the configured database needs (`src/migrate.py`)
before starting the app. Outside Docker, run them with `uv run python -m src.migrate`.

To provide a `secrets.toml`, create a `.streamlit` directory on the host containing a `secrets.toml` file, and mount it
at `/app/.streamlit`. Mounting it read-only (`:ro`) is recommended. Streamlit reads `secrets.toml` from this directory
at startup.

```text
.streamlit/
└── secrets.toml
```

### Docker Compose

Create a `compose.yaml`:

```yaml
services:
  cost-of-knowledge:
    image: ghcr.io/forrestlay/cost-of-knowledge:latest
    ports:
      - "8501:8501"
    environment:
      EXCHANGE_RATES_API_KEY: your_api_key
      DATABASE_TYPE: sqlite
    volumes:
      # Directory containing secrets.toml
      - ./costofknowledge/.streamlit:/app/.streamlit:ro
      # Persist the sqlite database
      - cost-of-knowledge-data:/app/data
    restart: unless-stopped

volumes:
  cost-of-knowledge-data:
```

Then start the service with `docker compose up -d`, and stop it with `docker compose down`.

Environment variables can be omitted when the equivalent settings are provided in `secrets.toml`. Do not commit
`secrets.toml` or API keys to version control.

### Manual Docker build

To manually build a Docker image for deployment, run `docker build -t streamlit`.

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
