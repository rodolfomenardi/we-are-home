# Implementation Plan: We Are Home

**Branch**: `001-we-are-home` | **Date**: 2026-08-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-we-are-home/spec.md`

## Summary

Desenvolver uma integração customizada para Home Assistant que aprende padrões probabilísticos de uso de dispositivos a partir do histórico (recorder) e gera simulações de presença realistas. Diferencia-se do `presence_simulation` existente por usar modelos probabilísticos leves (perfis temporais com EMA, regras de associação temporal entre pares de entidades) em vez de simples replay de histórico. Distribuição via HACS.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: Home Assistant Core (>=2024.10.0), numpy (included in HA)

**Storage**: JSON files in `.storage/we_are_home/` (profiles, rules, config) + read-only access to recorder SQLite database

**Testing**: pytest + pytest-homeassistant-custom-component

**Target Platform**: Home Assistant OS / Container / Core on Linux (Raspberry Pi 4+, x86)

**Project Type**: Home Assistant custom integration (Python package in `custom_components/`)

**Performance Goals**: <100 MB RAM, <5% CPU on RPi4 idle, <30s per learning cycle (50 entities), simulation tick <100ms

**Constraints**: 100% local (no cloud), no external Python packages beyond those in HA core, Python stdlib + numpy only

**Scale/Scope**: 1-50 entities per instance, 7-365 days of history, single home deployment

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution is a template with no defined principles. No gates to evaluate.

## Project Structure

### Documentation (this feature)

```text
specs/001-we-are-home/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── integration-contracts.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
custom_components/
└── we_are_home/
    ├── __init__.py              # async_setup, async_setup_entry, DOMAIN
    ├── manifest.json            # Integration metadata (HACS + HA)
    ├── config_flow.py           # UI configuration flow
    ├── const.py                 # Constants, defaults
    ├── coordinator.py           # DataUpdateCoordinator for learning loop
    ├── switch.py                # Switch entity for simulation toggle
    ├── services.py              # Service handlers (start, stop, train, get_profile, list_rules)
    ├── services.yaml            # Service definitions
    ├── strings.json             # Translations (English)
    ├── diagnostics.py           # Diagnostics endpoint
    ├── models/
    │   ├── __init__.py
    │   ├── time_profile.py      # TimeProfile, TimeSlot data classes
    │   ├── sequence_rule.py     # SequenceRule, ActiveBoost data classes
    │   └── learner.py           # Incremental learning engine (EMA, sequence discovery)
    ├── history_reader.py        # Optimized recorder query interface
    ├── simulator.py             # Simulation engine (sampler, boost manager)
    ├── storage.py               # JSON persistence layer
    └── translations/
        ├── en.json
        └── pt-BR.json

hacs.json                        # HACS metadata (repo root)
.github/
└── workflows/
    ├── hacs.yaml                # HACS validation action
    └── hassfest.yaml            # Home Assistant validation action

tests/
├── conftest.py                  # pytest fixtures (hass, recorder_mock)
├── test_config_flow.py          # Config flow tests
├── test_learner.py              # Learning engine tests
├── test_simulator.py            # Simulation engine tests
├── test_sequence_discovery.py   # Sequence rule discovery tests
├── test_services.py             # Service handler tests
└── test_storage.py              # Persistence tests
```

**Structure Decision**: Single project (Home Assistant custom integration). The `custom_components/we_are_home/` directory follows HA conventions. Tests live in a top-level `tests/` directory following `pytest-homeassistant-custom-component` patterns. GitHub Actions workflows validate HACS and HA compliance.

## Complexity Tracking

No constitution violations. N/A.
