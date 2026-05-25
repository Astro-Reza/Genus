// --- CONFIGURATION ---
const EL_PX_PER_DEG = 4.133;
const LOGICAL_WIDTH_ORIGINAL = 7324 + 20;
const LOGICAL_WIDTH_RENDERED = LOGICAL_WIDTH_ORIGINAL * 0.151624;
const AZ_PX_PER_DEG = LOGICAL_WIDTH_RENDERED / 360;

// Step & Velocity State
let currentStepSize = 1.0;

// --- STATE TRACKING ---
let prevAzimuth = 0;
let globalAzimuthAccumulator = 0;
let isFirstRun = true;
let lastLogMessage = "";

// --- DOM ELEMENTS ---
const elRuler = document.getElementById('ruler-elevation');
const azRuler = document.getElementById('ruler-azimuth');
const elValDisplay = document.getElementById('el-val');
const elSubDisplay = document.getElementById('el-sub');
const azValDisplay = document.getElementById('az-val');
const azSubDisplay = document.getElementById('az-sub');
const polValDisplay = document.getElementById('pol-val');
const polSubDisplay = document.getElementById('pol-sub');
const statusTextDisplay = document.getElementById('status-text');
const horizonLine = document.querySelector('.horizon-line');
const logContainer = document.getElementById('system-log');
const clTrack = document.getElementById('cl-track');
const gpsLongDisplay = document.getElementById('gps-long');
const gpsLatDisplay = document.getElementById('gps-lat');
const gpsAltDisplay = document.getElementById('gps-alt');

// --- CHECKLIST CONFIG ---
const CHECKLIST_MODES = {
    'AUTO': [
        "Choose Satellite", "System Startup", "Sensor Initialize",
        "GPS Lock", "Calculate Pointing", "Antenna Search",
        "Antenna Lock", "Saving Offset", "Sending Request",
        "Registering", "Ready"
    ],
    'MANUAL': [
        "Manual Pointing Mode"
    ],
    'PATTERN': [
        "Ready",
        "Step 1: M0+M2 CW 45°@50%",
        "Step 2: M0 CCW 90° | M2 Stop",
        "Step 3: M0 Stop | M2 CCW 45°@30%",
        "Demo Complete"
    ]
};

// Initialize with AUTO mode by default
let clStepNames = CHECKLIST_MODES['AUTO'];
const STEP_WIDTH = 180;
let clCurrentIndex = 0;
let currentMode = 'AUTO';

// --- INITIALIZATION ---
function renderChecklist(mode) {
    if (!CHECKLIST_MODES[mode]) return;

    clStepNames = CHECKLIST_MODES[mode];

    clTrack.innerHTML = clStepNames.map((name, index) => `
        <div class="cl-step" data-index="${index}">
            <div class="cl-dot"></div>
            <div class="cl-label">${name}</div>
        </div>
    `).join('');

    // Reset position temporarily until next updateChecklistVisuals calls
    clTrack.style.transform = `translateX(-${STEP_WIDTH / 2}px)`;

    updateChecklistVisuals();
}

function initChecklist() {
    renderChecklist('AUTO');
}

// --- OFFSET LOGIC ---

