# Guardião Elétrico — versão ESP32

Esta versão substitui a implementação antiga para Arduino Uno. A pasta `Arduino/` e o firmware para Uno foram removidos; o firmware principal agora está em `ESP32/`.

## Estrutura principal
- `ESP32/`: projeto PlatformIO para ESP32 DevKit V1 clássico, firmware C++ e arquivos de simulação Wokwi.
- `Guardiao_eletrico/python/Guardiao_eletrico.py`: interface Python com OpenCV/MediaPipe e comunicação serial com o firmware ESP32.
- `Guardiao_eletrico/python/hand_landmarker.task`: modelo de detecção de mãos.
- `Guardiao_eletrico/python/requirements.txt`: dependências Python do projeto.

## Simulação
Abra a pasta `ESP32/` no VS Code com PlatformIO e compile o ambiente `esp32dev`. O `diagram.json` e `wokwi.toml` ficam nessa pasta. O botão no diagrama representa a saída digital do sensor SW-420.

A configuração serial do Python usa `rfc2217://localhost:4000`, destinada à simulação Wokwi configurada em `wokwi.toml`. Para uma placa física, ajuste `SERIAL_URL` no arquivo Python para a porta serial real, por exemplo `/dev/ttyUSB0` ou `/dev/ttyACM0`, conforme o dispositivo reconhecido pelo sistema.

## Protocolo serial
Cada comando termina com uma nova linha (`\n`):
- `M:1` = mão detectada
- `M:0` = mão não detectada
- `H:HH:MM:SS` = atualizar horário

## Hardware e limitações
- Os GPIOs 18 e 19 são exemplos para o ESP32 DevKit V1 clássico; confirme a pinagem da placa usada.
- GPIOs do ESP32 usam lógica de 3,3 V e não toleram entrada de 5 V.
- Não acione cargas de potência diretamente por um GPIO; dimensione o circuito de acionamento do buzzer/alarme.
- O Python e o MediaPipe continuam rodando no computador; esta migração troca o controlador de hardware para ESP32, mas não transfere a visão computacional para ele.
- O projeto ainda precisa ser compilado e testado no PlatformIO/Wokwi. A simulação não garante o comportamento elétrico real nem o funcionamento da câmera física.
