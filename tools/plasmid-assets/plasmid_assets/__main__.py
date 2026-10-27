import sys

from .cli import main

if __name__ == "__main__":  # guard: multiprocessing re-imports the main module in spawned workers
    sys.exit(main())
