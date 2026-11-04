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

# Private runtime overlay (domain runtime channel, skill plasmid-engine-runtime; replaces the 2026-10-26 copy of the engine).
# A run uses .engine-private/ce-5.7.1: a HARD-LINK overlay of the clean runtime Engines/runtime/stable, so a run is not
# disturbed while the dev engine (Engines/ce-5.7.1) is rebuilt. Building still uses the dev engine (headers and CMake live
# there) and `make build ENGINE=57` deploys the plugin to the dev bin; `deploy-private` copies it into the overlay with
# --remove-destination (a new inode, so the runtime's files are never written). Never write in place and never chmod inside
# the overlay. The environment variable beats .env, so `make run` itself stays on the dev engine. 5.7.1 only: 5.6.7 has no runtime.
DEV_ENGINE     ?= $(abspath $(CURDIR)/../../Engines/ce-5.7.1)
RUNTIME        ?= $(abspath $(CURDIR)/../../Engines/runtime/stable)
PRIVATE_ENGINE ?= $(CURDIR)/.engine-private/ce-5.7.1
PLUGIN_SO      := $(DEV_ENGINE)/bin/linux_x64_gcc/libGamePlugin.so
PRIVATE_ENV    := CRYENGINE_DIR_57=$(PRIVATE_ENGINE)

.PHONY: private-sync deploy-private run-private health-private private-status
private-sync: ## create the hard-link overlay of the stable runtime in .engine-private (no copy; fails if it exists)
	@test -d $(RUNTIME)/bin || { echo "no runtime at $(RUNTIME)"; exit 1; }
	@test ! -e $(PRIVATE_ENGINE) || { echo "$(PRIVATE_ENGINE) exists: delete it by hand to re-create it (see plasmid-engine-runtime)"; exit 1; }
	mkdir -p $(dir $(PRIVATE_ENGINE))
	cp -al $(RUNTIME) $(PRIVATE_ENGINE)
	ln -s $(DEV_ENGINE)/Code $(PRIVATE_ENGINE)/Code
	rm $(PRIVATE_ENGINE)/RUNTIME.json
deploy-private: ## copy the plugin built by `make build ENGINE=57` into the overlay (new inode, runtime untouched)
	@test -f $(PLUGIN_SO) || { echo "$(PLUGIN_SO) missing: run 'make build ENGINE=57' first"; exit 1; }
	@test -d $(PRIVATE_ENGINE)/bin/linux_x64_gcc || { echo "no overlay: run 'make private-sync' first"; exit 1; }
	cp --remove-destination $(PLUGIN_SO) $(PRIVATE_ENGINE)/bin/linux_x64_gcc/
run-private: deploy-private ## like `make run ENGINE=57`, from the overlay of the stable runtime
	@$(PRIVATE_ENV) $(MAKE) --no-print-directory run ENGINE=57 OPTS="$(OPTS)" ARGS="$(ARGS)"
health-private: deploy-private ## like `make health ENGINE=57`, from the overlay
	@$(PRIVATE_ENV) $(MAKE) --no-print-directory health ENGINE=57 OPTS="$(OPTS)" ARGS="$(ARGS)"
private-status: ## is the overlay still hard-linked to the stable runtime? is the plugin the one just built?
	@for f in GameLauncher libCrySystem.so libCryRenderVulkan.so libCry3DEngine.so; do \
	  r=$(RUNTIME)/bin/linux_x64_gcc/$$f; o=$(PRIVATE_ENGINE)/bin/linux_x64_gcc/$$f; \
	  printf '%-24s %s\n' $$f "$$([ "$$(stat -c %i $$r 2>/dev/null)" = "$$(stat -c %i $$o 2>/dev/null)" ] && echo 'linked to stable' || echo 'DIFFERS from stable')"; done
	@printf '%-24s %s\n' libGamePlugin.so "$$([ "$$(sha256sum < $(PLUGIN_SO) 2>/dev/null)" = "$$(sha256sum < $(PRIVATE_ENGINE)/bin/linux_x64_gcc/libGamePlugin.so 2>/dev/null)" ] && echo 'same as the dev bin (deployed)' || echo 'DIFFERS from the dev bin: run make deploy-private')"
	@echo "runtime: $$(readlink $(RUNTIME) 2>/dev/null || echo $(RUNTIME))"
