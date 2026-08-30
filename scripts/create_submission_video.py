"""Create the short submission demo video using macOS AVFoundation."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def create_video(output: Path, source_root: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        print("Video generation skipped: swiftc is not available on this host", file=sys.stderr)
        return 1
    source = source_root / "scripts" / "generate_demo_video.swift"
    compiler_output = Path("/tmp/releaseguard-demo-video")
    compile_result = subprocess.run(
        [swiftc, "-O", "-framework", "AVFoundation", "-framework", "CoreGraphics", "-framework", "CoreText", "-framework", "CoreVideo", "-o", str(compiler_output), str(source)],
        cwd=source_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if compile_result.returncode != 0:
        print("Video compilation failed:", file=sys.stderr)
        print(compile_result.stderr, file=sys.stderr)
        return compile_result.returncode
    run_result = subprocess.run([str(compiler_output), str(output)], cwd=source_root, check=False)
    return run_result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a ReleaseGuard submission demo video")
    parser.add_argument("--source-root", default=".")
    parser.add_argument("--out", default="submission/video/releaseguard_demo.mp4")
    args = parser.parse_args(argv)
    return create_video(Path(args.out).resolve(), Path(args.source_root).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
