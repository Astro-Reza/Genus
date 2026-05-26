# Genus Algorithm

<div align="center">
  <img width="150px" src="static/img/psn-new-logo.png"/>
</div>

[![Typing SVG](https://readme-typing-svg.herokuapp.com/?font=Geologica&weight=500&color=F8F9FA&center=true&width=500&height=50&lines=Building+Next-Gen+Hardware;Fusing+Sensor+Data;Adaptive+PID+Control;)](https://git.io/typing-svg)

<p align="center">
  <a>
    <img src="https://img.shields.io/badge/Version-2.0.2-darkorange?style=for-the-badge" alt="Version" />
  </a>
  <a href="https://www.linkedin.com/in/rezafauzanz/">
    <img src="https://img.shields.io/badge/PIC -Reza Fauzan-darkblue?style=for-the-badge" alt="Lead" />
  </a>
</p>

This codebase contains the software stack for an automated antenna positioner system. The system consists of a master controller (Orange Pi Zero 3) running a Python Flask backend and a slave controller (ESP32) running C++ firmware to directly drive the motors.

Genus Algo introduces highly adaptive sensor fusion algorithm using cascade PID control. Genus uses an adaptive confidence-score based sensor fusion utilizing two different sensors (AHRS and magnetic motor encoder).

## System Architecture

1. **Backend / Master (Orange Pi Zero 3)**
   - Runs `backend_orangepi.py`.
   - **Web UI & Telemetry:** Hosts a Flask web application with SocketIO for real-time telemetry and control.
   - **Sensors:** Reads GPS (`/dev/ttyS5`) and an AHRS module (`/dev/ttyUSB0`) to calculate antenna pointing angles for satellites.
   - **Auto-Pointing:** Features a background thread with an adaptive PI controller (with dead-zone compensation and gravity feedforward) to compute motor speed targets.
   - **Communications:** Sends motor commands to the ESP32 via SPI (`/dev/spidev1.1`) at a 20Hz update rate. Also hosts an OpenAMIP interface for modem integration.

2. **Slave Controller (ESP32)**
   - Runs `slave/esp32/esp32.ino`.
   - **Hardware Interface:** Directly interfaces with three **BTS7960 motor drivers** to control Azimuth, Elevation, and Polarization.
   - **Communications:** Configured as an SPI Slave using DMA to receive 12-byte command payloads from the Orange Pi.
   - **Safety:** Supports 6 hardware limit switches to prevent mechanical over-travel (logic integration pending).

## ESP32 Pinout Configuration

The ESP32 is wired to the SPI bus from the Orange Pi, the three BTS7960 motor drivers, and 6 limit switches.

### SPI Interface (VSPI)
| Function | ESP32 Pin | Connects To | Notes |
| :--- | :--- | :--- | :--- |
| **SPI CS** | `GPIO 5` | Orange Pi CS | Chip Select (Default is CS1 on OPi) |
| **SPI CLK** | `GPIO 18` | Orange Pi SCLK | SPI Clock |
| **SPI MISO** | `GPIO 19` | Orange Pi MISO | Master In Slave Out |
| **SPI MOSI** | `GPIO 23` | Orange Pi MOSI | Master Out Slave In |

### Motors (BTS7960 Drivers)
*Note: For speed control, tie the BTS7960 `R_EN` and `L_EN` pins together and connect them to the ESP32 `EN` pin for PWM. Use the `R_PWM` and `L_PWM` pins for digital directional logic (HIGH/LOW).*

| Motor Axis | Function | ESP32 Pin |
| :--- | :--- | :--- |
| **Azimuth** | EN (PWM Speed) | `GPIO 16` |
| **Azimuth** | R_PWM (Dir) | `GPIO 25` |
| **Azimuth** | L_PWM (Dir) | `GPIO 26` |
| **Elevation** | EN (PWM Speed) | `GPIO 12` |
| **Elevation** | R_PWM (Dir) | `GPIO 13` |
| **Elevation** | L_PWM (Dir) | `GPIO 15` |
| **Polarization** | EN (PWM Speed) | `GPIO 4` |
| **Polarization** | R_PWM (Dir) | `GPIO 2` |
| **Polarization** | L_PWM (Dir) | `GPIO 21` |

### Limit Switches
| Axis Direction | ESP32 Pin | Notes |
| :--- | :--- | :--- |
| **Azimuth Right** | `GPIO 32` | Uses Internal Pull-up |
| **Azimuth Left** | `GPIO 33` | Uses Internal Pull-up |
| **Elevation Up** | `GPIO 27` | Uses Internal Pull-up |
| **Elevation Down** | `GPIO 14` | Uses Internal Pull-up |
| **Polarization Right** | `GPIO 34` | **Input Only - Requires External Pull-up Resistor** |
| **Polarization Left** | `GPIO 35` | **Input Only - Requires External Pull-up Resistor** |

## Setup & Dependencies

**Backend (Orange Pi):**
Requires Python 3. You will need to install the following dependencies:
```bash
pip install flask flask-socketio pyserial numpy spidev rtlsdr
```

**Firmware (ESP32):**
Requires the Arduino IDE with the ESP32 Core installed. 
*Important: You must use **ESP32 Core version 3.0.0 or newer** as this codebase relies on the native `analogWrite()` function.*

## Research by:
**Reza Fauzan Zulkarnaen** (Physics | Universitas Negeri Jakarta)