function sendTelemetry(payload) {
    fetch('/api/telemetry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).catch(e => console.error("Send Error:", e));
}

// Update the UI state based on backend data
function updateOffsetRow(key, data) {
    const wrapper = document.getElementById(`wrap-${key}`);
    const input = document.getElementById(`inp-${key}`);
    const btn = document.getElementById(`btn-${key}`);

    // Get values from data
    const isActive = data[`offset_${key}_active`];
    const val = data[`offset_${key}`] || 0.0;

    // 1. Update Power Button & Wrapper State
    if (btn) {
        if (isActive) {
            if (!btn.classList.contains('is-on')) {
                btn.classList.add('is-on');
                btn.textContent = "ON";
            }
            if (wrapper && wrapper.classList.contains('faded')) {
                wrapper.classList.remove('faded');
            }
            if (input && input.disabled) input.disabled = false;
        } else {
            if (btn.classList.contains('is-on')) {
                btn.classList.remove('is-on');
                btn.textContent = "OFF";
            }
            if (wrapper && !wrapper.classList.contains('faded')) {
                wrapper.classList.add('faded');
            }
            if (input && !input.disabled) input.disabled = true;
        }
    }

    // 2. Update Input Value (if not focused)
    if (input && document.activeElement !== input) {
        input.value = val.toFixed(1);
    }

    // 3. Update Visuals (Blue/Yellow) inferred from sign
    if (wrapper) {
        // Only update based on value if value is non-zero.
        // If value is 0, let the user toggle the state manually without overriding.
        if (Math.abs(val) > 0.0001) {
            const isNegative = val < 0;
            if (isNegative) {
                if (!wrapper.classList.contains('state-yellow')) wrapper.classList.add('state-yellow');
            } else {
                if (wrapper.classList.contains('state-yellow')) wrapper.classList.remove('state-yellow');
            }
        }
    }
}

function initOffsetPanel() {
    ['az', 'el', 'pol'].forEach(key => {
        const switchEl = document.getElementById(`sw-${key}`);
        const wrapper = document.getElementById(`wrap-${key}`);
        const input = document.getElementById(`inp-${key}`);
        const btn = document.getElementById(`btn-${key}`);

        // --- Power Button Logic ---
        if (btn) {
            btn.addEventListener('click', () => {
                const currentlyOn = btn.classList.contains('is-on');
                const newState = !currentlyOn; // Toggle

                // Optimistic UI update
                if (newState) {
                    btn.classList.add('is-on');
                    btn.textContent = "ON";
                    if (wrapper) wrapper.classList.remove('faded');
                    if (input) input.disabled = false;
                } else {
                    btn.classList.remove('is-on');
                    btn.textContent = "OFF";
                    if (wrapper) wrapper.classList.add('faded');
                    if (input) input.disabled = true;
                }

                // Send to backend
                const payload = {};
                payload[`offset_${key}_active`] = newState;
                sendTelemetry(payload);
            });
        }

        // --- Switch Logic (Toggle Sign) ---
        if (switchEl && wrapper && input) {
            switchEl.addEventListener('click', () => {

                const isYellow = wrapper.classList.contains('state-yellow');
                let currentVal = parseFloat(input.value) || 0;
                currentVal = Math.abs(currentVal);

                let newVal;
                if (isYellow) {
                    // Was Yellow (-), Switch to Blue (+)
                    wrapper.classList.remove('state-yellow');
                    newVal = currentVal;
                } else {
                    // Was Blue (+), Switch to Yellow (-)
                    wrapper.classList.add('state-yellow');
                    newVal = -currentVal;
                }

                // Special handling for 0: force negative zero or handled by class logic
                if (currentVal === 0) {
                    // If 0, newVal is 0. But state-yellow is toggled.
                    // The backend receives 0. The UI class logic above (in updateOffsetRow) 
                    // will see 0 and NOT override our change. Good.
                }

                input.value = newVal.toFixed(1);
                const payload = {};
                payload[`offset_${key}`] = newVal;
                sendTelemetry(payload);
            });
        }

        // --- Input Logic ---
        if (input) {
            input.addEventListener('change', () => {
                let val = parseFloat(input.value) || 0;

                // If user typed a positive number but the mode is negative (Yellow), negate it.
                // This allows setting "-" mode then typing "5" to get "-5".
                // We trust the visual state as the "mode" if the input is ambiguous (positive).
                if (wrapper && wrapper.classList.contains('state-yellow') && val > 0) {
                    val = -val;
                    input.value = val.toFixed(1); // Update input to show negative
                }

                const payload = {};
                payload[`offset_${key}`] = val;
                sendTelemetry(payload);

                // Visual update based on sign
                if (val < 0) {
                    if (wrapper && !wrapper.classList.contains('state-yellow')) wrapper.classList.add('state-yellow');
                } else if (val > 0) { // Only force remove yellow if strictly positive
                    if (wrapper && wrapper.classList.contains('state-yellow')) wrapper.classList.remove('state-yellow');
                }
                // If val === 0, leave visual state alone (user might have set it)
            });
        }
    });
}




// --- SYSTEM PANEL LOGIC ---
function setSystemMode(mode) {
    // Optimistic Update
    updateModeUI(mode);
    renderChecklist(mode); // Update checklist immediately

    // Send to Backend
    sendTelemetry({ "system_mode": mode });
}

function updateModeUI(mode) {
    // Mode Keys corresponding to HTML IDs
    const modes = {
        'AUTO': 'mode-auto',
        'MANUAL': 'mode-manual',
        'PATTERN': 'mode-pattern'
    };

    currentMode = mode; // Update global state

    Object.entries(modes).forEach(([key, id]) => {
        const el = document.getElementById(id);
        if (key === mode) {
            el.classList.add('active');
        } else {
            el.classList.remove('active');
        }
    });
    // Update homing button color for demo mode
    if (mode === 'PATTERN') {
        if (!demoRunning) setDemoButtonState('ready');
    } else {
        // Reset to neutral when not in PATTERN mode
        if (demoRunning) {
            // If mode switched away during demo, stop it
            stopDemo();
        }
        setDemoButtonState('idle');
    }
}

function updateSystemPanel(data) {
    // Update Mode
    if (data.system_mode) {
        // If mode changed from external command (or backend confirmed), update UI
        // We only want to re-render checklist if it's different from what we have
        if (data.system_mode !== currentMode) {
            renderChecklist(data.system_mode);
        }
        updateModeUI(data.system_mode);
    }

    // Update Sensors
    const updateSensor = (id, isConnected) => {
        const el = document.getElementById(id);
        if (el) {
            if (isConnected) {
                el.classList.add('connected');
            } else {
                el.classList.remove('connected');
            }
        }
    };

    // Use Dev Settings if active, otherwise use backend data
    let gpsStatus = data.sensor_status_gps;
    let ahrsStatus = data.sensor_status_ahrs;
    let encoderStatus = data.sensor_status_encoder;

    // Check Dev Panel Overrides (if panel is sending "active" false, we might want to show disconnected)
    // Logic: If user creates a manual override in dev panel? 
    // The previous logic was: "Simulation".
    // If devSettings.encoder.active is FALSE (user clicked NOT ACTIVE), we should show RED even if backend is true?
    // User request: "if the encoder turned off in the developer settings, the status in the front end still reads it's connected"

    // We can assume if the user interacted with Dev Panel, we prioritize it?
    // Or strictly: if Dev Panel is OPEN?

    // Let's use the `devSettings` state.
    // However, devSettings defaults are false. 
    // We only want to override if the user explicitly *set* it.
    // Robust way: If devModeActive is true (which is confusing name, but seems to track "Are we simulating?").
    // Actually `devModeActive` logic was: "Track if any dev setting is active".

    // Let's check `devSettings.encoder.active`. If it's false, and we are "simulating", we show false.
    // But how do we know if we are simulating encoder?
    // The user toggles "ACTIVE/NOT ACTIVE".

    // Simple fix: If the toggle is "NOT ACTIVE" (which is default state of devSettings.encoder.active=false),
    // AND the backend says true, what do we do?
    // Usually Dev Settings is for *Simulation*.
    // If I turn OFF encoder in Dev Settings, I expect it to look OFF.

    // Let's defer to dev settings if dev panel is open? Or always? 
    // The user seems to imply they use Dev Settings to control the view.

    // Use devSettings if dev panel is open?
    const devPanel = document.getElementById('dev-panel');
    const devOpen = devPanel && devPanel.classList.contains('open');

    if (devOpen) {
        // Logic: If button says "ACTIVE" -> Green. If "NOT ACTIVE" -> Red.
        // regardless of backend.
        gpsStatus = devSettings.gps.active;
        ahrsStatus = devSettings.ahrs.active;
        encoderStatus = devSettings.encoder.active;
    }

    updateSensor('sensor-gps', gpsStatus);
    updateSensor('sensor-ahrs', ahrsStatus);
    updateSensor('sensor-encoder', encoderStatus);
}


// --- VISUAL UPDATERS ---

function updateChecklistVisuals() {
    const steps = document.querySelectorAll('.cl-step');
    // Slide Logic
    const translateX = -(clCurrentIndex * STEP_WIDTH) - (STEP_WIDTH / 2);
    clTrack.style.transform = `translateX(${translateX}px)`;

    // Color Logic
    steps.forEach((step, index) => {
        step.classList.remove('passed', 'active');
        if (index < clCurrentIndex) {
            step.classList.add('passed');
        } else if (index === clCurrentIndex) {
            step.classList.add('active');
        }
    });
}

function updateAttitude(elevation, azimuth, polarization) {
    // Text
    elValDisplay.textContent = elevation.toFixed(1);
    elSubDisplay.textContent = elevation.toFixed(2);
    azValDisplay.textContent = azimuth.toFixed(2);
    azSubDisplay.textContent = "| " + azimuth.toFixed(2);
    polValDisplay.textContent = polarization.toFixed(1);
    polSubDisplay.textContent = polarization.toFixed(2);

    // Elevation Ruler
    const elOffset = elevation * EL_PX_PER_DEG;
    elRuler.style.backgroundPosition = `center calc(50% + ${elOffset}px)`;

    // Azimuth Ruler
    if (isFirstRun) {
        prevAzimuth = azimuth;
        globalAzimuthAccumulator = azimuth;
        isFirstRun = false;
    }
    let delta = azimuth - prevAzimuth;
    if (delta < -180) delta += 360;
    if (delta > 180) delta -= 360;

    globalAzimuthAccumulator += delta;
    prevAzimuth = azimuth;

    const centerOffset = LOGICAL_WIDTH_RENDERED / 2;
    const azPixelMove = globalAzimuthAccumulator * AZ_PX_PER_DEG;
    azRuler.style.backgroundPosition = `calc(50% + ${centerOffset}px - ${azPixelMove}px) center`;

    // Horizon Line
    horizonLine.style.transform = `rotate(${polarization}deg)`;
}

function addLogEntry(message) {
    if (!message || message === lastLogMessage) return; // Prevent duplicate/empty logs

    lastLogMessage = message;

    const entry = document.createElement('div');
    entry.className = 'log-entry';

    const timeSpan = document.createElement('span');
    timeSpan.className = 'time';
    const now = new Date();
    timeSpan.textContent = now.toLocaleTimeString('en-GB', { hour12: false });

    const infoSpan = document.createElement('span');
    infoSpan.className = 'info';
    infoSpan.textContent = message;

    entry.appendChild(timeSpan);
    entry.appendChild(infoSpan);
    logContainer.appendChild(entry);
    logContainer.scrollTop = logContainer.scrollHeight;
}
// --- DEMO MOVEMENT LOGIC ---
// Track demo running state
let demoRunning = false;

function setDemoButtonState(state) {
    // state: 'idle' | 'ready' | 'running'
    const btn = document.getElementById('btn-homing');
    if (!btn) return;
    btn.classList.remove('demo-ready', 'demo-running');
    if (state === 'ready') {
        btn.classList.add('demo-ready');
    } else if (state === 'running') {
        btn.classList.add('demo-running');
    }
}

async function startDemo() {
    demoRunning = true;
    setDemoButtonState('running');
    addLogEntry('Demo sequence started...');

    // Update checklist to Step 1
    clCurrentIndex = 1;
    updateChecklistVisuals();

    try {
        const response = await fetch('/api/demo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'START' })
        });
        const result = await response.json();
        if (result.status === 'started') {
            addLogEntry('Demo running on backend...');
        }
    } catch (e) {
        console.error('Demo start error:', e);
        addLogEntry('Demo start error: ' + e.message);
        demoRunning = false;
        setDemoButtonState('ready');
    }
}

