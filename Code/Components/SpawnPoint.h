// Copyright 2001-2019 Crytek GmbH / Crytek Group. All rights reserved.

#pragma once

#include <CryEntitySystem/IEntitySystem.h>

////////////////////////////////////////////////////////
// Spawn point
////////////////////////////////////////////////////////
class CSpawnPointComponent final : public IEntityComponent
{
public:
	CSpawnPointComponent() = default;
	virtual ~CSpawnPointComponent() = default;

	// Reflect type to set a unique identifier for this component
	// and provide additional information to expose it in the sandbox
	static void ReflectType(Schematyc::CTypeDesc<CSpawnPointComponent>& desc)
	{
		desc.SetGUID("{41316132-8A1E-4073-B0CD-A242FD3D2E90}"_cry_guid);
		desc.SetEditorCategory("Game");
		desc.SetLabel("SpawnPoint");
		desc.SetDescription("This spawn point can be used to spawn entities");
		desc.SetComponentFlags({ IEntityComponent::EFlags::Transform, IEntityComponent::EFlags::Socket, IEntityComponent::EFlags::Attach });
	}
	
	static Matrix34 GetFirstSpawnPointTransform()
	{
		// Spawn at first default spawner
		IEntityItPtr pEntityIterator = gEnv->pEntitySystem->GetEntityIterator();
		pEntityIterator->MoveFirst();

		while (!pEntityIterator->IsEnd())
		{
			IEntity *pEntity = pEntityIterator->Next();

			if (CSpawnPointComponent* pSpawner = pEntity->GetComponent<CSpawnPointComponent>())
			{
				return pSpawner->GetWorldTransformMatrix();
			}
		}

		// No spawn point placed in the level — fall back to terrain center at a safe height
		const float terrainSize = gEnv->p3DEngine ? (float)gEnv->p3DEngine->GetTerrainSize() : 1024.f;
		const float cx = terrainSize * 0.5f;
		const float cy = terrainSize * 0.5f;
		const float terrainZ = gEnv->p3DEngine ? gEnv->p3DEngine->GetTerrainElevation(cx, cy) : 32.f;
		return Matrix34::Create(Vec3(1.f), IDENTITY, Vec3(cx, cy, terrainZ + 10.f));
	}
};
