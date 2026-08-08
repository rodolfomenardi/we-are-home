# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**We Are Home** — Home Assistant custom integration that learns device usage patterns from recorder history using probabilistic models and generates realistic synthetic presence simulations. Distributed via HACS. 100% local, no cloud dependencies.

## Commands

```bash
# Install dev dependencies
pip install -r requirements_dev.txt

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_learner.py

# Run with coverage (≥80% required by constitution)
pytest tests/ --cov=custom_components/we_are_home --cov-report=term --cov-fail-under=80

# Run with HTML coverage report
pytest tests/ --cov=custom_components/we_are_home --cov-report=html

# Validate HA integration structure (requires Home Assistant dev environment)
python3 -m script.hassfest

# Validate HACS compliance (runs in CI via GitHub Actions)
# See .github/workflows/hacs.yaml
```

No build step — Home Assistant loads files directly from `custom_components/we_are_home/`.

**Test coverage is mandatory**: constitution requires ≥80% overall, ≥90% for
core algorithms (`learner.py`, `simulator.py`), ≥85% for data models. CI
enforces this via `.github/workflows/coverage.yaml`.

## Architecture

### Learning Pipeline (coordinator.py → learner.py → storage.py)

The `WeAreHomeCoordinator` (DataUpdateCoordinator) runs periodic learning cycles (default 60 min). Each cycle:

1. **Reads** new state changes from `history_reader.py` (HA recorder via `get_significant_states`)
2. **Updates** `TimeProfile`s with EMA (α=0.3) — per-entity, per-15-min-slot, per-day-group
3. **Clusters** days using Jensen-Shannon divergence (threshold 0.15) → auto-discovers weekday/weekend split
4. **Discovers** `SequenceRule`s — pairwise A→B temporal associations within configurable window (default 60 min)
5. **Persists** to `.storage/we_are_home/` as JSON

### Simulation Engine (simulator.py)

`SimulationEngine.tick()` runs at configurable interval (default 30s):
- Reads current time slot's P(on) from profiles
- Applies active `SequenceRule` boosts (Gaussian decay centered at learned mean_delay)
- Samples with randomness — never deterministic
- Detects manual entity operation (grace period) to avoid conflicts

### Boost System (sequence_rule.py → simulator.py)

When entity A changes state during simulation:
1. `BoostManager` looks up matching `SequenceRule`s where source = A
2. Creates `ActiveBoost` targeting B with Gaussian multiplier decay over mean_delay ± 3*std_delay
3. On tick, B's P(on) is multiplied by combined boost (capped at 5×)
4. Conflicting rules (A→C and B→C) share proportionally via product

### Key Design Decisions

- **No external Python packages** beyond `numpy` (already in HA core) — zero pip installs needed
- **Profiles are 96 slots** (24h ÷ 15 min) per day_group, not 672 (7 days × 96) — day_group reduces dimensionality
- **EMA over full retrain** — incremental updates scale to years of history
- **Pares encadeáveis, not full episodes** — pairwise rules chain naturally (A→B + B→C ≈ A→B→C) without O(2ⁿ) mining
- **Boost, not trigger** — sequences influence probability, never force events (prevents "domino effect")
- **Services return dicts**, no custom response objects — compatible with HA service call patterns

### Multi-Instance Support

Each config entry creates its own coordinator + simulation engine. `_resolve_coordinator()` in services.py maps `switch_id` to the correct coordinator. First entry is default if no `switch_id` specified.

## SpecKit Workflow

This project uses SpecKit for spec-driven development:

```
/speckit-specify  → spec.md (feature spec)
/speckit-clarify  → refined spec with clarifications
/speckit-plan     → plan.md + research.md + data-model.md + contracts/ + quickstart.md
/speckit-tasks    → tasks.md (59 tasks with [pro]/[flash] model tags)
/speckit-analyze  → cross-artifact consistency check
/speckit-implement → execute all tasks respecting model tags
```

Task format: `- [ ] T### [Model] [P?] [Story?] Description with file path`
- `[pro]` → complex logic/algorithms (dispatch to deepseek-v4-pro/opus)
- `[flash]` → boilerplate/config/docs (dispatch to haiku/fast model)
