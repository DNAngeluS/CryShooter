#!/usr/bin/env python3
"""Compat shim: the dev runner is the vendored cryengine-dev tooling in tools/cryengine-dev/ (see its README.md); this file only forwards so VS Code tasks, docs and muscle memory keep working."""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
runner = os.path.join(here, "cryengine-dev", "dev.py")
if not os.path.isfile(runner):
    sys.exit("dev.py shim: tools/cryengine-dev/dev.py is missing (vendor it: python3 <Crytek>/Tools/dev/vendor.py --project-dir .)")
os.execv(sys.executable, [sys.executable, runner, "--project-dir", os.path.dirname(here), *sys.argv[1:]])
