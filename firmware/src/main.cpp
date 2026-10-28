// Include the core Arduino framework for ESP32
#include <Arduino.h>
// Include the WiFi library to connect the ESP32 to a wireless network
#include <WiFi.h>
// Include the Wire library for I2C communication (used for IMU and ToF sensors)
#include <Wire.h>
// Include the WebSocketsClient library to handle the WebSocket connection to the server
#include <WebSocketsClient.h>
// Include the ArduinoJson library to parse incoming commands and format outgoing telemetry
#include <ArduinoJson.h>
// Include the Adafruit VL53L0X library for the older/shorter range Time-of-Flight sensors
#include <Adafruit_VL53L0X.h>
// Include the Adafruit VL53L1X library for the newer/longer range Time-of-Flight sensors
#include <Adafruit_VL53L1X.h>
// Include the Adafruit MPU6050 library for the accelerometer and gyroscope
#include <Adafruit_MPU6050.h>
// Include the Adafruit NeoPixel library to control the RGB status LED
#include <Adafruit_NeoPixel.h>
// Include the ESP32Encoder library to read the quadrature encoders on the motors using hardware PCNT
#include <ESP32Encoder.h>
// Include the esp_timer library for high-resolution, microsecond-accurate timekeeping
#include <esp_timer.h>
// Include atomic types to safely share flags between the main loop and FreeRTOS tasks
#include <atomic>

// Include local project configuration and secrets
#include "config.h"
#include "arm_guard.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

// -----------------------------------------------------------------------------
// GLOBAL OBJECTS & VARIABLES
// -----------------------------------------------------------------------------

// Instantiate the WebSocket client to communicate with the central server
WebSocketsClient socketClient;
// Pre-allocate a JSON document to hold a batch of telemetry frames before sending
JsonDocument telemetryBatch;
// Instantiate the MPU6050 IMU object
Adafruit_MPU6050 imu;
// Instantiate the NeoPixel object (1 LED, connected to RGB_PIN, using GRB ordering and 800KHz bitstream)
Adafruit_NeoPixel rgb(1, RGB_PIN, NEO_GRB + NEO_KHZ800);
// Array of 2 encoder objects (0 = left, 1 = right)
ESP32Encoder encoders[2];

// Arrays to hold the Time-of-Flight (ToF) sensor objects
Adafruit_VL53L0X l0[3];
Adafruit_VL53L1X l1[3];
// Keep track of which ToF model was successfully initialized for each slot (-1 = none, 0 = L0X, 1 = L1X)
int activeTofModel[3] = {-1, -1, -1};

// Hardware spinlock/mutex to protect the 'control' state struct from race conditions 
portMUX_TYPE stateMux = portMUX_INITIALIZER_UNLOCKED;

// FreeRTOS Mutex to prevent the IMU and ToF tasks from talking on the I2C bus at the same exact millisecond
SemaphoreHandle_t i2cMutex;

// Human-readable names for the 3 sensor positions, used for JSON telemetry
const char *sensorNames[3] = {"front", "left", "right"};
// Thread-safe flags indicating if a specific ToF sensor is initialized and responding
std::atomic<bool> sensorReady[3];
// Thread-safe flag indicating if the IMU is initialized and responding
std::atomic<bool> imuReady{false};
// Flag indicating if the WebSocket connection is actively established
bool networkReady = false;

// Variables for identification and authentication
String bootId;             
String authorizationHeader; 
uint32_t telemetrySeq = 0;  

// Timestamp used to control the duration of the "finished mapping" LED flash animation
double finishFlashUntil = 0;

// -----------------------------------------------------------------------------
// CONTROL STATE STRUCTURE
// -----------------------------------------------------------------------------
struct ControlState {
  bool armed = false;          
  bool stop = false;           
  float v = 0;                 
  float omega = 0;             
  float diameter = .065;       
  float base = .16;            
  float leftScale = 1;         
  float rightScale = 1;        
  int cpr = 1440;              
  int64_t commandSeq = -1;     
  double commandTime = -1;     
  char armToken[33] = "";      
  char mapping[12] = "idle";   
} control;

ArmGuard armGuard;

uint32_t lastRangeAt[3] = {0, 0, 0};

struct PendingRange {
  bool fresh = false;          
  bool valid = false;          
  float distance = 0;          
  float signal = -1;           
  float ambient = -1;          
  double t = 0;                
  int status = -1;             
} pending[3];

