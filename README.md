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

### Motors (L298N Drivers)
*Note: For speed control, connect the ESP32 speed pins to the L298N Enable (`ENA`/`ENB`) pins. Use the corresponding digital input pins (`IN1`–`IN4`) for direction control.*

| Motor Axis | Function | ESP32 Pin | Connects To |
| :--- | :--- | :--- | :--- |
| **Azimuth (Motor A)** | ENA (PWM Speed) | `GPIO 32` | L298N #1 ENA |
| **Azimuth (Motor A)** | IN1 (Dir 1) | `GPIO 33` | L298N #1 IN1 |
| **Azimuth (Motor A)** | IN2 (Dir 2) | `GPIO 25` | L298N #1 IN2 |
| **Elevation (Motor B)** | ENB (PWM Speed) | `GPIO 14` | L298N #1 ENB |
| **Elevation (Motor B)** | IN3 (Dir 1) | `GPIO 26` | L298N #1 IN3 |
| **Elevation (Motor B)** | IN4 (Dir 2) | `GPIO 27` | L298N #1 IN4 |
| **Polarization (Motor C)** | ENA (PWM Speed) | `GPIO 12` | L298N #2 ENA |
| **Polarization (Motor C)** | IN1 (Dir 1) | `GPIO 13` | L298N #2 IN1 |
| **Polarization (Motor C)** | IN2 (Dir 2) | `GPIO 15` | L298N #2 IN2 |

### Limit Switches (Active LOW)
| Axis Direction | ESP32 Pin | Notes |
| :--- | :--- | :--- |
| **Azimuth Right (Motor A - Max)** | `GPIO 35` | **Input Only - Requires External 10k Pull-up Resistor** |
| **Azimuth Left (Motor A - Min)** | `GPIO 34` | **Input Only - Requires External 10k Pull-up Resistor** |
| **Elevation Up (Motor B - Max)** | `GPIO 39` | **Input Only - Requires External 10k Pull-up Resistor (VN)** |
| **Elevation Down (Motor B - Min)** | `GPIO 36` | **Input Only - Requires External 10k Pull-up Resistor (VP)** |
| **Polarization Right (Motor C - Max)** | `GPIO 16` | Uses Internal Pull-up |
| **Polarization Left (Motor C - Min)** | `GPIO 17` | Uses Internal Pull-up |

## Setup & Dependencies

This system consists of the **Backend** (running on an Orange Pi Zero 3 master controller) and the **Firmware** (running on an ESP32 slave controller). 

---

### 1. Backend (Orange Pi Zero 3)

The master controller runs Python and hosts the Flask/SocketIO telemetry dashboard. It interfaces directly with GPS, AHRS, and the ESP32 over hardware ports.

#### ⚙️ OS & Hardware Configuration
Before installing the Python packages, configure the system-level interfaces on your Orange Pi:

1. **Enable the SPI Bus:**
   The backend sends motor speed and directional commands to the ESP32 via SPI (`/dev/spidev1.1`). To enable it:
   ```bash
   sudo armbian-config
   # Navigate to: System -> Hardware -> Enable 'spi-spidev' and 'spidev1.1'
   # Or manually edit /boot/armbianEnv.txt to include the appropriate overlays
   ```
2. **Install RTL-SDR Driver & Library:**
   The SDR spectrum feature requires the native `librtlsdr` library to communicate with the USB dongle:
   ```bash
   sudo apt update
   sudo apt install -y librtlsdr-dev rtl-sdr
   ```
3. **Grant Hardware Permissions:**
   Ensure the current user belongs to the groups managing serial and SPI/I2C buses to avoid running scripts with `sudo`:
   ```bash
   sudo usermod -a -G dialout,spi,i2c $USER
   # Restart your terminal session or log out and back in
   ```

#### 🐍 Python Dependencies
> [!IMPORTANT]
> **Python Version Requirement:** Python **3.10 or newer** is required. The codebase utilizes PEP 604 type unions (`float | None`) and PEP 585 standard collections generics (`list[tuple[...]]`) which will raise syntax/runtime errors on older Python interpreters.

Install all required Python packages with `sudo pip`:
```bash
sudo pip install flask flask-socketio eventlet pyserial numpy spidev pyrtlsdr smbus2
```

