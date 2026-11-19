"""Export Phase 1 DDL for review and CI drift validation."""

from pathlib import Path

from app.platform_ddl import render

if __name__ == "__main__":
    (Path(__file__).parent / "migrations/003_platform.sql").write_text(
        render(), encoding="utf-8"
    )
