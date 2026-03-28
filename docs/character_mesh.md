# CRYENGINE 5.6 — Character Mesh & Animation

## Overview

Characters in CRYENGINE are driven by the **Mannequin** animation system. A character requires:
- A `.cdf` (Character Definition File) — links skeleton + skin mesh.
- An `.adb` (Animation Database) — defines available animation clips.
- A Controller Definition XML — maps fragment names to animation scopes.
- A scope context name — identifies which part of the controller this character uses.

The `CAdvancedAnimationComponent` manages all of this at runtime.

---

## Required Asset Files

For the FPS sample character:

| File | Path | Purpose |
|------|------|---------|
| Character definition | `Objects/Characters/SampleCharacter/firstperson.cdf` | Skeleton + skin binding |
| Animation database | `Animations/Mannequin/ADB/FirstPerson.adb` | Clips (Idle, Walk, …) |
| Controller definition | `Animations/Mannequin/ADB/FirstPersonControllerDefinition.xml` | Fragment/scope mapping |

All paths are relative to the project `Assets/` root.

> If any of these files are missing, `GetCharacter()` returns `nullptr` and the camera falls
> back to a fixed eye-height.

---

## Component Setup in Code (`Player.cpp`)

```cpp
void CPlayerComponent::Initialize()
{
    // 1. Character controller (physics capsule)
    m_pCharacterController =
        m_pEntity->GetOrCreateComponent<Cry::DefaultComponents::CCharacterControllerComponent>();
    // Offset capsule 1 m above entity pivot (heightPivot = 0, so pivot is at ground level)
    m_pCharacterController->SetTransformMatrix(
        Matrix34::Create(Vec3(1.f), IDENTITY, Vec3(0, 0, 1.f)));

    // 2. Advanced animation component
    m_pAnimationComponent =
        m_pEntity->GetOrCreateComponent<Cry::DefaultComponents::CAdvancedAnimationComponent>();

    m_pAnimationComponent->SetMannequinAnimationDatabaseFile(
        "Animations/Mannequin/ADB/FirstPerson.adb");
    m_pAnimationComponent->SetCharacterFile(
        "Objects/Characters/SampleCharacter/firstperson.cdf");
    m_pAnimationComponent->SetControllerDefinitionFile(
        "Animations/Mannequin/ADB/FirstPersonControllerDefinition.xml");
    m_pAnimationComponent->SetDefaultScopeContextName("FirstPersonCharacter");
    m_pAnimationComponent->SetDefaultFragmentName("Idle");

    // Disable root-motion (movement is physics-driven)
    m_pAnimationComponent->SetAnimationDrivenMotion(true);

    // Load everything from disk now
    m_pAnimationComponent->LoadFromDisk();

    // Cache fragment and tag IDs (avoids string lookups every frame)
    m_idleFragmentId = m_pAnimationComponent->GetFragmentId("Idle");
    m_walkFragmentId = m_pAnimationComponent->GetFragmentId("Walk");
    m_rotateTagId    = m_pAnimationComponent->GetTagId("Rotate");
}
```

---

## Character Controller Physics

`CCharacterControllerComponent` physicalises the entity as a **living entity** (capsule).

### Default Capsule Dimensions

| Parameter | Default | Notes |
|-----------|---------|-------|
| Radius | `0.45 m` | Capsule radius |
| Height | `0.935 m` | Cylinder height (excluding end caps) |
| `heightPivot` | `0.0` | Entity origin = ground contact point |
| `heightCollider` | set by transform | Z offset of capsule centre above entity |

With `SetTransformMatrix(Vec3(0, 0, 1.f))`, the capsule centre is 1 m above the entity origin.
Bottom of capsule ≈ entity_z + 0.05 m. Entity is effectively at ground level.

### Physicalize

Call after `Revive()` to apply physics:
```cpp
m_pAnimationComponent->ResetCharacter();
m_pCharacterController->Physicalize();
```

### Movement

```cpp
// Per-frame velocity request (walking)
m_pCharacterController->AddVelocity(GetEntity()->GetWorldRotation() * horizontalVelocity);

// One-shot jump impulse
if (m_pCharacterController->IsOnGround())
    m_pCharacterController->AddVelocity(Vec3(0.f, 0.f, 8.f));   // tune jump speed here
```

---

## Camera Setup

The camera is attached to the player entity as a `CCameraComponent`.
Its local transform is updated every frame in `UpdateCamera()`.

### With Character Loaded

```cpp
if (ICharacterInstance* pCharacter = m_pAnimationComponent->GetCharacter())
{
    // Get the head joint position in local space
    const QuatT& headPose = pCharacter->GetISkeletonPose()
                                ->GetAbsJointByID(m_cameraJointId);
    localTransform.SetTranslation(headPose.t + Vec3(0, 0.01f, 0.26f));
}
```

Cache the joint ID in `Revive()`:
```cpp
m_cameraJointId = pCharacter->GetIDefaultSkeleton()
                             .GetJointIDByName("head");
```

### Fallback (no character file)

```cpp
else
{
    // Fixed eye height: entity origin is at ground (heightPivot = 0)
    // so 1.8 m places the camera at a natural standing eye level.
    localTransform.SetTranslation(Vec3(0, 0.01f, 1.8f));
}
```

---

## Shooting Attachment Point

Bullet spawn origin is read from a character attachment named `"barrel_out"`:

```cpp
IAttachment* pBarrel = pCharacter->GetIAttachmentManager()
                                  ->GetInterfaceByName("barrel_out");
if (pBarrel)
{
    QuatTS origin = pBarrel->GetAttWorldAbsolute();
    // spawn bullet entity at origin.t with rotation origin.q
}
```

The attachment must be defined in the character's skeleton (`.cdf` / skin).

---

## Animation Playback

```cpp
// Queue a fragment by cached ID
m_pAnimationComponent->QueueFragmentWithId(m_walkFragmentId);

// Set a boolean tag
m_pAnimationComponent->SetTagWithId(m_rotateTagId, isTurning);

// Set a motion parameter (blending between animations)
m_pAnimationComponent->SetMotionParameter(eMotionParamID_TurnAngle, angle);
```

---

## Sandbox Workflow

1. Import your character FBX via **File → Import**.
2. In the **Character Editor** (double-click `.cdf`): assign skeleton, bind skin meshes.
3. Create an `.adb` in **Mannequin Editor** → add fragments (Idle, Walk, etc.).
4. Assign animation clips to fragments.
5. Export: clips go to `Animations/`, character to `Objects/Characters/`.
6. Reference the paths in `CAdvancedAnimationComponent` calls as above.

---

## `.cdf` File Structure (XML)

```xml
<CharacterDefinition>
  <Model File="Objects/Characters/SampleCharacter/skeleton.chr" />
  <AttachmentList>
    <Attachment Type="CA_SKIN"
                AName="body_skin"
                Binding="Objects/Characters/SampleCharacter/body.skin"
                Flags="0"/>
    <Attachment Type="CA_BONE"
                AName="barrel_out"
                BoneName="weapon_bone"
                Flags="0"/>
  </AttachmentList>
</CharacterDefinition>
```
