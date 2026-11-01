// Extension of the engine's own console (IConsole): plasmid_debug_* commands, argument autocomplete, an optional extra key to open it.
#include "StdAfx.h"
#include "Console.h"
#include <plasmid/debug/Debug.h>

#include <CryInput/IInput.h>
#include <CrySystem/ConsoleRegistration.h>

#include <vector>

namespace Plasmid
{
namespace Debug
{
namespace
{
struct SCommandInfo
{
	const char* name;
	const char* help;
};
std::vector<SCommandInfo> g_commands;

void AddDebugCommand(const char* name, ConsoleCommandFunc func, const char* help)
{
	ConsoleRegistrationHelper::AddCommand(name, func, 0, help);
	g_commands.push_back({ name, help });
}

// Fixed list of values offered by TAB after a command name.
class CValueList final : public IConsoleArgumentAutoComplete
{
public:
	explicit CValueList(std::vector<const char*> values) : m_values(std::move(values)) {}
	int GetCount() const override { return (int)m_values.size(); }
	const char* GetValue(int i) const override { return m_values[i]; }

private:
	std::vector<const char*> m_values;
};
CValueList g_consoleValues({ "0", "1", "toggle" });
CValueList g_keylogValues({ "0", "1" });

bool g_keylog = false;
ICVar* g_pConsoleKey = nullptr;

// Logs key events (plasmid_debug_keylog) and opens/closes the engine console on plasmid_debug_console_key, for layouts where the tilde key
// does not reach the engine.
class CKeyListener final : public IInputEventListener
{
public:
	bool OnInputEvent(const SInputEvent& event) override
	{
		if (g_keylog && event.deviceType == eIDT_Keyboard && event.state == eIS_Pressed)
			CryLogAlways("[plasmid:debug] key '%s' id=%d modifiers=%d console=%d", event.keyName.c_str(), (int)event.keyId, event.modifiers, (int)gEnv->pConsole->GetStatus());

		if (g_pConsoleKey && event.deviceType == eIDT_Keyboard && event.state == eIS_Pressed)
		{
			const char* key = g_pConsoleKey->GetString();
			if (key[0] != '\0' && strcmp(key, event.keyName.c_str()) == 0)
			{
				gEnv->pConsole->ShowConsole(!gEnv->pConsole->GetStatus());
				return true;
			}
		}
		return false;
	}
	// Run before the game's own listeners so a bound key is not also consumed as gameplay input.
	int GetPriority() const override { return 1000; }
};
CKeyListener g_keyListener;
bool g_listenerAdded = false;

void HelpCommand(IConsoleCmdArgs*)
{
	CryLogAlways("[plasmid:debug %s] commands:", Version());
	for (const SCommandInfo& c : g_commands)
		CryLogAlways("  %s - %s", c.name, c.help);
	CryLogAlways("[plasmid:debug] CVar plasmid_debug_console_key=<key name> adds a key that opens the console; plasmid_debug_keylog 1 prints key names.");
}

void ConsoleCommand(IConsoleCmdArgs* pArgs)
{
	const bool open = gEnv->pConsole->GetStatus();
	bool want = !open;
	if (pArgs->GetArgCount() > 1 && strcmp(pArgs->GetArg(1), "toggle") != 0)
		want = atoi(pArgs->GetArg(1)) != 0;
	gEnv->pConsole->ShowConsole(want);
	CryLogAlways("[plasmid:debug] console %s", want ? "open" : "closed");
}

void KeylogCommand(IConsoleCmdArgs* pArgs)
{
	g_keylog = pArgs->GetArgCount() > 1 ? atoi(pArgs->GetArg(1)) != 0 : !g_keylog;
	CryLogAlways("[plasmid:debug] key log %s", g_keylog ? "on" : "off");
}

void PingCommand(IConsoleCmdArgs* pArgs)
{
	CryLogAlways("[plasmid:debug] pong (console open: %d, args: %d)", (int)gEnv->pConsole->GetStatus(), pArgs->GetArgCount() - 1);
}
}

bool Console::Init()
{
	IConsole* pConsole = gEnv->pConsole;
	AddDebugCommand("plasmid_debug_help", HelpCommand, "List the plasmid_debug commands.");
	AddDebugCommand("plasmid_debug_ping", PingCommand, "Log a reply; proves the plasmid_debug commands are registered.");
	AddDebugCommand("plasmid_debug_console", ConsoleCommand, "Open/close the engine console: 0, 1 or toggle (default toggle).");
	AddDebugCommand("plasmid_debug_keylog", KeylogCommand, "Log the engine name of every key pressed: 0 or 1.");
	g_pConsoleKey = ConsoleRegistrationHelper::RegisterString("plasmid_debug_console_key", "", VF_NULL,
	                                         "Engine key name (see plasmid_debug_keylog) that also toggles the console, e.g. f1. Empty disables.");
	pConsole->RegisterAutoComplete("plasmid_debug_console", &g_consoleValues);
	pConsole->RegisterAutoComplete("plasmid_debug_keylog", &g_keylogValues);

	if (gEnv->pInput)
	{
		gEnv->pInput->AddEventListener(&g_keyListener);
		g_listenerAdded = true;
	}
	return true;
}

void Console::Shutdown()
{
	if (g_listenerAdded && gEnv && gEnv->pInput)
		gEnv->pInput->RemoveEventListener(&g_keyListener);
	g_listenerAdded = false;
	if (gEnv && gEnv->pConsole)
	{
		gEnv->pConsole->UnRegisterAutoComplete("plasmid_debug_console");
		gEnv->pConsole->UnRegisterAutoComplete("plasmid_debug_keylog");
	}
}
}
}
