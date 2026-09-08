"""Idempotent migration and deterministic inventory seeding; never resets stock."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pickmate.config import Settings
from pickmate.storage.database import Database
from pickmate.storage.seed import inventory

if __name__ == "__main__":
    cfg = Settings()
    asyncio.run(Database(cfg.database_path).initialize())
    Path("fixtures/inventory.json").write_text(
        json.dumps([i.model_dump() for i in inventory()], indent=2) + "\n"
    )
    print(f"Migrated and seeded {cfg.database_path}; existing quantities preserved.")
