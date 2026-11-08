"""Grove Ultrasonic Ranger: driver, obstacle assessment and range service (Team 15 ground robot).

Consumers import only ``RangeClient`` (and the schema constants); they never open GPIO.
"""
from .config import ElectricalConfig, ElectricalInterfaceError, SensorConfig  # noqa: F401
from .obstacle import ObstacleAssessor, ObstacleConfig, ObstacleStatus  # noqa: F401
from .reading import MeasurementStatus, RangeReading  # noqa: F401
from .service import RangeClient, RangeService  # noqa: F401
