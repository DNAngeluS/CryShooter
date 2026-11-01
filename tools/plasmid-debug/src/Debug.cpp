#include "StdAfx.h"
#include <plasmid/debug/Debug.h>
#include "Console.h"

namespace Plasmid
{
namespace Debug
{
namespace
{
bool g_initialised = false;
}

bool Init()
{
	if (g_initialised)
		return true;
	if (!gEnv || !gEnv->pConsole)
		return false;
	g_initialised = Console::Init();
	return g_initialised;
}

void Shutdown()
{
	if (!g_initialised)
		return;
	Console::Shutdown();
	g_initialised = false;
}

const char* Version()
{
	return "0.1.0";
}
}
}
