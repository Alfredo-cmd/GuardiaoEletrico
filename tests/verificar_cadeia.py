#!/usr/bin/env python3
"""Teste de integracao da cadeia local do Guardiao Eletrico.

    ESP32 simulado (PTY)  ->  app real (Guardiao_eletrico.py)  ->  FastAPI  ->  SQLite

Cobre duas coisas:

  A) o contrato serial que o firmware precisa cumprir
  B) a cadeia de ponta a ponta usando o codigo real do app

O backend precisa estar no ar antes:

    cd backend && nix-shell --run 'uvicorn app.main:app --host 127.0.0.1 --port 8000'

Este script deve rodar dentro do nix-shell do projeto, porque importa o app
(que precisa de cv2, mediapipe e customtkinter):

    cd Guardiao_eletrico && nix-shell --run "python ../tests/verificar_cadeia.py"

Saida: 0 = tudo passou, 1 = falha, 2 = pre-requisito faltando.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ESP32 = RAIZ / "ESP32"
PY_APP = RAIZ / "Guardiao_eletrico" / "python"
SIMULADOR = ESP32 / "esp32_simulado.py"
PORT_FILE = ESP32 / ".serial-port"

API_URL = os.getenv("GUARDIAO_API_URL", "http://127.0.0.1:8000")


# ---------------------------------------------------------------- utilidades


def api_get(caminho):
    with urllib.request.urlopen(f"{API_URL}{caminho}", timeout=3) as r:
        return json.loads(r.read())


class Falha(Exception):
    pass


def checar(condicao, mensagem):
    if not condicao:
        raise Falha(mensagem)
    print(f"    ok: {mensagem}")


# ------------------------------------------------------- subir o simulador


class Simulador:
    """Sobe esp32_simulado.py e controla a vibracao pelo stdin dele."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(SIMULADOR)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(ESP32),
        )
        self.porta = None

    def esperar_porta(self, segundos=15.0):
        """Le a porta da saida do simulador em vez de confiar no .serial-port,
        que pode estar obsoleto de uma execucao anterior."""
        limite = time.time() + segundos
        while time.time() < limite:
            linha = self.proc.stdout.readline()
            if not linha:
                if self.proc.poll() is not None:
                    raise Falha("simulador morreu ao iniciar")
                continue
            if "porta PTY :" in linha:
                self.porta = linha.split("porta PTY :")[1].strip()
                return self.porta
        raise Falha("simulador nao informou a porta PTY a tempo")

    def vibracao(self, ligada):
        self.proc.stdin.write("1\n" if ligada else "0\n")
        self.proc.stdin.flush()

    def encerrar(self):
        try:
            if self.proc.poll() is None:
                self.proc.stdin.write("q\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
        finally:
            PORT_FILE.unlink(missing_ok=True)


def coletar(ser, segundos):
    """Le linhas da serial por um tempo determinedo."""
    fim = time.time() + segundos
    linhas = []
    while time.time() < fim:
        bruta = ser.readline()
        if not bruta:
            continue
        linha = bruta.decode("utf-8", errors="replace").strip()
        if linha:
            linhas.append(linha)
    return linhas


# ------------------------------------------------- A) contrato serial


def teste_contrato(ser, sim):
    print("\nA) contrato serial do firmware")

    sim.vibracao(False)
    time.sleep(0.3)

    ser.write(b"M:1\n")
    checar("STATUS:M:1" in coletar(ser, 1.0), "M:1 responde STATUS:M:1")

    ser.write(b"M:0\n")
    checar("STATUS:M:0" in coletar(ser, 1.0), "M:0 responde STATUS:M:0")

    ser.write(b"H:07:05:09\n")
    checar("STATUS:H:07:05:09" in coletar(ser, 1.0), "H:responde com o horario")

    ser.write(b"X:1\n")
    checar(
        any(l.startswith("WARN:UNKNOWN:") for l in coletar(ser, 1.0)),
        "comando desconhecido responde WARN:UNKNOWN",
    )

    # mao + vibracao -> um EVENT, e o cooldown segura os seguintes
    sim.vibracao(True)
    time.sleep(0.3)
    ser.write(b"M:1\n")
    ser.write(b"H:07:05:09\n")
    linhas = coletar(ser, 2.5)
    eventos = [l for l in linhas if l.startswith("EVENT:")]
    checar(len(eventos) == 1, f"mao + vibracao gera 1 EVENT (recebi {len(eventos)})")
    checar(
        eventos[0] == "EVENT:possible_intrusion;V:1;M:1;H:07:05:09",
        f"formato do EVENT correto ({eventos[0]})",
    )

    # t~2.5s depois do 1o EVENT: nada pode chegar antes do cooldown de 5s
    linhas = coletar(ser, 2.0)
    checar(
        not [l for l in linhas if l.startswith("EVENT:")],
        "cooldown de 5s nao repete EVENT cedo demais",
    )

    # agora t~4.5s: o EVENT seguinte deve aparecer dentro desta janela
    linhas = coletar(ser, 3.0)
    repetidos = [l for l in linhas if l.startswith("EVENT:")]
    checar(
        len(repetidos) == 1,
        f"cooldown libera o proximo EVENT (recebi {len(repetidos)})",
    )

    ser.write(b"M:0\n")
    coletar(ser, 0.6)
    sim.vibracao(False)


# ------------------------------------------- B) cadeia com o codigo real


def teste_cadeia(ge, porta, sim):
    print("\nB) cadeia ESP32 -> app real -> API -> SQLite")

    import serial

    sim.vibracao(True)
    time.sleep(0.3)

    os.environ["GUARDIAO_SERIAL_URL"] = porta
    ge.SERIAL_URL = porta

    eventos_antes = len(api_get("/api/v1/events")["items"])

    enviados = []

    class AppSemGUI:
        """Usa ler_serial e enviar_evento_api reais; so a GUI e' substituida."""

        ler_serial = ge.GuardiaoApp.ler_serial

        def __init__(self):
            self.running = True
            self.ser = serial.serial_for_url(ge.SERIAL_URL, ge.BAUDRATE, timeout=0.5)

        def after(self, *_a, **_k):
            pass

        def atualizar_status(self, texto):
            pass

        def enviar_evento_api(self, vibration_detected, hand_detected):
            ge.GuardiaoApp.enviar_evento_api(self, vibration_detected, hand_detected)
            enviados.append((vibration_detected, hand_detected))

    app = AppSemGUI()
    t = threading.Thread(target=app.ler_serial, daemon=True)
    t.start()
    try:
        # a camera decidiria isto; injetamos o mesmo comando que ela enviaria
        app.ser.write(b"M:1\n")
        app.ser.flush()

        limite = time.time() + 8.0
        while time.time() < limite and not enviados:
            time.sleep(0.1)
    finally:
        app.running = False
        time.sleep(0.6)
        app.ser.close()

    checar(len(enviados) == 1, f"app recebeu 1 EVENT da serial (recebi {len(enviados)})")
    checar(enviados[0] == (True, True), f"app mapeou V/M corretamente {enviados[0]}")

    depois = api_get("/api/v1/events")["items"]
    checar(
        len(depois) == eventos_antes + 1,
        f"API gravou o evento ({eventos_antes} -> {len(depois)})",
    )
    ultimo = depois[-1]
    checar(ultimo["device_id"] == ge.DEVICE_ID, f"device_id correto ({ultimo['device_id']})")
    checar(
        ultimo["event_type"] == "possible_intrusion"
        and ultimo["vibration_detected"]
        and ultimo["hand_detected"],
        "evento gravado com os campos certos",
    )


# ------------------------------------------------------------------- main


def main():
    print("=" * 68)
    print("Guardiao Eletrico - verificacao da cadeia local")
    print("=" * 68)

    try:
        api_get("/api/v1/health")
        print(f"backend: no ar em {API_URL}")
    except (urllib.error.URLError, TimeoutError, OSError):
        print(f"\nBACKEND FORA DO AR em {API_URL}.")
        print("Suba com:")
        print(f"  cd {RAIZ / 'backend'}")
        print("  nix-shell --run 'uvicorn app.main:app --host 127.0.0.1 --port 8000'")
        return 2

    sys.path.insert(0, str(PY_APP))
    try:
        import Guardiao_eletrico as ge
    except ImportError as exc:
        print(f"\nFalta dependencia do app ({exc}).")
        print("Rode dentro do nix-shell do projeto.")
        return 2

    import serial

    sim = Simulador()
    ser = None
    try:
        porta = sim.esperar_porta()
        print(f"simulador: {porta}")
        checar(Path(porta).exists(), "porta PTY existe")

        ser = serial.serial_for_url(porta, 115200, timeout=0.3)
        sim.vibracao(True)
        time.sleep(0.4)

        teste_contrato(ser, sim)
        teste_cadeia(ge, porta, sim)
    except Falha as exc:
        print(f"\nFALHOU: {exc}")
        return 1
    finally:
        if ser is not None:
            ser.close()
        sim.encerrar()

    print("\n" + "=" * 68)
    print("TUDO OK")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())