# RoverC-Pro bench-test runbook (Gate 5 → 6)

**Do not start until every item in step 0 is signed off. Each step needs a named human operator present.**
Never move a wall-powered Pi, and never drag its cable. The RoverC runs on its own battery; the Pi stays still on the bench.

## 0. Preconditions (record answers in `HardwareVerification`)
- [ ] Controller identified from its label and boot screen: StickC or StickC Plus. Record `controller_model`.
- [ ] Firmware: which sketch is flashed, and from which commit. Record `controller_firmware`. If it's unknown, reflash the reviewed bridge firmware.
- [ ] RoverC revision and markings inspected. Record `roverc_revision`.
- [ ] Link chosen and wired: for example Pi USB serial → StickC bridge, so there's only one I²C master. Record `link` and `wiring_verified_by`.
- [ ] 16340 battery charged. Voltage measured with a meter at rest and under motor load. Undervoltage threshold chosen. Record `power_verified_by` and `MotionLimits.min_voltage_v`.
- [ ] Physical stop rehearsed: the operator can reach the RoverC power switch, or lift the robot, within 1 s.
- [ ] Software e-stop rehearsed: `touch <stop_file>` and `POST /rover/estop` both bring the output to zero (check in the dry-run log).

## 1. Dry run with no motor power
1. Motor power off, wheels lifted.
2. Run the navigator with `RecordingTransport` and check that every frame is `0x38, 0x00, <4 bytes>`. No servo registers should appear.
3. Confirm the first frame and the final frame are both `00 00 00 00`.

## 2. Link-loss timeout (wheels lifted, motor power ON, lowest speed)
1. Command `TURN_LEFT` at speed 0.10 for 0.5 s.
2. Pull the USB cable, or kill the host process, while the wheels are turning.
3. Measure how long the wheels take to stop. Record `stop_on_link_loss_ms`. **If they don't stop, stop the test. Gate 5 fails.**

## 3. Wheel mapping (wheels lifted)
For each of forward, strafe-left and CCW: command 0.10 for 0.3 s, then watch which way each wheel turns. Fill in `WheelMapping(forward_sign, strafe_left_sign, ccw_sign, evidence="<who> <when> <observations>")`. Repeat each once more to confirm.

## 4. Heading source (needed before any rotation scanning)
- Choose a source: the StickC IMU gyro integrated on the controller, or an external reference.
- Calibrate the gyro bias at rest.
- Rotate 90° by hand against a protractor mark at least 5 times. Record the error.
- If the error is above 5°, or drift is above 2°/min, do not enable `heading.source=imu-calibrated`.

## 5. Supervised floor test (clear 2 m × 2 m area, no people or pets in it)
1. Approve motion as a named operator. Run 0.5 m forward at speed 0.10 with the ultrasonic live.
2. Place a box 1.5 m ahead. Confirm the robot stops with at least 0.5 m to spare.
3. Run a scan: left, right and back views. Confirm each heading against a floor mark. Confirm that NO_ECHO directions are reported UNKNOWN.
4. Any surprise: physical stop first, then software e-stop. Record what happened.

## 6. Afterwards
- Archive logs, the `HardwareVerification` record and the measured numbers under `docs/rover/runs/<timestamp>/`.
- Update the gate table in `SAFETY_AND_LIMITATIONS.md`. Only claim what was measured.
