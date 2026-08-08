# Tasks: We Are Home

**Input**: Design documents from `specs/001-we-are-home/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Não explicitamente solicitados na especificação. Incluídos como tarefa de validação na fase final.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [Model] [P?] [Story] Description`

- **[ID]**: Task ID (T001, T002, etc.)
- **[Model]**: Execution model — `[pro]` for deepseek-v4-pro (complex logic, algorithms, integration) or `[flash]` for deepseek-v4-flash (boilerplate, config, docs)
- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Integration source**: `custom_components/we_are_home/` at repository root
- **Tests**: `tests/` at repository root
- **CI/CD**: `.github/workflows/` at repository root
- **Root files**: `hacs.json`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, CI/CD, and scaffolding

- [x] T001 [flash] Create project directory structure per implementation plan in custom_components/we_are_home/
- [x] T002 [flash] [P] Create hacs.json at repository root with name "We Are Home" and render_readme: true
- [x] T003 [flash] [P] Create GitHub Actions workflow for HACS validation in .github/workflows/hacs.yaml using hacs/action@main
- [x] T004 [flash] [P] Create GitHub Actions workflow for Hassfest validation in .github/workflows/hassfest.yaml using home-assistant/actions/hassfest@master
- [x] T005 [flash] [P] Create tests/conftest.py with pytest fixtures (hass, recorder_mock, enable_custom_integrations)
- [x] T006 [flash] [P] Create requirements_dev.txt with pytest, pytest-homeassistant-custom-component, pytest-asyncio

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core constants, manifest, storage layer, and history reader — needed by all user stories

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T007 [flash] Create const.py with DOMAIN="we_are_home", default configuration constants, supported domains list, and platform definitions in custom_components/we_are_home/const.py
- [x] T008 [flash] Create manifest.json with domain, name, version (0.1.0), codeowners, config_flow, iot_class, documentation URL in custom_components/we_are_home/manifest.json
- [x] T009 [flash] [P] Create translation strings for English in custom_components/we_are_home/translations/en.json (config flow labels, errors, service descriptions)
- [x] T010 [flash] [P] Create translation strings for Portuguese (Brazil) in custom_components/we_are_home/translations/pt-BR.json
- [x] T011 [pro] Create storage layer in custom_components/we_are_home/storage.py with JSON read/write for profiles, sequence rules, and entity configs under .storage/we_are_home/
- [x] T012 [pro] Create history_reader.py in custom_components/we_are_home/history_reader.py with async query interface to recorder database (state history extraction, batch query, optimization for SQLite via executor thread pool). Handle edge case: corrupted or purged recorder returns empty dataset with error log, learning gracefully degrades.
- [x] T013 [flash] Create services.yaml defining service schemas for we_are_home.start, we_are_home.stop, we_are_home.train, we_are_home.get_profile, we_are_home.list_rules in custom_components/we_are_home/services.yaml

**Checkpoint**: Foundation ready — all integration infrastructure in place, ready for user story implementation

---

## Phase 3: User Story 1 - Configurar Integração e Selecionar Dispositivos (Priority: P1) 🎯 MVP

**Goal**: User installs the integration via HACS, configures it through Home Assistant UI, selects entities to monitor

**Independent Test**: Install integration in any Home Assistant instance with recorder active, add the "We Are Home" integration, select entities, save — a switch entity `switch.we_are_home` appears in the dashboard

### Implementation for User Story 1

- [x] T014 [pro] [US1] Create __init__.py with async_setup, async_setup_entry, async_unload_entry, DOMAIN constant, and platform registration in custom_components/we_are_home/__init__.py
- [x] T015 [pro] [US1] Create config_flow.py with ConfigFlow class (entity multi-select with domain filtering, validation, OptionsFlow for reconfiguration) in custom_components/we_are_home/config_flow.py. Handle edge case: when entity is removed from config, its profile is preserved but excluded from simulation; any SequenceRules where it was source or target are deactivated.
- [x] T016 [flash] [P] [US1] Create EntityConfig data class in custom_components/we_are_home/models/__init__.py with entity_id, domain, enabled, min_confidence_threshold, restore_on_stop fields
- [x] T017 [flash] [P] [US1] Create SimulationState data class in custom_components/we_are_home/models/__init__.py with instance_id, active, started_at, entities dict, active_boosts list
- [x] T018 [flash] [US1] Create strings.json for config flow translations in custom_components/we_are_home/strings.json
- [x] T019 [pro] [US1] Create basic switch entity in custom_components/we_are_home/switch.py with async_setup_entry, PresenceSimulationSwitch class (on/off toggle, entity attributes: entities_controlled, profiles_loaded, profiles_ready, simulation_uptime)

**Checkpoint**: Integration installable, configurable via UI, switch entity visible and togglable (no simulation logic yet)

