<!--
  Sync Impact Report
  ==================
  Version change: 1.1.0 → 1.2.0
  Previous state: v1.1.0 (branch conventions added)
  Modified principles: None
  Added sections:
    - Test Coverage Standard (under Performance Standards)
    - Updated Quality Gates with coverage gate
    - Updated Development Workflow with test generation rule
  Removed sections: None
  Deferred items: None
-->

# We Are Home Constitution

## Core Principles

### I. 100% Local Execution

All data processing, learning, and simulation MUST run entirely on the user's
Home Assistant hardware. No cloud services, no telemetry, no external APIs, no
data leaving the local network. This is NON-NEGOTIABLE.

**Rationale**: This is the project's primary differentiator from cloud-dependent
alternatives. Users trust the system with their behavioral patterns; that trust
is irrevocably broken by any outbound network call.

### II. Probabilistic Learning, Not Replay

The system MUST learn statistical distributions from history and generate
synthetic behavior by sampling those distributions. It MUST NOT simply replay
recorded states from N days ago.

**Rules**:
- Every simulated event MUST include stochastic variation (Gaussian noise on
  timing, probabilistic state selection)
- Two consecutive simulated days MUST never be identical
- Sequence rules MUST boost probability, never force deterministic triggers
- Learned profiles MUST be inspectable (confidence scores, maturity levels)

**Rationale**: Pure replay is predictable and detectable. The value proposition
is behavior that is *statistically indistinguishable* from real patterns while
being *synthetically novel* each day.

### III. Zero External Dependencies

The integration MUST NOT require any Python packages beyond those already present
in a standard Home Assistant installation (numpy, stdlib).

**Rules**:
- `manifest.json` `requirements` field MUST be empty or contain only HA-core-included packages
- No `pip install` step in installation instructions beyond what HACS handles automatically
- If a new algorithm requires a library not in HA core, it MUST be implemented from scratch

**Rationale**: HACS users expect one-click install. Any extra dependency is a
support burden and a common point of installation failure, especially on
resource-constrained hardware like Raspberry Pi.

### IV. Incremental Over Batch

All model updates MUST use online/incremental algorithms. The system MUST never
require a full retraining pass over all historical data to incorporate new
observations.

**Rules**:
- TimeProfile updates MUST use Exponential Moving Average (EMA) or equivalent
  constant-memory online method
- SequenceRule delay statistics MUST update via Welford-style or EMA
- Adding a new entity MUST NOT trigger retraining of existing entities
- Learning cycle MUST complete in <30 seconds for 50 entities (Raspberry Pi 4)

**Rationale**: Recorder databases can hold years of data. Full retraining would
be O(years) on every cycle, violating performance constraints and blocking the
Home Assistant event loop.

### V. Home Assistant Native

All code MUST follow Home Assistant integration conventions. The integration
MUST pass both `hassfest` and `hacs/action` validation without warnings.

**Rules**:
- Use `ConfigEntry`-based setup with `async_setup_entry` (no YAML-only config)
- Use `DataUpdateCoordinator` for periodic background tasks
- All I/O MUST run via `hass.async_add_executor_job()` (never block the event loop)
- Expose services via `services.yaml` with proper schemas
- Provide `strings.json` and `translations/` for config flow UI
- Implement `diagnostics.py` for the HA diagnostics endpoint
- Support `OptionsFlow` for post-setup reconfiguration

**Rationale**: Home Assistant has well-documented integration patterns. Deviating
from them creates maintenance burden, breaks UI consistency, and causes HACS
submission rejection.

## Performance Standards

The integration MUST operate within these resource bounds on reference hardware
(Raspberry Pi 4, 2 GB RAM, Home Assistant OS):

| Metric | Limit | Verification |
|--------|-------|-------------|
| Additional RAM | < 100 MB | `htop` after 24h simulation |
| Average CPU | < 5% | `top` during idle simulation |
| Learning cycle | < 30 seconds | Coordinator update for 50 entities |
| Simulation tick | < 100 ms | Single tick() call with 50 entities |
| Storage (50 entities, 2 year-groups) | < 2 MB | `du -sh .storage/we_are_home/` |
| Event bus rate | < 2 events/second | Avoid flooding during simulation ticks |

### Test Coverage Standard

The project MUST maintain a minimum of **80% line coverage** across all
production modules in `custom_components/we_are_home/`.

