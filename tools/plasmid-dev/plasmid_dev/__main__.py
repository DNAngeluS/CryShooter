"""`python3 -m plasmid_dev` runs the dev runner (the same as the plas-dev launcher)."""
import sys

from .cli import main

sys.exit(main())
