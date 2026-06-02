import time
from smbus2 import SMBus

# --- Hardware Constants ---
I2C_BUS_NUMBER = 3        # Change this to match your Orange Pi's I2C bus (often 3 or 5)
TCA9548A_ADDR = 0x70      # Default I2C address for the multiplexer
AS5600_ADDR = 0x36        # Fixed I2C address for the AS5600

# AS5600 Register Map
RAW_ANGLE_REG_HI = 0x0C   # High byte of raw angle

def select_mux_channel(bus, channel):
    """
    Selects the active channel on the TCA9548A multiplexer.
    Channels range from 0 to 7.
    """
    if channel < 0 or channel > 7:
        raise ValueError("Multiplexer channel must be between 0 and 7")
    
    try:
        # Write to the multiplexer to open the specific channel (1 << channel)
        bus.write_byte(TCA9548A_ADDR, 1 << channel)
        return True
    except Exception as e:
        print(f"Multiplexer (0x{TCA9548A_ADDR:02X}) not responding: {e}")
        return False

def read_as5600_angle(bus):
    """
    Reads the 12-bit raw angle from the AS5600.
    Returns an integer between 0 and 4095.
    """
    try:
        # Read 2 sequential bytes starting from the high register
        data = bus.read_i2c_block_data(AS5600_ADDR, RAW_ANGLE_REG_HI, 2)
        
        # Combine high byte and low byte into a single 12-bit integer
        high_byte = data[0]
        low_byte = data[1]
        angle = (high_byte << 8) | low_byte
        
        return angle
    except Exception as e:
        return None

def main():
    # Initialize the I2C bus
    print(f"Starting I2C bus {I2C_BUS_NUMBER}...")
    try:
        bus = SMBus(I2C_BUS_NUMBER)
        print(f"Successfully opened I2C bus {I2C_BUS_NUMBER}.")
    except Exception as e:
        print(f"Error: Could not open I2C bus {I2C_BUS_NUMBER}: {e}")
        print("Check your orangepi-config and ensure I2C is enabled.")
        return

    # Assume sensors are connected to SD0/SC0 (Channel 0) and SD1/SC1 (Channel 1)
    sensor_channels = [0, 1]
    
    print("Starting sensor read loop. Press Ctrl+C to stop.\n")

    try:
        while True:
            for channel in sensor_channels:
                print(f"--- Switching to Channel {channel} ---")
                
                # 1. Switch the multiplexer to look at the current sensor
                mux_ok = select_mux_channel(bus, channel)
                
                if not mux_ok:
                    print(f"Status: DISCONNECTED. Multiplexer ERROR on channel {channel}.")
                else:
                    # 2. Add a tiny delay to ensure the bus has settled
                    time.sleep(0.01)
                    
                    # 3. Read the angle
                    angle = read_as5600_angle(bus)
                    
                    if angle is not None:
                        # Convert 0-4095 scale to 0-360 degrees for readability
                        degrees = (angle / 4096.0) * 360.0
                        print(f"Status: CONNECTED. Sensor {channel} Reading: {degrees:.2f}°")
                    else:
                        print(f"Status: DISCONNECTED. No AS5600 detected on channel {channel}.")
                
                print("Waiting 2 seconds before switching...\n")
                time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopping script.")
    finally:
        bus.close()

if __name__ == "__main__":
    main()