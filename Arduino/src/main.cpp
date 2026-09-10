#include <Arduino.h>


const int SW_PIN = 2;
const int BUZZER_PIN = 4;
String MAO_ESTADO = "0";
String HORA_ATUAL = "00:00:00";

void setup() {

  Serial.begin(9600);
  pinMode(SW_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  

}

void loop() {
  if (Serial.available() > 0) {
   String dado = Serial.readStringUntil('\n');
    dado.trim();


    if (dado.startsWith("H:")) {
      HORA_ATUAL = dado.substring(2);
      Serial.print("Horario atualizado: ");
      Serial.println(HORA_ATUAL);
    } 

    else {
      MAO_ESTADO = dado;
      Serial.print("RECEBIDO: ");
      Serial.println(MAO_ESTADO);
    }
    Serial.print("RECEBIDO: ");
    Serial.println(MAO_ESTADO);
  }
    int SW_STATE = digitalRead(SW_PIN);

    
    if(MAO_ESTADO == "1" and SW_STATE == HIGH){
      Serial.print("\n[Tentativa de furto! | "+ HORA_ATUAL+ "| ]\n");
      digitalWrite(BUZZER_PIN, HIGH);
      delay(200);
    }
    else if(MAO_ESTADO == "1" and SW_STATE == LOW){
      Serial.print("\n[MAO_DETECTADA! | "+ HORA_ATUAL+ "| ]\n");
      digitalWrite(BUZZER_PIN, LOW);
    }
    else if(MAO_ESTADO == "0" and SW_STATE == HIGH){
      Serial.print("\n[VIBRAÇÃO DETECTADA! | "+ HORA_ATUAL+ "| ]\n");
      digitalWrite(BUZZER_PIN, LOW);
    }
    else
    {
      digitalWrite(BUZZER_PIN, LOW);
    }
  
  
}
