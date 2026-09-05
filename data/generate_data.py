"""Regenerate the committed sample dataset.

Usage (from the project root):

    python data/generate_data.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import DATABASE_PATH  # noqa: E402
from src.data_generation import generate_dataset  # noqa: E402


def main() -> None:
    counts = generate_dataset(DATABASE_PATH, force=True)
    print(f"Regenerated {DATABASE_PATH}")
    print(
        "stores={stores} products={products} sales={sales} inventory={inventory}".format(**counts)
    )


if __name__ == "__main__":
    main()