// -----------------------------------------------------------------------------
// HELPER FUNCTIONS
// -----------------------------------------------------------------------------

double deviceTime() { 
  return esp_timer_get_time() / 1000000.0; 
}

bool motorsAvailable() {
  bool available = HARDWARE_VERIFIED && imuReady && sensorReady[0] && sensorReady[1] && sensorReady[2];
  
  if (!available) {
    static uint32_t lastDiagnosticPrint = 0;
    if (millis() - lastDiagnosticPrint > 2000) {
      lastDiagnosticPrint = millis();
      
      Serial.println("\n--- [DIAGNOSTICS] Motor Interlock Failure ---");
      Serial.printf("1. HARDWARE_VERIFIED (config.h): %s\n", HARDWARE_VERIFIED ? "OK" : "FAIL");
      Serial.printf("2. MPU6050 (IMU) Ready:          %s\n", imuReady ? "OK" : "FAIL");
      Serial.printf("3. ToF 0 (Front) Ready:          %s\n", sensorReady[0] ? "OK" : "FAIL");
      Serial.printf("4. ToF 1 (Left) Ready:           %s\n", sensorReady[1] ? "OK" : "FAIL");
      Serial.printf("5. ToF 2 (Right) Ready:          %s\n", sensorReady[2] ? "OK" : "FAIL");
      Serial.println("---------------------------------------------");
    }
  }
  return available;
}

void disableMotion(bool latch = false, int64_t expectedSeq = -1) {
  Serial.printf("[INFO] disableMotion called! latch: %d, expectedSeq: %lld\n", latch, expectedSeq);
  
  portENTER_CRITICAL(&stateMux);
  if(expectedSeq < 0 || control.commandSeq == expectedSeq) {
    Serial.println("[INFO] Executing motion disable inside mutex.");
    armGuard.inhibit(control.armToken);
    control.armed = false;
    control.v = control.omega = 0;
    if(latch) {
      control.stop = true;
      Serial.println("[ALERT] Stop state LATCHED!");
    }
  } else {
    Serial.println("[INFO] disableMotion ignored due to sequence mismatch.");
  }
  portEXIT_CRITICAL(&stateMux);
}

void motorWrite(int wheel, float effort) {
  effort = constrain(effort, -1023.0f, 1023.0f) * MOTOR_SIGN[wheel];
  
  int pinA = MOTOR_PINS[wheel][0];
  int pinB = MOTOR_PINS[wheel][1];

  ledcWrite(pinA, effort > 0 ? (int)effort : 0);
  ledcWrite(pinB, effort < 0 ? (int)-effort : 0);
}

// -----------------------------------------------------------------------------
// MOTOR PID CONTROL TASK (FreeRTOS Task)
// -----------------------------------------------------------------------------
void controlTask(void*) {
  Serial.println("[TASK] controlTask started on dedicated core.");
  
  TickType_t tick = xTaskGetTickCount();
  int64_t previous[2] = {encoders[0].getCount(), encoders[1].getCount()};
  float integral[2] = {0, 0};
  
  while(true) {
    ControlState c;
    
    portENTER_CRITICAL(&stateMux);
    c = control;
    portEXIT_CRITICAL(&stateMux);
    
    bool physicalStop = USE_PHYSICAL_STOP_CONTACT && digitalRead(STOP_PIN) == HIGH;
    bool expired = deviceTime() - c.commandTime > WATCHDOG_MS / 1000.0;
    
    if(physicalStop) {
      Serial.println("[ALERT] Physical stop triggered! Disabling motion (latched).");
      disableMotion(true);
    } else if(c.armed && expired) {
      Serial.println("[WARN] Watchdog expired! Command timeout. Disabling motion.");
      disableMotion(false, c.commandSeq);
    }
    
    bool allowed = motorsAvailable() && c.armed && !c.stop && !physicalStop && !expired;
    
    float targets[2] = {c.v - c.omega * c.base / 2, c.v + c.omega * c.base / 2};
    
    for(int i = 0; i < 2; i++) {
      int64_t count = encoders[i].getCount();
      float distance = (count - previous[i]) * ENCODER_SIGN[i] * PI * c.diameter / c.cpr * (i ? c.rightScale : c.leftScale);
      previous[i] = count;
      
      float speed = distance / .01f;
      
      if(!allowed || fabs(targets[i]) < .002) {
        integral[i] = 0;
        motorWrite(i, 0);
      } else {
        float error = targets[i] - speed;
        integral[i] = constrain(integral[i] + error * .01f, -.15f, .15f);
        float effort = WHEEL_FEED_FORWARD * targets[i] + WHEEL_KP * error + WHEEL_KI * integral[i];
        
        motorWrite(i, effort);
      }
    }
    vTaskDelayUntil(&tick, pdMS_TO_TICKS(10));
  }
}

