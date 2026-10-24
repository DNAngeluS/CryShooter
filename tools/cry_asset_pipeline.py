#!/usr/bin/env python3
"""
CRYENGINE asset pipeline for authored asset-graph driven generation.

Supports staged level generation, authored graphs, validation, publish, and mesh import jobs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from asset_pipeline.pipeline import AssetPipeline


def _print(data: dict) -> None:
    print(json.dumps(data, indent=2, sort_keys=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CRYENGINE authored asset pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-job", help="Create a staged asset job")
    create.add_argument("--kind", required=True, choices=["level", "mesh_import", "character_package"])
    create.add_argument("--prompt", required=True)
    create.add_argument("--target-package")
    create.add_argument("--source-input", action="append", default=[])
    create.add_argument("--capability", action="append", default=[])

    plan = sub.add_parser("plan-spec", help="Prepare prompt/capability/template authoring artifacts")
    plan.add_argument("--job", required=True)

    author = sub.add_parser("author-spec", help="Validate and store an authored asset_graph.json")
    author.add_argument("--job", required=True)
    author.add_argument("--json-file", required=True)

    edit = sub.add_parser("edit", help="Edit an existing job request or authored graph")
    edit.add_argument("--job", required=True)
    edit.add_argument("--prompt")
    edit.add_argument("--set", action="append", default=[], metavar="PATH=VALUE")
    edit.add_argument("--json-file")

    build = sub.add_parser("build", help="Build staged assets for a job")
    build.add_argument("--job", required=True)
    build.add_argument("--compile-mesh", action="store_true")
    build.add_argument("--cryengine-dir")

    validate = sub.add_parser("validate", help="Validate staged job outputs")
    validate.add_argument("--job", required=True)

    publish = sub.add_parser("publish", help="Publish validated assets into Assets/")
    publish.add_argument("--job", required=True)

    run = sub.add_parser("run", help="Create, plan, author, build, validate, and optionally publish a job")
    run.add_argument("--kind", required=True, choices=["level", "mesh_import", "character_package"])
    run.add_argument("--prompt", required=True)
    run.add_argument("--target-package")
    run.add_argument("--source-input", action="append", default=[])
    run.add_argument("--capability", action="append", default=[])
    run.add_argument("--asset-graph")
    run.add_argument("--publish", action="store_true")
    run.add_argument("--compile-mesh", action="store_true")
    run.add_argument("--cryengine-dir")

    convert = sub.add_parser("convert-mesh", help="Convenience wrapper for a mesh import job")
    convert.add_argument("--input", required=True)
    convert.add_argument("--target", required=True)
    convert.add_argument("--prompt", default="Import mesh into a CRYENGINE-compatible package")
    convert.add_argument("--compile", action="store_true")
    convert.add_argument("--cryengine-dir")
    convert.add_argument("--publish", action="store_true")

    fix = sub.add_parser("fix-terrain", help="Repair terrain/terrain.dat inside a level.pak written by the old writer (OF-09)")
    fix.add_argument("level", help="level folder (Assets/levels/<name>) or the level.pak path")
    fix.add_argument("--check", action="store_true", help="report what would change, write nothing")

    return parser


def _parse_set_args(items: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for item in items:
        if "=" not in item:
            raise SystemExit(f"Invalid --set value, expected PATH=VALUE: {item}")
        key, value = item.split("=", 1)
        pairs.append((key, value))
    return pairs


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    pipeline = AssetPipeline()

    if args.command == "create-job":
        _print(
            pipeline.create_job(
                args.kind,
                args.prompt,
                target_package=args.target_package,
                source_inputs=args.source_input,
                requested_capabilities=args.capability,
            )
        )
    elif args.command == "plan-spec":
        _print(pipeline.plan_spec(args.job))
    elif args.command == "author-spec":
        _print(pipeline.author_spec(args.job, json_file=args.json_file))
    elif args.command == "edit":
        merge_patch = None
        if args.json_file:
            merge_patch = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        _print(
            pipeline.edit_job(
                args.job,
                prompt=args.prompt,
                set_values=_parse_set_args(args.set),
                merge_patch=merge_patch,
            )
        )
    elif args.command == "build":
        _print(pipeline.build(args.job, compile_mesh=args.compile_mesh, cryengine_dir=args.cryengine_dir))
    elif args.command == "validate":
        _print(pipeline.validate(args.job))
    elif args.command == "publish":
        _print(pipeline.publish(args.job))
    elif args.command == "run":
        _print(
            pipeline.run(
                args.kind,
                args.prompt,
                target_package=args.target_package,
                source_inputs=args.source_input,
                requested_capabilities=args.capability,
                asset_graph_file=args.asset_graph,
                publish=args.publish,
                compile_mesh=args.compile_mesh,
                cryengine_dir=args.cryengine_dir,
            )
        )
    elif args.command == "fix-terrain":
        from asset_pipeline.procgen.terrain_dat_fix import fix_level_pak

        _print(fix_level_pak(Path(args.level), check_only=args.check))
    elif args.command == "convert-mesh":
        input_path = Path(args.input).resolve()
        _print(
            pipeline.run(
                "mesh_import",
                args.prompt,
                target_package=args.target,
                source_inputs=[str(input_path)],
                publish=args.publish,
                compile_mesh=args.compile,
                cryengine_dir=args.cryengine_dir,
            )
        )
    else:
        parser.error(f"Unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
