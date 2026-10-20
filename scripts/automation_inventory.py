"""Print the read-only migration report; no browser/profile side effects.

Example: python scripts/automation_inventory.py --recipes-dir recipes --data-dir data
"""
import argparse
import json
from pathlib import Path

from chat2api.automation.inventory import inspect_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes-dir", type=Path, default=Path("recipes"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--flows-dir", type=Path)
    args = parser.parse_args()
    report = inspect_sources(args.recipes_dir, args.data_dir, flows_dir=args.flows_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
