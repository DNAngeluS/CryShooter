#include "StdAfx.h"
#include "GamePlugin.h"

#include "Components/Player.h"

#include <CrySchematyc/Env/IEnvRegistry.h>
#include <CrySchematyc/Env/EnvPackage.h>
#include <CrySchematyc/Utils/SharedString.h>

#include <IGameObjectSystem.h>
#include <IGameObject.h>
#include <CrySystem/ICmdLine.h>
#include <CrySystem/ConsoleRegistration.h>

// Included only once per DLL module.
#include <CryCore/Platform/platform_impl.inl>

namespace
{
	constexpr const char *kDefaultStartupLevel = "fps_forest_basin";
}

static void GotoCommand(IConsoleCmdArgs *pArgs)
{
	// With no arguments: log current player position/angle so it can be pasted back
	// as "goto x y z yaw pitch" in the console. This is what the engine calls after
	// every screenshot (DriverD3D.cpp) to record the camera location in the log.
	if (pArgs->GetArgCount() == 1)
	{
		if (IEntity *pPlayer = gEnv->pEntitySystem->GetEntity(LOCAL_PLAYER_ENTITY_ID))
		{
			const Vec3 pos = pPlayer->GetWorldPos();
			const Ang3 ang(pPlayer->GetWorldRotation());
			CryLog("goto %.2f %.2f %.2f %.2f %.2f 0",
						 pos.x, pos.y, pos.z,
						 RAD2DEG(ang.z), RAD2DEG(ang.x));
		}
		return;
	}

	// With arguments: teleport the local player to the given position/angle.
	// Usage: goto x y z [yaw [pitch]]
	if (pArgs->GetArgCount() >= 4)
	{
		if (IEntity *pPlayer = gEnv->pEntitySystem->GetEntity(LOCAL_PLAYER_ENTITY_ID))
		{
			Vec3 pos(
					(float)atof(pArgs->GetArg(1)),
					(float)atof(pArgs->GetArg(2)),
					(float)atof(pArgs->GetArg(3)));

			Ang3 ang(0.f, 0.f, 0.f);
			if (pArgs->GetArgCount() >= 5)
				ang.z = DEG2RAD((float)atof(pArgs->GetArg(4)));
			if (pArgs->GetArgCount() >= 6)
				ang.x = DEG2RAD((float)atof(pArgs->GetArg(5)));

			pPlayer->SetWorldTM(Matrix34::Create(Vec3(1.f), Quat(ang), pos));

			// The player rebuilds its orientation from its own look state every frame, so set that too
			if (CPlayerComponent *pPlayerComp = pPlayer->GetComponent<CPlayerComponent>())
				pPlayerComp->SetLookAngles(RAD2DEG(ang.z), RAD2DEG(ang.x));
		}
	}
}

static void ScreenshotCommand(IConsoleCmdArgs* pArgs)
{
	if (pArgs->GetArgCount() > 2)
	{
		CryLog("Usage: fps_screenshot [absolute_path]");
		return;
	}

	const char* path = pArgs->GetArgCount() == 2 ? pArgs->GetArg(1) : nullptr;
	if (CGamePlugin* pPlugin = CGamePlugin::GetInstance())
	{
		pPlugin->IterateOverPlayers([path](CPlayerComponent& player)
		{
			if (player.IsLocalClient())
				player.RequestDebugScreenshot(path);
		});
	}
}

static void ApplyLaunchCVar(const char* name)
{
	if (const ICmdLineArg* pArg = gEnv->pSystem->GetICmdLine()->FindArg(eCLAT_Post, name))
	{
		if (ICVar* pCVar = gEnv->pConsole->GetCVar(name))
			pCVar->Set(pArg->GetValue());
	}
}

CGamePlugin::~CGamePlugin()
{
	// Remove any registered listeners before 'this' becomes invalid
	if (gEnv->pGameFramework != nullptr)
	{
		gEnv->pGameFramework->RemoveNetworkedClientListener(*this);
	}

	gEnv->pSystem->GetISystemEventDispatcher()->RemoveListener(this);

	if (gEnv->pSchematyc)
	{
		gEnv->pSchematyc->GetEnvRegistry().DeregisterPackage(CGamePlugin::GetCID());
	}
}

