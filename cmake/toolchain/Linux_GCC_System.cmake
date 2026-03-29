# Local GCC toolchain for the FirstPersonShooter project.
# Self-contained: does not delegate to the engine's Linux_GCC.cmake so it is
# resilient to changes in the engine's toolchain directory layout.
# Mirrors the structure of Linux_Clang_System.cmake.

set(CMAKE_CONFIGURATION_TYPES Debug Profile Release)
set(CMAKE_CONFIGURATION_TYPES "${CMAKE_CONFIGURATION_TYPES}" CACHE STRING "Reset the configurations to what we need" FORCE)

set(BUILD_CPU_ARCHITECTURE x64)
set(BUILD_PLATFORM Linux64)
set(LINUX TRUE)
set(OUTPUT_DIRECTORY_NAME "linux_x64_gcc")

if(NOT CMAKE_C_COMPILER)
    set(CMAKE_C_COMPILER gcc-9)
endif()
if(NOT CMAKE_CXX_COMPILER)
    set(CMAKE_CXX_COMPILER g++-9)
endif()

message(STATUS "CMAKE_C_COMPILER   = ${CMAKE_C_COMPILER}")
message(STATUS "CMAKE_CXX_COMPILER = ${CMAKE_CXX_COMPILER}")

# Resolve CRYENGINE_DIR and persist it in the CMake cache.
#
# Priority:
#   1. Already set and non-empty in the CMake cache (e.g. from a previous run or
#      a CMakeUserPresets.json cacheVariable that resolved correctly).
#   2. CRYENGINE_DIR environment variable (set by cmake.environment in VS Code or
#      exported in the shell).
#
# Why FORCE: with cmake.useCMakePresets the preset evaluates $env{CRYENGINE_DIR}
# before VS Code applies cmake.environment, so the variable may arrive as an empty
# string in the cache.  FORCE overwrites that empty value with the real path.
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

include("${_cry_cmake_dir}/CRYENGINE-GCC.cmake")

set(CMAKE_C_FLAGS   "${CMAKE_C_FLAGS}   -DLINUX -D__linux__" CACHE STRING "C Common Flags"   FORCE)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DLINUX -D__linux__" CACHE STRING "C++ Common Flags" FORCE)
