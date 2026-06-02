#include <Arduino.h>
#include "driver/spi_slave.h"

// ================= PIN DEFINITIONS =================

// Motor A: Azimuth (Left/Right) - L298N #1
const int AZI_EN = 32;
const int AZI_R_PWM = 33;
const int AZI_L_PWM = 25;

// Motor B: Elevation (Up/Down) - L298N #1
const int ELE_EN = 14;
const int ELE_R_PWM = 26;
const int ELE_L_PWM = 27;

// Motor C: Polarization (Turn Right/Turn Left) - L298N #2
const int POL_EN = 12;
const int POL_R_PWM = 13;
const int POL_L_PWM = 15;

// SPI SLAVE PINS (VSPI Default)
const int SPI_CS   = 5;
const int SPI_CLK  = 18;
const int SPI_MISO = 19;
const int SPI_MOSI = 23;

// ================= SPI BUFFERS =================

// We expect 12 bytes (padded for 32-bit DMA alignment): [SpdAz, SpdEl, SpdPol, Up, Dn, Rt, Lt, PRt, PLt, pad, pad, pad]
#define SPI_BUF_SIZE 12
WORD_ALIGNED_ATTR char sendbuf[132] = ""; // Buffer for data TO Master (optional)
WORD_ALIGNED_ATTR char recvbuf[132] = ""; // Buffer for data FROM Master
spi_slave_transaction_t t;

// ================= SETUP =================

void setup() {
    Serial.begin(115200);
    Serial.setTimeout(50);

    // --- MOTOR CONFIG ---
    pinMode(AZI_EN, OUTPUT); digitalWrite(AZI_EN, LOW);
    pinMode(AZI_R_PWM, OUTPUT); pinMode(AZI_L_PWM, OUTPUT);

    pinMode(ELE_EN, OUTPUT); digitalWrite(ELE_EN, LOW);
    pinMode(ELE_R_PWM, OUTPUT); pinMode(ELE_L_PWM, OUTPUT);

    pinMode(POL_EN, OUTPUT); digitalWrite(POL_EN, LOW);
    pinMode(POL_R_PWM, OUTPUT); pinMode(POL_L_PWM, OUTPUT);

    stopAll();

    // --- SPI SLAVE CONFIG ---
    
    // 1. Bus Configuration
    spi_bus_config_t buscfg = {
        .mosi_io_num = SPI_MOSI,
        .miso_io_num = SPI_MISO,
        .sclk_io_num = SPI_CLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
    };

    // 2. Slave Interface Configuration
    spi_slave_interface_config_t slvcfg = {
        .spics_io_num = SPI_CS,  // 1. CS Pin
        .flags = 0,              // 2. Flags
        .queue_size = 3,         // 3. Queue Size
        .mode = 0,               // 4. SPI Mode
        .post_setup_cb = NULL,   // 5. Callback (optional, explicitly NULL)
        .post_trans_cb = NULL    // 6. Callback (optional, explicitly NULL)
    };

    // Initialize SPI Slave
    esp_err_t ret = spi_slave_initialize(VSPI_HOST, &buscfg, &slvcfg, SPI_DMA_CH_AUTO);
    
    if (ret != ESP_OK) {
        Serial.print("SPI INIT FAILED: ");
        Serial.println(ret);
    } else {
        Serial.println("SPI SLAVE READY");
    }

    // Set signature to master
    strcpy(sendbuf, "ESP32_RDY");

    // Queue the first SPI reception
    prepareSPI();

    Serial.println("SYSTEM READY: Waiting for Input (Serial OR SPI)");
    Serial.println("SERIAL FORMAT: spd_az,spd_el,spd_pol,up,dn,rt,lt,p_rt,p_lt");
}

// ================= LOOP =================

void loop() {
    // 1. Check Serial Input
    if (Serial.available() > 0) {
        String input = Serial.readStringUntil('\n');
        input.trim();
        if (input.length() > 0) {
            parseSerialAndExecute(input);
        }
    }

    // 2. Check SPI Input
    spi_slave_transaction_t* out_trans;
    // ticks_to_wait=0 makes it non-blocking
    if (spi_slave_get_trans_result(VSPI_HOST, &out_trans, 0) == ESP_OK) {
        Serial.printf("SPI RX event! trans_len = %d bits (%d bytes)\n", out_trans->trans_len, out_trans->trans_len / 8);
        
        // Print the first 12 bytes of the receive buffer regardless of trans_len to help debug
        Serial.print("Rx buffer: ");
        for (int i = 0; i < 12; i++) {
            Serial.printf("%02X ", (uint8_t)recvbuf[i]);
        }
        Serial.println();

        if (out_trans->trans_len >= 12 * 8) {
            // Extract values
            int s_az  = (uint8_t)recvbuf[0];
            int s_el  = (uint8_t)recvbuf[1];
            int s_pol = (uint8_t)recvbuf[2];
            int up    = (uint8_t)recvbuf[3];
            int down  = (uint8_t)recvbuf[4];
            int right = (uint8_t)recvbuf[5];
            int left  = (uint8_t)recvbuf[6];
            int p_rt  = (uint8_t)recvbuf[7];
            int p_lt  = (uint8_t)recvbuf[8];

            // Print extracted values for easy verification
            Serial.printf("Parsed: az=%d el=%d pol=%d | up=%d dn=%d rt=%d lt=%d pr=%d pl=%d\n",
                          s_az, s_el, s_pol, up, down, right, left, p_rt, p_lt);

            updateMotors(s_az, s_el, s_pol, up, down, right, left, p_rt, p_lt);
        } else {
            Serial.println("DEBUG: SPI transaction too short for command processing!");
        }

        memset(recvbuf, 0, 33);
        prepareSPI();
    }
}

