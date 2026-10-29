"""Hand-written Schematyc entity-class script (ported from the P0(c) spike make_ent_fixture.py).

write_schematyc(out_dir, name, variant, mesh_file) writes <out_dir>/<name>.schematyc_ent and returns [that path].

Layout derived from the engine source, not from a sample: archive version 2 (CrySystem/Serialization/XmlOArchive.cpp,
scalars are attributes, structs are child nodes, containers hold <element> children); file = <CrySchematyc> with
version/guid/scope and a <root> Class that has one Base child pointing at the Entity env class
(IEntity::GetEntityScopeGUID(), be845278-0dd2-409f-b8be-97895607c256). Elements: ScriptSerializers.cpp, ScriptBase.cpp.
Run the game with +sys_SchematycPlugin 2; folders must not start with an underscore.

GUIDs come from uuid.uuid4() and are therefore different on every run (the spike behaves the same way).
"""

import os
import uuid

DEFAULT_MESH_FILE = "Objects/plasmid_test/uvquad.cgf"
ENTITY_ENV_CLASS = "be845278-0dd2-409f-b8be-97895607c256"
# OF-20: a ComponentInstance (Mesh, DefaultComponents StaticMeshComponent.h:51) as a sibling of Base under root. Layout from
# ScriptComponentInstance.cpp:97-122 (typeGUID + properties); FilePath is a GeomFileName (string). badtype = unknown typeGUID.
MESH_TYPE = "6DDD0033-6AAA-4B71-B8EA-108258205E29"
LIGHT_TYPE = "0A86908D-642F-4590-ACEF-484E8E39F31B"


def _g():
    return str(uuid.uuid4())


def build_xml(name="plasmid_probe", variant="ok", mesh_file=DEFAULT_MESH_FILE):
    """Return the .schematyc_ent text for a variant. Negative controls: truncated, badguid."""
    entity_env_class = ENTITY_ENV_CLASS
    if variant == "badguid":
        entity_env_class = "00000000-dead-beef-0000-000000000000"
    g = _g
    comp = ""
    if variant == "multi":  # enum property (Mesh Type=Collider: the engine then clears the slot render flag, BaseMeshComponent.h:202) + a second component (Point Light, float and bool properties)
        comp = f'''   <element elementType="ComponentInstance" guid="{g()}" name="Mesh" typeGUID="{MESH_TYPE}">
    <properties Type="Collider" FilePath="{mesh_file}"/>
   </element>
   <element elementType="ComponentInstance" guid="{g()}" name="Light" typeGUID="{LIGHT_TYPE}">
    <properties Radius="3" Active="true"/>
   </element>
'''
    if variant == "light":  # a lone Point Light (OF-23 test: does direct light lift the black normal-mapped quad?)
        comp = f'''   <element elementType="ComponentInstance" guid="{g()}" name="Light" typeGUID="{LIGHT_TYPE}">
    <properties Radius="8"/>
   </element>
'''
    if variant in ("mesh", "badtype"):
        tg = MESH_TYPE if variant == "mesh" else "00000000-dead-beef-0000-000000000001"
        comp = f'''   <element elementType="ComponentInstance" guid="{g()}" name="Mesh" typeGUID="{tg}">
    <properties FilePath="{mesh_file}"/>
   </element>
'''
    xml = f'''<CrySchematyc CryXmlVersion="2" version="105" guid="{g()}" scope="00000000-0000-0000-0000-000000000000">
 <root elementType="Class" guid="{g()}" name="{name}">
  <children>
   <element elementType="Base" guid="{g()}" name="Base">
    <classId domain="Env" guid="{entity_env_class}"/>
   </element>
{comp}  </children>
 </root>
</CrySchematyc>
'''
    if variant == "truncated":
        xml = xml[:len(xml) // 2]
    return xml


def write_schematyc(out_dir, name="plasmid_probe", variant="ok", mesh_file=DEFAULT_MESH_FILE):
    """Write <out_dir>/<name>.schematyc_ent for the given variant; return [path]."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name + ".schematyc_ent")
    xml = build_xml(name, variant, mesh_file)
    with open(path, "w") as f:
        f.write(xml)
    return [path]