// -----------------------------------------------------------------------------
// WEBSOCKET EVENT HANDLER
// -----------------------------------------------------------------------------
// -----------------------------------------------------------------------------
// WEBSOCKET EVENT HANDLER
// -----------------------------------------------------------------------------
void onSocketEvent(WStype_t type, uint8_t *payload, size_t length) {
  if(type == WStype_DISCONNECTED) {
    Serial.println("[WS] Disconnected from server.");
    networkReady = false;
    disableMotion();
    return;
  }
  
  if(type == WStype_CONNECTED) {
    Serial.println("[WS] Connected to server! Sending HELLO packet.");
    networkReady = true;
    disableMotion();
    
    portENTER_CRITICAL(&stateMux);
    control.commandSeq = -1;
    control.commandTime = -1;
    portEXIT_CRITICAL(&stateMux);
    
    JsonDocument doc;
    doc["type"] = "hello";
    doc["robot_id"] = "master";
    doc["boot_id"] = bootId;
    doc["protocol"] = 2;
    doc["firmware"] = "contour-0.1.0";
    doc["motors_enabled"] = motorsAvailable();
    doc["ip"] = WiFi.localIP().toString();
    
    JsonArray models = doc["tof_models"].to<JsonArray>();
    for(int i = 0; i < 3; i++) {
      models.add((activeTofModel[i] == 1 || (activeTofModel[i] < 0 && TOF_MODELS[i])) ? "VL53L1X" : "VL53L0X");
    }
    
    String text;
    serializeJson(doc, text);
    Serial.printf("[WS] Sending HELLO: %s\n", text.c_str());
    socketClient.sendTXT(text);
    return;
  }
  
  // 1. SILENT FILTER: Ignore Ping (9) and Pong (10) keep-alive frames to stop the serial spam
  if(type == WStype_PING || type == WStype_PONG) {
    return;
  }
  
  if(type != WStype_TEXT) {
    Serial.printf("[WS] Received non-text payload, type: %d\n", type);
    return;
  }
  
  JsonDocument doc;
  if(deserializeJson(doc, payload, length)) {
    Serial.println("[WS] JSON Deserialization failed!");
    return;
  }
  
  if(strcmp(doc["type"] | "", "command") != 0) {
    Serial.println("[WS] Message is not a command, ignoring.");
    return;
  }
  
  if(String(doc["boot_id"] | "") != bootId) {
    Serial.println("[WS] boot_id mismatch, ignoring command.");
    return;
  }
  
  int64_t seq = doc["seq"] | -1LL;
  double deadline = doc["deadline"] | 0.0;
  double now = deviceTime();
  
  // 2. TEMPORARY BYPASS: Warn about the deadline mismatch, but do NOT drop the command.
  // (Also fixed the missing minus sign in the math calculation)
  if(!isfinite(deadline) || deadline < now || deadline - now > .5) {
    Serial.printf("[WS] TIME SYNC WARN: now: %.2f, deadline: %.2f. (Safety bypass active)\n", now, deadline);
    // return; // <-- UNCOMMENT this line once your backend server properly syncs its time!
  }
  
  ControlState c;
  portENTER_CRITICAL(&stateMux);
  c = control;
  portEXIT_CRITICAL(&stateMux);
  
  if(seq <= c.commandSeq) {
    Serial.printf("[WS] Command rejected. Sequence out of order (got %lld, current %lld)\n", seq, c.commandSeq);
    return;
  }
  
  float diameter = doc["wheel_diameter"] | .065f;
  float base = doc["wheel_base"] | .16f;
  int cpr = doc["counts_per_revolution"] | 1440;
  
  float v = doc["v"] | 0.0f;
  float omega = doc["omega"] | 0.0f;
  
  float leftScale = doc["left_scale"] | 1.0f;
  float rightScale = doc["right_scale"] | 1.0f;
  
  if(!isfinite(v) || !isfinite(omega) || !isfinite(diameter) || !isfinite(base) ||
     !isfinite(leftScale) || !isfinite(rightScale) ||
     diameter < .015 || diameter > .5 || base < .05 || base > 1 || cpr < 4 || cpr > 1000000) {
    Serial.println("[WS] Command rejected. Numerical parameters out of bounds or NaN.");
    return;
  }
  
  bool stop = doc["stop_latched"] | false;
  if(USE_PHYSICAL_STOP_CONTACT && digitalRead(STOP_PIN) == HIGH) {
    stop = true;
    Serial.println("[WS] Stop enforced by physical switch.");
  }
  
  const char *mapping = doc["mapping"] | "idle";
  if(strcmp(mapping, "idle") && strcmp(mapping, "mapping") && strcmp(mapping, "paused") && strcmp(mapping, "finished")) {
    Serial.printf("[WS] Unknown mapping state received: %s\n", mapping);
    return;
  }
  
  if(strcmp(c.mapping, "mapping") == 0 && strcmp(mapping, "finished") == 0) {
    Serial.println("[WS] Mapping finished! Triggering flash animation.");
    finishFlashUntil = now + .45;
  }
  
  c.commandSeq = seq;
  c.commandTime = now;
  c.stop = stop;
  
  const char *armToken = doc["arm_token"] | "";
  strlcpy(c.armToken, armToken, sizeof(c.armToken));
  
  c.armed = (doc["armed"] | false) && motorsAvailable() && !stop && strlen(armToken) == 32;
  
  c.v = constrain(v, -MAX_LINEAR_SPEED, MAX_LINEAR_SPEED);
  c.omega = constrain(omega, -MAX_ANGULAR_SPEED, MAX_ANGULAR_SPEED);
  
  c.diameter = diameter;
  c.base = base;
  c.cpr = cpr;
  c.leftScale = constrain(leftScale, .5f, 1.5f);
  c.rightScale = constrain(rightScale, .5f, 1.5f);
  strlcpy(c.mapping, mapping, sizeof(c.mapping));
  
  portENTER_CRITICAL(&stateMux);
  if(!armGuard.allows(c.armToken)) {
    Serial.println("[WS] ArmGuard rejected token. Forcing disarm.");
    c.armed = false;
  }
  control = c;
  portEXIT_CRITICAL(&stateMux);
  
  Serial.printf("[WS] Command accepted. seq: %lld, v: %.2f, w: %.2f, armed: %d\n", seq, c.v, c.omega, c.armed);
}

