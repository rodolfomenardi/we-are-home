# Contracts: We Are Home Integration

**Feature**: Simulador de Presença Inteligente
**Date**: 2026-08-08

## 1. Config Flow Schema

The integration exposes a UI configuration flow. Below are the configuration options.

### Initial Setup (ConfigFlow)

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | Yes | "We Are Home" | Display name for this simulation instance |
| `entities` | list[string] | Yes | [] | List of entity IDs to monitor and control |
| `learning_interval` | int (minutes) | No | 60 | How often to run incremental learning |
| `simulation_interval` | int (seconds) | No | 30 | How often the simulation loop ticks |
| `restore_states` | bool | No | true | Restore entity states when simulation stops |
| `min_confidence` | float (0.0–1.0) | No | 0.3 | Minimum confidence threshold for using entity in simulation |
| `sequence_window` | int (minutes) | No | 60 | Maximum time window for discovering event sequences |
| `sequence_min_occurrences` | int | No | 3 | Minimum occurrences to create a sequence rule |
| `boost_factor` | float | No | 2.0 | Default probability boost multiplier for sequences |
| `random_seed` | int or null | No | null | Optional seed for reproducible simulations |

### Options Flow (Reconfiguration)

All parameters above can be modified post-setup via Options flow, plus:

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `entities` | list[string] | No | (current) | Add or remove entities; existing profiles preserved |

### Validation Rules

- `entities`: At least 1 entity required; all must exist in HA registry
- `learning_interval`: Min 15 min, Max 1440 min (24h)
- `simulation_interval`: Min 10 sec, Max 300 sec
- `sequence_window`: Min 15 min, Max 360 min (6h)
- `min_confidence`: 0.0 to 1.0
- Domain support: light, switch, cover, media_player, climate, scene, input_boolean, fan, humidifier

## 2. Services Contract

### `we_are_home.start`

Start the presence simulation.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `switch_id` | string | No* | Which simulation switch to start (required if multiple instances) |
| `entity_id` | list[string] | No | Override: entities to simulate (uses config default if omitted) |
| `restore_states` | bool | No | Override: restore states on stop |

**Response**: `{"success": true, "instance_id": "switch.we_are_home_<name>"}`

### `we_are_home.stop`

Stop the presence simulation.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `switch_id` | string | No* | Which simulation switch to stop |

**Response**: `{"success": true, "restored_entities": 5}`

### `we_are_home.train`

Force a full or partial re-training of learned profiles.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_id` | list[string] | No | Specific entities to retrain (all if omitted) |
| `full_reset` | bool | No | If true, discard existing profiles and relearn from scratch |
| `days_back` | int | No | How many days of history to use (default: all available) |

**Response**: `{"success": true, "entities_processed": 10, "new_observations": 342, "rules_discovered": 3, "duration_ms": 850}`

### `we_are_home.get_profile`

Retrieve the learned profile for an entity.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_id` | string | Yes | Entity to retrieve profile for |

**Response**:
```json
{
  "entity_id": "light.sala",
  "domain": "light",
  "confidence": 0.85,
  "day_groups": {
    "weekday": {
      "peak_hours": ["18:00-21:00"],
      "avg_on_probability": 0.35
    },
    "weekend": {
      "peak_hours": ["10:00-13:00", "18:00-23:00"],
      "avg_on_probability": 0.52
    }
  },
  "sequence_rules_as_source": ["light.sala→media_player.tv"],
  "sequence_rules_as_target": [],
  "total_observations": 1240,
  "last_updated": "2026-08-07T22:00:00"
}
```

### `we_are_home.list_rules`

List all discovered sequence rules.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `entity_id` | string | No | Filter rules involving this entity (all if omitted) |
| `min_confidence` | float | No | Filter by minimum confidence |

**Response**:
```json
{
  "rules": [
    {
      "id": "abc123",
      "source": "light.sala",
      "target": "media_player.tv",
      "mean_delay_seconds": 120,
      "std_delay_seconds": 45,
      "confidence": 0.78,
      "occurrences": 23
    }
  ],
  "total": 1
}
```

## 3. Switch Entity Attributes

The `switch.we_are_home_<name>` entity exposes these attributes:

| Attribute | Type | Description |
|---|---|---|
| `entities_controlled` | list[string] | Entities being simulated |
| `profiles_loaded` | int | Number of entities with learned profiles |
| `profiles_ready` | int | Number of profiles meeting minimum confidence |
| `sequence_rules` | int | Number of active sequence rules |
| `last_training` | datetime | Timestamp of last learning update |
| `active_boosts` | int | Number of currently active sequence boosts |
| `simulation_uptime` | float (hours) | How long simulation has been running |
| `commands_sent` | int | Total commands sent during current simulation |

## 4. Events

The integration fires these events on the Home Assistant event bus:

### `we_are_home_command`

Fired each time the simulation sends a command to an entity.

```json
{
  "event_type": "we_are_home_command",
  "data": {
    "entity_id": "light.sala",
    "service": "turn_on",
    "reason": "time_profile",
    "probability": 0.72,
    "triggered_by_sequence": null
  }
}
```

### `we_are_home_sequence_triggered`

Fired when a sequence rule's boost is activated.

```json
{
  "event_type": "we_are_home_sequence_triggered",
  "data": {
    "rule_id": "abc123",
    "source": "light.sala",
    "target": "media_player.tv",
    "mean_delay": 120.0,
    "boost_multiplier": 2.0
  }
}
```
