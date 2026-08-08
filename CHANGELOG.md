# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-08

### Added
- Initial release of We Are Home presence simulation integration
- UI config flow for entity selection and parameter configuration
- Probabilistic time profiles (TimeProfile) with per-slot P(on), P(transition), and duration distributions
- Exponential Moving Average (EMA) incremental learning from recorder history
- Automatic day-of-week clustering (weekday vs weekend) via Jensen-Shannon divergence
- Temporal association rules (SequenceRule) discovery between entity pairs
- Simulation engine with Gaussian-varied behavior generation
- Sequence boost system for cross-entity behavior chaining
- State capture and optional restoration on simulation stop
- 5 services: start, stop, train, get_profile, list_rules
- Event bus integration: we_are_home_command, we_are_home_sequence_triggered
- Multi-instance support
- Diagnostics endpoint with profile maturity and rule summaries
- English and Portuguese (Brazil) translations
- HACS and Hassfest CI/CD validation