async function stopDemo() {
    addLogEntry('EMERGENCY STOP sent.');
    clCurrentIndex = 0;
    updateChecklistVisuals();
    try {
        await fetch('/api/demo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'STOP' })
        });
    } catch (e) {
        console.error('Demo stop error:', e);
    }
    demoRunning = false;
    setDemoButtonState('ready');
}

// --- MANUAL CONTROL & VELOCITY LOGIC ---
function initManualControl() {
    // 1. Step Input
    const stepInput = document.querySelector('.step-input');
    if (stepInput) {
        stepInput.addEventListener('change', () => {
            let val = parseFloat(stepInput.value);
            if (isNaN(val) || val <= 0) val = 0.1; // safety
            // send to backend
            currentStepSize = val; // local update
            sendTelemetry({ 'step_size': val });
        });
    }


    // 2. Velocity Sliders
    ['vel-el', 'vel-az', 'vel-pol'].forEach(id => {
        const slider = document.getElementById(id);
        const valueDisplay = document.getElementById(id + '-value');
        if (slider) {
            slider.addEventListener('input', () => {
                const val = parseInt(slider.value, 10);
                if (valueDisplay) valueDisplay.textContent = val + '%';
                // Construct payload key: vel-el -> velocity_el
                const key = id.replace('vel-', 'velocity_');
                const payload = {};
                payload[key] = val;
                sendTelemetry(payload);
            });
        }
    });

    // 3. Control Buttons - Send to COM7 via /api/control
    // Format: [spd_azm],[spd_elv],[spd_pol],[up],[down],[right],[left],[pol_right],[pol_left]

    function sendControl(controlData) {
        // Get current speed from each axis slider
        const velAzSlider = document.getElementById('vel-az');
        const velElSlider = document.getElementById('vel-el');
        const velPolSlider = document.getElementById('vel-pol');

        // Include all speeds in control messages
        controlData.spd_azm = velAzSlider ? parseInt(velAzSlider.value, 10) : 0;
        controlData.spd_elv = velElSlider ? parseInt(velElSlider.value, 10) : 0;
        controlData.spd_pol = velPolSlider ? parseInt(velPolSlider.value, 10) : 0;

        fetch('/api/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(controlData)
        }).catch(e => console.error("Control Error:", e));
    }

    // Bind button with pointerdown (press) and pointerup (release)
    // Using pointer events for better compatibility with nested elements (like <img>)
    const bindControlBtn = (id, controlKey) => {
        const btn = document.getElementById(id);
        if (btn) {
            // Press: send 1 immediately
            btn.addEventListener('pointerdown', (e) => {
                e.preventDefault();
                console.log(`[Control] Button ${controlKey} PRESSED`);
                const data = {};
                data[controlKey] = 1;
                sendControl(data);
            });

            // Release: send 0
            btn.addEventListener('pointerup', (e) => {
                e.preventDefault();
                console.log(`[Control] Button ${controlKey} RELEASED`);
                const data = {};
                data[controlKey] = 0;
                sendControl(data);
            });

            // Also handle pointer leaving button while pressed
            btn.addEventListener('pointerleave', (e) => {
                const data = {};
                data[controlKey] = 0;
                sendControl(data);
            });

            // Prevent context menu on long press
            btn.addEventListener('contextmenu', (e) => e.preventDefault());
        }
    };

    // Bindings: Map button IDs to control keys
    // up = el_up, down = el_down, right = az_right, left = az_left, pol_right, pol_left
    bindControlBtn('btn-el-up', 'up');
    bindControlBtn('btn-el-down', 'down');
    bindControlBtn('btn-az-right', 'right');
    bindControlBtn('btn-az-left', 'left');
    bindControlBtn('btn-pol-right', 'pol_right');
    bindControlBtn('btn-pol-left', 'pol_left');

    const btnHoming = document.getElementById('btn-homing');
    if (btnHoming) {
        btnHoming.addEventListener('click', () => {
            if (currentMode === 'PATTERN') {
                // In demo mode: green starts, red stops
                if (demoRunning) {
                    stopDemo();
                } else {
                    startDemo();
                }
            } else {
                // Other modes: original homing behavior
                sendTelemetry({ "manual_cmd": { "type": "homing" } });
            }
        });
    }
}

