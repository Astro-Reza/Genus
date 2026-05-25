# Hardware Testing Utilities

This directory contains standalone scripts to verify sensor hardware connectivity on the Orange Pi Zero 3 before running the main application.

## Files

### 1. `read-gps.py`
**Purpose**: Verifies GPS module connectivity and NMEA data parsing.
- **Port**: `/dev/ttyS5`
- **Baud**: 9600
- **Usage**:
  ```bash
  sudo python3 read-gps.py
  ```
- **Expected Output**:
  It prints raw NMEA lines starting with `$GPGGA` and the parsed Latex/Long/Alt.
  ```
  $GPGGA,123456.00,0612.3456,S,10654.3210,E,1,08,0.9,15.5,M,-5.0,M,,*47
  Lat: -6.20576, Long: 106.90535, Alt: 15.5
  ```

### 2. `wt901c.py`
**Purpose**: Verifies WT901C Attitude Sensor (AHRS) via RS485.
- **Port**: `/dev/ttyUSB0` (USB-RS485 Adapter)
- **Baud**: 9600
- **Protocol**: Modbus RTU (Slave ID 0x50)
- **Usage**:
  ```bash
  sudo python3 wt901c.py
  ```
- **Expected Output**:
  Prints Angle X (Roll), Angle Y (Pitch), and Angle Z (Yaw) in degrees.
  ```
  Angle X: 0.05, Y: 1.20, Z: 120.50
  Angle X: 0.06, Y: 1.19, Z: 120.51
  ...
  ```

## Troubleshooting
- **Permission Denied**: Run with `sudo`.
- **Port Not Found**: Check connection and run `ls /dev/tty*`.
- **No Data**: 
  - GPS: Ensure antenna is connected and has clear view of sky.
  - WT901C: Check A/B wiring on RS485 adapter (swap if needed).
