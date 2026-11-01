# Include from the host plugin's CMakeLists.txt after Configure.cmake:
#   set(PLASMID_DEBUG_DIR "${CMAKE_SOURCE_DIR}/../tools/plasmid-debug")
#   include("${PLASMID_DEBUG_DIR}/cmake/PlasmidDebug.cmake")
# then, inside start_sources()/end_sources():
#   add_sources("PlasmidDebug_uber.cpp" PROJECTS <Module> SOURCE_GROUP "PlasmidDebug" ${PLASMID_DEBUG_SOURCES})
# and add ${PLASMID_DEBUG_INCLUDE_DIR} to the module's target_include_directories.
# PLASMID_DEBUG_SOURCES are relative to the including CMakeLists.txt, which is what add_sources() expects.
get_filename_component(_plasmid_debug_root "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(PLASMID_DEBUG_INCLUDE_DIR "${_plasmid_debug_root}/include")
set(PLASMID_DEBUG_SOURCES)
foreach(_f src/Debug.cpp src/Console.cpp src/Console.h)
    file(RELATIVE_PATH _rel "${CMAKE_CURRENT_SOURCE_DIR}" "${_plasmid_debug_root}/${_f}")
    list(APPEND PLASMID_DEBUG_SOURCES "${_rel}")
endforeach()
