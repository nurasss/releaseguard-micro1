# metrics-exporter

Exports application metrics in Prometheus format.

## Testing

```bash
pytest
```

## Release build

```bash
python scripts/build_release.py
```

This bundles static assets and writes the distributable archive to `dist/`.
