set(CMAKE_CONFIGURATION_TYPES Debug Profile Release)
set(CMAKE_CONFIGURATION_TYPES "${CMAKE_CONFIGURATION_TYPES}" CACHE STRING "Reset the configurations to what we need" FORCE)

set(BUILD_CPU_ARCHITECTURE x64)
set(BUILD_PLATFORM Linux64)
set(LINUX TRUE)

# Configurable output directory.
# Default "linux_x64_gcc" deploys the plugin to the same bin dir as the
# GCC-compiled GameLauncher so it can be loaded immediately.
# Override to "linux_x64_clang" when building against a full Clang engine:
#   cmake ... -DCLANG_OUTPUT_DIR_NAME=linux_x64_clang
if(NOT DEFINED CLANG_OUTPUT_DIR_NAME)
    set(CLANG_OUTPUT_DIR_NAME "linux_x64_gcc")
endif()
set(OUTPUT_DIRECTORY_NAME "${CLANG_OUTPUT_DIR_NAME}")

if(NOT CMAKE_C_COMPILER)
    set(CMAKE_C_COMPILER clang)
endif()
if(NOT CMAKE_CXX_COMPILER)
    set(CMAKE_CXX_COMPILER clang++)
endif()

message(STATUS "CMAKE_C_COMPILER = ${CMAKE_C_COMPILER}")
message(STATUS "CMAKE_CXX_COMPILER = ${CMAKE_CXX_COMPILER}")
message(STATUS "OUTPUT_DIRECTORY_NAME = ${OUTPUT_DIRECTORY_NAME}")

# Resolve CRYENGINE_DIR and persist it in the CMake cache.
# Why FORCE: with cmake.useCMakePresets the preset evaluates $env{CRYENGINE_DIR}
# before VS Code applies cmake.environment, so it may arrive as "" in the cache.
# FORCE overwrites that empty value with the real path from the env var.
if(DEFINED CRYENGINE_DIR AND NOT CRYENGINE_DIR STREQUAL "")
    # Cache variable already has a good value — nothing to do.
elseif(DEFINED ENV{CRYENGINE_DIR} AND NOT "$ENV{CRYENGINE_DIR}" STREQUAL "")
    set(CRYENGINE_DIR "$ENV{CRYENGINE_DIR}" CACHE PATH "CRYENGINE root directory." FORCE)
else()
    message(FATAL_ERROR
        "CRYENGINE_DIR is not set.\n"
        "Options:\n"
        "  - Set cmake.environment.CRYENGINE_DIR in .vscode/settings.json\n"
        "  - Add CRYENGINE_DIR to cacheVariables in a CMakeUserPresets.json\n"
        "  - Export CRYENGINE_DIR in your shell profile (~/.zshrc or ~/.bashrc)")
endif()
set(_cry_cmake_dir "${CRYENGINE_DIR}/Tools/CMake")

if(EXISTS "${_cry_cmake_dir}/../linux_bootstrap")
    set(SDK_DIR "${_cry_cmake_dir}/../linux_bootstrap/Code/SDKs")
endif()

add_definitions(-DLINUX64)

include("${_cry_cmake_dir}/CRYENGINE-CLANG.cmake")

set(CMAKE_C_FLAGS   "${CMAKE_C_FLAGS}   -DLINUX -D__linux__" CACHE STRING "C Common Flags"   FORCE)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DLINUX -D__linux__" CACHE STRING "C++ Common Flags" FORCE)
