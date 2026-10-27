# FirstPersonShooter dev menu. Generic targets (setup, build, run, debug, ...) come from the vendored
# tools/plasmid-dev/Makefile.common (pinned by tools_version in plasmid.config.json); run `make help` for the full list. Project-specific targets are below.
#
# Usage examples:
#   make build COMPILER=gcc14 TYPE=Profile
#   make run ENGINE=57          # CRYENGINE 5.7.1 (CRYENGINE_DIR_57 in .env), builds with gcc13
#   make pipeline ARGS="create-job --kind level --prompt 'desert arena' --target-package desert"

include $(CURDIR)/tools/plasmid-dev/Makefile.common

.PHONY: test pipeline

test: ## run the Python test suite (venv)
	@$(DEV) test -- $(ARGS)
pipeline: ## asset pipeline CLI; ARGS="create-job --kind level ..."
	@$(DEV) pipeline -- $(ARGS)

# Private engine runtime (E-04/T-03, pattern from SandboxLLM): an independent copy of the SHARED engine's runtime
# (bin, Engine, system.cfg) under .engine-private, so a run is not disturbed while the parent folder rebuilds or patches
# Engines/ce-5.6.7. Building still uses the shared engine (headers and CMake live there); `make build` deploys the plugin to
# the shared bin, `make deploy-private` copies it here. The shader server must run from the SHARED engine (the private copy
# has no DXC), so run-private starts it from there and launches the game from the private copy.
SHARED_ENGINE  ?= $(abspath $(CURDIR)/../../Engines/ce-5.6.7)
PRIVATE_ENGINE ?= $(CURDIR)/.engine-private/ce-5.6.7
PLUGIN_SO      := $(CURDIR)/bin/linux_x64_gcc/libGamePlugin.so
PRIVATE_ENV    := CRYENGINE_DIR=$(PRIVATE_ENGINE) CRYENGINE_DIR_56=$(PRIVATE_ENGINE)

.PHONY: private-sync deploy-private run-private private-status
private-sync: ## (re)copy the shared engine runtime into .engine-private (real copies; keeps our plugin)
	mkdir -p $(PRIVATE_ENGINE)
	rsync -a --exclude=libGamePlugin.so --exclude=libSandboxLLMPlugin.so $(SHARED_ENGINE)/bin $(PRIVATE_ENGINE)/
	rsync -a $(SHARED_ENGINE)/Engine $(PRIVATE_ENGINE)/
	ln -sfn Engine $(PRIVATE_ENGINE)/engine
	cp --remove-destination $(SHARED_ENGINE)/system.cfg $(SHARED_ENGINE)/cryengine.cryengine $(PRIVATE_ENGINE)/
	@echo "private engine synced from $(SHARED_ENGINE); run 'make deploy-private' for the plugin"
deploy-private: ## copy the built plugin into the private engine bin (after every `make build`)
	@test -f $(PLUGIN_SO) || { echo "$(PLUGIN_SO) missing: run 'make build' first"; exit 1; }
	@test -d $(PRIVATE_ENGINE)/bin/linux_x64_gcc || { echo "no private engine: run 'make private-sync' first"; exit 1; }
	cp --remove-destination $(PLUGIN_SO) $(PRIVATE_ENGINE)/bin/linux_x64_gcc/
run-private: deploy-private ## like run, but launches GameLauncher from .engine-private (shader server from the shared engine)
	@$(DEV) up
	@$(PRIVATE_ENV) $(DEV) run --no-services $(OPTS) -- $(ARGS)
private-status: ## compare the shared and private engine libraries and plugin
	@for f in GameLauncher libCrySystem.so libCryRenderVulkan.so libCry3DEngine.so libGamePlugin.so; do \
	  s=$(SHARED_ENGINE)/bin/linux_x64_gcc/$$f; p=$(PRIVATE_ENGINE)/bin/linux_x64_gcc/$$f; \
	  printf '%-24s shared %s  private %s\n' $$f "$$(sha256sum $$s 2>/dev/null | cut -c1-12)" "$$(sha256sum $$p 2>/dev/null | cut -c1-12)"; done
