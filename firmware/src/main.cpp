#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Adafruit_VL53L0X.h>
#include <Adafruit_VL53L1X.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_NeoPixel.h>
#include <ESP32Encoder.h>
#include <esp_timer.h>
#include <atomic>
#include "config.h"
#include "arm_guard.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

WebSocketsClient socketClient;
JsonDocument telemetryBatch;
Adafruit_MPU6050 imu;
Adafruit_NeoPixel rgb(1, RGB_PIN, NEO_GRB + NEO_KHZ800);
ESP32Encoder encoders[2];
Adafruit_VL53L0X l0[3];
Adafruit_VL53L1X l1[3];
portMUX_TYPE stateMux = portMUX_INITIALIZER_UNLOCKED;
const char *sensorNames[3] = {"front", "left", "right"};
std::atomic<bool> sensorReady[3] = {{false}, {false}, {false}};
std::atomic<bool> imuReady{false};
bool networkReady = false;
String bootId, authorizationHeader;
uint32_t telemetrySeq = 0;
double finishFlashUntil = 0;
struct ControlState {
  bool armed = false, stop = false;
  float v = 0, omega = 0, diameter = .065, base = .16;
  float leftScale = 1, rightScale = 1;
  int cpr = 1440;
  int64_t commandSeq = -1;
  double commandTime = -1;
  char armToken[33] = "";
  char mapping[12] = "idle";
} control;
ArmGuard armGuard;
uint32_t lastRangeAt[3] = {0,0,0};
struct PendingRange {
  bool fresh=false, valid=false;
  float distance=0, signal=-1, ambient=-1;
  double t=0;
  int status=-1;
} pending[3];

