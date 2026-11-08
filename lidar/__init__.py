"""SLAMTEC RPLIDAR C1 (C1M1-R2) driver, scan processing and adapters for the Team-15 ground robot.

SIMULATION-TESTED ONLY. No physical scan has been taken. Hardware mode is gated by
lidar.config.check_hardware_gate (LIDAR_C1_HARDWARE_CHECKLIST.md). This package issues no
motor, servo or GPIO commands. See LIDAR_C1_ARCHITECTURE.md.
"""
__all__ = ["config", "protocol", "scan", "driver", "processing", "adapters", "simulation", "tracking", "panel"]