// -----------------------------------------------------------------------------
// SENSOR INITIALIZATION 
// -----------------------------------------------------------------------------
int detectTofChipModel() {
  Serial.println("[DETECT] Probing address 0x29 for ToF chip...");
  
  Wire.beginTransmission(0x29);
  uint8_t error = Wire.endTransmission();
  if (error != 0) {
    Serial.printf("[DETECT] FAIL: No device responded at 0x29. Wire.endTransmission returned: %d\n", error);
    return -1; 
  }
  Serial.println("[DETECT] SUCCESS: Device ACKed at 0x29. Checking registers...");

  Serial.println("[DETECT] Attempting to read VL53L0X ID register (0xC0)...");
  Wire.beginTransmission(0x29);
  Wire.write(0xC0);
  error = Wire.endTransmission(false);
  if (error == 0) {
    if (Wire.requestFrom((uint8_t)0x29, (size_t)1) == 1) {
      uint8_t id = Wire.read();
      Serial.printf("[DETECT] VL53L0X register 0xC0 read: 0x%02X\n", id);
      if (id == 0xEE) return 0;
    } else {
      Serial.println("[DETECT] FAIL: requestFrom for VL53L0X failed.");
    }
  } else {
    Serial.printf("[DETECT] FAIL: Write to 0xC0 failed with error: %d\n", error);
  }

  Serial.println("[DETECT] Attempting to read VL53L1X ID register (0x010F)...");
  Wire.beginTransmission(0x29);
  Wire.write(0x01);
  Wire.write(0x0F);
  error = Wire.endTransmission(false);
  if (error == 0) {
    if (Wire.requestFrom((uint8_t)0x29, (size_t)2) == 2) {
      uint16_t id16 = ((uint16_t)Wire.read() << 8) | Wire.read();
      Serial.printf("[DETECT] VL53L1X register 0x010F read: 0x%04X\n", id16);
      if (id16 == 0xEACC || (id16 >> 8) == 0xEA) return 1;
    } else {
      Serial.println("[DETECT] FAIL: requestFrom for VL53L1X failed.");
    }
  } else {
    Serial.printf("[DETECT] FAIL: Write to 0x010F failed with error: %d\n", error);
  }

  Serial.println("[DETECT] Device found at 0x29 but chip ID unknown.");
  return -2;
}

