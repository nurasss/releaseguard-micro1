"""Release build entry point.

Bundles static assets before packaging. This imports packaging_utils,
which does not exist anywhere in the repository, so the build fails
immediately with ModuleNotFoundError.
"""

from __future__ import annotations

from metrics_exporter.packaging_utils import bundle_assets


def main() -> None:
    bundle_assets(output_dir="dist")


if __name__ == "__main__":
    main()
