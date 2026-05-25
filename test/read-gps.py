import serial
import time

SERIAL_PORT = '/dev/ttyS5'  
BAUD_RATE = 9600            

print(f"Attempting to connect to {SERIAL_PORT} at {BAUD_RATE} baud...")
print("If connection fails, it will retry every 2 seconds until the UART is available.")
print("Place the GPS antenna outdoors with clear sky view.\n")

while True:
    ser = None
    try:
        ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUD_RATE,
            timeout=1,              # 1 second timeout for readline
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE
        )
        print(f"Successfully connected to {SERIAL_PORT}! Reading raw NMEA sentences...\n")
        
        while True:
            try:
                raw_bytes = ser.readline()
                if raw_bytes:
                    try:
                        line = raw_bytes.decode('utf-8', errors='ignore').strip()
                        if line.startswith('$'):
                            print(f"Raw: {line}")
                        # If non-NMEA garbage appears, you can uncomment:
                        # elif line:
                        #     print(f"Garbage: {line}")
                    except:
                        print(f"Raw (decode error): {raw_bytes}")
                # No else needed - empty reads are normal if no data in timeout window
            except serial.SerialException as e:
                print(f"\nSerial read error (device disconnected?): {e}")
                break  # Break inner loop to retry connection
            except Exception as e:
                print(f"\nUnexpected read error: {e}")
                break
                
    except serial.SerialException as e:
        print(f"No UART device available: {e}")
        print("   → Check: Is UART5 enabled? Are wires connected? Correct port name?")
        print("   Retrying in 2 seconds...\n")
        time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopped by user.")
        break
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        time.sleep(2)
    finally:
        if ser:
            ser.close()