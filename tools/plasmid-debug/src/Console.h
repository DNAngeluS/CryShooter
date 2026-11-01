#pragma once

namespace Plasmid
{
namespace Debug
{
// Extension of the engine console (IConsole). Internal to the kit; not part of the public API.
class Console
{
public:
	static bool Init();
	static void Shutdown();
};
}
}
