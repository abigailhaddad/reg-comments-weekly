"""Selection rules, models, prompts and settings, read from config/reg-comments-weekly.yaml (2026-11-28)."""
from pathlib import Path

import yaml

CONFIG = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "reg-comments-weekly.yaml")
                        .read_text(encoding="utf-8"))
