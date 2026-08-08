# We Are Home

**Intelligent presence simulation for Home Assistant that learns your home's rhythms.**

[![HACS][hacs-badge]][hacs-url]
[![GitHub Release][release-badge]][release-url]
[![License][license-badge]](LICENSE)

We Are Home learns how you use your devices — lights, switches, media players, covers, climate, and more — by analyzing your Home Assistant recorder history. It builds probabilistic time profiles for each entity, discovers temporal sequence rules between them (e.g., "when the living room light turns on, the TV usually follows 2 minutes later"), and generates realistic synthetic presence simulations. No two simulated days are ever the same.

**100% local. Zero cloud dependencies. No extra pip installs.**

Unlike simpler simulators that replay recorded days verbatim, We Are Home uses statistical models (EMA-updated time profiles, Jensen-Shannon day clustering, pairwise Markov-like sequence rules with Gaussian boost decay) to produce behavior that matches your home's statistical fingerprint without repeating exact historical days.

---

## How It Works

### Learning Engine

1. **History Reading** — Queries Home Assistant's recorder database via `get_significant_states` to extract state-change timelines for each configured entity.

2. **Time Profiles** — Each entity gets a `TimeProfile` with 96 slots per day (15‑minute windows × 24 hours). For each slot, the system tracks `P(on)` (probability the entity is on), `P(transition)`, mean duration, and observation count. Profiles use **Exponential Moving Average** updates (α = 0.3) so new data is incorporated incrementally — no full retraining needed.

3. **Day Clustering** — The system computes Jensen-Shannon divergence between day-of-week profiles and auto‑discovers weekday/weekend groupings when divergence falls below a 0.15 threshold. This means your Saturday patterns are never confused with your Tuesday commute routine.

4. **Sequence Rules** — Pairwise temporal associations (`A → B`) are mined from the history: when entity A changes state, does entity B follow within a configurable window (default 60 minutes)? Rules include mean delay, standard deviation, and occurrence count. Minimum 3 occurrences required by default.

### Simulation Engine

- Every tick (default 30 seconds), the engine reads the current time slot's `P(on)` from the learned profiles.
- **Sequence boosts**: When entity A fires during simulation, any matching `A → B` rule creates an **ActiveBoost** targeting B. The boost is a Gaussian multiplier centered at the learned mean delay, decaying over `mean ± 3σ`. Boosts are capped at a configurable factor (default 5×) and product-combined when multiple rules target the same entity.
- **Boost, not trigger**: Sequences influence probability — they never force events. This prevents domino-effect cascades and keeps the simulation feeling organic.
- **Sampling with randomness**: Every decision passes through a random sampler, so the same slot on two different days produces different outcomes within the learned distribution.
- **Manual override detection**: If you physically operate a device during simulation, a grace period prevents the simulator from immediately countermanding your action.

### Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                  Home Assistant                       │
│  ┌──────────┐  ┌─────────────┐  ┌────────────────┐  │
│  │ Recorder │  │ Config Flow │  │ switch.we_are_ │  │
│  │ (SQLite) │  │   (UI/Options│  │ home           │  │
│  └────┬─────┘  └──────┬──────┘  └───────┬────────┘  │
│       │               │                 │            │
│  ┌────▼───────────────▼─────────────────▼─────────┐  │
│  │              We Are Home Integration             │  │
│  │                                                  │  │
│  │  HistoryReader → Learner → TimeProfiles          │  │
│  │                      ↘ SequenceRules             │  │
│  │                         ↓                        │  │
│  │                    Simulator → BoostManager      │  │
│  │                         ↓                        │  │
│  │                   Entity Commands                │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

---

## Supported Entity Domains

| Domain | Example |
|---|---|
| `light` | `light.sala`, `light.cozinha` |
| `switch` | `switch.fan` |
| `cover` | `cover.persiana_quarto` |
| `media_player` | `media_player.tv` |
| `climate` | `climate.ar_condicionado` |
| `scene` | `scene.cinema` |
| `input_boolean` | `input_boolean.guest_mode` |
| `fan` | `fan.teto` |
| `humidifier` | `humidifier.quarto` |

Motion sensors and other high-frequency entities are automatically filtered out — the system ignores state changes lasting less than 5 seconds.

---

## Installation

### Requirements

- Home Assistant **2024.10.0** or newer
- The `recorder` and `history` integrations enabled (both are default in HA)
- Python 3.12+

### Method 1: HACS (Recommended)

[![Add to HACS][hacs-install-badge]][hacs-url]

1. Make sure [HACS](https://hacs.xyz) is installed.
2. Add this repository as a custom repository:
   - Go to **HACS → Integrations → ⋮ → Custom repositories**
   - URL: `https://github.com/rodolfomenardi/we-are-home`
   - Category: **Integration**
3. Search for "We Are Home" in HACS and click **Download**.
4. **Restart Home Assistant**.

### Method 2: Manual

```bash
cd /path/to/your/ha-config
mkdir -p custom_components/we_are_home
git clone https://github.com/rodolfomenardi/we-are-home.git /tmp/we-are-home
cp -r /tmp/we-are-home/custom_components/we_are_home/* custom_components/we_are_home/
```

Then restart Home Assistant.

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **"We Are Home"** and select it.
3. Choose which entities to monitor and simulate. You can select any combination from the supported domains.
4. Adjust optional parameters:

| Parameter | Default | Description |
|---|---|---|
| **Entities** | *(required)* | Which entities to learn and simulate |
| **Learning interval** | 60 min | How often to pull new data from recorder |
| **Simulation interval** | 30 sec | How often the engine evaluates and fires events |
| **Restore states** | Yes | Restore entity states when simulation stops |
| **Min confidence** | 0.3 | Threshold below which an entity won't be simulated |
| **Sequence window** | 60 min | Max gap to consider two events as a sequence |
| **Min sequence occurrences** | 3 | How many times A→B must appear to become a rule |
| **Boost factor** | 2.0 | Max probability multiplier from sequence rules |
| **Random seed** | *(none)* | Fixed seed for reproducible simulations (optional) |

After saving, a `switch.we_are_home` entity appears. Turn it on to start simulating.

> **Multi‑instance**: You can add the integration more than once (e.g., different entity groups with different intervals). Each instance creates its own switch.

---

## Services

All services are callable from automations, scripts, or the Developer Tools panel.

### `we_are_home.start`

Start the presence simulation.

| Parameter | Required | Description |
|---|---|---|
| `switch_id` | No | Switch entity ID (auto‑detected if single instance) |
| `entity_id` | No | Override which entities to simulate |
| `restore_states` | No | Override the restore-states setting |

```yaml
service: we_are_home.start
data:
  restore_states: false
```

### `we_are_home.stop`

Stop the presence simulation and optionally restore entity states.

| Parameter | Required | Description |
|---|---|---|
| `switch_id` | No | Which simulation switch to stop |

```yaml
service: we_are_home.stop
```

### `we_are_home.train`

Force a training cycle. Use `full_reset: true` to discard existing profiles and relearn from scratch.

| Parameter | Required | Description |
|---|---|---|
| `entity_id` | No | Specific entities to retrain (all if omitted) |
| `full_reset` | No | Discard existing profiles before retraining |
| `days_back` | No | Limit history to N days (all available if omitted) |

```yaml
service: we_are_home.train
data:
  full_reset: true
  days_back: 90
```

### `we_are_home.get_profile`

Retrieve the learned probability profile for an entity.

| Parameter | Required | Description |
|---|---|---|
| `entity_id` | **Yes** | Entity to retrieve profile for |

Returns: day groups with peak-hour ranges, average on-probability, confidence score, observation count, and associated sequence rules.

### `we_are_home.list_rules`

List all discovered sequence rules.

| Parameter | Required | Description |
|---|---|---|
| `entity_id` | No | Filter rules involving this entity |
| `min_confidence` | No | Minimum confidence threshold (default 0.5) |

Returns: rule ID, source/target entity, mean delay, std delay, confidence, and occurrence count.

---

## Automation Examples

### Activate simulation when everyone leaves

```yaml
alias: "Simulate presence when away"
trigger:
  - platform: state
    entity_id: zone.home
    to: "0"
action:
  - service: we_are_home.start
```

### Force retraining every Sunday at 3 AM

```yaml
alias: "Weekly profile refresh"
trigger:
  - platform: time
    at: "03:00:00"
condition:
  - condition: time
    weekday:
      - sun
action:
  - service: we_are_home.train
    data:
      days_back: 14
```

---

## Profile Maturity

The system classifies each entity's profile based on how much history it has seen:

| Level | Observations | Behavior |
|---|---|---|
| **COLD** | 0–2 | Insufficient data — entity is not simulated |
| **WARM** | 3–13 | Baseline patterns detected — simulation with low confidence |
| **HOT** | 14–29 | Reliable patterns — normal simulation |
| **STABLE** | 30+ | Well‑established patterns — full confidence |

Use `we_are_home.get_profile` to check an entity's maturity level and confidence score.

---

## Development

See [CLAUDE.md](CLAUDE.md) for architecture details, development commands, and the feature specification.

```bash
pip install -r requirements_dev.txt
pytest tests/ --cov=custom_components/we_are_home --cov-report=term --cov-fail-under=80
```

---

## License

MIT © Rodolfo Menardi

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[hacs-install-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[release-badge]: https://img.shields.io/github/v/release/rodolfomenardi/we-are-home
[release-url]: https://github.com/rodolfomenardi/we-are-home/releases
[license-badge]: https://img.shields.io/github/license/rodolfomenardi/we-are-home
