# DataOps Event Manager

A Streamlit app for managing DataOps.live events via the Admin API.

## Features

- **List/Search Events** — Browse and search all events
- **View Event Details** — Full event configuration and account summary
- **Create Event** — Form-based event creation with validation
- **Patch Event** — Edit event fields with before/after diff
- **Decommission Account** — Search and decommission individual accounts

## Setup

### Local Development

1. Clone this repo
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in your values:
   ```bash
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```
4. Run the app:
   ```bash
   streamlit run app.py
   ```

### Streamlit Community Cloud

1. Fork/push this repo to a public GitHub repository
2. Deploy on [Streamlit Community Cloud](https://share.streamlit.io)
3. Add your secrets in the app settings (Settings → Secrets):
   - `APP_PASSWORD` — password to access the app
   - `DATAOPS_API_TOKEN` — your DataOps.live Bearer token

## Configuration

| Secret | Required | Description |
|--------|----------|-------------|
| `APP_PASSWORD` | Yes | Password gate for app access |
| `DATAOPS_API_TOKEN` | Yes | DataOps.live Admin API bearer token |
