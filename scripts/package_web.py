"""Package Linux Next.js standalone output without local environment files."""

import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path


def package() -> None:
    if sys.platform != "linux":
        raise RuntimeError(
            "Build the deployable web bundle on Linux; Windows native modules are not portable"
        )
    root = Path(__file__).resolve().parents[1]
    source = root / "apps/web/.next/standalone"
    output = root / ".phase1-api/web-build"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "web.zip"
    if not (source / "apps/web/server.js").is_file():
        raise RuntimeError("Next.js standalone server is missing")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for directory, folders, files in os.walk(source, followlinks=False):
            parent = Path(directory)
            for name in [*folders, *files]:
                path = parent / name
                relative = path.relative_to(source)
                if any(
                    part.startswith(".env") or part in {".aws", ".git"}
                    for part in relative.parts
                ):
                    continue
                if path.is_symlink():
                    target = os.readlink(path)
                    if Path(target).is_absolute() or not path.resolve().is_relative_to(
                        source.resolve()
                    ):
                        raise ValueError(
                            "Standalone symlink escapes the deployment root"
                        )
                    entry = zipfile.ZipInfo(relative.as_posix())
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                    bundle.writestr(entry, target)
                elif path.is_file():
                    bundle.write(path, relative.as_posix())
        bundle.write(root / "apps/web/deployment/index.cjs", "index.cjs")
        static = root / "apps/web/.next/static"
        for path in static.rglob("*"):
            if path.is_file():
                bundle.write(
                    path, "apps/web/.next/static/" + path.relative_to(static).as_posix()
                )
        public = root / "apps/web/public"
        if public.exists():
            for path in public.rglob("*"):
                if path.is_file():
                    bundle.write(
                        path, "apps/web/public/" + path.relative_to(public).as_posix()
                    )
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {
        "sha256": digest,
        "bytes": archive.stat().st_size,
        "platform": "linux",
        "environment_files_included": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    package()