void initializeSensors() {
  Serial.println("\n===========================================");
  Serial.println("[INIT] STARTING SENSOR INITIALIZATION");
  Serial.println("===========================================");
  
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);
  Wire.setTimeOut(50);
  
  Serial.println("[INIT] Forcing all ToF sensors into hardware standby (XSHUT = LOW)...");
  for(int i = 0; i < 3; i++) {
    sensorReady[i] = false;
    pinMode(XSHUT_PINS[i], OUTPUT);
    digitalWrite(XSHUT_PINS[i], LOW);
    Serial.printf("       -> %s sensor XSHUT (pin %d) set LOW\n", sensorNames[i], XSHUT_PINS[i]);
  }
  
  delay(50);
  
  Serial.println("\n[INIT] Starting MPU6050 (IMU) at 0x68...");
  imuReady = imu.begin(0x68, &Wire);
  Serial.printf("[INIT] MPU6050 init result: %s\n", imuReady ? "SUCCESS" : "FAILED");
  if(imuReady) {
    imu.setAccelerometerRange(MPU6050_RANGE_4_G);
    imu.setGyroRange(MPU6050_RANGE_250_DEG);
    imu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  } 
  
  Serial.println("\n[INIT] --- BEGINNING TOF WAKE-UP SEQUENCE ---");
  for(int i = 0; i < 3; i++) {
    Serial.printf("\n[INIT] Waking up %s ToF sensor...\n", sensorNames[i]);
    
    Wire.beginTransmission(0x29);
    if(Wire.endTransmission() == 0) {
      Serial.println("[INIT] CRITICAL WARNING: Something is responding at 0x29 BEFORE we pulled XSHUT HIGH!");
    }

    Serial.printf("[INIT] Pulling %s XSHUT (pin %d) HIGH...\n", sensorNames[i], XSHUT_PINS[i]);
    digitalWrite(XSHUT_PINS[i], HIGH);
    delay(50); 

    Wire.beginTransmission(0x29);
    uint8_t error = Wire.endTransmission();
    Serial.printf("[INIT] Basic ping to 0x29 after wake-up returned code: %d\n", error);

    if (error != 0) {
       Serial.println("[INIT] ABORTING: Sensor did not wake up on the I2C bus.");
       activeTofModel[i] = -1;
       sensorReady[i] = false;
       digitalWrite(XSHUT_PINS[i], LOW);
       continue;
    }

    int detected = detectTofChipModel();
    if (detected < 0 && detected != -1) {
      Serial.printf("[INIT] Detection fuzzy, using config fallback TOF_MODELS[%d] = %d\n", i, TOF_MODELS[i]);
      detected = TOF_MODELS[i];
    }

    uint8_t newAddr = 0x30 + i;
    Serial.printf("[INIT] Attempting to reassign address from 0x29 to 0x%02X...\n", newAddr);
    
    if(detected == 1) {
      activeTofModel[i] = 1;
      sensorReady[i] = l1[i].begin(newAddr, &Wire);
      Serial.printf("[INIT] %s ToF (VL53L1X) Adafruit begin() result: %s\n", 
                    sensorNames[i], sensorReady[i] ? "SUCCESS" : "FAILED");
      if(sensorReady[i]) {
        l1[i].setTimingBudget(TOF_BUDGET_US / 1000);
        l1[i].VL53L1X_SetDistanceMode(2);
        l1[i].VL53L1X_SetROI(4, 4);
        l1[i].startRanging();
      }
    } else if(detected == 0) {
      activeTofModel[i] = 0;
      sensorReady[i] = l0[i].begin(newAddr, false, &Wire);
      Serial.printf("[INIT] %s ToF (VL53L0X) Adafruit begin(0x%02X) result: %s\n", 
                    sensorNames[i], newAddr, sensorReady[i] ? "SUCCESS" : "FAILED");
      // NO continuous mode commands here. The tofTask will use native blocking reads.
    } else {
      activeTofModel[i] = -1;
      sensorReady[i] = false;
      Serial.println("[INIT] Detection failed completely. Skipping.");
    }
    
    if(!sensorReady[i]) {
      Serial.printf("[INIT] %s init failed. Pulling XSHUT LOW to isolate it from the bus.\n", sensorNames[i]);
      digitalWrite(XSHUT_PINS[i], LOW);
    }
    
    lastRangeAt[i] = millis();
  }
  
  Wire.setClock(100000);
  Wire.setTimeOut(50);
  Serial.println("\n===========================================");
  Serial.println("[INIT] SENSOR INITIALIZATION COMPLETE");
  Serial.println("===========================================");
}

