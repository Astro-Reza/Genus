from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import serial
import math
import time
import struct
import threading
import os
import numpy as np
import socket
import re

# --- Flask App Setup ---
# Use absolute paths so the script works from any directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, 
            template_folder=os.path.join(SCRIPT_DIR, 'templates'), 
            static_folder=os.path.join(SCRIPT_DIR, 'static'))
socketio = SocketIO(app, async_mode='threading')

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
    "satellite_id": "N1",
    "target_az": 0.0,
    "target_el": 0.0,
    "target_beam": None,
    "target_pol": None,
    "locked": False,
    "auto_state": "IDLE",
    "target_satellite_lon": None,
    "amip_ip": "192.168.0.2",
    "amip_port": 2000,
    "amip_active": False,
    "tracking_mode": "amip",
    "agc_threshold": -20.0,
    "dvb_symbol_rate": 27500.0,
    "dvb_nid": "00A1",
    "amip_log_buffer": ["[INFO] ACU Ready"]
}

state_lock = threading.Lock()

# --- Hardware Configuration ---
GPS_PORT = '/dev/ttyS5'
GPS_BAUD = 9600
AHRS_PORT = '/dev/ttyUSB0'
AHRS_BAUD = 9600
CONTROL_PORT = '/dev/ttyS1' 
CONTROL_BAUD = 115200

# --- UTILS & Math Models ---
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

WGS84_A = 6378137.0
WGS84_E2 = 0.00669437999014
GEO_RADIUS_M = 42164000.0
NEAR_M = 30000.0

# Path KML (disamakan ke folder static seperti di app1.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KML_PATH = os.path.join(BASE_DIR, "static", "NUSANTARA SATU.kml")

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

def load_kml_features_beams_1_8(kml_path: str) -> list[KmlFeature]:
    if not os.path.exists(kml_path):
        print(f"[WARN] File KML tidak ditemukan di: {kml_path}")
        return []
        
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    try:
        tree = ET.parse(kml_path)
    except Exception as e:
        print(f"[WARN] Gagal parse KML: {e}")
        return []
        
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

def deg2rad(d: float) -> float: return d * math.pi / 180.0
def rad2deg(r: float) -> float: return r * 180.0 / math.pi
def wrap_360(deg: float) -> float:
    deg = deg % 360.0
    return deg if deg >= 0 else deg + 360.0
