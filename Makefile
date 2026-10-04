# Dev command menu — the npm-scripts equivalent. All logic lives in tools/dev.py.
# `make help` lists targets. Override variables on the command line, e.g.
#   make build COMPILER=gcc14 TYPE=Profile
#   make pipeline ARGS="create-job --kind level --prompt 'desert arena' --target-package desert"

PY       ?= python3
DEV      := $(PY) tools/dev.py
COMPILER ?= gcc9
TYPE     ?= Debug
ARGS     ?=
OPTS     := --compiler $(COMPILER) --type $(TYPE)

.DEFAULT_GOAL := help
.PHONY: help setup doctor configure build clean release up down run run-release debug debug-batch stop status logs logs-all test pipeline

help: ## list targets
	@echo "Targets (variables: COMPILER=gcc9|gcc14|clang  TYPE=Debug|Profile|Release  ARGS=...):"
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup: ## first-time: venv + deps + prerequisite check + configure
	@$(DEV) setup $(OPTS)
doctor: ## check prerequisites (engine path, compilers, gdb, wine, display)
	@$(DEV) doctor
configure: ## (re)configure CMake with the chosen preset
	@$(DEV) configure $(OPTS)
build: ## dev compile: build the plugin and deploy it to the engine bin dir
	@$(DEV) build $(OPTS)
clean: ## clean build outputs
	@$(DEV) clean $(OPTS)
release: ## production build (Release)
	@$(DEV) build --compiler $(COMPILER) --type Release

up: ## start background services (shader compiler server)
	@$(DEV) up
down: ## stop background services
	@$(DEV) down
run: ## start services + launch the game in the background (returns immediately)
	@$(DEV) run $(OPTS) -- $(ARGS)
run-release: ## build Release, then launch the game
	@$(DEV) run --compiler $(COMPILER) --type Release --build -- $(ARGS)
debug: ## launch under gdb, interactive
	@$(DEV) debug -- $(ARGS)
debug-batch: ## launch under gdb non-interactively; backtrace in .dev/logs/gdb.log (ARGS unused; set TIMEOUT=secs)
	@$(DEV) debug --batch --timeout $(or $(TIMEOUT),0)
stop: ## stop the game and all services
	@$(DEV) stop
status: ## show services, game, builds, plugin timestamps
	@$(DEV) status
logs: ## recent warnings/errors from game.log
	@$(DEV) logs
logs-all: ## last 80 lines of game.log, unfiltered
	@$(DEV) logs --all -n 80

test: ## run the Python test suite (venv)
	@$(DEV) test -- $(ARGS)
pipeline: ## asset pipeline CLI; ARGS="create-job --kind level ..."
	@$(DEV) pipeline -- $(ARGS)
