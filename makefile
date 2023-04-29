###############
## VARIABLES ##
###############

# Binaries
PYTHON=python3

# Directories
SRC_DIR=$(shell pwd)
BUILD_DIR=$(SRC_DIR)/build
SCRIPT_DIR=$(SRC_DIR)/scripts

# Virtualenv for building
BUILD_VENV=$(BUILD_DIR)/venv
BUILD_VENV_PYTHON=$(BUILD_VENV)/bin/python
BUILD_VENV_INSTALLED=$(BUILD_VENV)/.installed

# Build tools
PYTHON_IMPORTCHECK_SCRIPT=$(SCRIPT_DIR)/import-check.py
PYTHON_TEMPLATE_SCRIPT=$(SCRIPT_DIR)/template-files.py

# Python paths and directories
PYTHON_SETUP=$(SRC_DIR)/setup.py
PYTHON_SRC=$(shell find $(SRC_DIR) -type f -name "*.py" -not -path '*/.*' -not -path '*/test*' -not -path '*/sphnx*')
PYTHON_PATH=$(abspath $(SRC_DIR)/..)
PYTHON_PACKAGE_NAME=$(shell cat $(PYTHON_SETUP) | grep 'package_name =' | awk -F= '{print $$2}' | sed 's/[ "]//g' | sed "s/[ ']//g")
PYTHON_PACKAGE_VERSION_MAJOR=$(shell cat $(PYTHON_SETUP) | grep 'version_major =' | awk -F= '{print $$2}' | sed 's/[ "]//g' | sed "s/[ ']//g")
PYTHON_PACKAGE_VERSION_MINOR=$(shell cat $(PYTHON_SETUP) | grep 'version_minor =' | awk -F= '{print $$2}' | sed 's/[ "]//g' | sed "s/[ ']//g")
PYTHON_PACKAGE_VERSION_PATCH=$(shell cat $(PYTHON_SETUP) | grep 'version_patch =' | awk -F= '{print $$2}' | sed 's/[ "]//g' | sed "s/[ ']//g")
PYTHON_PACKAGE_FILENAME=$(PYTHON_PACKAGE_NAME)-$(PYTHON_PACKAGE_VERSION_MAJOR)-$(PYTHON_PACKAGE_VERSION_MINOR)-$(PYTHON_PACKAGE_VERSION_PATCH).tar.gz
PYTHON_PACKAGE=$(SRC_DIR)/dist/$(PYTHON_PACKAGE_FILENAME)

# Touch'd files for testing
PYTHON_TEST_SRC=$(patsubst $(SRC_DIR)/%,%,$(filter-out %setup.py %__main__.py,$(PYTHON_SRC)))
PYTHON_TEST_TYPE=$(PYTHON_TEST_SRC:%=$(BUILD_DIR)/%.typecheck)
PYTHON_TEST_IMPORT=$(PYTHON_TEST_SRC:%=$(BUILD_DIR)/%.importcheck)
PYTHON_TEST_UNIT=$(PYTHON_TEST_SRC:%=$(BUILD_DIR)/%.unittest)
PYTHON_TEST_INTEGRATION=$(BUILD_DIR)/.test

#############
## TARGETS ##
#############

## Builds source distribution
.PHONY: sdist
sdist: $(PYTHON_PACKAGE)
$(PYTHON_PACKAGE): $(PYTHON_SETUP) $(PYTHON_TEST_TYPE) $(PYTHON_TEST_IMPORT) $(PYTHON_TEST_UNIT) $(PYTHON_TEST_INTEGRATION)
	$(BUILD_VENV_PYTHON) $(PYTHON_SETUP) sdist

## Deletes build directory
.PHONY: clean
clean:
	rm -rf $(BUILD_DIR)
	@if [ -L $(SRC_DIR)/python ]; then \
		unlink $(SRC_DIR)/python; \
	fi
	@rm -rf $(SRC_DIR)/dist
	@find $(SRC_DIR) -type d -name "__pycache__" -exec rm -rf {} + 2>&1 > /dev/null
	@find $(SRC_DIR) -type d -name ".mypy_cache" -exec rm -rf {} + 2>&1 > /dev/null
	@find $(SRC_DIR) -type d -name "*.egg-info" -exec rm -rf {} + 2>&1 > /dev/null

## Makes virtual environment
.PHONY: venv
venv: $(BUILD_VENV_INSTALLED)
$(BUILD_VENV_INSTALLED): $(PYTHON_SETUP)
	mkdir -p $(BUILD_DIR)
	$(PYTHON) -m virtualenv $(BUILD_VENV)
	$(BUILD_VENV_PYTHON) -m pip install -e $(SRC_DIR)[all]
	@ln -sf $(BUILD_VENV_PYTHON) $(SRC_DIR)/python
	@touch $@

## Run mypy
.PHONY: typecheck
typecheck: $(PYTHON_TEST_TYPE)
$(PYTHON_TEST_TYPE): $(PYTHON_TEST_SRC) $(BUILD_VENV_INSTALLED)
	@mkdir -p $(shell dirname $@)
	$(BUILD_VENV_PYTHON) -m mypy $(patsubst %.typecheck,%,$(patsubst $(BUILD_DIR)%,.%,$@))
	@touch $@

## Run importcheck
.PHONY: importcheck
importcheck: $(PYTHON_TEST_IMPORT)
$(PYTHON_TEST_IMPORT): $(PYTHON_TEST_SRC) $(BUILD_VENV_INSTALLED)
	@mkdir -p $(shell dirname $@)
	$(BUILD_VENV_PYTHON) $(PYTHON_IMPORTCHECK_SCRIPT) $(patsubst %.importcheck,%,$(patsubst $(BUILD_DIR)%,.%,$@))
	@touch $@

## Run doctest
.PHONY: unittest
unittest: $(PYTHON_TEST_UNIT)
$(PYTHON_TEST_UNIT): $(PYTHON_TEST_SRC) $(BUILD_VENV_INSTALLED)
	@mkdir -p $(shell dirname $@)
	PYTHONPATH=$(PYTHON_PATH) $(BUILD_VENV_PYTHON) -m doctest $(patsubst $(BUILD_DIR)/%.unittest,%,$@)
	@touch $@

## Run integration tests
.PHONY: test
test: $(PYTHON_TEST_INTEGRATION)
$(PYTHON_TEST_INTEGRATION): $(PYTHON_TEST_SRC) $(BUILD_VENV_INSTALLED)
	@mkdir -p $(shell dirname $@)
	PYTHONPATH=$(PYTHON_PATH) $(BUILD_VENV_PYTHON) test/run.py
	@touch $@
