###################
## CONFIGURATION ##
###################

PYTHON=python
BUILD_DIR=build
TEST_DIR=test
DOCS_DIR=docs
PACKAGE_DIR=package
README=README.md

SCRIPT_DIR=scripts
SCRIPT_IMPORTCHECK=importcheck.py
SCRIPT_TEMPLATE=templatefiles.py

###############
## VARIABLES ##
###############

# Directories
SRC_DIR=$(shell pwd)
BUILD=$(SRC_DIR)/$(BUILD_DIR)
SCRIPTS=$(SRC_DIR)/$(SCRIPT_DIR)
PACKAGE=$(SRC_DIR)/$(PACKAGE_DIR)

# Virtualenv for building
VENV=$(BUILD)/venv
VENV_PYTHON=$(VENV)/bin/python
VENV_INSTALLED=$(VENV)/.installed

# Build tools
IMPORTCHECK=$(SCRIPTS)/$(SCRIPT_IMPORTCHECK)
TEMPLATE=$(SCRIPTS)/$(SCRIPT_TEMPLATE)

# Python paths and directories
PYTHON_SETUP=$(SRC_DIR)/setup.py
PYTHON_SRC=$(shell find $(SRC_DIR) -type f -name "*.py" -not -path '*/.*' -not -path '*/$(TEST_DIR)*' -not -path '*/$(BUILD_DIR)*' -not -path '*/$(DOCS_DIR)*' -not -path '*/package*')
PYTHON_PATH=$(abspath $(SRC_DIR)/..)

# Python variables from setup
PYTHON_PACKAGE_NAME=$(shell cat $(PYTHON_SETUP) | grep 'package_name =' | awk -F= '{print $$2}' | sed 's/[ "]//g' | sed "s/[ ']//g")
PYTHON_PACKAGE_VERSION_MAJOR=$(shell cat $(PYTHON_SETUP) | grep 'version_major =' | awk -F= '{print $$2}' | sed 's/[ "]//g' | sed "s/[ ']//g")
PYTHON_PACKAGE_VERSION_MINOR=$(shell cat $(PYTHON_SETUP) | grep 'version_minor =' | awk -F= '{print $$2}' | sed 's/[ "]//g' | sed "s/[ ']//g")
PYTHON_PACKAGE_VERSION_PATCH=$(shell cat $(PYTHON_SETUP) | grep 'version_patch =' | awk -F= '{print $$2}' | sed 's/[ "]//g' | sed "s/[ ']//g")

# Python distribution
PYTHON_PACKAGE_DIR=$(PACKAGE)/$(PYTHON_PACKAGE_NAME)
PYTHON_PACKAGE_SRC=$(patsubst $(SRC_DIR)/%,$(PYTHON_PACKAGE_DIR)/%,$(PYTHON_SRC))
PYTHON_PACKAGE_FILENAME=$(PYTHON_PACKAGE_NAME)-$(PYTHON_PACKAGE_VERSION_MAJOR).$(PYTHON_PACKAGE_VERSION_MINOR).$(PYTHON_PACKAGE_VERSION_PATCH).tar.gz
PYTHON_PACKAGE=$(BUILD)/$(PYTHON_PACKAGE_FILENAME)

# Touched files for testing
PYTHON_TEST_SRC=$(patsubst $(SRC_DIR)/%,%,$(filter-out %setup.py,$(PYTHON_SRC)))
PYTHON_TEST_TYPE=$(PYTHON_TEST_SRC:%=$(BUILD)/%.typecheck)
PYTHON_TEST_IMPORT=$(PYTHON_TEST_SRC:%=$(BUILD)/%.importcheck)
PYTHON_TEST_UNIT=$($(filter-out %__main__.py,$(PYTHON_TEST_SRC)):%=$(BUILD)/%.unittest)
PYTHON_TEST_INTEGRATION=$(BUILD)/.test

#############
## TARGETS ##
#############