// --- SATELLITE SWITCH LOGIC ---
function initSatelliteSwitch() {
    const selector = document.getElementById('sat-selector');
    if (selector) {
        selector.addEventListener('change', () => {
            const satId = selector.value;
            sendTelemetry({ 'satellite_id': satId });
            // Optimistic update
            updateSatelliteVisuals(satId);
        });
    }
}

function updateSatelliteVisuals(satId) {
    const satImage = document.getElementById('sat-image');
    const satEmblem = document.getElementById('sat-emblem');
    const satNameDisplay = document.getElementById('sat-name-display');
    const satOrbitalSlot = document.getElementById('sat-orbital-slot');
    const selector = document.getElementById('sat-selector');

    if (satId === 'N5') {
        if (satImage) satImage.src = "/static/img/nusantara5.png";
        if (satEmblem) satEmblem.src = "/static/img/N5_emblem.png";
        if (satNameDisplay) satNameDisplay.textContent = "NUSANTARA LIMA";
        if (satOrbitalSlot) satOrbitalSlot.textContent = "113° E";
    } else {
        // Default to N1
        if (satImage) satImage.src = "/static/img/nusantara1_877x308.28.png";
        if (satEmblem) satEmblem.src = "/static/img/N1-emblem.png";
        if (satNameDisplay) satNameDisplay.textContent = "NUSANTARA SATU";
        if (satOrbitalSlot) satOrbitalSlot.textContent = "146° E";
    }

    // Sync selector if it wasn't the source of change (e.g. initial load)
    if (selector && selector.value !== satId) {
        selector.value = satId;
    }
}

