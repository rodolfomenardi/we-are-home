# Research: We Are Home — Home Assistant Integration

**Feature**: Simulador de Presença Inteligente
**Date**: 2026-08-08

## 1. Home Assistant Integration Architecture

### Decision: Custom Integration (async, config-flow based)

**Rationale**: Home Assistant modern integrations use `ConfigEntry`-based setup with async/await. The recommended pattern is:

- `__init__.py` with `async_setup` and `async_setup_entry`
- `config_flow.py` for UI-based configuration
- `DataUpdateCoordinator` for periodic background tasks (learning loop)
- `switch.py` platform for the simulation toggle entity
- `services.py` + `services.yaml` for exposed services

**Alternatives considered**:
- YAML-only configuration — deprecated, not HACS-compatible for new integrations
- MQTT-based external service — violates local-only constraint, adds complexity

### Decision: Use recorder.get_instance(hass) for history access

**Rationale**: Home Assistant's `recorder` integration stores state history in SQLite (default) or MySQL/PostgreSQL. The standard approach for integrations to query history is via `recorder.get_instance(hass).async_add_executor_job()` with SQL queries, or via the higher-level `history` integration's API. Using the recorder directly gives us optimized batch queries.

**Reference**: [Home Assistant recorder docs](https://developers.home-assistant.io/docs/core/entity/recorder)

### Decision: JSON storage for learned profiles

**Rationale**: Home Assistant uses `.storage/` directory for integration state (JSON files). Storing TimeProfiles and SequenceRules as JSON in `.storage/we_are_home/` follows conventions and survives restarts. For 50 entities with 672-slot profiles, total storage is ~500 KB — negligible.

**Alternatives considered**:
- Custom SQLite database — overkill, adds migration burden
- In-memory only (rebuild on restart) — wasteful for CPU and slow to bootstrap
- HA `hass.data[DOMAIN]` only — lost on restart

## 2. Probabilistic Model Design

### Decision: Per-entity time-window profiles with exponential moving average (EMA)

**Rationale**: Each entity gets a profile discretized into time windows (15-min slots × 7 days × 2 day-groups = 1344 windows when considering weekday/weekend split). Each window stores P(on), P(transition), mean_duration, std_duration. Updates use EMA with α=0.3 (configurable), giving more weight to recent data without forgetting historical patterns.

**Alternatives considered**:
- Full retraining from scratch — wasteful, slow, loses long-term patterns
- Simple average — doesn't adapt to changing routines
- Sliding window (last N days) — loses seasonal patterns (winter vs summer routines)

### Decision: Pairwise temporal association rules for sequences

**Rationale**: As clarified in spec, the system discovers A→B pairs (entity A changes state → entity B changes state within time window W, with mean delay μ and std σ). Discovery is O(n²) in worst case but prunes aggressively:
- Only consider pairs where both entities changed state within the time window
- Minimum 3 occurrences to create a rule
- Only store rules with statistical significance (Z-score > 1.96 for observed frequency vs random chance)

During simulation, when A fires, B gets a probability boost = base_probability × boost_factor × decay(t), where decay(t) is a Gaussian centered at the learned mean delay.

**Alternatives considered**:
- Full episode mining (Apriori/PrefixSpan) — O(2^n) complexity, too heavy for RPi
- No sequence learning — misses the key user requirement about chained behaviors
- Deterministic rule execution (always fire B when A fires) — unrealistic, makes simulation predictable

### Decision: Day-of-week clustering via automatic variance analysis

**Rationale**: The system starts by assuming 7 independent day profiles. After accumulating ≥14 days of data, it runs a similarity check: for each pair of days, compute Jensen-Shannon divergence between their probability distributions. Days with JS divergence < threshold (0.15) are merged. In practice, this auto-discovers weekend (Sat+Sun) and weekday (Mon-Fri) clusters, with Wednesday potentially splitting off (mid-week patterns).

**Alternatives considered**:
- Hardcoded weekday/weekend split — fails for users with non-standard work schedules
- K-means clustering — requires scikit-learn, violates no-heavy-deps constraint
- Manual only — less automation, worse UX

## 3. HACS Distribution Requirements

### Decision: Standard HACS integration structure

**Requirements confirmed**:
- `hacs.json` at repo root with `name` and `render_readme: true`
- GitHub Actions: `hacs/action@main` + `home-assistant/actions/hassfest@master`
- Brand registration at `home-assistant/brands` repository
- Public GitHub repo with tagged releases (v1.0.0+)
- `manifest.json` with `version`, `codeowners`, `config_flow: true`

**Reference**: [HACS Integration Guide](https://hacs.xyz/docs/publish/start)

## 4. Performance & Constraints

### Decision: Numpy for vectorized probability calculations

**Rationale**: numpy is already a dependency of Home Assistant core. All probability calculations (sampling from distributions, computing means/stds, EMA updates) can be vectorized. For 50 entities, a full learning update is ~100ms on RPi4.

### Decision: Async I/O for recorder queries

**Rationale**: Recorder queries can be slow (SQLite on SD card). All history reads use `async_add_executor_job()` to run in thread pool, keeping the HA event loop responsive. Learning coordinator runs at low priority.

### Decision: Throttled simulation loop

**Rationale**: Simulation checks at fixed intervals (default 30s, configurable). Each tick: evaluate which entities should change state based on current time slot probabilities + active sequence boosts, then batch-send commands via `hass.services.async_call()`. Avoids flooding the event bus.

## 5. Testing Strategy

### Decision: pytest-homeassistant-custom-component

**Rationale**: The `pytest-homeassistant-custom-component` package provides HA test fixtures (`hass`, `recorder_mock`, `enable_custom_integrations`). Tests cover:
- Config flow (valid/invalid entity selection)
- Learning engine (profile generation from mock history)
- Simulation engine (correct state changes given profiles)
- Sequence discovery (correct pair detection from mock sequences)
- Edge cases (empty history, entity offline, recorder purge)

**Alternatives considered**:
- Manual testing only — insufficient for HACS submission quality
- HA built-in test framework — pytest-hass is the standard