---

## Phase 4: User Story 2 - Aprendizado Automático de Padrões (Priority: P1) 🎯 MVP

**Goal**: System queries recorder history, builds probabilistic TimeProfiles per entity, discovers SequenceRules between entity pairs, updates incrementally

**Independent Test**: Configure integration with ≥7 days of history, wait for initial learning cycle, call `get_profile` service — returns probabilities per day/hour with confidence > 0.3 and weekend vs weekday differentiation

### Implementation for User Story 2

- [x] T020 [flash] [P] [US2] Create TimeSlot data class in custom_components/we_are_home/models/time_profile.py with slot_index, p_on, p_transition, mean_duration_on, std_duration_on, sample_count, last_updated fields
- [x] T021 [pro] [US2] Create TimeProfile class in custom_components/we_are_home/models/time_profile.py with entity_id, day_group (weekday/weekend), 96 slots array, confidence, total_observations, and EMA update method
- [x] T022 [flash] [P] [US2] Create SequenceRule data class in custom_components/we_are_home/models/sequence_rule.py with source_entity, source_state, target_entity, target_state, mean_delay, std_delay, occurrence_count, confidence, boost_factor fields
- [x] T023 [flash] [P] [US2] Create ActiveBoost data class in custom_components/we_are_home/models/sequence_rule.py with rule_id, target_entity, multiplier, activated_at, expires_at fields and decay function
- [x] T024 [pro] [US2] Implement TimeProfile learner in custom_components/we_are_home/models/learner.py — build_time_profiles(history_data, entities) that constructs per-entity profiles from recorder state history, computing p_on per slot with EMA (alpha=0.3). Handle edge cases: insufficient history (<24h) results in COLD maturity with warning; high-frequency entities (motion sensors) are filtered by minimum state duration threshold; entities not in recorder return empty profile with zero confidence.
- [x] T025 [pro] [US2] Implement day-of-week clustering in custom_components/we_are_home/models/learner.py — auto_detect_day_groups(profiles) using Jensen-Shannon divergence between day distributions, merging days below 0.15 threshold into weekday/weekend groups
- [x] T026 [pro] [US2] Implement sequence rule discovery in custom_components/we_are_home/models/learner.py — discover_sequence_rules(history_data, window_minutes=60, min_occurrences=3) that scans for A→B temporal pairs, computes mean_delay and std_delay, filters by statistical significance
- [x] T027 [pro] [US2] Implement incremental learning update in custom_components/we_are_home/models/learner.py — incremental_update(existing_profiles, new_history) that applies EMA to slot probabilities and updates sequence rule occurrences without full retraining
- [x] T028 [pro] [US2] Create DataUpdateCoordinator in custom_components/we_are_home/coordinator.py with configurable polling interval (default 60 min), async _async_update_data() calling learner and storage persistence
- [x] T029 [flash] [US2] Create diagnostics endpoint in custom_components/we_are_home/diagnostics.py exposing entity profiles summary, confidence levels, sequence rule count, and last learning run metrics
- [x] T030 [pro] [US2] Integrate learning coordinator into __init__.py async_setup_entry — initialize coordinator on config entry setup, handle coordinator lifecycle

**Checkpoint**: Learning engine fully functional — profiles generated, sequences discovered, incremental updates working, diagnostics accessible

---

## Phase 5: User Story 3 - Ativar e Desativar Simulação (Priority: P2)

**Goal**: User toggles switch to start simulation; system generates synthetic device commands based on learned profiles and sequence boosts; toggling off optionally restores previous states

**Independent Test**: With profiles learned, toggle switch ON → within minutes devices receive turn_on/turn_off commands consistent with weekday/weekend patterns; toggle OFF → states optionally restored

### Implementation for User Story 3