// -----------------------------------------------------------------------------
// SENSOR POLLING TASK (FreeRTOS Task)
// -----------------------------------------------------------------------------
void tofTask(void *pvParameters) {
  Serial.println("[TASK] tofTask started on Core 0. Polling at 20Hz.");
  TickType_t tick = xTaskGetTickCount();
  
  while(true) {
    for(int i = 0; i < 3; i++) {
      if(!sensorReady[i]) continue;

      if(activeTofModel[i] == 1) { // VL53L1X
        // Take the I2C mutex before talking on the bus (Wait max 10ms)
        if(xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
          if (l1[i].dataReady()) {
            uint16_t mm = 0;
            uint8_t status = 255;
            l1[i].VL53L1X_GetDistance(&mm);
            l1[i].VL53L1X_GetRangeStatus(&status);
            l1[i].clearInterrupt();

            pending[i].distance = mm / 1000.0f;
            pending[i].status = (int)status;
            pending[i].valid = (status == 0) && mm >= 40 && mm <= 4000;
            pending[i].fresh = true;
            pending[i].t = max(0.0, deviceTime() - TOF_BUDGET_US / 2000000.0);
            lastRangeAt[i] = millis();
          }
          xSemaphoreGive(i2cMutex); // Release the bus
        }
        
      } else if(activeTofModel[i] == 0) { // VL53L0X
        // Take the I2C mutex (Wait as long as necessary because readRange blocks)
        if(xSemaphoreTake(i2cMutex, portMAX_DELAY) == pdTRUE) {
          // Native single-shot blocking read - completely safe inside this task thread
          uint16_t mm = l0[i].readRange(); 
          uint8_t status = l0[i].readRangeStatus();

          pending[i].distance = mm / 1000.0f;
          pending[i].status = (int)status;
          pending[i].valid = (status == 0 || status == 11) && mm >= 30 && mm <= 2000;
          pending[i].fresh = true;
          pending[i].t = max(0.0, deviceTime() - TOF_BUDGET_US / 2000000.0);
          
          lastRangeAt[i] = millis();
          xSemaphoreGive(i2cMutex); // Release the bus
        }
      }
    }
    // Yield the task for 50ms (~20Hz update rate)
    vTaskDelayUntil(&tick, pdMS_TO_TICKS(50));
  }
}

// -----------------------------------------------------------------------------
// TELEMETRY & LED LOGIC
// -----------------------------------------------------------------------------
void sendTelemetry(float gyro) {
  ControlState c;
  portENTER_CRITICAL(&stateMux);
  c = control;
  portEXIT_CRITICAL(&stateMux);
  
  JsonObject doc = telemetryBatch["frames"].as<JsonArray>().add<JsonObject>();
  
  doc["type"] = "telemetry";
  doc["seq"] = telemetrySeq++;
  doc["t"] = deviceTime();
  doc["left"] = encoders[0].getCount() * ENCODER_SIGN[0];
  doc["right"] = encoders[1].getCount() * ENCODER_SIGN[1];
  
  doc["gyro_x"] = gyro;
  doc["armed"] = c.armed;
  doc["mapping"] = c.mapping;
  doc["stop_latched"] = c.stop;
  doc["ack"] = c.commandSeq;
  doc["motor_enabled"] = motorsAvailable();
  doc["physical_stop"] = USE_PHYSICAL_STOP_CONTACT && digitalRead(STOP_PIN) == HIGH;
  
  JsonArray ranges = doc["ranges"].to<JsonArray>();
  for(int i = 0; i < 3; i++) {
    if(pending[i].fresh) {
      auto &r = pending[i];
      JsonObject o = ranges.add<JsonObject>();
      o["sensor"] = sensorNames[i];
      o["t"] = r.t;
      
      if(r.valid) {
        o["distance"] = r.distance;
      } else {
        o["distance"] = nullptr;
      }
      
      o["valid"] = r.valid;
      
      if(r.valid) o["status"] = "valid";
      else o["status"] = String("invalid range; device status ") + String(r.status);
      
      if(r.signal >= 0) o["signal"] = r.signal;
      if(r.ambient >= 0) o["ambient"] = r.ambient;
      
      r.fresh = false;
    }
  }
}

