# Quickstart: We Are Home

**Feature**: Simulador de Presença Inteligente
**Date**: 2026-08-08

## Prerequisites

- Home Assistant 2024.10+ running on Python 3.12+
- Recorder integration enabled (default) with at least 7 days of history
- History integration enabled (default)
- HACS installed (for installation)

## Installation

### Via HACS (Recommended)

1. Open HACS → Integrations → "⋮" menu → Custom repositories
2. Add repository URL: `https://github.com/<user>/we-are-home`
3. Category: Integration
4. Search "We Are Home" → Download
5. Restart Home Assistant

### Manual

```bash
cd /config/custom_components
git clone https://github.com/<user>/we-are-home.git we_are_home
# Restart Home Assistant
```

## Configuration

1. Go to **Settings** → **Devices & Services** → **+ Add Integration**
2. Search "We Are Home"
3. Select entities to learn and control (lights, switches, covers, etc.)
4. Adjust parameters (or keep defaults):
   - **Learning interval**: 60 min
   - **Simulation tick**: 30 sec
   - **Sequence window**: 60 min
   - **Min confidence**: 0.3
   - **Restore states**: ON
5. Click **Submit**

The integration creates a `switch.we_are_home` entity.

## Initial Learning

After configuration, the system immediately starts learning:

1. **First 2 minutes**: Initial profile generation from available history
2. **Ongoing**: Incremental updates every 60 minutes (configurable)

Check `switch.we_are_home` attributes to monitor:
- `profiles_loaded` / `profiles_ready`
- `last_training` timestamp

## Running Simulation

### Manual

Toggle `switch.we_are_home` ON in your dashboard.

### Automated (via Automation)

```yaml
automation:
  - alias: "Simulate presence when away"
    trigger:
      - platform: state
        entity_id: person.you
        to: "not_home"
    action:
      - service: we_are_home.start
```

## Verification Scenarios

### Scenario 1: Profile Generation

**Prerequisites**: Config saved with ≥5 entities

1. Wait 2 minutes after setup
2. Call service: `we_are_home.get_profile` with `entity_id: light.<any>`
3. **Expected**: Response has `confidence > 0.3`, `peak_hours` populated, `total_observations > 0`

### Scenario 2: Sequence Discovery

**Prerequisites**: ≥14 days of history with ≥2 correlated entities

1. Wait for first learning cycle to complete
2. Call service: `we_are_home.list_rules`
3. **Expected**: Response lists rules where `occurrences ≥ 3` and `confidence ≥ 0.5`

### Scenario 3: Simulation Activation

**Prerequisites**: Profiles ready (`profiles_ready > 0`)

1. Toggle `switch.we_are_home` ON
2. Wait 1-5 minutes
3. Observe Home Assistant log or event bus for `we_are_home_command` events
4. **Expected**: Entities receive `turn_on`/`turn_off` commands; `commands_sent` attribute increments

### Scenario 4: State Restoration

**Prerequisites**: Simulation active, `restore_states: true`

1. Note current states of controlled entities
2. Toggle `switch.we_are_home` OFF
3. **Expected**: Entities return to their pre-simulation states within 30 seconds

### Scenario 5: Sequence Boost Behavior

**Prerequisites**: At least one sequence rule discovered

1. Start simulation at a time when source entity typically turns on
2. Watch for `we_are_home_sequence_triggered` event
3. Observe target entity receives command within learned delay ± std
4. **Expected**: Target entity turns on/off with timing consistent with learned distribution

### Scenario 6: Long-Running Stability

**Prerequisites**: Simulation active

1. Let simulation run for 24 hours
2. Check Home Assistant memory usage: `we_are_home` should stay <100 MB
3. Check CPU: <5% average on Raspberry Pi 4
4. **Expected**: No memory leaks, no progressively increasing CPU, no event bus flooding

## Troubleshooting

| Symptom | Check |
|---|---|
| No profiles loaded | Verify recorder has ≥7 days of data for selected entities |
| Low confidence | Wait more days; entities with irregular usage need more data |
| No sequences discovered | Verify `sequence_window` is large enough for your patterns |
| Simulation sends no commands | Check `min_confidence` threshold; lower if too strict |
| Entities not restoring | Verify `restore_states` is enabled in Options |
