"""`python -m dev_updater` のエントリポイント。"""

import sys

from .updater import main_cli

if __name__ == "__main__":
    sys.exit(main_cli())
