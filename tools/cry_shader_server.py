#!/usr/bin/env python3
"""Compat shim: the shader compiler server is vendored in tools/cryengine-dev/cry_shader_server.py (kept here for .vscode/tasks.json)."""
import os
import sys

real = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cryengine-dev", "cry_shader_server.py")
if not os.path.isfile(real):
    sys.exit("cry_shader_server shim: tools/cryengine-dev/cry_shader_server.py is missing (re-vendor the tooling)")
os.execv(sys.executable, [sys.executable, real, *sys.argv[1:]])