- [x] T031 [pro] [US3] Implement simulation engine in custom_components/we_are_home/simulator.py — SimulationEngine class with tick() method that: evaluates current time slot probabilities for each entity, samples p_on with Gaussian noise, decides state changes, applies active sequence boosts as temporary probability multipliers
- [x] T032 [pro] [US3] Implement boost manager in custom_components/we_are_home/simulator.py — BoostManager class that: on entity state change queries matching SequenceRules, creates ActiveBoost instances with Gaussian decay over learned mean_delay ± std_delay, expires stale boosts. Handle edge case: conflicting rules (A→B and A→C with overlapping delays) share probability boost proportionally; interrupted sequences (A fired, B didn't occur) have boost naturally expire without side effects.
- [x] T033 [flash] [US3] Implement state capture/restore in custom_components/we_are_home/simulator.py — capture_entity_states(hass, entities) and restore_entity_states(hass, captured_states) for optional pre-simulation state restoration
- [x] T034 [pro] [US3] Update switch.py PresenceSimulationSwitch with async_turn_on (starts simulation loop, captures states) and async_turn_off (stops loop, optionally restores states) using simulation engine
- [x] T035 [pro] [US3] Implement simulation loop in coordinator.py — add simulation tick at configurable interval (default 30s), batch-send commands via hass.services.async_call(), fire we_are_home_command events
- [x] T036 [pro] [US3] Add entity conflict detection in custom_components/we_are_home/simulator.py — skip sending commands to entities manually operated within the last tick (configurable grace period), implement last-command-wins policy
- [x] T037 [pro] [US3] Add simulation edge case handling: skip entities below min_confidence (with warning log), handle entity going unavailable mid-simulation, handle HA restart with simulation state recovery via storage, handle new entity added mid-simulation (start controlling immediately if profile has min_confidence, otherwise wait for next learning cycle)

**Checkpoint**: Full simulation loop working — toggle ON/OFF, devices follow learned patterns, sequences boost probabilities, states optionally restored

---

## Phase 6: User Story 4 - Visualizar Perfis e Confiança (Priority: P3)

**Goal**: User can inspect learned profiles, confidence levels, and discovered sequence rules via services and diagnostics

**Independent Test**: Call `we_are_home.get_profile` for a specific entity → receive structured response with probabilities by day/time and confidence level; call `we_are_home.list_rules` → receive list of discovered sequence rules

### Implementation for User Story 4

- [x] T038 [flash] [P] [US4] Implement get_profile service handler in custom_components/we_are_home/services.py — query storage for entity TimeProfile, format response with day_groups (weekday/weekend peak_hours, avg_on_probability), confidence, total_observations, related sequence rules
- [x] T039 [flash] [P] [US4] Implement list_rules service handler in custom_components/we_are_home/services.py — query storage for all SequenceRules, support entity_id filter and min_confidence filter, format response with source, target, delays, confidence, occurrences
- [x] T040 [flash] [US4] Register services in __init__.py — wire get_profile and list_rules service calls to handlers, add service schemas
- [x] T041 [flash] [US4] Enhance diagnostics.py with detailed entity breakdown: per-entity confidence, slot coverage (how many slots have data), last observation timestamp, profile maturity level (COLD/WARM/HOT/STABLE)
- [x] T042 [flash] [US4] Enhance diagnostics.py with sequence rule summary: total rules, rules per entity pair, average confidence, most frequent sequences, discovery window used
- [x] T043 [flash] [P] [US4] Add entity attributes to switch entity in switch.py to expose real-time simulation metrics: active_boosts count, commands_sent counter, last command timestamp, last training timestamp

**Checkpoint**: Full observability — users can inspect profiles, debug confidence issues, view sequence rules

---

## Phase 7: User Story 5 - Integrar com Automações (Priority: P3)

**Goal**: Advanced users can trigger simulation via Home Assistant automations using services, with parameter overrides for custom scenarios

**Independent Test**: Create a Home Assistant automation that calls `we_are_home.start` when a device tracker leaves home → simulation starts automatically

### Implementation for User Story 5

- [x] T044 [flash] [P] [US5] Implement start service handler in custom_components/we_are_home/services.py — support switch_id (for multi-instance), entity_id override, restore_states override parameters
- [x] T045 [flash] [P] [US5] Implement stop service handler in custom_components/we_are_home/services.py — support switch_id parameter, return restored_entities count
- [x] T046 [pro] [P] [US5] Implement train service handler in custom_components/we_are_home/services.py — support entity_id filter, full_reset flag, days_back parameter for historical range
- [x] T047 [flash] [US5] Register start, stop, train services in __init__.py — wire service calls to handlers
- [x] T048 [flash] [US5] Add service response schemas: start returns instance_id, stop returns restored_entities count, train returns entities_processed/new_observations/rules_discovered/duration_ms
- [x] T049 [flash] [P] [US5] Fire events on Home Assistant event bus from services.py: we_are_home_command (entity_id, service, reason, probability, triggered_by_sequence), we_are_home_sequence_triggered (rule_id, source, target, mean_delay, boost_multiplier)
- [x] T050 [pro] [US5] Implement multi-instance support — allow creating multiple We Are Home configuration entries with different entity sets and parameters, each with its own switch entity

**Checkpoint**: Full automation integration — all services functional, events firing, multi-instance support working

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: HACS submission readiness, documentation, validation, and hardening

- [x] T051 [flash] [P] Run hassfest validation and fix any manifest/translation/schema issues
- [x] T052 [flash] [P] Run HACS validation action and fix any compliance issues
- [x] T053 [flash] [P] Write comprehensive README.md in Portuguese and English with installation (HACS + manual), configuration guide, service examples, and troubleshooting
- [x] T054 [flash] [P] Create LICENSE file (MIT) at repository root
- [x] T055 [flash] [P] Create CHANGELOG.md with semantic versioning format
- [x] T056 [flash] Create initial git tag v0.1.0 for first development release
- [x] T057 [flash] Run quickstart.md validation scenarios 1-6 end-to-end and document results
- [x] T058 [pro] [P] Performance profiling: verify <100 MB RAM, <5% CPU on Raspberry Pi 4 during 24h simulation using quickstart scenario 6
- [x] T059 [pro] Code review: verify all async/await patterns correct, no blocking I/O in event loop, proper error handling and logging throughout

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational — provides integration skeleton + config
- **User Story 2 (Phase 4)**: Depends on US1 models + config — core learning engine
- **User Story 3 (Phase 5)**: Depends on US2 profiles — simulation uses learned data
- **User Story 4 (Phase 6)**: Depends on US2 profiles + US3 simulation — exposes learned data
- **User Story 5 (Phase 7)**: Depends on US3 services — wraps simulation with service layer
- **Polish (Phase 8)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational — No dependencies on other stories
- **US2 (P1)**: Can start after US1 completion (needs models + config entries)
- **US3 (P2)**: Can start after US2 completion (needs learned profiles)
- **US4 (P3)**: Can start after US2 completion (needs profiles to display)
- **US5 (P3)**: Can start after US3 completion (needs simulation services)

### Within Each User Story

- Models before logic
- Logic before integration into __init__.py
- Core implementation before edge cases
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel: T002, T003, T004, T005, T006
- All Foundational tasks marked [P] can run in parallel: T009, T010 (translations)
- Within US1: T016 [P] and T017 [P] can run in parallel (separate data classes)
- Within US2: T020 [P], T022 [P], T023 [P] can run in parallel (separate model files)
- Within US4: T038 [P], T039 [P], T043 [P] can run in parallel
- Within US5: T044 [P], T045 [P], T046 [P], T049 [P] can run in parallel
- Polish phase: T051-T055, T058 all [P] can run in parallel

---

## Parallel Example: User Story 4

```bash
# Launch all independent service handlers together:
Task: "Implement get_profile service handler in custom_components/we_are_home/services.py"
Task: "Implement list_rules service handler in custom_components/we_are_home/services.py"
Task: "Add entity attributes to switch entity in custom_components/we_are_home/switch.py"
```

## Parallel Example: User Story 5

```bash
# Launch all independent service handlers together:
Task: "Implement start service handler in custom_components/we_are_home/services.py"
Task: "Implement stop service handler in custom_components/we_are_home/services.py"
Task: "Implement train service handler in custom_components/we_are_home/services.py"
Task: "Fire events on Home Assistant event bus from services.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Setup → Project scaffold + CI green
2. Complete Phase 2: Foundational → Core infrastructure ready
3. Complete Phase 3: US1 → Integration installable, configurable via UI
4. Complete Phase 4: US2 → Learning engine functional, profiles generated
5. **STOP and VALIDATE**: Test US1 + US2 independently per spec acceptance criteria
6. Integration is already testable: install in HA instance, configure entities, verify profiles generated

### Incremental Delivery

1. Setup + Foundational → Integration skeleton with CI passing
2. + US1 → Configurable integration, switch entity visible (first demo)
3. + US2 → Learning engine running, profiles discoverable (core value demo)
4. + US3 → Simulation functional, devices controlled (full MVP!)
5. + US4 → Diagnostics and profile inspection (debuggability)
6. + US5 → Automation integration, multi-instance (power users)
7. + Polish → HACS-ready, documented, tested

### Suggested MVP Scope

**T001-T030** (Setup + Foundational + US1 + US2) = 30 tasks covering the core learning capability. This delivers the fundamental value proposition: a Home Assistant integration that learns device usage patterns from history.

Full MVP including simulation: **T001-T037** (Setup + Foundational + US1 + US2 + US3 = 37 tasks).

---

## Notes

- `[pro]` tasks (22) = deepseek-v4-pro: complex logic, algorithms, async integration, edge case handling
- `[flash]` tasks (37) = deepseek-v4-flash: boilerplate, JSON/YAML config, data classes, docs, validation
- [P] tasks = different files, no dependencies — safe to parallelize within the same phase
- [Story] label maps task to specific user story for traceability
- Each user story phase builds on the previous but can be validated independently at its checkpoint
- Commit after each task or logical group (e.g., all models in US2)
- Stop at any checkpoint to validate the story independently
- File paths follow `custom_components/we_are_home/` convention from plan.md
- All service names use `we_are_home.*` prefix per updated contracts
- Switch entity is `switch.we_are_home` (or `switch.we_are_home_<name>` for multi-instance)
