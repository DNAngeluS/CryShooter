# Local wrapper around the engine's Linux GCC toolchain.
# Resolves CRYENGINE_DIR from the CMake cache (set via -DCRYENGINE_DIR=... or
# cmake.configureSettings in VS Code) or from the CRYENGINE_DIR environment
# variable (set in shell profile or via cmake.environment in VS Code).

if(NOT CRYENGINE_DIR)
    if(DEFINED ENV{CRYENGINE_DIR})
        set(CRYENGINE_DIR "$ENV{CRYENGINE_DIR}" CACHE PATH "CRYENGINE root directory.")
    else()
        message(FATAL_ERROR
            "CRYENGINE_DIR is not set.\n"
            "Either:\n"
            "  - Pass -DCRYENGINE_DIR=<path> on the cmake command line\n"
            "  - Set cryengineDir in .vscode/settings.json (cmake.configureSettings handles the rest)\n"
            "  - Export CRYENGINE_DIR in your shell profile (~/.zshrc or ~/.bashrc)")
    endif()
endif()

include("${CRYENGINE_DIR}/Tools/CMake/toolchain/linux/Linux_GCC.cmake")