double deviceTime() { return esp_timer_get_time() / 1000000.0; }
bool motorsAvailable() {
  return HARDWARE_VERIFIED && imuReady && sensorReady[0] && sensorReady[1] && sensorReady[2];
}
void disableMotion(bool latch=false, int64_t expectedSeq=-1) {
  portENTER_CRITICAL(&stateMux);
  if(expectedSeq<0 || control.commandSeq==expectedSeq) {
    armGuard.inhibit(control.armToken);
    control.armed=false;
    control.v=control.omega=0;
    if(latch) control.stop=true;
  }
  portEXIT_CRITICAL(&stateMux);
}
void motorWrite(int wheel, float effort) {
  effort=constrain(effort,-1023.0f,1023.0f)*MOTOR_SIGN[wheel];
  int a=wheel*2,b=a+1;
  // Arduino-ESP32 2.x LEDC channels (platform is pinned in platformio.ini).
  ledcWrite(a,effort>0 ? (int)effort : 0);
  ledcWrite(b,effort<0 ? (int)-effort : 0);
}
void controlTask(void*) {
  TickType_t tick=xTaskGetTickCount();
  int64_t previous[2]={encoders[0].getCount(),encoders[1].getCount()};
  float integral[2]={0,0};
  while(true) {
    ControlState c;
    portENTER_CRITICAL(&stateMux);c=control;portEXIT_CRITICAL(&stateMux);
    bool physicalStop=USE_PHYSICAL_STOP_CONTACT && digitalRead(STOP_PIN)==HIGH;
    bool expired=deviceTime()-c.commandTime > WATCHDOG_MS/1000.0;
    if(physicalStop) disableMotion(true);
    else if(c.armed && expired) disableMotion(false,c.commandSeq);
    bool allowed=motorsAvailable() && c.armed && !c.stop && !physicalStop && !expired;
    float targets[2]={c.v-c.omega*c.base/2,c.v+c.omega*c.base/2};
    for(int i=0;i<2;i++) {
      int64_t count=encoders[i].getCount();
      float distance=(count-previous[i])*ENCODER_SIGN[i]*PI*c.diameter/c.cpr*(i?c.rightScale:c.leftScale);
      previous[i]=count;
      float speed=distance/.01f;
      if(!allowed || fabs(targets[i])<.002) {
        integral[i]=0;motorWrite(i,0);
      } else {
        float error=targets[i]-speed;
        integral[i]=constrain(integral[i]+error*.01f,-.15f,.15f);
        float effort=WHEEL_FEED_FORWARD*targets[i]+WHEEL_KP*error+WHEEL_KI*integral[i];
        motorWrite(i,effort);
      }
    }
    vTaskDelayUntil(&tick,pdMS_TO_TICKS(10));
  }
}
void onSocketEvent(WStype_t type,uint8_t *payload,size_t length) {
  if(type==WStype_DISCONNECTED) {networkReady=false;disableMotion();return;}
  if(type==WStype_CONNECTED) {
    networkReady=true;disableMotion();
    // Sequences belong to this connection; the computer may have restarted.
    portENTER_CRITICAL(&stateMux);
    control.commandSeq=-1;control.commandTime=-1;
    portEXIT_CRITICAL(&stateMux);
    JsonDocument doc;doc["type"]="hello";doc["robot_id"]="master";doc["boot_id"]=bootId;
    doc["protocol"]=2;
    doc["firmware"]="contour-0.1.0";doc["motors_enabled"]=motorsAvailable();doc["ip"]=WiFi.localIP().toString();
    JsonArray models=doc["tof_models"].to<JsonArray>();
    for(int i=0;i<3;i++)models.add(TOF_MODELS[i] ? "VL53L1X" : "VL53L0X");
    String text;serializeJson(doc,text);socketClient.sendTXT(text);return;
  }
  if(type!=WStype_TEXT)return;
  JsonDocument doc;
  if(deserializeJson(doc,payload,length))return;
  if(strcmp(doc["type"]|"","command")!=0)return;
  if(String(doc["boot_id"]|"")!=bootId)return;
  int64_t seq=doc["seq"]|-1LL;
  double deadline=doc["deadline"]|0.0,now=deviceTime();
  if(!isfinite(deadline) || deadline<now || deadline-now>.5)return;
  ControlState c;
  portENTER_CRITICAL(&stateMux);c=control;portEXIT_CRITICAL(&stateMux);
  if(seq<=c.commandSeq)return;
  float diameter=doc["wheel_diameter"]|.065f,base=doc["wheel_base"]|.16f;
  int cpr=doc["counts_per_revolution"]|1440;
  float v=doc["v"]|0.0f,omega=doc["omega"]|0.0f;
  float leftScale=doc["left_scale"]|1.0f,rightScale=doc["right_scale"]|1.0f;
  if(!isfinite(v)||!isfinite(omega)||!isfinite(diameter)||!isfinite(base)||
     !isfinite(leftScale)||!isfinite(rightScale)||
     diameter<.015||diameter>.5||base<.05||base>1||cpr<4||cpr>1000000)return;
  bool stop=doc["stop_latched"]|false;
  if(USE_PHYSICAL_STOP_CONTACT && digitalRead(STOP_PIN)==HIGH)stop=true;
  const char *mapping=doc["mapping"]|"idle";
  if(strcmp(mapping,"idle")&&strcmp(mapping,"mapping")&&strcmp(mapping,"paused")&&strcmp(mapping,"finished"))return;
  if(strcmp(c.mapping,"mapping")==0 && strcmp(mapping,"finished")==0)finishFlashUntil=now+.45;
  c.commandSeq=seq;c.commandTime=now;c.stop=stop;
  const char *armToken=doc["arm_token"]|"";
  strlcpy(c.armToken,armToken,sizeof(c.armToken));
  c.armed=(doc["armed"]|false)&&motorsAvailable()&&!stop&&strlen(armToken)==32;
  c.v=constrain(v,-MAX_LINEAR_SPEED,MAX_LINEAR_SPEED);
  c.omega=constrain(omega,-MAX_ANGULAR_SPEED,MAX_ANGULAR_SPEED);
  c.diameter=diameter;c.base=base;c.cpr=cpr;
  c.leftScale=constrain(leftScale,.5f,1.5f);
  c.rightScale=constrain(rightScale,.5f,1.5f);
  strlcpy(c.mapping,mapping,sizeof(c.mapping));
  portENTER_CRITICAL(&stateMux);
  // Timeout/disconnect inhibition survives repeated armed commands. Only an
  // explicit new operator arm action issues a different token.
  if(!armGuard.allows(c.armToken))c.armed=false;
  control=c;
  portEXIT_CRITICAL(&stateMux);
}
void initializeSensors() {
  Wire.begin(SDA_PIN,SCL_PIN);Wire.setClock(100000);Wire.setTimeOut(10);
  for(int i=0;i<3;i++){pinMode(XSHUT_PINS[i],OUTPUT);digitalWrite(XSHUT_PINS[i],LOW);}
  delay(10);
  imuReady=imu.begin(0x68,&Wire);
  if(imuReady) {
    imu.setAccelerometerRange(MPU6050_RANGE_4_G);
    imu.setGyroRange(MPU6050_RANGE_250_DEG);
    imu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  }
  for(int i=0;i<3;i++) {
    // HIGH releases the open-drain pin; the breakout supplies its own XSHUT pull-up.
    digitalWrite(XSHUT_PINS[i],HIGH);delay(50);
    uint8_t newAddr = 0x30 + i;
    if(TOF_MODELS[i]==1) {
      sensorReady[i]=l1[i].begin(newAddr,&Wire);
      if(sensorReady[i]) {
        l1[i].setTimingBudget(TOF_BUDGET_US/1000);
        l1[i].setDistanceMode(VL53L1X::Long);
        l1[i].startRanging();
      }
    } else {
      sensorReady[i]=l0[i].begin(newAddr,false,&Wire);
      if(sensorReady[i]) {
        l0[i].setMeasurementTimingBudgetMicroSeconds(TOF_BUDGET_US);
        l0[i].startRangeContinuous(TOF_PERIOD_MS);
      }
    }
    if(!sensorReady[i])digitalWrite(XSHUT_PINS[i],LOW);
    lastRangeAt[i]=millis();
    Serial.printf("%s ToF: %s\n",sensorNames[i],sensorReady[i]?"ready":"FAILED (check chip model and wiring)");
  }
  Serial.printf("MPU6050: %s\n",imuReady?"ready":"FAILED");
}
void pollRanges() {
  for(int i=0;i<3;i++) {
    if(!sensorReady[i])continue;
    bool ready=TOF_MODELS[i] ? l1[i].dataReady() : l0[i].isRangeComplete();
    if(!ready)continue;
    lastRangeAt[i]=millis();
    auto &r=pending[i];
    r.fresh=true;r.t=max(0.0,deviceTime()-TOF_BUDGET_US/2000000.0);
    if(TOF_MODELS[i]) {
      int16_t mm=l1[i].distance();
      uint8_t status=l1[i].vl_status;
      l1[i].clearInterrupt();
      r.status=(int)status;
      if(mm>=40 && mm<=4000) {
        r.distance=mm/1000.0f;
        r.valid=(status==0);
      } else {
        r.distance=0;
        r.valid=false;
      }
      r.signal=r.ambient=-1;
    } else {
      uint8_t status=l0[i].readRangeStatus();
      uint16_t mm=l0[i].readRange();
      r.distance=mm/1000.0f;
      r.status=(int)status;
      // Adafruit VL53L0X status 0 = Range Valid (VL53L0X_ERROR_NONE)
      r.valid=(status==0) && mm>=30 && mm<=2000;
      r.signal=r.ambient=-1;
    }
  }
}
void sendTelemetry(float gyro) {
  ControlState c;
  portENTER_CRITICAL(&stateMux);c=control;portEXIT_CRITICAL(&stateMux);
  JsonObject doc=telemetryBatch["frames"].as<JsonArray>().add<JsonObject>();
  doc["type"]="telemetry";doc["seq"]=telemetrySeq++;doc["t"]=deviceTime();
  doc["left"]=encoders[0].getCount()*ENCODER_SIGN[0];
  doc["right"]=encoders[1].getCount()*ENCODER_SIGN[1];
  doc["gyro_z"]=gyro;doc["armed"]=c.armed;doc["mapping"]=c.mapping;
  doc["stop_latched"]=c.stop;doc["ack"]=c.commandSeq;doc["motor_enabled"]=motorsAvailable();
  doc["physical_stop"]=USE_PHYSICAL_STOP_CONTACT && digitalRead(STOP_PIN)==HIGH;
  JsonArray ranges=doc["ranges"].to<JsonArray>();
  for(int i=0;i<3;i++)if(pending[i].fresh) {
    auto &r=pending[i];JsonObject o=ranges.add<JsonObject>();
    o["sensor"]=sensorNames[i];o["t"]=r.t;
    if(r.valid)o["distance"]=r.distance;else o["distance"]=nullptr;
    o["valid"]=r.valid;
    if(r.valid)o["status"]="valid";
    else o["status"]=String("invalid range; device status ")+String(r.status);
    if(r.signal>=0)o["signal"]=r.signal;if(r.ambient>=0)o["ambient"]=r.ambient;
    r.fresh=false;
  }
}
void updateLed() {
  ControlState c;portENTER_CRITICAL(&stateMux);c=control;portEXIT_CRITICAL(&stateMux);
  double now=deviceTime();uint8_t level=8+(uint8_t)(10*(.5+.5*sin(now*3)));
  uint32_t colour;
  if(c.stop)colour=rgb.Color(35,0,4);
  else if(now<finishFlashUntil)colour=rgb.Color(23,0,30);
  else if(!networkReady)colour=rgb.Color(0,0,level);
  else if(strcmp(c.mapping,"paused")==0)colour=rgb.Color(level,level/2,0);
  else if(strcmp(c.mapping,"mapping")==0)colour=rgb.Color(0,level,level);
  else colour=rgb.Color(0,20,5);
  rgb.setPixelColor(0,colour);rgb.show();
}