// --- MAIN LOOP ---
async function fetchTelemetry() {
    try {
        const response = await fetch(`/api/telemetry?_=${new Date().getTime()}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const data = await response.json();

        // 1. Update Attitude
        updateAttitude(
            data.elevation || 0,
            data.azimuth || 0,
            data.polarization || 0
        );
        if (devSettings.comms && devSettings.comms.locked) {
            statusTextDisplay.textContent = "LOCKED";
            statusTextDisplay.style.color = "#00ff00";
        } else if (data.status) {
            statusTextDisplay.textContent = data.status;
            statusTextDisplay.style.color = (data.status === "LOCKED") ? "#00ff00" : "#ffcc00";
        }

        // Only update checklist from backend if dev mode is not controlling it
        if (data.checklist_step !== undefined && !devModeActive && currentMode !== 'PATTERN') {
            clCurrentIndex = data.checklist_step;
            updateChecklistVisuals();
        }

        // Handle demo step and DONE signal from backend
        if (currentMode === 'PATTERN' && data.demo_step !== undefined) {
            if (data.demo_step >= 0 && data.demo_step <= 4) {
                clCurrentIndex = data.demo_step;
                updateChecklistVisuals();
            }
            // Detect demo abort: backend reset demo_step to 0 while we think demo is running
            if (demoRunning && data.demo_step === 0 && data.demo_done === false) {
                demoRunning = false;
                setDemoButtonState('ready');
            }
        }
        // When demo is done, reset button to green (ready)
        if (currentMode === 'PATTERN' && data.demo_done === true && demoRunning) {
            demoRunning = false;
            setDemoButtonState('ready');
            clCurrentIndex = 4; // 'Demo Complete'
            updateChecklistVisuals();
        }
        if (data.log_message) {
            addLogEntry(data.log_message);
        }

        // Render target data directly from backend if present
        if (data.target_az !== undefined && data.target_el !== undefined) {
            const targetDisplay = document.getElementById('target-pointing-display');
            if (targetDisplay) {
                const azVal = data.target_az.toFixed(1);
                const elVal = data.target_el.toFixed(1);
                const beamVal = data.target_beam || '-';
                const polVal = data.target_pol || '-';

                targetDisplay.innerHTML = `
                      <div class="target-row" style="margin-bottom: 8px;">
                          <span class="label">Target</span>
                          <span class="value" style="font-size: 1.1rem;">Az ${azVal}&deg; El ${elVal}&deg;</span>
                      </div>
                      <div class="target-row">
                          <span class="label">Beam</span>
                          <span class="value" style="font-size: 1rem;">${beamVal}</span>
                          <span class="label" style="margin-left: 15px;">Pol</span>
                          <span class="value" style="font-size: 1rem;">${polVal}</span>
                      </div>
                 `;
            }
        }

        // 2. Update GPS
        if (gpsLongDisplay) gpsLongDisplay.textContent = (data.gps_long || 0).toFixed(6);
        if (gpsLatDisplay) gpsLatDisplay.textContent = (data.gps_lat || 0).toFixed(6);
        if (gpsAltDisplay) gpsAltDisplay.textContent = (data.gps_alt || 0).toFixed(1) + " m";

        // 3. Update Offsets (New Components)
        updateOffsetRow('az', data);
        updateOffsetRow('el', data);
        updateOffsetRow('pol', data);

        // 4. Update System Panel (New)
        updateSystemPanel(data);

        // 4b. Store backend sensor status for mixed mode
        backendSensorStatus.gps = data.sensor_status_gps || false;
        backendSensorStatus.ahrs = data.sensor_status_ahrs || false;
        backendSensorStatus.encoder = data.sensor_status_encoder || false;

        // 4c. Update checklist from dev if any dev setting is active
        if (devModeActive) {
            updateChecklistFromDev();
        }

        // 5. Update Velocity Sliders
        const updateSliderIfNotFocused = (id, val) => {
            const slider = document.getElementById(id);
            const valueDisplay = document.getElementById(id + '-value');
            if (slider && document.activeElement !== slider) {
                const intVal = Math.round(val || 0);
                slider.value = intVal;
                if (valueDisplay) valueDisplay.textContent = intVal + '%';
            }
        };
        updateSliderIfNotFocused('vel-el', data.velocity_el);
        updateSliderIfNotFocused('vel-az', data.velocity_az);
        updateSliderIfNotFocused('vel-pol', data.velocity_pol);

        // 6. Update Step Input
        const stepInput = document.querySelector('.step-input');
        if (stepInput && document.activeElement !== stepInput) {
            // Only update if backend has a valid step_size
            if (data.step_size !== undefined) {
                stepInput.value = data.step_size.toFixed(1);
            }
        }

        // 7. Update Satellite (New)
        if (data.satellite_id) {
            updateSatelliteVisuals(data.satellite_id);
        }

    } catch (error) {
        console.error("Connection Error:", error);
    }
}

// =========================================
// DEVELOPER SETTINGS
// =========================================

// City coordinates for GPS simulation
const CITY_COORDS = {
    'jakarta': { lat: -6.2088, lon: 106.8456 },
    'kualalumpur': { lat: 3.1390, lon: 101.6869 },
    'singapore': { lat: 1.3521, lon: 103.8198 },
    'balikpapan': { lat: -1.2379, lon: 116.8529 },
    'bandung': { lat: -6.9175, lon: 107.6191 }
};

// Satellite orbital positions (longitude in degrees East)
const SATELLITE_POSITIONS = {
    'N1': 146.0,  // Nusantara Satu
    'N5': 123.0   // Nusantara Lima
};

// Developer settings state
const devSettings = {
    gps: { active: false, city: null, locked: false },
    ahrs: { active: false, x: 0, y: 0, z: 0 },
    encoder: { active: false },
    comms: { locked: false }
};

// Track if any dev setting is active (prevents backend from overwriting checklist)
let devModeActive = false;

// Track backend's real sensor status (for mixing with dev settings)
const backendSensorStatus = {
    gps: false,
    ahrs: false,
    encoder: false
};

/**
 * Calculate azimuth and elevation to a geostationary satellite
 * @param {number} lat - Observer latitude in degrees
 * @param {number} lon - Observer longitude in degrees
 * @param {number} satLon - Satellite longitude in degrees East
 * @returns {Object} { azimuth, elevation } in degrees
 */
function calculatePointing(lat, lon, satLon) {
    const DEG2RAD = Math.PI / 180;
    const RAD2DEG = 180 / Math.PI;

    // Earth radius and geostationary orbit radius in km
    const Re = 6378.137;
    const Rs = 42164.0;

    // Convert to radians
    const latRad = lat * DEG2RAD;
    const lonDiff = (satLon - lon) * DEG2RAD;

    // Calculate elevation
    const cosLat = Math.cos(latRad);
    const cosLonDiff = Math.cos(lonDiff);

    const d = Rs * Math.sqrt(1 + (Re / Rs) ** 2 - 2 * (Re / Rs) * cosLat * cosLonDiff);
    const elevation = RAD2DEG * Math.acos((Rs / d) * Math.sqrt(1 - (cosLat * cosLonDiff) ** 2));

    // Correct elevation using proper formula
    const b = Rs * Math.sqrt(1 - (cosLat * cosLonDiff) ** 2);
    const elevationAngle = RAD2DEG * Math.atan((b - Re) / (Rs * cosLat * Math.sin(Math.abs(lonDiff))));

    // Simplified elevation formula for geostationary satellites
    const r = Rs / Re;
    const el = RAD2DEG * Math.atan(
        (Math.cos(latRad) * Math.cos(lonDiff) - 1 / r) /
        Math.sqrt(1 - (Math.cos(latRad) * Math.cos(lonDiff)) ** 2)
    );

    // Calculate azimuth
    let azimuth;
    if (lat > 0) {
        // Northern hemisphere
        azimuth = 180 + RAD2DEG * Math.atan(Math.tan(lonDiff) / Math.sin(latRad));
    } else if (lat < 0) {
        // Southern hemisphere
        azimuth = RAD2DEG * Math.atan(Math.tan(lonDiff) / Math.sin(latRad));
        if (azimuth < 0) azimuth += 360;
    } else {
        // On equator
        azimuth = lonDiff > 0 ? 90 : 270;
    }

    // Normalize azimuth to 0-360
    if (azimuth < 0) azimuth += 360;
    if (azimuth >= 360) azimuth -= 360;

    return {
        azimuth: azimuth,
        elevation: Math.max(0, el)  // Elevation can't be negative (below horizon)
    };
}

function initDevPanel() {
    const panel = document.getElementById('dev-panel');
    const overlay = document.getElementById('dev-overlay');
    const toggleBtn = document.getElementById('dev-panel-toggle');
    const closeBtn = document.getElementById('dev-close');

    if (!panel || !toggleBtn) return;

    // Toggle panel
    function openPanel() {
        panel.classList.add('open');
        overlay.classList.add('open');
        toggleBtn.classList.add('active');
    }

    function closePanel() {
        panel.classList.remove('open');
        overlay.classList.remove('open');
        toggleBtn.classList.remove('active');
    }

    toggleBtn.addEventListener('click', () => {
        if (panel.classList.contains('open')) {
            closePanel();
        } else {
            openPanel();
        }
    });

    closeBtn.addEventListener('click', closePanel);
    overlay.addEventListener('click', closePanel);

    // Status button toggle helper
    function setupStatusToggle(btnId, stateKey, subKey, activeText = 'ACTIVE', inactiveText = 'NOT ACTIVE') {
        const btn = document.getElementById(btnId);
        if (!btn) return;

        btn.addEventListener('click', () => {
            const isActive = btn.classList.contains('active');
            if (isActive) {
                btn.classList.remove('active');
                btn.classList.add('inactive');
                btn.textContent = inactiveText;
                if (subKey) devSettings[stateKey][subKey] = false;
                else devSettings[stateKey] = false;
            } else {
                btn.classList.remove('inactive');
                btn.classList.add('active');
                btn.textContent = activeText;
                if (subKey) devSettings[stateKey][subKey] = true;
                else devSettings[stateKey] = true;
            }
            updateDevState();
        });
    }

    // Setup toggles
    setupStatusToggle('dev-gps-toggle', 'gps', 'active');
    setupStatusToggle('dev-ahrs-toggle', 'ahrs', 'active');
    setupStatusToggle('dev-encoder-toggle', 'encoder', 'active');
    setupStatusToggle('dev-gps-lock-toggle', 'gps', 'locked', 'LOCK', 'SEARCH');
    setupStatusToggle('dev-comms-toggle', 'comms', 'locked', 'LOCKED', 'NO LOCK');
    const commsBtn = document.getElementById('dev-comms-toggle');
    if (commsBtn) {
        commsBtn.addEventListener('click', () => {
            const isLocked = commsBtn.classList.contains('active');
            sendTelemetry({ 'locked': isLocked });
        });
    }

    // City selection
    const citySelect = document.getElementById('dev-gps-city');
    if (citySelect) {
        citySelect.addEventListener('change', (e) => {
            devSettings.gps.city = e.target.value;
            updateDevState();
        });
    }

    // Note: Satellite selection uses the main UI's sat-selector, not a dev panel option

    // AHRS inputs
    ['x', 'y', 'z'].forEach(axis => {
        const input = document.getElementById(`dev-ahrs-${axis}`);
        if (input) {
            input.addEventListener('input', (e) => {
                devSettings.ahrs[axis] = parseFloat(e.target.value) || 0;
                updateDevState();
            });
        }
    });
}

function updateDevState() {
    const pointingCard = document.getElementById('dev-pointing-card');
    const calcAz = document.getElementById('dev-calc-az');
    const calcEl = document.getElementById('dev-calc-el');

    // Check if we can calculate pointing (GPS active + city selected + locked)
    if (devSettings.gps.active && devSettings.gps.city && devSettings.gps.locked) {
        const coords = CITY_COORDS[devSettings.gps.city];

        // Get satellite from main UI's selector
        const satSelector = document.getElementById('sat-selector');
        const currentSatellite = satSelector ? satSelector.value : 'N1';
        const satLon = SATELLITE_POSITIONS[currentSatellite];

        if (coords && satLon !== undefined) {
            const pointing = calculatePointing(coords.lat, coords.lon, satLon);

            if (pointingCard) pointingCard.style.display = 'block';
            if (calcAz) calcAz.textContent = pointing.azimuth.toFixed(2) + '°';
            if (calcEl) calcEl.textContent = pointing.elevation.toFixed(2) + '°';
        }
    } else {
        if (pointingCard) pointingCard.style.display = 'none';
    }

    // Always update checklist based on dev settings (moved outside pointing logic)
    updateChecklistFromDev();

    // Send simulated data to backend
    sendDevTelemetry();
}

function sendDevTelemetry() {
    const payload = {};

    // GPS simulation
    if (devSettings.gps.active && devSettings.gps.city) {
        const coords = CITY_COORDS[devSettings.gps.city];
        if (coords) {
            payload.sensor_status_gps = true;
            payload.gps_lat = coords.lat;
            payload.gps_long = coords.lon;
            payload.gps_alt = 0;
        }
    }

    // AHRS simulation
    if (devSettings.ahrs.active) {
        payload.sensor_status_ahrs = true;
        payload.polarization = devSettings.ahrs.x;
        payload.elevation = devSettings.ahrs.y;
        payload.azimuth = devSettings.ahrs.z;
    }

    // Encoder simulation
    if (devSettings.encoder.active) {
        payload.sensor_status_encoder = true;
    }

    // Note: satellite_id is managed by main UI's sat-selector, not dev settings

    // Send to backend if any dev setting is active
    if (devSettings.gps.active || devSettings.ahrs.active || devSettings.encoder.active) {
        fetch('/api/telemetry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).catch(e => console.error("Dev telemetry error:", e));
    }
}

function updateChecklistFromDev() {
    // Only process if we're in AUTO mode
    if (currentMode !== 'AUTO') return;

    // Check if any dev setting is active
    const anyDevActive = devSettings.gps.active || devSettings.ahrs.active || devSettings.encoder.active;
    devModeActive = anyDevActive;

    if (!anyDevActive) {
        return; // No dev settings active, let backend control checklist
    }

    // MIXED MODE: Use dev settings if active, otherwise fall back to backend sensor status
    // GPS: from dev settings OR backend
    const gpsActive = devSettings.gps.active || backendSensorStatus.gps;
    // AHRS: from dev settings OR backend
    const ahrsActive = devSettings.ahrs.active || backendSensorStatus.ahrs;
    // Encoder: from dev settings OR backend
    const encoderActive = devSettings.encoder.active || backendSensorStatus.encoder;

    // Step 0: Choose Satellite - always complete (satellite is always selected)
    // Step 1: System Startup - skip
    // Step 2: Sensor Initialize - all sensors connected (from any source)
    const allSensorsActive = gpsActive && ahrsActive && encoderActive;

    // Step 3: GPS Lock - only from dev settings (real GPS lock would come from backend)
    const gpsLocked = devSettings.gps.active && devSettings.gps.locked;

    // Step 4: Calculate Pointing - GPS locked + city selected
    const canCalculate = gpsLocked && devSettings.gps.city;

    // Determine target step based on current state
    let targetStep = 2;  // Default: Sensor Initialize (waiting for sensors)

    if (allSensorsActive) {
        // All sensors connected → move to GPS Lock (step 3)
        targetStep = 3;  // GPS Lock (waiting for lock)
    }
    if (allSensorsActive && gpsLocked) {
        // GPS is locked → move to step 3 complete
        targetStep = 3;  // GPS Lock complete
    }
    if (allSensorsActive && canCalculate) {
        // GPS locked + city selected → move to Antenna Search (step 5)
        targetStep = 5;  // Calculate Pointing done → Antenna Search
    }

    // Update checklist - always update when dev mode is active
    clCurrentIndex = targetStep;
    updateChecklistVisuals();
}

// Initialize
initChecklist();
initOffsetPanel();
initManualControl();
initSatelliteSwitch();
initDevPanel();
const POLL_INTERVAL = 50; // ms

async function pollLoop() {
    await fetchTelemetry();
    setTimeout(pollLoop, POLL_INTERVAL); // Schedule NEXT iteration
}

// Start
pollLoop();