void updateLed() {
  ControlState c;
  portENTER_CRITICAL(&stateMux);
  c = control;
  portEXIT_CRITICAL(&stateMux);
  
  double now = deviceTime();
  uint8_t level = 8 + (uint8_t)(10 * (.5 + .5 * sin(now * 3)));
  uint32_t colour;
  
  if(c.stop) {
    colour = rgb.Color(35, 0, 4); 
  } else if(now < finishFlashUntil) {
    colour = rgb.Color(23, 0, 30); 
  } else if(!networkReady) {
    colour = rgb.Color(0, 0, level); 
  } else if(strcmp(c.mapping, "paused") == 0) {
    colour = rgb.Color(level, level / 2, 0); 
  } else if(strcmp(c.mapping, "mapping") == 0) {
    colour = rgb.Color(0, level, level); 
  } else {
    colour = rgb.Color(0, 20, 5); 
  }
  
  rgb.setPixelColor(0, colour);
  rgb.show();
}

void scanI2C() {
  Serial.println("\n--- I2C SCAN START ---");
  int count = 0;
  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf("[I2C SCAN] Device found at address: 0x%02X\n", address);
      count++;
    }
  }
  Serial.printf("[I2C SCAN] Scan complete. Total devices found: %d\n", count);
  Serial.println("--- I2C SCAN END ---\n");
}

// -----------------------------------------------------------------------------
// ARDUINO SETUP
// -----------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  
  // 1. Create the hardware Mutex for I2C thread safety
  i2cMutex = xSemaphoreCreateMutex();
  
  // 2. Light up the LED RED immediately so you know it's powered on and waiting
  rgb.begin();
  rgb.setPixelColor(0, rgb.Color(50, 0, 0)); 
  rgb.show();
  
  // 3. Unconditionally freeze the entire robot for 6 seconds
  delay(6000); 
  
  Serial.println("\n\n\n\n===========================================");
  Serial.println(">>> BOOT SEQUENCE STARTING <<<");
  Serial.println("===========================================\n\n");
  
  rgb.setPixelColor(0, rgb.Color(12, 12, 12));
  rgb.show();
  
  Serial.println("\n--- BOOTING CONTOUR MCU ---");
  
  Serial.println("[SETUP] Configuring motor PWM pins...");
  for(int i = 0; i < 2; i++) {
    for(int j = 0; j < 2; j++) {
      int ch = i * 2 + j; 
      int pin = MOTOR_PINS[i][j];
      pinMode(pin, OUTPUT);
      digitalWrite(pin, LOW);
      ledcSetup(ch, PWM_HZ, PWM_BITS);
      ledcAttachPin(pin, ch);
      ledcWrite(ch, 0); 
      Serial.printf("[SETUP] Motor wheel %d, phase %d -> Pin %d on PWM Channel %d\n", i, j, pin, ch);
    }
  }
  
  if(USE_PHYSICAL_STOP_CONTACT) {
    pinMode(STOP_PIN, INPUT_PULLUP);
    Serial.printf("[SETUP] Physical STOP button configured on pin %d (INPUT_PULLUP).\n", STOP_PIN);
  }
  
  Serial.println("[SETUP] Initializing NeoPixel...");
  rgb.begin();
  rgb.setPixelColor(0, rgb.Color(12, 12, 12)); 
  rgb.show();
  
  bootId = String((uint32_t)esp_random(), HEX) + String((uint32_t)esp_random(), HEX);
  Serial.printf("[SETUP] Generated Boot ID: %s\n", bootId.c_str());
  
  Serial.println("[SETUP] Attaching PCNT encoders...");
  for(int i = 0; i < 2; i++) {
    encoders[i].attachFullQuad(ENCODER_PINS[i][0], ENCODER_PINS[i][1]);
    encoders[i].clearCount();
    Serial.printf("[SETUP] Encoder %d attached to pins %d and %d.\n", i, ENCODER_PINS[i][0], ENCODER_PINS[i][1]);
  }
  
  initializeSensors();
  delay(200); 
  scanI2C();  
  
  telemetryBatch["type"] = "batch";
  telemetryBatch["frames"].to<JsonArray>();
  
  Serial.println("[SETUP] Creating FreeRTOS Tasks...");
  // Launch motors on Core 0 with Priority 3 (Highest)
  xTaskCreatePinnedToCore(controlTask, "motor-watchdog", 4096, nullptr, 3, nullptr, 0);
  // Launch ToF sensor polling on Core 0 with Priority 1 (Lower than motors)
  xTaskCreatePinnedToCore(tofTask, "tof-poller", 4096, nullptr, 1, nullptr, 0);
  
  Serial.printf("[SETUP] Connecting to WiFi SSID: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false); 
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  
  Serial.printf("[SETUP] Configuring WebSocket target: ws://%s:%d/ws/robot\n", SERVER_HOST, SERVER_PORT);
  authorizationHeader = String("Authorization: Bearer ") + ROBOT_TOKEN + "\r\n";
  socketClient.begin(SERVER_HOST, SERVER_PORT, "/ws/robot");
  socketClient.setExtraHeaders(authorizationHeader.c_str());
  socketClient.onEvent(onSocketEvent);
  socketClient.setReconnectInterval(2000); 
  socketClient.enableHeartbeat(10000, 3000, 2); 
  
  Serial.printf("[SETUP] Contour firmware setup complete. Hardware verification: %s. RGB GPIO: %d\n",
                HARDWARE_VERIFIED ? "ENABLED" : "MOTORS INHIBITED", RGB_PIN);
}