bool CGamePlugin::Initialize(SSystemGlobalEnvironment &env, const SSystemInitParams &initParams)
{
	// Register for engine system events, in our case we need ESYSTEM_EVENT_GAME_POST_INIT to load the map
	gEnv->pSystem->GetISystemEventDispatcher()->RegisterListener(this, "CGamePlugin");

	// Register the "goto" console command. The engine's ScreenShot() (DriverD3D.cpp)
	// always executes "goto" after taking a screenshot to log the camera position.
	// Without this registration the launcher prints "Unknown command: goto" every time.
	REGISTER_COMMAND("goto", GotoCommand, 0,
									 "With no args: log current player position/angle. "
									 "With args (x y z [yaw [pitch]]): teleport local player.");
	REGISTER_COMMAND("fps_screenshot", ScreenshotCommand, 0,
									 "Capture a JPEG to the default path or an absolute .jpg path.");
	REGISTER_FLOAT("fps_autoshot_after_s", 0.f, VF_NULL,
							 "Capture once this many seconds after the local player is ready; 0 disables it.");
	REGISTER_STRING("fps_autoshot_path", "", VF_NULL,
							 "Absolute .jpg path for fps_autoshot_after_s; empty uses the default path.");
	REGISTER_STRING("fps_autoshot_cmd", "", VF_NULL,
							 "Console command run once just before the fps_autoshot_after_s capture (e.g. \"goto x y z yaw pitch\"), followed by a 2 s settle delay.");
	ApplyLaunchCVar("fps_autoshot_after_s");
	ApplyLaunchCVar("fps_autoshot_path");
	ApplyLaunchCVar("fps_autoshot_cmd");
	REGISTER_STRING("fps_startup_level", "", VF_NULL,
							 "Level to load at startup (name under Assets/levels); empty or a level that does not exist falls back to fps_forest_basin.");
	ApplyLaunchCVar("fps_startup_level");

	return true;
}

void CGamePlugin::OnSystemEvent(ESystemEvent event, UINT_PTR wparam, UINT_PTR lparam)
{
	switch (event)
	{
	// Called when the game framework has initialized and we are ready for game logic to start
	case ESYSTEM_EVENT_GAME_POST_INIT:
	{
		// Listen for client connection events, in order to create the local player
		if (gEnv->pGameFramework != nullptr)
		{
			gEnv->pGameFramework->AddNetworkedClientListener(*this);
		}

		// Don't need to load the map in editor
		if (!gEnv->IsEditor())
		{
			// Load the level chosen with +fps_startup_level, or the default gameplay test map if unset or missing.
			const char *levelName = kDefaultStartupLevel;
			if (ICVar *pStartupLevel = gEnv->pConsole->GetCVar("fps_startup_level"))
			{
				const char *requestedLevel = pStartupLevel->GetString();
				if (requestedLevel[0] != '\0')
				{
					string levelFile;
					levelFile.Format("levels/%s/%s.level", requestedLevel, requestedLevel);
					if (gEnv->pCryPak->IsFileExist(levelFile.c_str()))
						levelName = requestedLevel;
					else
						CryLogAlways("fps_startup_level '%s' does not exist, using %s", requestedLevel, kDefaultStartupLevel);
				}
			}
			CryLogAlways("Startup level: %s", levelName);

			// Load the chosen map in client-server mode.
			string mapCommand;
			mapCommand.Format("map %s s", levelName);
			gEnv->pConsole->ExecuteString(mapCommand.c_str(), false, true);
		}
	}
	break;

	case ESYSTEM_EVENT_REGISTER_SCHEMATYC_ENV:
	{
		// Register all components that belong to this plug-in
		auto staticAutoRegisterLambda = [](Schematyc::IEnvRegistrar &registrar)
		{
			// Call all static callback registered with the CRY_STATIC_AUTO_REGISTER_WITH_PARAM
			Detail::CStaticAutoRegistrar<Schematyc::IEnvRegistrar &>::InvokeStaticCallbacks(registrar);
		};

		if (gEnv->pSchematyc)
		{
			gEnv->pSchematyc->GetEnvRegistry().RegisterPackage(
					stl::make_unique<Schematyc::CEnvPackage>(
							CGamePlugin::GetCID(),
							"EntityComponents",
							"Crytek GmbH",
							"Components",
							staticAutoRegisterLambda));
		}
	}
	break;

	case ESYSTEM_EVENT_LEVEL_LOAD_END:
	{
		// Disable ocean surface and its bottom quad — they sit coplanar with the
		// terrain surface and cause z-fighting even when the water level is low.
		gEnv->pConsole->ExecuteString("e_WaterOcean 0", false, true);
		gEnv->pConsole->ExecuteString("e_WaterOceanBottom 0", false, true);

		// Tighten terrain LOD error and extend the fine-mesh radius so sector
		// seams don't produce near-coplanar triangles at any visible distance.
		// Defaults: ErrorRatio=0.05, DistanceRatio=0.5
		gEnv->pConsole->ExecuteString("e_TerrainLodErrorRatio 0.001", false, true);
		gEnv->pConsole->ExecuteString("e_TerrainLodDistanceRatio 4.0", false, true);

		// Do NOT set e_TerrainAutoGenerateBaseTexture 1 here.
		// The asset pipeline generates a valid cover.ctc for every level.
		// Setting it to 1 causes sectors to be replaced with black tiles for
		// any terrain that was not painted inside the Sandbox editor.
	}
	break;

	case ESYSTEM_EVENT_LEVEL_UNLOAD:
	{
		m_players.clear();
	}
	break;
	}
}