// ================= LOGIC =================

void stopAll() {
    updateMotors(0, 0, 0, 0, 0, 0, 0, 0, 0);
}

// Helper to queue the next SPI transaction
void prepareSPI() {
    memset(&t, 0, sizeof(t));
    t.length = SPI_BUF_SIZE * 8; // Length in bits
    t.tx_buffer = sendbuf;
    t.rx_buffer = recvbuf;
    spi_slave_queue_trans(VSPI_HOST, &t, portMAX_DELAY);
}

void parseSerialAndExecute(String data) {
    int s_az = 0, s_el = 0, s_pol = 0;
    int up = 0, down = 0;
    int right = 0, left = 0;
    int p_right = 0, p_left = 0;

    int count = sscanf(data.c_str(), "%d,%d,%d,%d,%d,%d,%d,%d,%d", 
                       &s_az, &s_el, &s_pol, 
                       &up, &down, 
                       &right, &left, 
                       &p_right, &p_left);
    
    updateMotors(s_az, s_el, s_pol, up, down, right, left, p_right, p_left);
}

// Core Logic: Takes raw values -> Drives Pins
void updateMotors(int s_az, int s_el, int s_pol, int up, int down, int right, int left, int p_right, int p_left) {
    
    // --- 1. CALCULATE PWM FOR EACH AXIS ---
    // Clamp inputs 0-100
    if (s_az < 0) s_az = 0;   if (s_az > 100) s_az = 100;
    if (s_el < 0) s_el = 0;   if (s_el > 100) s_el = 100;
    if (s_pol < 0) s_pol = 0; if (s_pol > 100) s_pol = 100;

    int pwm_az  = map(s_az, 0, 100, 0, 255);
    int pwm_el  = map(s_el, 0, 100, 0, 255);
    int pwm_pol = map(s_pol, 0, 100, 0, 255);

    // --- 2. ELEVATION MOTOR LOGIC ---
    if (up == 1 && down == 0) {
        analogWrite(ELE_EN, pwm_el);
        digitalWrite(ELE_R_PWM, HIGH);
        digitalWrite(ELE_L_PWM, LOW);
    } 
    else if (down == 1 && up == 0) {
        analogWrite(ELE_EN, pwm_el);
        digitalWrite(ELE_R_PWM, LOW);
        digitalWrite(ELE_L_PWM, HIGH);
    } 
    else {
        analogWrite(ELE_EN, 0);
        digitalWrite(ELE_R_PWM, LOW);
        digitalWrite(ELE_L_PWM, LOW);
    }

    // --- 3. AZIMUTH MOTOR LOGIC ---
    if (right == 1 && left == 0) {
        analogWrite(AZI_EN, pwm_az);
        digitalWrite(AZI_R_PWM, HIGH);
        digitalWrite(AZI_L_PWM, LOW);
    } 
    else if (left == 1 && right == 0) {
        analogWrite(AZI_EN, pwm_az);
        digitalWrite(AZI_R_PWM, LOW);
        digitalWrite(AZI_L_PWM, HIGH);
    } 
    else {
        analogWrite(AZI_EN, 0);
        digitalWrite(AZI_R_PWM, LOW);
        digitalWrite(AZI_L_PWM, LOW);
    }

    // --- 4. POLARIZATION MOTOR LOGIC ---
    if (p_right == 1 && p_left == 0) {
        analogWrite(POL_EN, pwm_pol);
        digitalWrite(POL_R_PWM, HIGH);
        digitalWrite(POL_L_PWM, LOW);
    } 
    else if (p_left == 1 && p_right == 0) {
        analogWrite(POL_EN, pwm_pol);
        digitalWrite(POL_R_PWM, LOW);
        digitalWrite(POL_L_PWM, HIGH);
    } 
    else {
        analogWrite(POL_EN, 0);
        digitalWrite(POL_R_PWM, LOW);
        digitalWrite(POL_L_PWM, LOW);
    }
}
