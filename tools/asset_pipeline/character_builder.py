from __future__ import annotations

import uuid
from pathlib import Path

from .common import write_text


def _cdf_xml(spec: dict, skeleton_file: str, skin_file: str) -> str:
    attachment_bone = spec.get("attachment_bone", "R_hand")
    return "\n".join(
        [
            "<CharacterDefinition>",
            f' <Model File="{skeleton_file}"/>',
            " <AttachmentList>",
            f'  <Attachment Type="CA_SKIN" AName="body_skin" Binding="{skin_file}" Flags="0"/>',
            f'  <Attachment Type="CA_BONE" AName="barrel_out" Position="1.0,0.0,1.5" Rotation="1,0,0,0" BoneName="{attachment_bone}" Flags="0"/>',
            " </AttachmentList>",
            "</CharacterDefinition>",
            "",
        ]
    )


def _controller_definition_xml(character_name: str, scope: str, default_fragment: str) -> str:
    return "\n".join(
        [
            "<ControllerDef>",
            " <Contexts>",
            f'  <Context name="{scope}" database="{character_name}FirstPerson.adb"/>',
            " </Contexts>",
            " <FragmentDefs>",
            f'  <Fragment name="{default_fragment}" scope="{scope}"/>',
            '  <Fragment name="Walk" scope="{scope}"/>'.format(scope=scope),
            " </FragmentDefs>",
            "</ControllerDef>",
            "",
        ]
    )


def _adb_xml(scope: str, default_fragment: str) -> str:
    return "\n".join(
        [
            "<AnimationDatabase>",
            " <FragmentList>",
            f'  <Fragment name="{default_fragment}" tags="" priority="0"/>',
            '  <Fragment name="Walk" tags="" priority="0"/>',
            " </FragmentList>",
            f' <ScopeList><Scope name="{scope}"/></ScopeList>',
            "</AnimationDatabase>",
            "",
        ]
    )


def build_first_person_character_package(stage_assets_root: Path, bundle_slug: str, node_id: str, spec: dict, source_output: dict) -> dict:
    character_dir = stage_assets_root / "Assets" / "Objects" / "Characters" / spec["character_name"]
    adb_dir = stage_assets_root / "Assets" / "Animations" / "Mannequin" / "ADB"
    character_dir.mkdir(parents=True, exist_ok=True)
    adb_dir.mkdir(parents=True, exist_ok=True)

    source_path = source_output["asset_path"]
    skeleton_file = spec["skeleton_file"]
    skin_file = spec["skin_file"]
    cdf_path = character_dir / "firstperson.cdf"
    adb_name = f'{spec["character_name"]}FirstPerson.adb'
    controller_name = f'{spec["character_name"]}FirstPersonControllerDefinition.xml'
    write_text(cdf_path, _cdf_xml(spec, skeleton_file, skin_file))
    write_text(adb_dir / adb_name, _adb_xml(spec["controller_scope"], spec["default_fragment"]))
    write_text(adb_dir / controller_name, _controller_definition_xml(spec["character_name"], spec["controller_scope"], spec["default_fragment"]))

    return {
        "node_id": node_id,
        "type": "character_fp_package",
        "status": "built",
        "asset_path": f"Objects/Characters/{spec['character_name']}/firstperson.cdf",
        "adb_path": f"Animations/Mannequin/ADB/{adb_name}",
        "controller_path": f"Animations/Mannequin/ADB/{controller_name}",
        "source_asset_path": source_path,
        "guid": str(uuid.uuid4()),
    }
