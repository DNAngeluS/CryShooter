# FirstPersonShooter dev menu. Generic targets (setup, build, run, debug, ...) come from the vendored
# tools/cryengine-dev/Makefile.common (pinned by tools_version in cryengine-dev.config.json); run `make help` for the full list. Project-specific targets are below.
#
# Usage examples:
#   make build COMPILER=gcc14 TYPE=Profile
#   make run ENGINE=57          # CRYENGINE 5.7.1 (CRYENGINE_DIR_57 in .env), builds with gcc13
#   make pipeline ARGS="create-job --kind level --prompt 'desert arena' --target-package desert"

include $(CURDIR)/tools/cryengine-dev/Makefile.common

.PHONY: test pipeline

test: ## run the Python test suite (venv)
	@$(DEV) test -- $(ARGS)
pipeline: ## asset pipeline CLI; ARGS="create-job --kind level ..."
	@$(DEV) pipeline -- $(ARGS)
