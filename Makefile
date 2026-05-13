.PHONY: help setup venv rust python model build clean test serve release

PYTHON   ?= python3
VENV     := .venv
PORT     ?= 8765
MODEL    ?= base.en
MODEL_URL = https://openaipublic.azureedge.net/main/whisper/models/25a8566e1d0c1e2231d1c762132cd20e0f96a85d16145c3a00adf5d1ac670ead/base.en.pt

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── Environment ──────────────────────────────────────────────────────

venv: ## Create Python virtual environment
	@if [ ! -d "$(VENV)" ]; then \
		$(PYTHON) -m venv $(VENV); \
		echo "✔ Virtual environment created at $(VENV)/"; \
	else \
		echo "  Virtual environment already exists."; \
	fi

# ── Build steps ──────────────────────────────────────────────────────

rust: venv ## Build the Rust audio extension (maturin develop)
	@echo "⚙  Building Rust audio extension..."
	. $(VENV)/bin/activate && cd crates/noteagent-py && maturin develop
	@echo "✔ Rust extension built."

python: venv ## Install the Python package in editable mode
	@echo "⚙  Installing Python package..."
	. $(VENV)/bin/activate && pip install -e ".[dev]" --quiet
	@echo "✔ Python package installed."

model: ## Download the Whisper model (base.en by default)
	@mkdir -p models
	@if [ ! -f "models/$(MODEL).pt" ]; then \
		echo "⬇  Downloading Whisper $(MODEL) model..."; \
		curl -fSL -o "models/$(MODEL).pt" "$(MODEL_URL)"; \
		echo "✔ Model saved to models/$(MODEL).pt"; \
	else \
		echo "  Model models/$(MODEL).pt already exists."; \
	fi

build: venv rust python model ## Full build: Rust + Python + model download
	@echo ""
	@echo "══════════════════════════════════════════════"
	@echo "  ✔ NoteAgent is ready!"
	@echo "    Run:  source $(VENV)/bin/activate"
	@echo "          noteagent --help"
	@echo "══════════════════════════════════════════════"

setup: build ## Alias for 'build' — complete first-time setup

# ── Run ──────────────────────────────────────────────────────────────

test: ## Run the test suite
	. $(VENV)/bin/activate && python -m pytest tests/ -v

serve: ## Start the web UI (PORT=8765)
	. $(VENV)/bin/activate && noteagent serve --port $(PORT)

# ── Cleanup ──────────────────────────────────────────────────────────

clean: ## Remove build artifacts (keeps venv and models)
	rm -rf target crates/*/target
	rm -rf src/noteagent.egg-info dist build
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✔ Cleaned build artifacts."

distclean: clean ## Full clean including venv and downloaded models
	rm -rf $(VENV) models/*.pt
	@echo "✔ Removed virtual environment and models."

# ── Release ──────────────────────────────────────────────────────────

release: ## Build release packages for distribution
	./build-release.sh
