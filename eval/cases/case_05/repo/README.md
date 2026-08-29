# notifier-service

Sends email notifications for account events.

## Configuration

Copy `.env.example` to `.env` and adjust as needed.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SMTP_PORT` | no | `587` | Port used to connect to the SMTP relay. |
| `LOG_LEVEL` | no | `INFO` | Python logging level for the service. |
| `API_TIMEOUT_SECONDS` | no | `30` | Timeout in seconds for outbound API calls. |

## Testing

```bash
pytest
```