void scanI2C() {
  Serial.println("\n--- I2C SCAN ---");

  int count = 0;

  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);

    if (Wire.endTransmission() == 0) {
      Serial.printf("Device found: 0x%02X\n", address);
      count++;
    }
  }

  Serial.printf("Devices found: %d\n", count);
}





void setup() {
  for(int i=0;i<2;i++)for(int j=0;j<2;j++) {
    int ch=i*2+j;pinMode(MOTOR_PINS[i][j],OUTPUT);digitalWrite(MOTOR_PINS[i][j],LOW);
    ledcSetup(ch,PWM_HZ,PWM_BITS);ledcAttachPin(MOTOR_PINS[i][j],ch);ledcWrite(ch,0);
  }
  if(USE_PHYSICAL_STOP_CONTACT)pinMode(STOP_PIN,INPUT_PULLUP);
  Serial.begin(115200);rgb.begin();rgb.setPixelColor(0,rgb.Color(12,12,12));rgb.show();
  bootId=String((uint32_t)esp_random(),HEX)+String((uint32_t)esp_random(),HEX);
  for(int i=0;i<2;i++){encoders[i].attachFullQuad(ENCODER_PINS[i][0],ENCODER_PINS[i][1]);encoders[i].clearCount();}
  initializeSensors();
  delay(200);
  scanI2C();
  telemetryBatch["type"]="batch";
  telemetryBatch["frames"].to<JsonArray>();
  xTaskCreatePinnedToCore(controlTask,"motor-watchdog",4096,nullptr,3,nullptr,1);
  WiFi.mode(WIFI_STA);WiFi.setSleep(false);WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
  authorizationHeader=String("Authorization: Bearer ")+ROBOT_TOKEN+"\r\n";
  socketClient.begin(SERVER_HOST,SERVER_PORT,"/ws/robot");
  socketClient.setExtraHeaders(authorizationHeader.c_str());
  socketClient.onEvent(onSocketEvent);socketClient.setReconnectInterval(2000);
  socketClient.enableHeartbeat(10000,3000,2);
  Serial.printf("Contour firmware. Hardware verification: %s. RGB GPIO: %d\n",
                HARDWARE_VERIFIED?"ENABLED":"MOTORS INHIBITED",RGB_PIN);
}
void loop() {
  static uint32_t imuAt=0,telemetryAt=0,ledAt=0;
  static uint32_t healthAt=0;
  static float gyro=0;
  socketClient.loop();
  uint32_t now=millis();
  pollRanges();
  if(now-imuAt>=10) {
    imuAt=now;
    if(imuReady){
      sensors_event_t a,g,t;
      if(imu.getEvent(&a,&g,&t))gyro=g.gyro.z;
      else {imuReady=false;disableMotion();Serial.println("IMU read failed; motors inhibited until restart.");}
    }
    sendTelemetry(gyro);
  }
  if(now-telemetryAt>=50){
    telemetryAt=now;
    if(networkReady && telemetryBatch["frames"].size()){
      String text;serializeJson(telemetryBatch,text);socketClient.sendTXT(text);
    }
    telemetryBatch["frames"].as<JsonArray>().clear();
  }
  if(now-ledAt>=40){ledAt=now;updateLed();}
  if(now-healthAt>=1000){
    healthAt=now;
    for(int i=0;i<3;i++)if(sensorReady[i]){
      Wire.beginTransmission(0x30+i);
      if(Wire.endTransmission()!=0 || now-lastRangeAt[i]>5000){
        sensorReady[i]=false;disableMotion();
        Serial.printf("%s ToF disconnected or stale; motors inhibited until restart.\n",sensorNames[i]);
      }
    }
  }
  delay(1);
}