## Builds source distribution
.PHONY: sdist
sdist: $(PYTHON_PACKAGE)
$(PYTHON_PACKAGE): $(PYTHON_SETUP) $(PYTHON_TEST_TYPE) $(PYTHON_TEST_IMPORT) $(PYTHON_TEST_UNIT) $(PYTHON_TEST_INTEGRATION) $(PYTHON_PACKAGE_SRC)
	@cp $(PYTHON_SETUP) $(PACKAGE)/
	@cp $(SRC_DIR)/$(README) $(PACKAGE)/
	cd $(PACKAGE) && $(VENV_PYTHON) setup.py sdist
	mv $(PACKAGE)/dist/$(PYTHON_PACKAGE_FILENAME) $@
	@rm -rf $(PACKAGE)

## Copy source distribution to package directory
$(PYTHON_PACKAGE_SRC):
	mkdir -p $(shell dirname $@)
	cp $(patsubst $(PYTHON_PACKAGE_DIR)/%,$(SRC_DIR)/%,$@) $@

## Uploads to PyPI
.PHONY: pypi
pypi: $(PYTHON_PACKAGE)
	$(VENV_PYTHON) -m twine upload $(PYTHON_PACKAGE)

## Formats with black
.PHONY: format
format: $(PYTHON_SRC)
	$(VENV_PYTHON) -m black $?

## Deletes build directory
.PHONY: clean
clean:
	rm -rf $(BUILD)
	@if [ -L $(SRC_DIR)/python ]; then \
		unlink $(SRC_DIR)/python; \
	fi
	@rm -rf $(SRC_DIR)/dist
	@find $(SRC_DIR) -type d -name "__pycache__" -exec rm -rf {} + 2>&1 > /dev/null
	@find $(SRC_DIR) -type d -name ".mypy_cache" -exec rm -rf {} + 2>&1 > /dev/null
	@find $(SRC_DIR) -type d -name "*.egg-info" -exec rm -rf {} + 2>&1 > /dev/null

## Makes virtual environment
.PHONY: venv
venv: $(VENV_INSTALLED)
$(VENV_INSTALLED): $(PYTHON_SETUP)
	mkdir -p $(BUILD)
	$(PYTHON) -m virtualenv $(VENV)
	$(VENV_PYTHON) -m pip install $(SRC_DIR)[all]
	@ln -sf $(VENV_PYTHON) $(SRC_DIR)/python
	@touch $@

## Run mypy
.PHONY: typecheck
typecheck: $(PYTHON_TEST_TYPE)
$(PYTHON_TEST_TYPE): $(PYTHON_TEST_SRC) $(VENV_INSTALLED)
	@mkdir -p $(shell dirname $@)
	$(VENV_PYTHON) -m mypy $(patsubst %.typecheck,%,$(patsubst $(BUILD)%,.%,$@))
	@touch $@

## Run importcheck
.PHONY: importcheck
importcheck: $(PYTHON_TEST_IMPORT)
$(PYTHON_TEST_IMPORT): $(PYTHON_TEST_SRC) $(VENV_INSTALLED)
	@mkdir -p $(shell dirname $@)
	$(VENV_PYTHON) $(IMPORTCHECK) $(patsubst %.importcheck,%,$(patsubst $(BUILD)%,.%,$@))
	@touch $@

## Run doctest
.PHONY: unittest
unittest: $(PYTHON_TEST_UNIT)
$(PYTHON_TEST_UNIT): $(PYTHON_TEST_SRC) $(VENV_INSTALLED)
	@mkdir -p $(shell dirname $@)
	PYTHONPATH=$(PYTHON_PATH) $(VENV_PYTHON) -m doctest $(patsubst $(BUILD)/%.unittest,%,$@)
	@touch $@

## Run integration tests
.PHONY: test
test: $(PYTHON_TEST_INTEGRATION)
$(PYTHON_TEST_INTEGRATION): $(PYTHON_TEST_SRC) $(VENV_INSTALLED)
	@mkdir -p $(shell dirname $@)
	PYTHONPATH=$(PYTHON_PATH) $(VENV_PYTHON) test/run.py
	@touch $@
