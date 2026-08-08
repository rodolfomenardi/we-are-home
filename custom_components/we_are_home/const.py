"""Constants for the We Are Home integration."""

DOMAIN = "we_are_home"

# Default configuration values
DEFAULT_NAME = "We Are Home"
DEFAULT_LEARNING_INTERVAL = 60  # minutes
DEFAULT_SIMULATION_INTERVAL = 30  # seconds
DEFAULT_RESTORE_STATES = True
DEFAULT_MIN_CONFIDENCE = 0.3
DEFAULT_SEQUENCE_WINDOW = 60  # minutes
DEFAULT_SEQUENCE_MIN_OCCURRENCES = 3
DEFAULT_BOOST_FACTOR = 2.0
DEFAULT_RANDOM_SEED = None

# Learning model parameters
EMA_ALPHA = 0.3  # exponential moving average weight for new data
DAY_SIMILARITY_THRESHOLD = 0.15  # Jensen-Shannon divergence max for merging days
MIN_STATE_DURATION = 5  # seconds - filters out transient states (motion sensors)
MIN_OBSERVATIONS_COLD = 0
MIN_OBSERVATIONS_WARM = 3
MIN_OBSERVATIONS_HOT = 14
MIN_OBSERVATIONS_STABLE = 30

# Profile maturity levels
MATURITY_COLD = "COLD"      # < 3 observations
MATURITY_WARM = "WARM"      # 3-13 observations
MATURITY_HOT = "HOT"        # 14-29 observations
MATURITY_STABLE = "STABLE"  # >= 30 observations

# Supported entity domains
SUPPORTED_DOMAINS = [
    "light",
    "switch",
    "cover",
    "media_player",
    "climate",
    "scene",
    "input_boolean",
    "fan",
    "humidifier",
]

# Storage
STORAGE_DIR = ".storage"
STORAGE_VERSION = 1

# Platforms
PLATFORMS = ["switch"]

# Services
SERVICE_START = "start"
SERVICE_STOP = "stop"
SERVICE_TRAIN = "train"
SERVICE_GET_PROFILE = "get_profile"
SERVICE_LIST_RULES = "list_rules"

# Events
EVENT_COMMAND = "we_are_home_command"
EVENT_SEQUENCE_TRIGGERED = "we_are_home_sequence_triggered"

# Configuration flow
CONF_ENTITIES = "entities"
CONF_LEARNING_INTERVAL = "learning_interval"
CONF_SIMULATION_INTERVAL = "simulation_interval"
CONF_RESTORE_STATES = "restore_states"
CONF_MIN_CONFIDENCE = "min_confidence"
CONF_SEQUENCE_WINDOW = "sequence_window"
CONF_SEQUENCE_MIN_OCCURRENCES = "sequence_min_occurrences"
CONF_BOOST_FACTOR = "boost_factor"
CONF_RANDOM_SEED = "random_seed"

# Time slots
SLOTS_PER_DAY = 96  # 24h * 4 slots/hour (15-min windows)
SECONDS_PER_SLOT = 900  # 15 minutes
