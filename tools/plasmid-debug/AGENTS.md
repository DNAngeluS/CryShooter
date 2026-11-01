# plasmid-debug — Agent Instructions

This repo is self-contained: its rules are in this file, `README.md` and `CHANGELOG.md`. Nothing outside this directory
is required to work on it.

Scope: C++ debug kit for CRYENGINE 5.6 game plugins (console extension, render views, screenshots, debug menu, pause, free
camera, camera locks, sky/weather debugging) plus an optional Python Remote Console client. Liftable: no references to a host
project, no files outside this directory, no engine edits. Every change needs a `VERSION` bump, a `CHANGELOG.md` entry and a git
tag `vX.Y.Z`; projects use a tagged vendored copy and never edit it.

Read `README.md` and `CHANGELOG.md` first.
Engine facts: extend `IConsole` (`CryCommon/CrySystem/IConsole.h`); do not build a parallel console.
