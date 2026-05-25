from flask import Flask, render_template, jsonify, request
import serial
import time
import struct
import threading
import os

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

# Konstanta Pointing
WGS84_A = 6378137.0
WGS84_E2 = 0.00669437999014
GEO_RADIUS_M = 42164000.0
DEFAULT_SAT_LON_DEG = 146.0
NEAR_M = 30000.0

# Path KML 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KML_PATH = os.path.join(BASE_DIR,"static", "NUSANTARA SATU.kml")

@dataclass
class PointLLA:
    lat_deg: float
    lon_deg: float
    alt_m: float

@dataclass
class KmlFeature:
    beam_id: int
    name: str
    pol: str
    coords: list[tuple[float, float]]
    eirp: float | None = None
    gt: float | None = None

app = Flask(__name__, template_folder='templates', static_folder='static')

# =========================
# Basic Helpers & Geo Pointing Math
# =========================
def deg2rad(d: float) -> float:
    return d * math.pi / 180.0

def rad2deg(r: float) -> float:
    return r * 180.0 / math.pi

def wrap_360(deg: float) -> float:
    deg = deg % 360.0
    return deg if deg >= 0 else deg + 360.0

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p1 = deg2rad(lat1)
    p2 = deg2rad(lat2)
    dp = p2 - p1
    dl = deg2rad(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2) + math.cos(p1) * math.cos(p2) * (math.sin(dl / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(_clamp(a, 0.0, 1.0)))

def load_kml_features_beams_1_8(kml_path: str) -> list[KmlFeature]:
    if not os.path.exists(kml_path):
        print(f"[WARN] File KML tidak ditemukan di: {kml_path}")
        return []
        
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    tree = ET.parse(kml_path)
    root = tree.getroot()
    feats: list[KmlFeature] = []

    for doc in root.findall(".//kml:Document", ns):
        doc_name_el = doc.find("kml:name", ns)
        doc_name = (doc_name_el.text or "").strip() if doc_name_el is not None else ""
        mbeam = re.match(r"Beam\s*(\d+)", doc_name, re.IGNORECASE)
        if not mbeam: continue
        beam_id = int(mbeam.group(1))
        if beam_id < 1 or beam_id > 8: continue

        for pm in doc.findall(".//kml:Placemark", ns):
            pm_name_el = pm.find("kml:name", ns)
            desc_el = pm.find("kml:description", ns)
            pm_name = (pm_name_el.text or "").strip() if pm_name_el is not None else ""
            desc = (desc_el.text or "").strip() if desc_el is not None else ""

            pol = None
            m = re.search(r"Pol\.\s*([A-Za-z]+)", desc)
            if m: pol = m.group(1).strip().capitalize()

            eirp = None
            m = re.search(r"@EIRP\s*([0-9.]+)", desc)
            if m:
                try: eirp = float(m.group(1))
                except: pass

            coords: list[tuple[float, float]] = []
            for coords_el in pm.findall(".//kml:coordinates", ns):
                if coords_el is None or not coords_el.text: continue
                for tok in coords_el.text.strip().split():
                    parts = tok.split(",")
                    if len(parts) >= 2: coords.append((float(parts[1]), float(parts[0])))

            if pol and coords:
                feats.append(KmlFeature(beam_id=beam_id, name=pm_name, pol=pol, coords=coords, eirp=eirp))

    return feats

def lookup_beam_pol_with_overlap_rule(lat: float, lon: float, feats: list[KmlFeature], near_m: float = NEAR_M) -> tuple[int | None, str | None, dict | None]:
    if not feats: return None, None, None
    scored = []
    for f in feats:
        md = min(haversine_m(lat, lon, la, lo) for (la, lo) in f.coords)
        scored.append((md, f))

    candidates = [(d, f) for (d, f) in scored if d <= near_m]
    if candidates:
        best_d, best_f = sorted(candidates, key=lambda item: (-(item[1].eirp if item[1].eirp is not None else float("-inf")), item[0]))[0]
    else:
        best_d, best_f = sorted(scored, key=lambda x: x[0])[0]

    return best_f.beam_id, best_f.pol, {}

def geodetic_to_ecef(lat_deg: float, lon_deg: float, alt_m: float):
    lat, lon = deg2rad(lat_deg), deg2rad(lon_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    N = WGS84_A / math.sqrt(1.0 - WGS84_E2 * (sin_lat ** 2))
    return (N + alt_m) * cos_lat * math.cos(lon), (N + alt_m) * cos_lat * math.sin(lon), (N * (1.0 - WGS84_E2) + alt_m) * sin_lat

def ecef_to_enu(dx: float, dy: float, dz: float, lat_deg: float, lon_deg: float):
    lat, lon = deg2rad(lat_deg), deg2rad(lon_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    return (-sin_lon * dx + cos_lon * dy), (-sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz), (cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz)

def compute_geo_pointing(gcs: PointLLA, sat_lon_deg: float, sat_radius_m: float) -> dict:
    X, Y, Z = geodetic_to_ecef(gcs.lat_deg, gcs.lon_deg, gcs.alt_m)
    Xs = sat_radius_m * math.cos(deg2rad(sat_lon_deg))
    Ys = sat_radius_m * math.sin(deg2rad(sat_lon_deg))
    
    E, N, U = ecef_to_enu(Xs - X, Ys - Y, -Z, gcs.lat_deg, gcs.lon_deg)
    az = wrap_360(rad2deg(math.atan2(E, N)))
    el = rad2deg(math.atan2(U, math.sqrt(E * E + N * N)))

    beam_id, pol_label, _ = lookup_beam_pol_with_overlap_rule(gcs.lat_deg, gcs.lon_deg, KML_FEATURES)
    
    return {"azimuth_deg": az, "elevation_deg": el, "beam_id": beam_id, "polar_label": pol_label}

# --- Load KML Once ---
try:
    KML_FEATURES = load_kml_features_beams_1_8(KML_PATH)
    print(f"[INFO] KML loaded. Total features: {len(KML_FEATURES)}")
except Exception as e:
    KML_FEATURES = []
    print(f"[WARN] Gagal load KML: {e}")

# --- Global State ---
telemetry_state = {
    "elevation": 0.0,
    "azimuth": 0.0,
    "polarization": 0.0,
    "status": "WAITING...",
    "checklist_step": 0,
    "log_message": "System Initialized",
    "gps_lat": 0.0,
    "gps_long": 0.0,
    "gps_alt": 0.0,
    "offset_az": 0.0,
    "offset_az_active": True,
    "offset_el": 0.0,
    "offset_el_active": False,
    "offset_pol": 0.0,
    "offset_pol_active": False,
    "system_mode": "AUTO",
    "sensor_status_gps": False,
    "sensor_status_ahrs": False,
    "sensor_status_encoder": False,
    "velocity_el": 0.0,
    "velocity_az": 0.0,
    "velocity_pol": 0.0,
    "step_size": 1.0,
    "satellite_id": "N1"
}

state_lock = threading.Lock()

# --- Sensor Configuration ---
COM_PORT = 'COM8'
BAUD_RATE = 9600
SLAVE_ID = 0x50

class WT901CSensor:
    def __init__(self, com_port=COM_PORT, baud_rate=BAUD_RATE):
        self.com_port = com_port
        self.baud_rate = baud_rate
        self.is_running = False
        self.thread = None

    def _log(self, message):
        """Updates the global log message."""
        print(f"[Sensor] {message}")
        with state_lock:
            telemetry_state['log_message'] = message

    def _update_state(self, updates):
        """Updates the global telemetry state safely."""
        with state_lock:
            telemetry_state.update(updates)

    def get_crc16(self, data: bytes) -> bytes:
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
        try:
            command = struct.pack('>BBHH', slave_id, 0x03, start_reg, count)
            command += self.get_crc16(command)
            ser.write(command)
            expected_len = 5 + 2 * count
            data = ser.read(expected_len)
            
            if len(data) < expected_len:
                return None
                
            received_crc = data[-2:]
            calculated_crc = self.get_crc16(data[:-2])
            if received_crc != calculated_crc:
                return None
                
            return data[3:-2]
        except Exception:
            return None

    def parse_sensor_data(self, payload):
        values = struct.unpack('>12h', payload)
        angle_x = values[9] / 32768.0 * 180.0
        angle_y = values[10] / 32768.0 * 180.0
        angle_z = values[11] / 32768.0 * 180.0
        return {"x": angle_x, "y": angle_y, "z": angle_z}

    def _run_loop(self):
        self._log(f"Service started. Target: {self.com_port}")
        
        while self.is_running:
            ser = None
            try:
                self._log(f"Connecting to {self.com_port}...")
                ser = serial.Serial(self.com_port, self.baud_rate, timeout=0.1)
                self._log(f"Connected to {self.com_port}")
                
                consecutive_failures = 0
                MAX_FAILURES = 20  # ~1 second of failures at 50ms interval
                
                while self.is_running and ser.is_open:
                    start_time = time.time()
                    try:
                        data_bytes = self.read_registers(ser, SLAVE_ID, 0x0034, 12)
                        if data_bytes:
                            consecutive_failures = 0  # Reset on success
                            data = self.parse_sensor_data(data_bytes)
                            raw_az = -data['z']
                            if raw_az < 0: raw_az += 360

                            self._update_state({
                                "azimuth": raw_az,
                                "elevation": data['y'],
                                "polarization": data['x'],
                                "status": "TRACKING",
                                "sensor_status_ahrs": True
                            })
                        else:
                            consecutive_failures += 1
                            if consecutive_failures >= MAX_FAILURES:
                                self._log(f"Sensor disconnected (no response)")
                                self._update_state({"status": "DISCONNECTED", "sensor_status_ahrs": False})
                                break  # Exit inner loop to trigger reconnect
                        
                    except serial.SerialException as e:
                        self._log(f"Serial Error: {e}")
                        self._update_state({"sensor_status_ahrs": False})
                        break
                    except Exception as e:
                        self._log(f"Error: {e}")
                        self._update_state({"sensor_status_ahrs": False})
                        break
                    
                    elapsed = time.time() - start_time
                    time.sleep(max(0, 0.05 - elapsed))
                    
            except serial.SerialException:
                self._update_state({"status": "ERROR", "sensor_status_ahrs": False})
                self._log(f"Failed to open {self.com_port}. Retrying in 2s...")
                time.sleep(2)
            except Exception as e:
                self._update_state({"status": "ERROR", "sensor_status_ahrs": False})
                self._log(f"Critical Error: {e}. Retrying in 2s...")
                time.sleep(2)
            finally:
                if ser and ser.is_open:
                    try: ser.close()
                    except: pass
        
        self._log("Service Stopped")
        self._update_state({"status": "STOPPED"})

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join()

sensor_service = WT901CSensor()

# --- Control Output (COM7 -> Slave) ---
CONTROL_COM_PORT = 'COM7'
CONTROL_BAUD_RATE = 115200
control_serial = None
control_lock = threading.Lock()

# Control state: [spd_azm, spd_elv, spd_pol, up, down, right, left, pol_right, pol_left]
control_state = {
    "spd_azm": 0,
    "spd_elv": 0,
    "spd_pol": 0,
    "up": 0,
    "down": 0,
    "right": 0,
    "left": 0,
    "pol_right": 0,
    "pol_left": 0
}

def init_control_serial():
    """Initialize the control serial port."""
    global control_serial
    try:
        control_serial = serial.Serial(CONTROL_COM_PORT, CONTROL_BAUD_RATE, timeout=0.1)
        print(f"[Control] Connected to {CONTROL_COM_PORT}")
        with state_lock:
            telemetry_state['sensor_status_encoder'] = True
            telemetry_state['log_message'] = f"Control connected: {CONTROL_COM_PORT}"
        return True
    except serial.SerialException as e:
        print(f"[Control] Failed to open {CONTROL_COM_PORT}: {e}")
        with state_lock:
            telemetry_state['sensor_status_encoder'] = False
        return False

def send_control_message():
    """Send control message to slave via COM7."""
    global control_serial
    
    with control_lock:
        # Format: spd_azm,spd_elv,spd_pol,up,down,right,left,pol_right,pol_left
        msg = f"{control_state['spd_azm']},{control_state['spd_elv']},{control_state['spd_pol']},{control_state['up']},{control_state['down']},{control_state['right']},{control_state['left']},{control_state['pol_right']},{control_state['pol_left']}\n"
    
    if control_serial and control_serial.is_open:
        try:
            control_serial.write(msg.encode('utf-8'))
            print(f"[Control] Sent: {msg.strip()}")
        except serial.SerialException as e:
            print(f"[Control] Write error: {e}")
            # Try to reconnect
            init_control_serial()
    else:
        # Try to connect if not connected
        if init_control_serial():
            try:
                control_serial.write(msg.encode('utf-8'))
                print(f"[Control] Sent: {msg.strip()}")
            except:
                pass

# Initialize control serial on startup
if os.name == 'nt':
    init_control_serial()
else:
    print("Non-Windows env: Skipping internal Control Serial (COM7).")

# Start Sensor Thread
# Start Sensor Thread (Only on Windows/Primary Node)
if os.name == 'nt':
    try:
        sensor_service.start()
    except Exception as e:
        print(f"Warning: Could not start sensor service: {e}")
else:
    print("Non-Windows env detected: Skipping internal sensor thread (Expecting external backend).")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/telemetry', methods=['GET', 'POST'])
def telemetry():
    # Direct access to global state (thread updates it in background)
    
    if request.method == 'POST':
        # RECEIVE data
        new_data = request.get_json()
        if new_data:
            with state_lock:
                telemetry_state.update(new_data)
                
            # --- AUTO CALCULATE POINTING & LOG ---
            if 'gps_lat' in new_data and 'gps_long' in new_data:
                try:
                    # Ambil data GPS saat ini
                    gcs = PointLLA(
                        lat_deg=float(telemetry_state.get('gps_lat', 0.0)),
                        lon_deg=float(telemetry_state.get('gps_long', 0.0)),
                        alt_m=float(telemetry_state.get('gps_alt', 0.0))
                    )
                    
                    # Hitung Arah ke Satelit
                    res = compute_geo_pointing(gcs, DEFAULT_SAT_LON_DEG, GEO_RADIUS_M)
                    
                    # Buatkan format pesan log
                    log_msg = f"Target N1 - Az:{res['azimuth_deg']:.1f}° El:{res['elevation_deg']:.1f}° Beam:{res['beam_id']} Pol:{res['polar_label']}"
                    
                    # Print ke terminal server back-end
                    print(f"[Pointing] {log_msg}")
                    
                    # Simpan ke log_message agar frontend bisa baca
                    with state_lock:
                        telemetry_state['log_message'] = log_msg
                        # also save the raw target points to state so frontend doesn't need to parse string
                        telemetry_state['target_az'] = round(res['azimuth_deg'], 2)
                        telemetry_state['target_el'] = round(res['elevation_deg'], 2)
                        telemetry_state['target_beam'] = res['beam_id']
                        telemetry_state['target_pol'] = res['polar_label']
                        
                except Exception as e:
                    err_msg = f"Gagal menghitung target: {e}"
                    print(f"[Pointing Error] {err_msg}")
                    with state_lock:
                        telemetry_state['log_message'] = err_msg

        return jsonify({"status": "success", "received": new_data}), 200
    
    else:
        # SEND data with offsets applied
        with state_lock:
            response_data = telemetry_state.copy()
        
        # Apply offsets if active
        if response_data.get('offset_el_active', False):
            response_data['elevation'] += response_data.get('offset_el', 0)
        if response_data.get('offset_az_active', False):
            try:
                # Add offset and modulo 360 to ensure 0-360 range
                az_val = response_data['azimuth'] + response_data.get('offset_az', 0)
                response_data['azimuth'] = az_val % 360.0
            except Exception:
                pass # safely ignore if types are wrong
        if response_data.get('offset_pol_active', False):
            response_data['polarization'] += response_data.get('offset_pol', 0)
        
        return jsonify(response_data)

@app.route('/api/control', methods=['POST'])
def control():
    global control_state
    
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No data"}), 400
    
    with control_lock:
        # Update control state with received values
        if 'spd_azm' in data:
            control_state['spd_azm'] = int(data['spd_azm'])
        if 'spd_elv' in data:
            control_state['spd_elv'] = int(data['spd_elv'])
        if 'spd_pol' in data:
            control_state['spd_pol'] = int(data['spd_pol'])
        if 'up' in data:
            control_state['up'] = int(data['up'])
        if 'down' in data:
            control_state['down'] = int(data['down'])
        if 'right' in data:
            control_state['right'] = int(data['right'])
        if 'left' in data:
            control_state['left'] = int(data['left'])
        if 'pol_right' in data:
            control_state['pol_right'] = int(data['pol_right'])
        if 'pol_left' in data:
            control_state['pol_left'] = int(data['pol_left'])
    
    # Send the message immediately
    send_control_message()
    
    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', debug=True, port=5000, use_reloader=False) 
        # use_reloader=False prevents double initialization of threads
    finally:
        sensor_service.stop()
        if control_serial and control_serial.is_open:
            control_serial.close()