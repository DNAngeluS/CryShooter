cmake_minimum_required(VERSION 3.14)
project(FirstPersonShooter)

set(CRYENGINE_DIR "$ENV{CRYENGINE_DIR}" CACHE STRING "CRYENGINE root directory.")
set(TOOLS_CMAKE_DIR "${CRYENGINE_DIR}/Tools/CMake")

set(PROJECT_BUILD 1)
set(PROJECT_DIR "${CMAKE_SOURCE_DIR}/../")

include("${TOOLS_CMAKE_DIR}/InitialSetup.cmake")
include("${TOOLS_CMAKE_DIR}/CommonOptions.cmake")

add_subdirectory("${CRYENGINE_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/CRYENGINE")

include("${TOOLS_CMAKE_DIR}/Configure.cmake")
# Configure.cmake clears OUTPUT_DIRECTORY_NAME after folding it into OUTPUT_DIRECTORY.
# Derive the bin subdir name from the fully-constructed OUTPUT_DIRECTORY instead.
get_filename_component(_bin_subdir "${OUTPUT_DIRECTORY}" NAME)
set(GAME_ENGINE_BIN_DIR "${CRYENGINE_DIR}/bin/${_bin_subdir}")

# plasmid-debug: debug kit, the vendored tag copy under tools/plasmid-debug (never edited here). To develop the kit itself,
# build against its working tree instead: cmake -DPLASMID_DEBUG_DIR=<Crytek>/Tools/plasmid-debug (then tag, re-vendor, rebuild).
if(NOT PLASMID_DEBUG_DIR)
    set(PLASMID_DEBUG_DIR "${CMAKE_SOURCE_DIR}/../tools/plasmid-debug")
endif()
include("${PLASMID_DEBUG_DIR}/cmake/PlasmidDebug.cmake")

start_sources()

sources_platform(ALL)
add_sources("GamePlugin_uber.cpp"
    PROJECTS GamePlugin
    SOURCE_GROUP "Root"
        "GamePlugin.cpp"
        "GamePlugin.h"
        "StdAfx.cpp"
        "StdAfx.h"
)

add_sources("Components_uber.cpp"
    PROJECTS GamePlugin
    SOURCE_GROUP "Components"
        "Components/Player.cpp"
        "Components/Player.h"
        "Components/SpawnPoint.cpp"
        "Components/SpawnPoint.h"
        "Components/Bullet.h"
)

add_sources("PlasmidDebug_uber.cpp"
    PROJECTS GamePlugin
    SOURCE_GROUP "PlasmidDebug"
        ${PLASMID_DEBUG_SOURCES}
)

end_sources()

CryEngineModule(GamePlugin PCH "StdAfx.cpp" SOLUTION_FOLDER "Project")

target_include_directories(${THIS_PROJECT} SYSTEM PRIVATE
    "${CRYENGINE_DIR}/Code/CryEngine/CryCommon"
    "${CRYENGINE_DIR}/Code/CryEngine/CryAction"
    "${CRYENGINE_DIR}/Code/CryEngine/CrySchematyc/Core/Interface"
    "${CRYENGINE_DIR}/Code/CryPlugins/CryDefaultEntities/Module"
)
target_include_directories(${THIS_PROJECT} PRIVATE "${PLASMID_DEBUG_INCLUDE_DIR}")

if(CMAKE_CXX_COMPILER_ID MATCHES "[Cc]lang")
    target_compile_options(${THIS_PROJECT} PRIVATE
        -Wno-unused-variable
        -Wno-reorder
        -Wno-unknown-pragmas
        -Wno-parentheses
        -Wno-switch
        -Wno-format
        -Wno-dynamic-class-memaccess
        -Wno-unused-private-field
        -Wno-unused-value
        -Wno-invalid-offsetof
        -Wno-multichar
        -Wno-char-subscripts
        -Wno-null-conversion
        -Wno-empty-body
        -Wno-unused-lambda-capture
        -Wno-unused-function
        -Wno-tautological-constant-out-of-range-compare
        # Clang 16+ warnings from CryEngine headers
        -Wno-deprecated-copy
        -Wno-mismatched-tags
    )
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(${THIS_PROJECT} PRIVATE
        -Wno-unused-function
        -Wno-unused-value
        -Wno-unused-variable
        -Wno-aligned-new
        -Wno-int-in-bool-context
        -Wno-invalid-offsetof
        -Wno-comment
        -Wno-sign-compare
        -Wno-unused-but-set-variable
        -Wno-maybe-uninitialized
        -Wno-misleading-indentation
        -Wno-unused-result
        -Wno-unknown-pragmas
        -Wno-multichar
        -Wno-strict-aliasing
        -Wno-char-subscripts
        -Wno-conversion-null
        -Wno-reorder
        -Wno-parentheses
        -Wno-format
        -Wno-switch
        -Wno-deprecated-declarations
        # GCC 10+ warnings from CryEngine headers
        $<$<VERSION_GREATER_EQUAL:${CMAKE_CXX_COMPILER_VERSION},10.0>:-Wno-deprecated-copy>
        $<$<VERSION_GREATER_EQUAL:${CMAKE_CXX_COMPILER_VERSION},10.0>:-Wno-mismatched-tags>
        $<$<VERSION_GREATER_EQUAL:${CMAKE_CXX_COMPILER_VERSION},10.0>:-Wno-redundant-tags>
        # GCC 12+ warnings from CryEngine headers
        $<$<VERSION_GREATER_EQUAL:${CMAKE_CXX_COMPILER_VERSION},12.0>:-Wno-array-parameter>
        $<$<VERSION_GREATER_EQUAL:${CMAKE_CXX_COMPILER_VERSION},12.0>:-Wno-dangling-pointer>
    )
endif()

add_library(GameLauncher STATIC "${CRYENGINE_DIR}/Code/CryEngine/CryCommon/CryCore/Platform/platform.h")
set_target_properties(GameLauncher PROPERTIES LINKER_LANGUAGE CXX)

# Copy the built plugin to the engine's bin dir so the engine can find it.
# On Linux, CryLoadLibrary resolves plugins relative to MODULE_PATH, which
# is set to the engine's bin dir (the CWD when GameLauncher starts).
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    add_custom_command(TARGET GamePlugin POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:GamePlugin>
            "${GAME_ENGINE_BIN_DIR}/$<TARGET_FILE_NAME:GamePlugin>"
        COMMENT "Deploying $<TARGET_FILE_NAME:GamePlugin> to ${GAME_ENGINE_BIN_DIR}"
    )
endif()