def _clamp(x: float, lo: float, hi: float) -> float: return max(lo, min(hi, x))

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    p1 = deg2rad(lat1)
    p2 = deg2rad(lat2)
    dp = p2 - p1
    dl = deg2rad(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2) + math.cos(p1) * math.cos(p2) * (math.sin(dl / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(_clamp(a, 0.0, 1.0)))

def lookup_beam_pol_with_overlap_rule(lat: float, lon: float, feats: list[KmlFeature], near_m: float = NEAR_M):
    if not feats: return None, None, {}
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

# --- Load KML Once saat OrangePi booting ---
KML_FEATURES = load_kml_features_beams_1_8(KML_PATH)
print(f"[INFO] KML loaded on Orange Pi. Total features: {len(KML_FEATURES)}")

def calculate_pointing(lat, lon, sat_lon):
    """
    Calculate azimuth and elevation for geostationary satellite.
    lat, lon, sat_lon in degrees.
    """
    rad = math.pi / 180.0
    deg = 180.0 / math.pi
    
    # Earth radius and geostationary radius (km)
    Re = 6378.137
    Rs = 42164.0
    
    lat_rad = lat * rad
    lon_diff_rad = (sat_lon - lon) * rad
    
    # Beta angle
    b = math.acos(math.cos(lat_rad) * math.cos(lon_diff_rad))
    
    # Elevation
    # el = atan( (cos(b) - (Re/Rs)) / sin(b) )
    # Check for division by zero (if b is 0, user is under satellite)
    if abs(math.sin(b)) < 1e-6:
        el = 90.0
    else:
        el = math.atan((math.cos(b) - (Re / Rs)) / math.sin(b)) * deg
    
    # Azimuth
    # Northern Hemisphere
    if lat > 0:
        az = 180.0 + math.atan(math.tan(lon_diff_rad) / math.sin(lat_rad)) * deg
    # Southern Hemisphere
    else:
        az = math.atan(math.tan(lon_diff_rad) / math.sin(lat_rad)) * deg
        if az < 0: az += 360.0
        
    # Equator edge cases simplified above or handled by math domain
    
    # 4. Cari Beam dan Polarisasi dari KML
    beam_id, pol_label, _ = lookup_beam_pol_with_overlap_rule(lat, lon, KML_FEATURES)
    
    return {
        "azimuth": (az + 360) % 360,
        "elevation": el,
        "beam_id": beam_id,
        "polar_label": pol_label
    }

# --- CLASS: AUTO POINTING LOGIC (Background Thread) ---
class AdaptivePWMController:
    """
    Three-layer adaptive PWM for JGY-370 + L298N on an antenna positioner.

    Layer 1 — Dead-zone compensator:
        L298N drops ~2 V internally, so PWM values below ~20–25% produce
        zero torque.  We remap the *logical* 0-100 range through this gap
        so that cmd=1 always produces some motion.

    Layer 2 — Stiction (static-friction) kickstart:
        Worm-gear static friction is higher than running friction.  When the
        controller detects zero angular rate despite a nonzero error for
        STALL_COUNT_THRESHOLD consecutive cycles, it fires a brief high-PWM
        burst to break the gear free, then hands control back to the PI.

    Layer 3 — Gravity feedforward (elevation axis only):
        Load torque ∝ cos(elevation).  At 0° elevation the motor fights full
        gravitational moment; at 90° it fights nothing.  A cosine feedforward
        term pre-compensates this so the PI loop only has to correct residual
        errors, not the bulk of the load.

    Usage
    -----
        ctrl_az  = AdaptivePWMController('az')
        ctrl_el  = AdaptivePWMController('el')

        # inside your 10 Hz loop:
        pwm = ctrl_el.compute(el_error_deg, current_el_deg)
        if el_error_deg > 0:
            cmd = {"up": 1, "spd_elv": pwm}
        else:
            cmd = {"down": 1, "spd_elv": pwm}
    """

    # ------------------------------------------------------------------ config
    # L298N dead-zone: commands below this produce no torque at all.
    # Tune with a multimeter on the motor terminals vs duty-cycle.
    PWM_DEADZONE_MIN: int = 25      # % below which L298N produces no motion
    PWM_MAX:          int = 100

    # Kickstart burst parameters
    KICKSTART_PWM:        int   = 45    # % — strong enough to break stiction
    KICKSTART_DURATION_S: float = 0.15  # seconds — short enough not to overshoot

    # Stall detection: how many 0.1-s ticks at near-zero rate before we kick
    STALL_COUNT_THRESHOLD: int   = 5   # 5 ticks × 0.1 s = 0.5 s of stall
    STALL_RATE_DEG_S:      float = 0.1 # deg/s — below this we call it stalled

    # PI gains — tune in this order: raise Kp until you see oscillation, halve
    # it, then raise Ki until steady-state error is zero.
    KP_DEFAULT = {"az": 3.5, "el": 3.0}
    KI_DEFAULT = {"az": 0.4, "el": 0.5}

    INTEGRAL_MAX: float = 20.0  # anti-windup clamp (deg)

    # Gravity feedforward (elevation only)
    # FF_PEAK is the PWM percentage added at 0° elevation to hold the antenna
    # against gravity.  Measure: command 0 PWM and find the minimum PWM that
    # keeps the antenna from drifting down when pointing at the horizon.
    FF_PEAK_PERCENT: float = 12.0

    def __init__(self, axis: str = "az"):
        if axis not in ("az", "el", "pol"):
            raise ValueError("axis must be 'az', 'el', or 'pol'")
        self.axis = axis

        self.kp = self.KP_DEFAULT.get(axis, 3.0)
        self.ki = self.KI_DEFAULT.get(axis, 0.5)

        self._integral:      float = 0.0
        self._prev_pos:      float = 0.0
        self._prev_time:     float = time.monotonic()
        self._measured_rate: float = 0.0   # deg / s (magnitude)

        # Stall / kickstart state
        self._stall_counter:    int   = 0
        self._kickstart_active: bool  = False
        self._kickstart_start:  float = 0.0

        self._lock = threading.Lock()  # thread-safe if called from multiple threads

    # ------------------------------------------------------------------ public
    def reset(self):
        """Call when switching from MANUAL to AUTO or after a large target jump."""
        with self._lock:
            self._integral      = 0.0
            self._stall_counter = 0
            self._kickstart_active = False

    @property
    def measured_rate(self) -> float:
        """Angular rate (deg/s) observed on the last compute() call."""
        return self._measured_rate

    def compute(
        self,
        error_deg:   float,
        current_pos: float,
        current_el:  float = 0.0,
    ) -> int:
        """
        Parameters
        ----------
        error_deg   : signed angular error (target − current), degrees
        current_pos : current axis angle from AHRS, degrees
        current_el  : current elevation angle — used only for gravity FF

        Returns
        -------
        PWM value in range [0, 100] (integer percent)
        The *direction* (up/down/left/right) is the caller's responsibility.
        """
        with self._lock:
            return self._compute_locked(error_deg, current_pos, current_el)

    # ----------------------------------------------------------------- private
    def _compute_locked(self, error_deg, current_pos, current_el):
        now = time.monotonic()
        dt  = max(now - self._prev_time, 0.01)   # floor at 10 ms

        # ── 1. Angular rate measurement ────────────────────────────────────
        self._measured_rate = abs(current_pos - self._prev_pos) / dt
        self._prev_pos  = current_pos
        self._prev_time = now

        abs_err = abs(error_deg)

        # ── 2. Stall detection ─────────────────────────────────────────────
        #  Only watch for stalls when we have a meaningful error to correct.
        if abs_err > 1.5:
            if self._measured_rate < self.STALL_RATE_DEG_S:
                self._stall_counter += 1
            else:
                self._stall_counter = 0
        else:
            # Within dead-band — reset stall so we don't kick needlessly
            self._stall_counter = 0

        # ── 3. Kickstart burst ─────────────────────────────────────────────
        if self._stall_counter >= self.STALL_COUNT_THRESHOLD and not self._kickstart_active:
            self._kickstart_active = True
            self._kickstart_start  = now
            self._integral         = 0.0   # flush wound-up integral
            self._stall_counter    = 0

        if self._kickstart_active:
            if now - self._kickstart_start < self.KICKSTART_DURATION_S:
                return self.KICKSTART_PWM        # ← burst, skip rest of logic
            self._kickstart_active = False       # burst done

        # ── 4. PI control ─────────────────────────────────────────────────
        self._integral += error_deg * dt
        self._integral  = max(-self.INTEGRAL_MAX,
                              min(self.INTEGRAL_MAX, self._integral))

        pwm_pi = self.kp * abs_err + self.ki * abs(self._integral)

        # ── 5. Gravity feedforward (elevation axis only) ───────────────────
        ff = 0.0
        if self.axis == "el":
            el_rad = math.radians(current_el)
            ff     = self.FF_PEAK_PERCENT * math.cos(el_rad)
            ff     = max(0.0, ff)

        # ── 6. Dead-zone compensation ──────────────────────────────────────
        #  Map the logical [0, 100] range to [PWM_DEADZONE_MIN, PWM_MAX].
        #  This ensures that even a small PI output produces actual shaft motion.
        raw = pwm_pi + ff
        if raw > 0.01:
            span = self.PWM_MAX - self.PWM_DEADZONE_MIN
            pwm_final = self.PWM_DEADZONE_MIN + (raw / 100.0) * span
        else:
            pwm_final = 0.0

        return int(max(0, min(self.PWM_MAX, pwm_final)))


class AutoPointing:
    def __init__(self, ctrl_service):
        self.ctrl = ctrl_service
        self.running = False
        self.thread = None
        self.state = "INIT"
        self.last_state_change = 0
        self.sweep_step = 0
        self.sweep_dir = 1

        self.ctrl_az  = AdaptivePWMController("az")
        self.ctrl_el  = AdaptivePWMController("el")
        
        # Satellite Longitudes
        self.satellites = {
            "N1": 146.0,
            "N5": 113.0
        }

    def _get_time(self):
        return time.time()

    def _set_log(self, msg):
        with state_lock:
            if telemetry_state["log_message"] != msg:
                telemetry_state["log_message"] = msg

    def _move_motor(self, cmd_dict):
        self.ctrl.update_command(cmd_dict)

    def _stop_motors(self):
        self.ctrl.update_command({
            "spd_azm": 0, "spd_elv": 0, "spd_pol": 0,
            "up": 0, "down": 0, "right": 0, "left": 0
        })

    def _run(self):
        print("[AutoPoint] Starting...")
        last_mode = None  # Fix: initialize before use
        while self.running:
            time.sleep(0.1) # 10Hz Logic Loop
            
            # 1. READ STATE
            with state_lock:
                mode = telemetry_state.get("system_mode", "MANUAL")
                gps_ok = telemetry_state.get("sensor_status_gps", False)
                ahrs_ok = telemetry_state.get("sensor_status_ahrs", False)
                encoder_ok = telemetry_state.get("sensor_status_encoder", False)
                lat = telemetry_state.get("gps_lat", 0.0)
                lon = telemetry_state.get("gps_long", 0.0)
                curr_az = telemetry_state.get("azimuth", 0.0)
                curr_el = telemetry_state.get("elevation", 0.0)
                
                # Apply Offsets
                if telemetry_state.get("offset_az_active", False):
                    curr_az = (curr_az + telemetry_state.get("offset_az", 0.0)) % 360.0
                if telemetry_state.get("offset_el_active", False):
                    curr_el += telemetry_state.get("offset_el", 0.0)
                    
                sat_id = telemetry_state.get("satellite_id", "N1")
                is_locked = telemetry_state.get("locked", False)
                
            # Update public state for UI
            with state_lock:
                telemetry_state["auto_state"] = self.state

            # 2. MODE TRANSITION CHECK (Interference Fix)
            if mode != "AUTO":
                if last_mode == "AUTO":
                    self.state = "IDLE"
                    self._stop_motors()
                    self._set_log("Manual Mode Active")
                last_mode = mode
                continue
            elif last_mode != "AUTO":
                # Just switched INTO auto — flush any stale integrator state
                self.ctrl_az.reset()
                self.ctrl_el.reset()
                self.state = "INIT"
                self._set_log("Auto Mode Active")

            last_mode = mode
            
            last_mode = mode

            if is_locked:
                if self.state != "LOCKED":
                    self.state = "LOCKED"
                    self._stop_motors()
                    self._set_log("System Locked")
                    with state_lock:
                        telemetry_state["checklist_step"] = 6 # Antenna Lock (or adjust to 10 for 'Ready')
                continue

            # 3. STATE MACHINE
            now = self._get_time()
            mode_trk = telemetry_state.get("tracking_mode", "amip")
            if mode_trk == "amip" and telemetry_state.get("target_satellite_lon") is not None:
                sat_lon = telemetry_state.get("target_satellite_lon")
            else:
                sat_lon = self.satellites.get(sat_id, 146.0)

            if self.state == "IDLE":
                self.state = "INIT"

            elif self.state == "INIT":
                self._set_log("Initializing Sensors...")
                with state_lock:
                    telemetry_state["checklist_step"] = 2 # Sensor Initialize
                
                if gps_ok and ahrs_ok and encoder_ok:
                    self.state = "GPS_WAIT"
                else:
                    self._stop_motors()

            elif self.state == "GPS_WAIT":
                self._set_log("Waiting for GPS Fix...")
                with state_lock:
                    telemetry_state["checklist_step"] = 3 # GPS Lock
                if abs(lat) > 0.0001:
                    self.state = "CALC"

            elif self.state == "CALC":
                with state_lock:
                    telemetry_state["checklist_step"] = 4 # Calculate Pointing
                
                if abs(lat) > 0.01: 
                    target = calculate_pointing(lat, lon, sat_lon)
                    with state_lock:
                        telemetry_state["target_az"] = round(target['azimuth'], 2)
                        telemetry_state["target_el"] = round(target['elevation'], 2)
                        telemetry_state["target_beam"] = target.get('beam_id')
                        telemetry_state["target_pol"] = target.get('polar_label')
                    self._set_log(f"Target: Az {target['azimuth']:.1f}deg El {target['elevation']:.1f}deg | Beam: {target.get('beam_id')} Pol: {target.get('polar_label')}")
                    self.state = "SEEK"
                else:
                    self.state = "GPS_WAIT"

            elif self.state == "SEEK":
                with state_lock:
                    tgt_az = telemetry_state["target_az"]
                    tgt_el = telemetry_state["target_el"]

                # Signed azimuth error, normalised to −180..+180
                az_err = tgt_az - curr_az
                if az_err > 180:  az_err -= 360
                if az_err < -180: az_err += 360

                el_err = tgt_el - curr_el

                # Compute adaptive PWM for each axis independently.
                # Pass current_el into both so gravity FF has the real angle.
                spd_az = self.ctrl_az.compute(az_err, curr_az, current_el=curr_el)
                spd_el = self.ctrl_el.compute(el_err, curr_el, current_el=curr_el)

                cmd = {
                    "spd_azm": spd_az,
                    "spd_elv": spd_el,
                    "spd_pol": 0,
                    "up":    0, "down":  0,
                    "right": 0, "left":  0,
                }

                aligned = True

                # Deadband: 1.0° — inside this the motor is off
                if abs(az_err) > 1.0:
                    aligned = False
                    cmd["right"] = 1 if az_err > 0 else 0
                    cmd["left"]  = 1 if az_err < 0 else 0

                if abs(el_err) > 1.0:
                    aligned = False
                    cmd["up"]   = 1 if el_err > 0 else 0
                    cmd["down"] = 1 if el_err < 0 else 0

                self._move_motor(cmd)
                self._set_log(
                    f"Seek Az:{az_err:+.1f}deg El:{el_err:+.1f}deg | "
                    f"PWM az:{spd_az} el:{spd_el} | "
                    f"rate az:{self.ctrl_az.measured_rate:.1f} el:{self.ctrl_el.measured_rate:.1f} °/s"
                )

                with state_lock:
                    telemetry_state["checklist_step"] = 5

                if aligned:
                    # Reset integrators so HOLD/SEARCH won't inherit wound-up state
                    self.ctrl_az.reset()
                    self.ctrl_el.reset()
                    self.state = "HOLD"
                    self.last_state_change = now
                    self._stop_motors()

            elif self.state == "HOLD":
                self._set_log("System Hold (5s)...") # Updated: 5s
                if now - self.last_state_change > 5.0:
                    self.state = "SEARCH_SEQ"
                    self._stop_motors()
                    
                    # Initialize Search Sequence State
                    with state_lock:
                        self.center_az = curr_az
                        self.center_el = curr_el
                    
                    self.seq_step = 1
                    self.seq_substep_target = None
                    self._set_log("Starting Search Pattern...")

            elif self.state == "SEARCH_SEQ":
                spd = 6 # Updated: Speed 6%
                cmd = {"spd_azm": spd, "spd_elv": spd, "up": 0, "down": 0, "right": 0, "left": 0}
                
                # Helper to move to relative target
                # If target reached (within tolerance), increments seq_step.
                
                # Define Sequence Targets (Relative to Center)
                # Step 1: Sweep right 10 degree -> Target: CenterAz + 10
                # Step 2: Sweep left 20 degree  -> Target: (CenterAz + 10) - 20 = CenterAz - 10
                # Step 3: Up 5 degree           -> Target: CenterEl - 5 (Up decreases val)
                # Step 4: Sweep 20 right        -> Target: (CenterAz - 10) + 20 = CenterAz + 10
                # Step 5: Down 10 degree        -> Target: (CenterEl - 5) + 10 = CenterEl + 5
                # Step 6: Wipe 20 left          -> Target: (CenterAz + 10) - 20 = CenterAz - 10
                
                if self.seq_step == 1:
                    # Target: Az + 10
                    tgt_az = (self.center_az + 10.0) % 360
                    self._set_log("Step 1: Sweep Right 10 -> {:.1f}".format(tgt_az))
                    if self._move_to_az(curr_az, tgt_az, cmd):
                        self.seq_step += 1
                        
                elif self.seq_step == 2:
                    # Target: Az - 10
                    tgt_az = (self.center_az - 10.0) % 360
                    self._set_log("Step 2: Sweep Left 20 -> {:.1f}".format(tgt_az))
                    if self._move_to_az(curr_az, tgt_az, cmd):
                        self.seq_step += 1

                elif self.seq_step == 3:
                    # Target: El - 5 (Up)
                    # Note: We maintain the current Az (which should be CenterAz - 10 from Step 2)
                    tgt_el = max(0, self.center_el - 5.0)
                    self._set_log("Step 3: Up 5 -> {:.1f}".format(tgt_el))
                    if self._move_to_el(curr_el, tgt_el, cmd):
                        self.seq_step += 1

                elif self.seq_step == 4:
                    # Target: Az + 10 (Sweep Right 20 from -10)
                    tgt_az = (self.center_az + 10.0) % 360
                    self._set_log("Step 4: Sweep Right 20 -> {:.1f}".format(tgt_az))
                    if self._move_to_az(curr_az, tgt_az, cmd):
                        self.seq_step += 1

                elif self.seq_step == 5:
                    # Target: El + 5 (Down 10 from -5)
                    tgt_el = min(90, (self.center_el - 5.0) + 10.0) # Center + 5 effectively
                    self._set_log("Step 5: Down 10 -> {:.1f}".format(tgt_el))
                    if self._move_to_el(curr_el, tgt_el, cmd):
                        self.seq_step += 1

                elif self.seq_step == 6:
                    # Target: Az - 10 (Wipe Left 20 from +10)
                    tgt_az = (self.center_az - 10.0) % 360
                    self._set_log("Step 6: Wipe Left 20 -> {:.1f}".format(tgt_az))
                    if self._move_to_az(curr_az, tgt_az, cmd):
                        self.seq_step += 1
                
                else:
                    self.state = "DONE"
                    self._stop_motors()
                    self._set_log("Search Pattern Complete.")
                
                if self.state == "SEARCH_SEQ":
                    self._move_motor(cmd)

    # --- Helper methods for Search Sequence ---
    def _move_to_az(self, curr, target, cmd):
        """Returns True if reached"""
        diff = target - curr
        if diff > 180: diff -= 360
        if diff < -180: diff += 360
        
        if abs(diff) < 1.0: return True
        
        if diff > 0: cmd["right"] = 1
        else: cmd["left"] = 1
        return False

    def _move_to_el(self, curr, target, cmd):
        """Returns True if reached"""
        diff = target - curr
        if abs(diff) < 1.0: return True
        
        if diff > 0: cmd["up"] = 1 # Down increases El
        else: cmd["down"] = 1 # Up decreases El
        return False

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread: self.thread.join()



# --- CLASS: GPS READER (Background Thread) ---
class GPSReader:
    def __init__(self, port=GPS_PORT, baud=GPS_BAUD):
        self.port = port
        self.baud = baud
        self.running = False
        self.thread = None

    def parse_gpgga(self, line):
        try:
            parts = line.split(',')
            if len(parts) < 10 or not parts[2] or not parts[4]: return None
            
            def dm_to_dd(val, direction):
                if not val: return 0.0
                decimal_point = val.find('.')
                if decimal_point == -1: return 0.0
                degrees = float(val[:decimal_point-2])
                minutes = float(val[decimal_point-2:])
                dd = degrees + minutes / 60.0
                if direction in ['S', 'W']: dd = -dd
                return dd

            return {
                "lat": dm_to_dd(parts[2], parts[3]), 
                "long": dm_to_dd(parts[4], parts[5]), 
                "alt": float(parts[9]) if parts[9] else 0.0
            }
        except: return None

    def _run(self):
        print("[GPS] Starting on {}...".format(self.port))
        while self.running:
            ser = None
            try:
                ser = serial.Serial(self.port, self.baud, timeout=1)
                print("[GPS] Connected")
                while self.running and ser.is_open:
                    try:
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        if line.startswith('$GPGGA'):
                            data = self.parse_gpgga(line)
                            with state_lock:
                                if data:
                                    telemetry_state.update({
                                        "sensor_status_gps": True,
                                        "gps_lat": data['lat'],
                                        "gps_long": data['long'],
                                        "gps_alt": data['alt']
                                    })
                                    # Auto-recalculate pointing target whenever GPS updates
                                    lat = data['lat']
                                    lon = data['long']
                                    sat_id = telemetry_state.get("satellite_id", "N1")
                                    sat_lons = {"N1": 146.0, "N5": 113.0}
                                    sat_lon = sat_lons.get(sat_id, 146.0)
                                    if abs(lat) > 0.01:
                                        try:
                                            target = calculate_pointing(lat, lon, sat_lon)
                                            telemetry_state["target_az"] = round(target['azimuth'], 2)
                                            telemetry_state["target_el"] = round(target['elevation'], 2)
                                            telemetry_state["target_beam"] = target.get('beam_id')
                                            telemetry_state["target_pol"] = target.get('polar_label')
                                        except Exception as e:
                                            print(f"[GPS Pointing Calc Error] {e}")
                                else:
                                    telemetry_state["sensor_status_gps"] = True
                    except serial.SerialException: break 
            except Exception:
                with state_lock: telemetry_state["sensor_status_gps"] = False
                time.sleep(2)
            finally:
                if ser: ser.close()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread: self.thread.join()

# --- CLASS: AHRS READER (Background Thread) ---
class WT901CReader:
    def __init__(self, port=AHRS_PORT, baud=AHRS_BAUD):
        self.port = port
        self.baud = baud
        self.running = False
        self.thread = None

    def calculate_crc16(self, data):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1: crc = (crc >> 1) ^ 0xA001
                else: crc >>= 1
        return struct.pack('<H', crc)

    def _run(self):
        print("[AHRS] Starting on {}...".format(self.port))
        while self.running:
            ser = None
            try:
                ser = serial.Serial(self.port, self.baud, timeout=0.2)
                print("[AHRS] Connected")
                while self.running and ser.is_open:
                    try:
                        # Request Angle Data (0x50 slave ID hardcoded for now)
                        req = struct.pack('>BBHH', 0x50, 0x03, 0x0034, 12)
                        req += self.calculate_crc16(req)
                        ser.reset_input_buffer()
                        ser.write(req)
                        res = ser.read(29)
                        
                        if len(res) == 29 and res[-2:] == self.calculate_crc16(res[:-2]):
                            val = struct.unpack('>12h', res[3:27])
                            x = val[9] / 32768.0 * 180.0
                            y = val[10] / 32768.0 * 180.0
                            z = val[11] / 32768.0 * 180.0
                            z_norm = z if z >= 0 else z + 360
                            
                            with state_lock:
                                telemetry_state.update({
                                    "sensor_status_ahrs": True,
                                    "polarization": x,
                                    "elevation": 90.0 - y,
                                    "azimuth": (360.0 - z_norm) % 360.0,
                                    "status": "TRACKING"
                                })
                        else:
                            pass # Bad CRC or partial data
                        
                        time.sleep(0.05) # ~20Hz update rate
                    except serial.SerialException: break
            except Exception:
                with state_lock: 
                    telemetry_state["sensor_status_ahrs"] = False
                    telemetry_state["status"] = "DISCONNECTED"
                time.sleep(2)
            finally:
                if ser: ser.close()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread: self.thread.join()

# --- CLASS: CONTROL SENDER via SPI (Background Thread) ---
# Sends 9 bytes to ESP32 SPI Slave: [SpdAz, SpdEl, SpdPol, Up, Dn, Rt, Lt, PRt, PLt]
class ControlSender:
    def __init__(self, spi_bus=1, spi_device=1):
        """
        SPI Configuration for Orange Pi Zero 3:
        - spi_bus: Usually 1 (check /dev/spidev*)
        - spi_device: Usually 0 (CS0)
        """
        self.spi_bus = spi_bus
        self.spi_device = spi_device
        self.running = False
        self.thread = None
        self.state = {
            "spd_azm": 0, "spd_elv": 0, "spd_pol": 0,
            "up": 0, "down": 0, "right": 0, "left": 0,
            "pol_right": 0, "pol_left": 0
        }
        self.lock = threading.Lock()

    def update_command(self, new_data):
        """Called by Flask Route to update targets"""
        with self.lock:
            for k in self.state.keys():
                if k in new_data:
                    self.state[k] = int(new_data[k])

    def _run(self):
        print("[Control/SPI] Starting on /dev/spidev{}.{}...".format(self.spi_bus, self.spi_device))
        
        while self.running:
            spi = None
            try:
                import spidev
                spi = spidev.SpiDev()
                spi.open(self.spi_bus, self.spi_device)
                spi.max_speed_hz = 1000000  # 1 MHz (adjust if needed)
                spi.mode = 0  # SPI Mode 0 (matches ESP32 config)
                print("[Control/SPI] Connected")
                
                with state_lock: 
                    telemetry_state['sensor_status_encoder'] = True

                while self.running:
                    # 1. Get current command snapshot
                    with self.lock:
                        cmd = self.state.copy()
                    
                    # 2. Build 12-byte payload (matching ESP32 expectations + 32-bit DMA alignment)
                    # Clamp values to 0-255 for bytes
                    payload = [
                        max(0, min(100, cmd['spd_azm'])),   # Byte 0: Speed Azimuth (0-100)
                        max(0, min(100, cmd['spd_elv'])),   # Byte 1: Speed Elevation (0-100)
                        max(0, min(100, cmd['spd_pol'])),   # Byte 2: Speed Polarization (0-100)
                        1 if cmd['up'] else 0,              # Byte 3: Up
                        1 if cmd['down'] else 0,            # Byte 4: Down
                        1 if cmd['right'] else 0,           # Byte 5: Right
                        1 if cmd['left'] else 0,            # Byte 6: Left
                        1 if cmd['pol_right'] else 0,       # Byte 7: Pol Right
                        1 if cmd['pol_left'] else 0,        # Byte 8: Pol Left
                        0, 0, 0                             # Bytes 9-11: Padding for ESP32 SPI Slave DMA
                    ]
                    
                    # 3. Send via SPI
                    try:
                        spi.xfer2(payload)
                    except Exception as e:
                        print("[Control/SPI] Write Error: {}".format(e))
                        break
                    
                    # 4. Limit Rate (~20Hz)
                    time.sleep(0.05)

            except ImportError:
                print("[Control/SPI] ERROR: spidev not installed. Run: pip install spidev")
                with state_lock: telemetry_state['sensor_status_encoder'] = False
                time.sleep(10)  
            except FileNotFoundError:
                print("[Control/SPI] ERROR: /dev/spidev{}.{} not found. Enable SPI in armbian-config.".format(self.spi_bus, self.spi_device))
                with state_lock: telemetry_state['sensor_status_encoder'] = False
                time.sleep(5)
            except Exception as e:
                print("[Control/SPI] Error: {}".format(e))
                with state_lock: telemetry_state['sensor_status_encoder'] = False
                time.sleep(2)
            finally:
                if spi:
                    try: spi.close()
                    except: pass

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread: self.thread.join()

# --- INITIALIZATION ---
gps_service = GPSReader()
ahrs_service = WT901CReader()
control_service = ControlSender()
auto_service = AutoPointing(control_service)

# --- ACU AMIP & SDR Integration ---
amip_thread = None
amip_stop_event = threading.Event()
spectrum_threads = {}

def add_amip_log(msg):
    log_entry = "[{}] {}".format(time.strftime('%H:%M:%S'), msg)
    with state_lock:
        if len(telemetry_state["amip_log_buffer"]) > 50:
            telemetry_state["amip_log_buffer"].pop(0)
        telemetry_state["amip_log_buffer"].append(log_entry)
    print("[AMIP] {}".format(msg))

def openamip_server_thread():
    with state_lock:
        telemetry_state["amip_active"] = True

    while not amip_stop_event.is_set():
        with state_lock:
            # Kita simpan IP yang diinput user untuk keperluan display/konfigurasi sistem
            # Namun untuk socket python, kita BIND ke 0.0.0.0 agar tidak pernah error 10049 di Windows
            display_ip = telemetry_state.get("amip_ip", "192.168.0.2")
            acu_port = telemetry_state.get("amip_port", 2000)
            
        amip_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        amip_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            amip_server_socket.bind(('0.0.0.0', acu_port))
            amip_server_socket.listen(1)
            add_amip_log("Server Listening di Port {} (Virtual IP: {})".format(acu_port, display_ip))
        except Exception as e:
            add_amip_log("Gagal Bind: {}".format(e))
            time.sleep(2)
            continue
            
        try:
            while not amip_stop_event.is_set():
                amip_server_socket.settimeout(1.0)
                try:
                    conn, addr = amip_server_socket.accept()
                except socket.timeout:
                    continue
                except Exception:
                    break
                    
                with conn:
                    add_amip_log("Modem Connected: {}".format(addr[0]))
                    conn.setblocking(False)
                    while not amip_stop_event.is_set():
                        try:
                            data = conn.recv(1024)
                            if not data: break
                            msg = data.decode('utf-8').strip()
                            for line in msg.splitlines():
                                add_amip_log("RX: {}".format(line))
                                parts = line.split()
                                cmd = parts[0] if parts else ''
                                res = None
                                
                                if cmd == 'W': # GPS Request
                                    with state_lock: 
                                        lat, lon = telemetry_state.get('gps_lat', 0.0), telemetry_state.get('gps_long', 0.0)
                                    res = "w 1 {:.6f} {:.6f} {} 0 0 0 0 0\r\n".format(lat, lon, int(time.time()))
                                elif cmd == 'S': # Sat Target
                                    with state_lock: 
                                        telemetry_state['target_satellite_lon'] = float(parts[1])
                                        telemetry_state['system_mode'] = 'AUTO'
                                elif cmd == 'A': 
                                    res = "a 1\r\n"
                                elif cmd == 'F': # Finalization
                                    pass
                                elif cmd == 'L': # Lock Status
                                    with state_lock:
                                        if len(parts) >= 2 and telemetry_state.get('tracking_mode') == 'openamip':
                                            telemetry_state['locked'] = (parts[1] == '1')
                                        
                                if res:
                                    conn.sendall(res.encode('utf-8'))
                                    add_amip_log("TX: {}".format(res.strip()))
                        except BlockingIOError: 
                            time.sleep(0.1)
                        except Exception: 
                            break
        finally:
            amip_server_socket.close()

    with state_lock:
        telemetry_state["amip_active"] = False
    add_amip_log("AMIP Server Stopped.")


class DVBS2_Demodulator:
    def __init__(self):
        self.phase = 0.0
        self.freq = 0.0
        self.loop_bw = 0.05
        self.alpha = np.sqrt(2) * self.loop_bw
        self.beta = self.loop_bw * self.loop_bw

    def process_carrier(self, iq_samples):
        locked_samples = np.zeros(len(iq_samples), dtype=np.complex64)
        error_sum = 0.0
        for i in range(len(iq_samples)):
            locked_samples[i] = iq_samples[i] * np.exp(-1j * self.phase)
            error = np.sign(locked_samples[i].real) * locked_samples[i].imag - \
                    np.sign(locked_samples[i].imag) * locked_samples[i].real
            self.freq += self.beta * error
            self.phase += self.freq + self.alpha * error
            error_sum += abs(error)
        avg_error = error_sum / len(iq_samples)
        power_level = np.mean(np.abs(iq_samples))
        
        # Dilonggarkan: error rate dari 0.2 jadi 0.35, power_level minimal 0.005
        is_locked = (avg_error < 0.35) and (power_level > 0.005)
        return is_locked, avg_error

class Beacon_Detector:
    def __init__(self):
        pass

    def process_beacon(self, freqs_mhz, powers, target_mhz, threshold_db):
        """ Detects a narrow CW Beacon Peak at Absolute Frequency """
        if target_mhz < freqs_mhz[0] or target_mhz > freqs_mhz[-1]:
            return False, -180.0
            
        idx = (np.abs(freqs_mhz - target_mhz)).argmin()
        
        start_idx = max(0, idx - 5)
        end_idx = min(len(powers), idx + 6)
        
        peak_power = np.max(powers[start_idx:end_idx])
        
        noise_floor = np.median(powers)
        snr = peak_power - noise_floor
        
        # Dilonggarkan: SNR cukup 3.0 dB di atas noise floor, tidak perlu 10 dB
        is_locked = (peak_power > threshold_db) and (snr > 3.0)
        return is_locked, peak_power

def spectrum_worker(sid):
    try:
        from rtlsdr import RtlSdr
        sdr = RtlSdr()
        sdr.gain = 'auto'
        FFT_SIZE = 1024
        dvbs2_demod = DVBS2_Demodulator()
        beacon_demod = Beacon_Detector()
        power_avg = None
        window = np.hanning(FFT_SIZE)
        
        while sid in spectrum_threads:
            config = spectrum_threads[sid]
            if config['stop_event'].is_set():
                break
                
            freq = config['freq']
            span = config['span']
            gain_val = config.get('gain', 'auto')
            
            sample_rate = span * 1e6
            if sample_rate < 900001: sample_rate = 900001
            elif sample_rate > 3200000: sample_rate = 3200000
                
            if sdr.sample_rate != sample_rate: sdr.sample_rate = sample_rate
            if sdr.center_freq != freq * 1e6: sdr.center_freq = freq * 1e6
            
            try:
                if str(gain_val).lower() == 'auto':
                    if sdr.gain != 'auto': sdr.gain = 'auto'
                else:
                    g = float(gain_val)
                    if sdr.gain != g: sdr.gain = g
            except Exception:
                pass
                
            samples = sdr.read_samples(FFT_SIZE)
            samples = samples - np.mean(samples)
            
            fft_vals = np.fft.fftshift(np.fft.fft(samples * window))
            
            center_idx = FFT_SIZE // 2
            fft_vals[center_idx] = (fft_vals[center_idx - 1] + fft_vals[center_idx + 1]) / 2.0
            
            agc_offset = float(config.get('agc_thr', 0))
            power_inst = 20 * np.log10(np.abs(fft_vals)/FFT_SIZE + 1e-9) + agc_offset
            
            if power_avg is None:
                power_avg = power_inst
            else:
                power_avg = power_avg * 0.8 + power_inst * 0.2
            
            with state_lock:
                current_mode = telemetry_state.get('tracking_mode', 'agc')
                agc_threshold = telemetry_state.get('agc_threshold', -20)
                
            is_locked_status = False
            freqs = np.linspace(freq - span/2, freq + span/2, FFT_SIZE)
                
            if current_mode == 'agc':
                total_power = np.mean(power_avg)
                if total_power > agc_threshold:
                    socketio.emit('spectrum_status', {"message": "[AGC LOCKED] Power: {:.1f} dB".format(total_power)}, to=sid)
                    is_locked_status = True
                else:
                    socketio.emit('spectrum_status', {"message": "AGC Searching... (Power: {:.1f} dB)".format(total_power)}, to=sid)
                    
            elif current_mode == 'dvbs2':
                is_locked, avg_err = dvbs2_demod.process_carrier(samples)
                if is_locked:
                    socketio.emit('spectrum_status', {"message": "[DVB-S2 LOCKED] Phase Err: {:.3f}".format(avg_err)}, to=sid)
                    is_locked_status = True
                else:
                    socketio.emit('spectrum_status', {"message": "DVB-S2 Searching... (Err: {:.3f})".format(avg_err)}, to=sid)
                    
            elif current_mode == 'beacon':
                with state_lock:
                    bcn_freq = telemetry_state.get('beacon_freq', 1542.0)
                    bcn_thr = telemetry_state.get('beacon_threshold', -15.0)
                    
                is_locked, peak_pwr = beacon_demod.process_beacon(freqs, power_avg, bcn_freq, bcn_thr)
                if is_locked:
                    socketio.emit('spectrum_status', {"message": "[BEACON LOCKED] Peak: {:.1f} dB".format(peak_pwr)}, to=sid)
                    is_locked_status = True
                else:
                    socketio.emit('spectrum_status', {"message": "Beacon Searching... (Peak: {:.1f} dB)".format(peak_pwr)}, to=sid)
            
            with state_lock:
                if current_mode in ['agc', 'dvbs2', 'beacon']:
                    telemetry_state['locked'] = is_locked_status

            socketio.emit('spectrum_data', {
                'frequencies': freqs.tolist(),
                'powers': power_avg.tolist()
            }, to=sid)
            
            socketio.sleep(0.1) 
            
        sdr.close()
        socketio.emit('spectrum_status', {"message": "Scan stopped."}, to=sid)
    except ImportError:
        socketio.emit('spectrum_status', {"message": "Error: rtlsdr tidak terinstall"}, to=sid)
        print("[!] rtlsdr not installed")
    except Exception as e:
        socketio.emit('spectrum_status', {"message": "Error: {}".format(str(e))}, to=sid)

@socketio.on('start_spectrum')
def on_start_spectrum(data):
    sid = request.sid
    freq = float(data.get('frequency', 1542))
    span = float(data.get('span', 2))
    gain = data.get('gain', 'auto')
    agc_thr = float(data.get('agc_thr', 0))
    
    if sid in spectrum_threads and not spectrum_threads[sid]['stop_event'].is_set():
        spectrum_threads[sid]['freq'] = freq
        spectrum_threads[sid]['span'] = span
        spectrum_threads[sid]['gain'] = gain
        spectrum_threads[sid]['agc_thr'] = agc_thr
        socketio.emit('spectrum_status', {"message": "Scanning {} MHz...".format(freq)}, to=sid)
    else:
        stop_event = threading.Event()
        spectrum_threads[sid] = {'stop_event': stop_event, 'freq': freq, 'span': span, 'gain': gain, 'agc_thr': agc_thr}
        socketio.emit('spectrum_status', {"message": "Scanning {} MHz...".format(freq)}, to=sid)
        socketio.start_background_task(spectrum_worker, sid)

@socketio.on('stop_spectrum')
def on_stop_spectrum(data):
    sid = request.sid
    if sid in spectrum_threads:
        spectrum_threads[sid]['stop_event'].set()

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    if sid in spectrum_threads:
        spectrum_threads[sid]['stop_event'].set()

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html', version=time.time())

@app.route('/api/telemetry', methods=['GET', 'POST'])
def telemetry():
    if request.method == 'POST':
        # UI sending us updates (like Offsets)
        new_data = request.get_json()
        if new_data:
            with state_lock:
                telemetry_state.update(new_data)
                # Check for lock command
                if 'locked' in new_data:
                    telemetry_state['locked'] = new_data['locked']

            # --- AUTO CALCULATE POINTING saat GPS data masuk ---
            # Berjalan di semua platform (Windows dev & OrangePi),
            # tanpa perlu menunggu state machine AutoPointing.
            if 'gps_lat' in new_data or 'gps_long' in new_data:
                try:
                    with state_lock:
                        lat    = float(telemetry_state.get('gps_lat', 0.0))
                        lon    = float(telemetry_state.get('gps_long', 0.0))
                        alt    = float(telemetry_state.get('gps_alt', 0.0))
                        sat_id = telemetry_state.get('satellite_id', 'N1')

                    sat_lon = {"N1": 146.0, "N5": 113.0}.get(sat_id, 146.0)

                    if abs(lat) > 0.01:
                        res = calculate_pointing(lat, lon, sat_lon)
                        log_msg = (
                            f"Target {sat_id} - Az:{res['azimuth']:.1f} "
                            f"El:{res['elevation']:.1f} "
                            f"Beam:{res['beam_id']} Pol:{res['polar_label']}"
                        )
                        print(f"[Pointing] {log_msg}")
                        with state_lock:
                            telemetry_state['log_message'] = log_msg
                            telemetry_state['target_az']   = res['azimuth']
                            telemetry_state['target_el']   = res['elevation']
                            telemetry_state['target_beam'] = res['beam_id']
                            telemetry_state['target_pol']  = res['polar_label']
                except Exception as e:
                    print(f"[Pointing Error] {e}")

        return jsonify({"status": "success"}), 200
    else:
        # UI polling for data
        with state_lock:
            response = telemetry_state.copy()
        
        # Apply Offsets for display logic
        if response.get('offset_el_active', False):
            response['elevation'] += response.get('offset_el', 0)
        
        if response.get('offset_az_active', False):
            val = response['azimuth'] + response.get('offset_az', 0)
            response['azimuth'] = val % 360.0
            
        if response.get('offset_pol_active', False):
            response['polarization'] += response.get('offset_pol', 0)
            
        return jsonify(response)

@app.route('/api/control', methods=['POST'])
def control():
    # 1. Get Data
    data = request.get_json()
    if not data: return jsonify({"status":"error"}), 400
    
    # 2. Update the background thread's state ONLY (Instant)
    control_service.update_command(data)
    
    # 3. Return immediately (Client doesn't wait for Serial I/O)
    return jsonify({"status":"success"}), 200

@app.route('/api/start_listener', methods=['POST'])
def start_listener():
    global amip_thread, amip_stop_event
    data = request.get_json() or {}
    
    with state_lock:
        if data.get('amip_ip'):
            telemetry_state['amip_ip'] = data['amip_ip']
        if data.get('amip_port'):
            telemetry_state['amip_port'] = int(data['amip_port'])
            
    if amip_thread and amip_thread.is_alive():
        amip_stop_event.set()
        amip_thread.join(timeout=2)
        
    amip_stop_event.clear()
    amip_thread = threading.Thread(target=openamip_server_thread, daemon=True)
    amip_thread.start()
    
    return jsonify({"status": "success", "message": "Listener started"}), 200

@app.route('/api/stop_listener', methods=['POST'])
def stop_listener():
    global amip_thread, amip_stop_event
    amip_stop_event.set()
    if amip_thread and amip_thread.is_alive():
        # wait a bit for it to close
        # thread will close socket and update state
        pass
    return jsonify({"status": "success", "message": "Listener stop requested"}), 200

@app.route('/api/set_tracking_mode', methods=['POST'])
def set_tracking_mode():
    data = request.get_json() or {}
    with state_lock:
        if 'tracking_mode' in data:
            telemetry_state['tracking_mode'] = data['tracking_mode']
        if 'agc_threshold' in data:
            telemetry_state['agc_threshold'] = float(data['agc_threshold'])
        if 'beacon_freq' in data:
            telemetry_state['beacon_freq'] = float(data['beacon_freq'])
        if 'beacon_threshold' in data:
            telemetry_state['beacon_threshold'] = float(data['beacon_threshold'])
            
    return jsonify({"status": "success"}), 200

# --- MAIN ---
if __name__ == '__main__':
    import atexit
    
    def start_hardware():
        """Delayed hardware startup - runs 2 seconds after Flask binds"""
        print("[Init] Starting hardware threads...")
        gps_service.start()
        ahrs_service.start()
        control_service.start()
        auto_service.start()
    
    def stop_hardware():
        print("[Init] Stopping hardware threads...")
        amip_stop_event.set()
        gps_service.stop()
        ahrs_service.stop()
        control_service.stop()
        auto_service.stop()
    
    atexit.register(stop_hardware)
    
    # Delay hardware init by 2 seconds so Flask can bind first
    threading.Timer(2.0, start_hardware).start()
    
    print("=" * 50)
    print("Starting Web Server on http://0.0.0.0:80")
    print("=" * 50)
    
    # Start AMIP Server
    amip_thread = threading.Thread(target=openamip_server_thread, daemon=True)
    amip_thread.start()
    
    socketio.run(app, host='0.0.0.0', port=80, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)