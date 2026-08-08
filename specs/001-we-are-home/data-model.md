# Data Model: We Are Home

**Feature**: Simulador de Presença Inteligente
**Date**: 2026-08-08

## Entities

### TimeProfile

Probabilistic profile for a single entity, learned from historical data.

| Field | Type | Description |
|---|---|---|
| `entity_id` | string | Home Assistant entity ID (e.g., `light.sala`) |
| `domain` | string | Entity domain (`light`, `switch`, `cover`, etc.) |
| `day_group` | string | Day grouping key: `weekday` or `weekend` |
| `slots` | list[TimeSlot] | Array of 96 time slots (15-min windows across 24h) |
| `confidence` | float (0.0–1.0) | Overall confidence in this profile based on observation count |
| `total_observations` | int | Total number of observations incorporated |
| `last_updated` | datetime | Timestamp of last incremental update |

**Validation**:
- `entity_id` must be a valid HA entity ID format
- `confidence` in [0.0, 1.0]
- `slots` must have exactly 96 entries (24h × 4 slots/hour)

### TimeSlot

One 15-minute window within a day-group profile.

| Field | Type | Description |
|---|---|---|
| `slot_index` | int (0–95) | Position in the day (0 = 00:00-00:15, 95 = 23:45-00:00) |
| `p_on` | float (0.0–1.0) | Probability entity is in ON state during this slot |
| `p_transition` | float (0.0–1.0) | Probability entity changes state during this slot |
| `mean_duration_on` | float (minutes) | Mean duration when entity turns ON in this slot |
| `std_duration_on` | float (minutes) | Standard deviation of ON duration |
| `sample_count` | int | Number of observations for this specific slot |
| `last_updated` | datetime | Last time this slot was updated |

**Validation**:
- `p_on`, `p_transition` in [0.0, 1.0]
- `mean_duration_on` > 0
- `std_duration_on` ≥ 0

### SequenceRule

Temporal association rule between two entities (A→B).

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique rule identifier (hash of source+target) |
| `source_entity` | string | Entity that triggers the rule |
| `source_state` | string | State that triggers the rule (`on`, `off`, `playing`, etc.) |
| `target_entity` | string | Entity affected by the rule |
| `target_state` | string | Expected state of target entity |
| `mean_delay` | float (seconds) | Mean delay between source and target events |
| `std_delay` | float (seconds) | Standard deviation of delay |
| `occurrence_count` | int | Number of times this sequence was observed |
| `confidence` | float (0.0–1.0) | Statistical confidence in this rule |
| `boost_factor` | float | Probability multiplier applied during simulation (default: 2.0) |
| `discovery_window` | int (minutes) | Time window used when this rule was discovered |
| `last_observed` | datetime | Last time this sequence occurred |

**Validation**:
- `source_entity` ≠ `target_entity`
- `occurrence_count` ≥ 3 (minimum for rule creation)
- `mean_delay` ≤ `discovery_window * 60` (seconds)
- `boost_factor` ≥ 1.0
- `confidence` in [0.0, 1.0]

### EntityConfig

User configuration for a monitored entity.

| Field | Type | Description |
|---|---|---|
| `entity_id` | string | Home Assistant entity ID |
| `domain` | string | Entity domain |
| `enabled` | bool | Whether entity is active for simulation |
| `min_confidence_threshold` | float (0.0–1.0) | Minimum confidence to use this entity in simulation |
| `restore_on_stop` | bool | Restore pre-simulation state when simulation stops |
| `profile` | TimeProfile | Learned profile (null if not yet learned) |

**Validation**:
- `entity_id` must exist in Home Assistant registry
- `min_confidence_threshold` in [0.0, 1.0], default 0.3

### SimulationState

Runtime state of an active simulation instance.

| Field | Type | Description |
|---|---|---|
| `instance_id` | string | Unique simulation instance identifier |
| `active` | bool | Whether simulation is currently running |
| `started_at` | datetime | When simulation was started |
| `entities` | dict[str, str] | Pre-simulation states: entity_id → last known state |
| `active_boosts` | list[ActiveBoost] | Currently active sequence boosts |
| `override_params` | dict | Optional parameter overrides (delta, brightness, etc.) |

### ActiveBoost

Temporary probability boost from a triggered sequence rule.

| Field | Type | Description |
|---|---|---|
| `rule_id` | string | Reference to the SequenceRule that generated this boost |
| `target_entity` | string | Entity receiving the boost |
| `multiplier` | float | Current boost multiplier (decays over time) |
| `activated_at` | datetime | When the boost was triggered |
| `expires_at` | datetime | When the boost decays to 1.0 (no effect) |

### LearningRun

Record of a learning cycle execution.

| Field | Type | Description |
|---|---|---|
| `timestamp` | datetime | When this learning run started |
| `entities_processed` | int | Number of entities updated |
| `new_observations` | int | Number of new state changes incorporated |
| `rules_discovered` | int | New sequence rules found this run |
| `rules_updated` | int | Existing rules updated this run |
| `duration_ms` | int | Execution time in milliseconds |
| `errors` | list[str] | Any errors encountered |

## State Transitions

### Simulation Lifecycle

```
IDLE → LEARNING → READY → SIMULATING → IDLE
  ↑                 ↑         ↓
  └─── (always) ────┘    PAUSED (simulation stopped)
```

- **IDLE**: No configuration loaded
- **LEARNING**: Initial profile building (blocking, ~seconds)
- **READY**: Profiles loaded, simulation not active
- **SIMULATING**: Actively generating commands
- **PAUSED**: Temporarily stopped, can resume (states optionally restored)

### Entity Profile Maturity

```
COLD (0 days) → WARM (1-3 days) → HOT (3-14 days) → STABLE (>14 days)
```

- **COLD**: `confidence < 0.3` — not used in simulation
- **WARM**: `0.3 ≤ confidence < 0.6` — used with low weight
- **HOT**: `0.6 ≤ confidence < 0.85` — normal simulation weight
- **STABLE**: `confidence ≥ 0.85` — full simulation weight

## Relationships

```
EntityConfig 1──1 TimeProfile
EntityConfig *──* SequenceRule (as source or target)
SimulationState 1──* ActiveBoost
ActiveBoost *──1 SequenceRule
```

## Storage Layout

```
.storage/we_are_home/
├── config.json          # List of EntityConfig
├── profiles/
│   ├── light.sala.json  # TimeProfile for light.sala
│   ├── light.cozinha.json
│   └── ...
├── sequence_rules.json  # All SequenceRules
└── learning_log.json    # Last N LearningRun records (rolling)
```