**Rules**:
- Every `[pro]` task in `tasks.md` MUST have a corresponding test task
- `/speckit-tasks` MUST generate test tasks for all `[pro]` implementation
  tasks automatically
- `/speckit-implement` MUST implement tests alongside production code and
  validate coverage before reporting completion
- Coverage is measured via `pytest --cov=custom_components/we_are_home --cov-report=term --cov-fail-under=80`
- PRs MUST pass the coverage gate in CI; PRs with <80% coverage MUST be rejected
- Test files follow the naming convention `tests/test_<module>.py` mirroring
  the source module structure

**Coverage targets by module criticality**:

| Module criticality | Minimum | Modules |
|---|---|---|
| Core algorithms | ≥ 90% | `learner.py`, `simulator.py` |
| Data models | ≥ 85% | `time_profile.py`, `sequence_rule.py` |
| Integration layer | ≥ 75% | `services.py`, `config_flow.py`, `storage.py` |
| Infrastructure | ≥ 70% | `history_reader.py`, `coordinator.py`, `switch.py`, `diagnostics.py` |

## Development Workflow

### SpecKit-Driven

All feature work follows the SpecKit pipeline: `/speckit-specify` →
`/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` →
`/speckit-analyze` → `/speckit-implement`.

Tests are NOT optional — `/speckit-tasks` MUST generate test tasks for every
`[pro]` implementation task, and `/speckit-implement` MUST execute them
alongside production code with coverage validation.

### Branch Conventions

All work MUST follow these branch naming and targeting rules:

| Branch Type | Naming Pattern | Target for PR | Example |
|---|---|---|---|
| **Release** | `release/X.Y.Z` | — (base branch) | `release/0.1.0` |
| **Feature** | `feature/description` | `release/X.Y.Z` | `feature/add-mqtt-support` |
| **Fix** | `fix/description` | `release/X.Y.Z` | `fix/profile-load-error` |
| **Hotfix** | `hotfix/description` | `main` | `hotfix/crash-on-empty-history` |

**Rules**:
- The latest `release/X.Y.Z` branch MUST always exist and be the default
  integration target for features and fixes
- Feature and fix branches MUST have their PRs opened against the current
  release branch
- Hotfix branches MUST have their PRs opened directly against `main`
- Branch descriptions MUST use lowercase kebab-case
- The `/speckit-branch` command automates branch creation, commit, push, and
  PR creation with the correct target per these conventions

### Model-Aware Task Execution

Every task in `tasks.md` MUST carry a `[pro]` or `[flash]` model tag:

- **`[pro]`** (deepseek-v4-pro / opus-tier): Algorithm implementation, async
  integration logic, simulation engine, edge case handling, multi-instance
  architecture
- **`[flash]`** (deepseek-v4-flash / haiku-tier): JSON/YAML config files, data
  class definitions, translation files, CI/CD workflows, documentation,
  validation runs

A `[pro]` task MUST NOT be executed with a flash model. A `[flash]` task MUST
NOT consume pro-tier compute resources.

### Quality Gates

Before any release:
1. `hassfest` validation passes (0 errors)
2. `hacs/action` validation passes
3. **Test coverage ≥ 80%** (`pytest --cov --cov-fail-under=80`)
4. Manual integration test on a real Home Assistant instance with ≥7 days of
   recorder history
5. Performance profiling confirms all metrics in Performance Standards table

Before merging any PR:
1. All CI checks pass (HACS + Hassfest + coverage)
2. Coverage diff shows no decrease from baseline

## Governance

This constitution supersedes all other project practices and conventions. Any
deviation from a MUST clause requires a documented amendment to this document.

**Amendment Process**:
1. Propose change via GitHub issue with "Constitution" label
2. Discussion period (minimum 48 hours)
3. Approval by project maintainer
4. Update this file with version bump and Sync Impact Report

**Versioning**: `MAJOR.MINOR.PATCH` per semantic versioning.
- MAJOR: Principle removal or redefinition (backward-incompatible governance)
- MINOR: New principle or section added
- PATCH: Clarifications, wording, typo fixes

**Compliance**: All PRs and `/speckit-implement` runs MUST verify alignment with
these principles. The `/speckit-analyze` command checks for constitution
violations automatically.

**Version**: 1.2.0 | **Ratified**: 2026-08-08 | **Last Amended**: 2026-08-08