bool CGamePlugin::OnClientConnectionReceived(int channelId, bool bIsReset)
{
	// Connection received from a client, create a player entity and component
	SEntitySpawnParams spawnParams;
	spawnParams.pClass = gEnv->pEntitySystem->GetClassRegistry()->GetDefaultClass();

	// Set a unique name for the player entity
	const string playerName = string().Format("Player%" PRISIZE_T, m_players.size());
	spawnParams.sName = playerName;

	// Set local player details
	if (m_players.empty() && !gEnv->IsDedicated())
	{
		spawnParams.id = LOCAL_PLAYER_ENTITY_ID;
		spawnParams.nFlags |= ENTITY_FLAG_LOCAL_PLAYER;
	}

	// Spawn the player entity
	if (IEntity *pPlayerEntity = gEnv->pEntitySystem->SpawnEntity(spawnParams))
	{
		// Set the local player entity channel id, and bind it to the network so that it can support Multiplayer contexts
		pPlayerEntity->GetNetEntity()->SetChannelId(channelId);

		// Create the player component instance
		CPlayerComponent *pPlayer = pPlayerEntity->GetOrCreateComponentClass<CPlayerComponent>();

		if (pPlayer != nullptr)
		{
			// Push the component into our map, with the channel id as the key
			m_players.emplace(std::make_pair(channelId, pPlayerEntity->GetId()));
		}
	}

	return true;
}

bool CGamePlugin::OnClientReadyForGameplay(int channelId, bool bIsReset)
{
	// Revive players when the network reports that the client is connected and ready for gameplay
	auto it = m_players.find(channelId);
	if (it != m_players.end())
	{
		if (IEntity *pPlayerEntity = gEnv->pEntitySystem->GetEntity(it->second))
		{
			if (CPlayerComponent *pPlayer = pPlayerEntity->GetComponent<CPlayerComponent>())
			{
				pPlayer->OnReadyForGameplayOnServer();
			}
		}
	}

	return true;
}

void CGamePlugin::OnClientDisconnected(int channelId, EDisconnectionCause cause, const char *description, bool bKeepClient)
{
	// Client disconnected, remove the entity and from map
	auto it = m_players.find(channelId);
	if (it != m_players.end())
	{
		gEnv->pEntitySystem->RemoveEntity(it->second);

		m_players.erase(it);
	}
}

void CGamePlugin::IterateOverPlayers(std::function<void(CPlayerComponent &player)> func) const
{
	for (const auto &playerPair : m_players)
	{
		if (IEntity *pPlayerEntity = gEnv->pEntitySystem->GetEntity(playerPair.second))
		{
			if (CPlayerComponent *pPlayer = pPlayerEntity->GetComponent<CPlayerComponent>())
			{
				func(*pPlayer);
			}
		}
	}
}

CRYREGISTER_SINGLETON_CLASS(CGamePlugin)
