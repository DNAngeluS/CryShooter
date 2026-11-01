// Plasmid Debug public API. The host plugin's StdAfx.h must be on the include path (CryEngine module defines).
#pragma once

namespace Plasmid
{
namespace Debug
{
//! Registers the plasmid_debug_* commands and CVars with the engine console. Call once, from ESYSTEM_EVENT_GAME_POST_INIT.
//! Returns false if the console is unavailable. Calling it twice is a no-op.
bool Init();

//! Unregisters listeners. Call from ESYSTEM_EVENT_FULL_SHUTDOWN. Safe without Init.
void Shutdown();

const char* Version();
}
}
