# toolbox-cli

A small command-line toolbox for text and number utilities.

## Installation

```bash
pip install -r requirements.lock
```

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and adjust as needed.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `TOOLBOX_API_KEY` | no | `""` | API key used for the optional remote lookup feature. |
| `TOOLBOX_LOG_LEVEL` | no | `INFO` | Python logging level for the CLI. |
| `TOOLBOX_TIMEOUT_SECONDS` | no | `30` | Network timeout in seconds for remote lookups. |

## Testing

```bash
pytest
```

## Release process

Tags of the form `vX.Y.Z` trigger the CI workflow, which runs the test suite before a release is published.
