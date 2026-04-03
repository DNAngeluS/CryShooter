# Debug Screenshot Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind Ctrl+P in-game to capture a timestamped JPEG screenshot saved to `FirstPersonShooter/Screenshots/`.

**Architecture:** Register a `"screenshot"` input action on `eKI_P` inside `CPlayerComponent::InitializeLocalPlayer()`. The callback checks Ctrl state via `gEnv->pInput->IsKeyDown()` then delegates to a new private method `TakeDebugScreenshot()` which resolves the project root, ensures the `Screenshots/` directory exists, and writes the file via `gEnv->pRenderer->ScreenShot()`.

**Tech Stack:** C++14, CRYENGINE 5.6, `CInputComponent`, `IFileIO`, `IRenderer`, GCC 9 / Ninja build.

---

## File Map

| File | Change |
|------|--------|
| `Code/Components/Player.h` | Add `void TakeDebugScreenshot()` private declaration |
| `Code/Components/Player.cpp` | Register/bind input action in `InitializeLocalPlayer()`; implement `TakeDebugScreenshot()` |

---

### Task 1: Declare `TakeDebugScreenshot()` in the header

**Files:**
- Modify: `Code/Components/Player.h`

- [ ] **Step 1: Add private method declaration**

In [Code/Components/Player.h](Code/Components/Player.h), locate the `protected:` block that contains the other `Update*` and `HandleInputFlagChange` method declarations (around line 117). Add the new declaration immediately after `HandleInputFlagChange`:

```cpp
	void HandleInputFlagChange(CEnumFlags<EInputFlag> flags, CEnumFlags<EActionActivationMode> activationMode, EInputFlagType type = EInputFlagType::Hold);

	void TakeDebugScreenshot();
```

- [ ] **Step 2: Verify the header compiles in isolation (dry build)**

```bash
source .env
cmake --build build/gcc --parallel $(nproc) 2>&1 | head -20
```

Expected: build succeeds (no new errors — the method is declared but not yet defined, which is fine until it's called).

- [ ] **Step 3: Commit**

```bash
git add Code/Components/Player.h
git commit -m "feat: declare TakeDebugScreenshot on CPlayerComponent"
```

---

### Task 2: Implement `TakeDebugScreenshot()`

**Files:**
- Modify: `Code/Components/Player.cpp`

- [ ] **Step 1: Add the implementation at the bottom of Player.cpp**

Append the following after the closing brace of `HandleInputFlagChange` (end of file):

```cpp
void CPlayerComponent::TakeDebugScreenshot()
{
	// Resolve project root (e.g. /home/user/projects/FirstPersonShooter)
	const char* szProjectDir = gEnv->pSystem->GetIProjectManager()->GetCurrentProjectDirectoryAbsolute();
	if (!szProjectDir || szProjectDir[0] == '\0')
	{
		CryWarning(VALIDATOR_MODULE_GAME, VALIDATOR_WARNING, "[Screenshot] Could not resolve project directory");
		return;
	}

	// Ensure Screenshots/ directory exists
	char screenshotsDir[512];
	cry_sprintf(screenshotsDir, "%s/Screenshots", szProjectDir);
	gEnv->pFileIO->MakeDir(screenshotsDir);

	// Build timestamped filename
	time_t now = time(nullptr);
	struct tm* t = localtime(&now);
	char filename[256];
	cry_sprintf(filename, "screenshot_%04d%02d%02d_%02d%02d%02d.jpg",
		t->tm_year + 1900, t->tm_mon + 1, t->tm_mday,
		t->tm_hour, t->tm_min, t->tm_sec);

	char fullPath[768];
	cry_sprintf(fullPath, "%s/%s", screenshotsDir, filename);

	gEnv->pRenderer->ScreenShot(fullPath);
	CryLog("[Screenshot] Saved to %s", fullPath);
}
```

- [ ] **Step 2: Add required `<ctime>` include**

At the top of `Player.cpp`, the existing includes are sufficient (`StdAfx.h` pulls in standard C headers via the precompiled header). Verify `ctime` / `time_t` is available by checking that the build succeeds in the next step — no explicit include needed.

- [ ] **Step 3: Build and verify it compiles**

```bash
cmake --build build/gcc --parallel $(nproc) 2>&1 | tail -20
```

Expected: `[100%] Linking CXX shared library ... libGamePlugin.so` with no errors.

- [ ] **Step 4: Commit**

```bash
git add Code/Components/Player.cpp
git commit -m "feat: implement TakeDebugScreenshot saving timestamped JPEG to Screenshots/"
```

---

### Task 3: Register the Ctrl+P input action

**Files:**
- Modify: `Code/Components/Player.cpp`

- [ ] **Step 1: Add action registration in `InitializeLocalPlayer()`**

In [Code/Components/Player.cpp](Code/Components/Player.cpp), find the last `BindAction` call in `InitializeLocalPlayer()` (the `"quit"` binding around line 157). Add the screenshot action immediately after it, before the closing `}` of `InitializeLocalPlayer()`:

```cpp
	// Take a debug screenshot on Ctrl+P
	m_pInputComponent->RegisterAction("player", "screenshot", [this](int activationMode, float value)
	{
		if (activationMode == eAAM_OnPress)
		{
			if (gEnv->pInput->IsKeyDown(eKI_LCtrl) || gEnv->pInput->IsKeyDown(eKI_RCtrl))
			{
				TakeDebugScreenshot();
			}
		}
	});
	m_pInputComponent->BindAction("player", "screenshot", eAID_KeyboardMouse, EKeyId::eKI_P);
```

- [ ] **Step 2: Build**

```bash
cmake --build build/gcc --parallel $(nproc) 2>&1 | tail -20
```

Expected: `libGamePlugin.so` built successfully, deployed to engine bin dir.

- [ ] **Step 3: Runtime smoke test**

Launch the game:
```bash
$CRYENGINE_DIR/bin/linux_x64_gcc/GameLauncher -project $PROJECT_ROOT/Game.cryproject
```

1. Wait for the level to load.
2. Press **Ctrl+P**.
3. Check that `FirstPersonShooter/Screenshots/` was created and contains a `.jpg` file with today's date in the name.
4. Optionally check the engine console log for the `[Screenshot] Saved to ...` message.
5. Open the JPEG and verify it shows the in-game viewport.

- [ ] **Step 4: Commit**

```bash
git add Code/Components/Player.cpp
git commit -m "feat: bind Ctrl+P to debug screenshot in CPlayerComponent"
```

---

### Task 4: Add Screenshots/ to .gitignore

**Files:**
- Modify: `.gitignore` (project root)

- [ ] **Step 1: Check whether .gitignore exists and add the entry**

```bash
echo "Screenshots/" >> .gitignore
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore Screenshots/ directory"
```