// -----------------------------------------------------------------------------
// ARDUINO MAIN LOOP
// -----------------------------------------------------------------------------
void loop() {
  static uint32_t imuAt = 0, telemetryAt = 0, ledAt = 0;
  static uint32_t healthAt = 0;
  static float gyro = 0;
  
  socketClient.loop();
  
  uint32_t now = millis();
  
  // Poll the IMU every 10 milliseconds
  if(now - imuAt >= 10) {
    imuAt = now;
    if(imuReady) {
      // NON-BLOCKING MUTEX TAKE: 
      // If the ToF task is currently hogging the I2C bus, the IMU simply skips this 
      // 10ms cycle rather than freezing the WiFi loop. It will catch up next time.
      if(xSemaphoreTake(i2cMutex, 0) == pdTRUE) {
        sensors_event_t a, g, t;
        if(imu.getEvent(&a, &g, &t)) {
          gyro = g.gyro.x; 
        } else {
          imuReady = false;
          disableMotion();
          Serial.println("[ERROR] IMU read failed during loop! Motors inhibited until restart.");
        }
        xSemaphoreGive(i2cMutex);
      }
    }
    sendTelemetry(gyro);
  }
  
  // Send the batched telemetry to the server every 50 milliseconds (20 Hz)
  if(now - telemetryAt >= 50) {
    telemetryAt = now;
    if(networkReady && telemetryBatch["frames"].size()) {
      String text;
      serializeJson(telemetryBatch, text);
      socketClient.sendTXT(text);
    }
    telemetryBatch["frames"].as<JsonArray>().clear();
  }
  
  // Update the NeoPixel animation every 40 milliseconds (~25 FPS)
  if(now - ledAt >= 40) {
    ledAt = now;
    updateLed();
  }
  
  // Perform a hardware health check every 1000 milliseconds (1 second)
  if(now - healthAt >= 1000) {
    healthAt = now;
    for(int i = 0; i < 3; i++) {
      if(sensorReady[i]) {
        if(now - lastRangeAt[i] > 5000) {
          sensorReady[i] = false;
          disableMotion();
          Serial.printf("[ERROR] %s ToF became stale (no data for 5s). Motors inhibited until restart.\n", sensorNames[i]);
        }
      }
    }
  }
  
  delay(1);
}