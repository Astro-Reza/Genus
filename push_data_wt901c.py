
"""
Refactored WT901C Sensor Interface
Acts as a background thread "slave" to the main Flask app "master".
"""
import serial
import time
import struct
import threading
import logging

# --- Configuration ---
# Serial Config
COM_PORT = 'COM8'
BAUD_RATE = 9600
SLAVE_ID = 0x50

class WT901CSensor:
    def __init__(self, com_port=COM_PORT, baud_rate=BAUD_RATE):
        self.com_port = com_port
        self.baud_rate = baud_rate
        self.is_running = False
        self.thread = None
        self._latest_data = {
            "azimuth": 0.0,
            "elevation": 0.0,
            "polarization": 0.0,
            "status": "WAITING"
        }
        self.lock = threading.Lock()
        self.log_callback = None

    def set_log_callback(self, callback):
        """Sets a callback function to receive log messages."""
        self.log_callback = callback

    def _log(self, message):
        """Internal helper to log to console and callback."""
        print(f"[Sensor] {message}")
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception as e:
                print(f"Error in log callback: {e}")

    def get_crc16(self, data: bytes) -> bytes:
        """Calculates the CRC16 checksum for Modbus RTU."""
        crc = 0xFFFF
        for char in data:
            crc ^= char
            for _ in range(8):
                if crc & 1:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)

    def read_registers(self, ser, slave_id, start_reg, count):
        """Sends a Modbus command to read holding registers."""
        try:
            command = struct.pack('>BBHH', slave_id, 0x03, start_reg, count)
            command += self.get_crc16(command)
            ser.write(command)
            
            # Expected bytes: Slave(1) + Func(1) + BytesCount(1) + Data(Count*2) + CRC(2)
            expected_len = 5 + 2 * count
            
            data = ser.read(expected_len)
            
            if len(data) < expected_len:
                return None
                
            # Validate CRC
            received_crc = data[-2:]
            calculated_crc = self.get_crc16(data[:-2])
            if received_crc != calculated_crc:
                return None
                
            return data[3:-2]
        except Exception as e:
            # self._log(f"Serial Read Error: {e}") 
            # (Too noisy to log every read error, maybe just return None)
            return None

    def parse_sensor_data(self, payload):
        """Parses Modbus bytes into angles."""
        values = struct.unpack('>12h', payload)
        angle_x = values[9] / 32768.0 * 180.0
        angle_y = values[10] / 32768.0 * 180.0
        angle_z = values[11] / 32768.0 * 180.0
        return {"x": angle_x, "y": angle_y, "z": angle_z}

    def _run_loop(self):
        """Background thread loop with retry logic."""
        self._log(f"Service started. Target: {self.com_port}")
        
        while self.is_running:
            ser = None
            try:
                self._log(f"Connecting to {self.com_port}...")
                ser = serial.Serial(self.com_port, self.baud_rate, timeout=0.1)
                self._log(f"Connected to {self.com_port}")
                
                # Inner loop for reading data while connected
                while self.is_running and ser.is_open:
                    start_time = time.time()
                    try:
                        data_bytes = self.read_registers(ser, SLAVE_ID, 0x0034, 12)
                        
                        if data_bytes:
                            data = self.parse_sensor_data(data_bytes)
                            
                            raw_az = data['z']
                            if raw_az < 0: raw_az += 360

                            # Update shared state safely
                            with self.lock:
                                self._latest_data = {
                                    "azimuth": raw_az,
                                    "elevation": data['y'],
                                    "polarization": data['x'],
                                    "status": "TRACKING"
                                }
                        else:
                            # Optional: Count consecutive failures to determine disconnect?
                            pass
                        
                    except serial.SerialException as e:
                        self._log(f"Serial Error during read: {e}")
                        break # Break inner loop to trigger reconnect logic
                    except Exception as e:
                        self._log(f"Unexpected error: {e}")
                        break
                    
                    # Smart sleep for performance
                    elapsed = time.time() - start_time
                    time.sleep(max(0, 0.05 - elapsed))
                    
            except serial.SerialException:
                self._update_status("ERROR")
                self._log(f"Failed to open {self.com_port}. Retrying in 2s...")
                time.sleep(2)
            except Exception as e:
                self._update_status("ERROR")
                self._log(f"Critical Error: {e}. Retrying in 2s...")
                time.sleep(2)
            finally:
                if ser and ser.is_open:
                    try:
                        ser.close()
                    except:
                        pass
        
        self._log("Service Stopped")
        self._update_status("STOPPED")

    def _update_status(self, status):
        """Helper to update status safely."""
        with self.lock:
            self._latest_data["status"] = status

    def start(self):
        """Starts the background sensor reading thread."""
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()

    def stop(self):
        """Stops the background thread."""
        self.is_running = False
        if self.thread:
            self.thread.join()

    def get_latest_data(self):
        """Returns the latest sensor reading."""
        with self.lock:
            return self._latest_data.copy()

# Singleton instance for easy import
sensor_service = WT901CSensor()
