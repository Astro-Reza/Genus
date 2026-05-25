import serial
import time
import struct

# ================= CONFIGURATION =================
PORT = '/dev/ttyUSB0'         # ← CHANGE THIS if needed (check with ls /dev/ttyUSB*)
BAUDRATE = 9600               # Default for most WT901C-485 modules
SLAVE_ID = 0x50               # Default slave address – change if yours is different (0x00–0xF7)

READ_INTERVAL = 0.2           # seconds between readings
RETRY_DELAY = 2.0             # seconds before retry on failure
# ==================================================

def calculate_crc16(data: bytes) -> bytes:
    """Modbus RTU CRC-16/MODBUS"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)


def read_angles(ser):
    """Read 12 registers starting from 0x0034 (angles in regs 9,10,11)"""
    # Modbus RTU: slave + func(03) + start(0034) + count(0012) + CRC
    request = struct.pack('>BBHH', SLAVE_ID, 0x03, 0x0034, 12)
    request += calculate_crc16(request)

    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write(request)
    ser.flush()

    # Response: slave(1) + func(1) + bytecount(1) + data(24) + crc(2) = 29 bytes
    response = ser.read(29)

    if len(response) != 29:
        return None

    # Validate CRC
    received_crc = response[-2:]
    calc_crc = calculate_crc16(response[:-2])
    if received_crc != calc_crc:
        return None

    # Extract data (24 bytes = 12 signed 16-bit ints, big-endian)
    data = response[3:27]
    values = struct.unpack('>12h', data)

    # Angles usually in registers 9,10,11 (0-based)
    angle_x = values[9] / 32768.0 * 180.0   # Roll / X
    angle_y = values[10] / 32768.0 * 180.0  # Pitch / Y
    angle_z = values[11] / 32768.0 * 180.0  # Yaw / Z

    return angle_x, angle_y, angle_z


def main():
    print("WT901C-485 reader via USB-RS485 adapter")
    print(f"Using port: {PORT} @ {BAUDRATE} baud, slave ID {SLAVE_ID}")
    print("Ctrl+C to stop\n")

    while True:
        ser = None
        try:
            ser = serial.Serial(
                port=PORT,
                baudrate=BAUDRATE,
                parity=serial.PARITY_NONE,
                bytesize=serial.EIGHTBITS,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.8                  # generous timeout
            )
            print(f"✓ Connected to {PORT}\n")

            while True:
                result = read_angles(ser)
                if result:
                    x, y, z = result
                    z_norm = z if z >= 0 else z + 360  # Optional: 0–360° for yaw
                    print(f" X: {x:8.3f}°   Y: {y:8.3f}°   Z: {z_norm:8.3f}°")
                else:
                    print("No valid response / CRC error", end="\r", flush=True)

                time.sleep(READ_INTERVAL)

        except serial.SerialException as e:
            print(f"\n✗ Port error: {e}")
            print("   → Check connection, is adapter plugged in? Correct port?")
            print(f"   Retrying in {RETRY_DELAY} seconds...\n")
            time.sleep(RETRY_DELAY)

        except KeyboardInterrupt:
            print("\nStopped by user.")
            break

        except Exception as e:
            print(f"\nUnexpected error: {e}")
            time.sleep(RETRY_DELAY)

        finally:
            if ser and ser.is_open:
                ser.close()


if __name__ == '__main__':
    main()