##### Dependency Breakdown
| Dependency | PyPI Package Name | Purpose | Used In |
| :--- | :--- | :--- | :--- |
| **Flask** | `flask` | Hosts the web application server and HTTP API endpoints | `backend_orangepi.py` |
| **Flask-SocketIO** | `flask-socketio` | Real-time bi-directional communications for live telemetry and commands | `backend_orangepi.py` |
| **Eventlet** | `eventlet` | High-performance asynchronous WSGI server support for Socket.IO | Web Server Runtime |
| **PySerial** | `pyserial` | Reads NMEA sentences from GPS (`/dev/ttyS5`) and Modbus from WT901C (`/dev/ttyUSB0`) | `backend_orangepi.py`, `test/*` |
| **NumPy** | `numpy` | Efficient numeric calculations and array structures | `backend_orangepi.py` |
| **SpiDev** | `spidev` | Handles communication with the ESP32 slave via the hardware SPI bus | `backend_orangepi.py` |
| **PyRTLSDR** | `pyrtlsdr` | Python wrapper for the RTL-SDR radio dongle to capture spectrum data | `backend_orangepi.py` |
| **SMBus2** | `smbus2` | Pure Python I2C library (used for testing I2C interfaces) | `test/i2c.py` |

---

### 2. Firmware (ESP32 Slave)

The slave firmware runs on the ESP32 to receive SPI commands from the Orange Pi and drive the H-Bridge motor controllers.

#### 🛠️ Toolchain & Core Requirements
- **IDE:** Arduino IDE (version 2.x+) or VS Code with PlatformIO.
- **ESP32 Arduino Core:** **Version 3.0.0 or newer** is **strictly required**. 
  > [!WARNING]
  > Older versions of the ESP32 core do not support the native `analogWrite()` function used in this codebase to drive the motor speed EN pins.
- **Standard Libraries (Included in ESP32 Core):**
  - `#include <Arduino.h>`
  - `#include "driver/spi_slave.h"` (Native ESP-IDF SPI Slave driver with DMA support)
  *No external libraries need to be downloaded from the Arduino Library Manager.*

#### 🔌 Hardware Configuration Note
- **Limit Switches:** 6 limit switches are defined. Note that the Polarization Limit Switches (**GPIO 34 and 35**) are on input-only pins and **do not support internal pull-ups** on the ESP32 chip. You **must** wire external pull-up resistors (e.g., 10 kΩ to 3.3V) for these switches to function correctly.

## Installation & Running Guide

Follow these sequential steps to set up, install dependencies, and run the master backend and test scripts on the Orange Pi.

### Step 1: Clone the Repository
Clone the codebase and navigate to the project directory:
```bash
git clone https://github.com/Astro-Reza/Genus.git
cd Genus
```

### Step 2: System and Hardware Configuration
Enable the SPI bus and configure device permissions on the Orange Pi Zero 3:
```bash
# Open configuration utility to enable SPI (spidev1.1)
sudo armbian-config

# Add current user to hardware groups
sudo usermod -a -G dialout,spi,i2c $USER
```
> [!NOTE]
> For the group updates to take effect, you must restart your shell session (log out and log back in, or open a new SSH connection).

### Step 3: Install Native Libraries
Install system-level libraries for the RTL-SDR receiver:
```bash
sudo apt update
sudo apt install -y librtlsdr-dev rtl-sdr
```

### Step 4: Install Python Packages
Install the required packages using `sudo pip`:
```bash
sudo pip install flask flask-socketio eventlet pyserial numpy spidev pyrtlsdr smbus2
```

### Step 5: Verify Hardware Connectivity (Optional / Recommended)
Before running the main application, run the testing scripts inside the `test` directory to verify your hardware connections:
```bash
# Test GPS receiver connection and coordinate reading (/dev/ttyS5)
python3 test/read-gps.py

# Test WT901C AHRS attitude sensor reading (/dev/ttyUSB0)
python3 test/wt901c.py

# Test I2C bus communication (if equipped)
python3 test/i2c.py
```

### Step 6: Start the Master Backend
The Flask socket server is configured to bind to port **80** (standard HTTP port). Therefore, you must start the application using `sudo` to bind to privileged ports:
```bash
sudo python3 backend_orangepi.py
```
After launching the script, the web dashboard will be accessible at:
`http://<orange-pi-ip-address>/` or `http://localhost/` (if local).

## Research by:
**Reza Fauzan Zulkarnaen** (Physics | Universitas Negeri Jakarta)
