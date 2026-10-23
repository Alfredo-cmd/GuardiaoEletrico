#include <Arduino.h>

// Pinos de exemplo para ESP32 DevKit V1 clássico.
// Confirme o pinout da sua placa antes de ligar hardware real.
constexpr uint8_t SW_PIN = 18;
constexpr uint8_t BUZZER_PIN = 19;

bool maoDetectada = false;
String horaAtual = "00:00:00";
String linhaSerial;
unsigned long ultimoEvento = 0;
constexpr unsigned long EVENT_COOLDOWN_MS = 5000;

void processarComando(String comando) {
  comando.trim();

  if (comando.startsWith("M:")) {
    const String valor = comando.substring(2);
    maoDetectada = (valor == "1");
    Serial.printf("STATUS:M:%d\n", maoDetectada ? 1 : 0);
  } else if (comando.startsWith("H:")) {
    horaAtual = comando.substring(2);
    Serial.printf("STATUS:H:%s\n", horaAtual.c_str());
  } else if (comando.length() > 0) {
    Serial.printf("WARN:UNKNOWN:%s\n", comando.c_str());
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(SW_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  Serial.println("READY:GUARDIAO_ELETRICO");
}

void loop() {
  while (Serial.available() > 0) {
    const char caractere = static_cast<char>(Serial.read());

    if (caractere == '\n') {
      processarComando(linhaSerial);
      linhaSerial = "";
    } else if (caractere != '\r') {
      if (linhaSerial.length() < 80) {
        linhaSerial += caractere;
      } else {
        linhaSerial = "";
      }
    }
  }

  const bool vibracao = digitalRead(SW_PIN) == HIGH;
  const bool tentativaSuspeita = maoDetectada && vibracao;

  if (tentativaSuspeita) {
      tone(BUZZER_PIN, 2000);
  } else {
      noTone(BUZZER_PIN);
  }

  if (tentativaSuspeita && millis() - ultimoEvento >= EVENT_COOLDOWN_MS) {
    Serial.printf("EVENT:possible_intrusion;V:1;M:1;H:%s\n", horaAtual.c_str());
    ultimoEvento = millis();
  }

  delay(5);
}
