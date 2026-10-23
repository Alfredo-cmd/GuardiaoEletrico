"""Substituto headless do ESP32 simulado (camada 1).

O Wokwi para VS Code roda a engine dentro de um iframe remoto (wokwi.com),
preso a GUI e a licenca paga. Para desenvolver e testar as camadas seguintes
(Python -> POST -> FastAPI -> SQLite) nao e preciso de um ESP32 de verdade:
o que importa e o contrato de protocolo.

Este script emula o firmware de src/main.cpp sobre um PTY:
  - anuncia READY:GUARDIAO_ELETRICO assim que um cliente conecta
  - responde STATUS:M:x e STATUS:H:... a cada comando recebido
  - responde WARN:UNKNOWN:<cmd> para comandos desconhecidos
  - emite EVENT:possible_intrusion;V:1;M:1;H:... quando ha vibracao E mao,
    respeitando o cooldown de 5 segundos do firmware

Injecao de vibracao (teclado, uma tecla por vez):
  1 = ligar vibracao      0 = desligar vibracao      q = encerrar

Uso:
    python esp32_simulado.py
    GUARDIAO_SERIAL_URL=/dev/pts/7 python ../Guardiao_eletrico/python/Guardiao_eletrico.py
"""

import os
import select
import signal
import stat
import sys
import termios
import time

EVENT_COOLDOWN_MS = 5000
READY_REANUNCIO_S = 1.0
PORT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".serial-port")


class Esp32Simulado:
    def __init__(self) -> None:
        self.rodando = True
        self.vibracao = False
        self.mao_detectada = False
        self.hora_atual = "00:00:00"
        self.conectado = False
        self.recebeu_comando = False
        self.ultimo_evento = 0.0
        self.ultimo_anuncio = 0.0
        self.fila: list[str] = []
        self.buffer = ""
        self.master_fd = -1
        self.slave_fd = -1
        self.stdin_tty = False
        self.stdin_pipe = False
        self.stdin_anterior = None

    def avisar(self, texto: str) -> None:
        print(texto, file=sys.stderr, flush=True)

    def enviar(self, linha: str) -> None:
        self.fila.append(f"{linha}\n")

    def flush(self) -> None:
        if not self.fila:
            return
        try:
            os.write(self.master_fd, "".join(self.fila).encode("utf-8"))
        except OSError:
            self.conectado = False
            return
        self.fila.clear()
        self.conectado = True

    def processar_comando(self, comando: str) -> None:
        comando = comando.strip()

        if comando.startswith("M:"):
            self.recebeu_comando = True
            self.mao_detectada = comando[2:] == "1"
            self.enviar(f"STATUS:M:{1 if self.mao_detectada else 0}")
        elif comando.startswith("H:"):
            self.recebeu_comando = True
            self.hora_atual = comando[2:]
            self.enviar(f"STATUS:H:{self.hora_atual}")
        elif comando:
            self.recebeu_comando = True
            self.enviar(f"WARN:UNKNOWN:{comando}")

    def abrir_pty(self) -> str:
        self.master_fd, self.slave_fd = os.openpty()
        porta = os.ttyname(self.slave_fd)
        # o slave precisa ficar aberto para o no /dev/pts/N continuar existindo
        atributos = termios.tcgetattr(self.slave_fd)
        atributos[3] &= ~(termios.ECHO | termios.ICANON)
        termios.tcsetattr(self.slave_fd, termios.TCSANOW, atributos)
        return porta

    def configurar_stdin(self) -> None:
        try:
            modo = os.fstat(0).st_mode
        except OSError:
            modo = None

        # pipe anonimo (subprocess) ou FIFO nomeado: ambos servem para comandos.
        # /dev/null e um dispositivo de caractere e nao serve para nada.
        self.stdin_pipe = modo is not None and not stat.S_ISCHR(modo)
        self.stdin_tty = sys.stdin.isatty()
        if not self.stdin_tty:
            return
        self.stdin_anterior = termios.tcgetattr(sys.stdin)
        atributos = list(self.stdin_anterior)
        atributos[3] &= ~(termios.ECHO | termios.ICANON)
        atributos[6][termios.VMIN] = 1
        atributos[6][termios.VTIME] = 0
        termios.tcsetattr(sys.stdin, termios.TCSANOW, atributos)

    def tratar_tecla(self, tecla: bytes) -> None:
        if tecla in (b"1", b"0"):
            self.vibracao = tecla == b"1"
            estado = "ON" if self.vibracao else "OFF"
            mao = "sim" if self.mao_detectada else "nao"
            self.avisar(f"[tecla] vibracao {estado} | mao detectada: {mao}")
        elif tecla in (b"q", b"\x03", b"\x04"):
            self.rodando = False

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "rodando", False))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "rodando", False))

        porta = self.abrir_pty()
        self.configurar_stdin()

        with open(PORT_FILE, "w") as arquivo:
            arquivo.write(porta + "\n")

        self.enviar("READY:GUARDIAO_ELETRICO")

        self.avisar("ESP32 simulado (headless)")
        self.avisar(f"  porta PTY : {porta}")
        self.avisar(f"  arquivo   : {PORT_FILE}")
        self.avisar(f"  use       : GUARDIAO_SERIAL_URL={porta}")
        if self.stdin_tty:
            self.avisar("  teclas    : 1=vibracao on  0=vibracao off  q=encerra")

        leitura = [self.master_fd]
        if self.stdin_tty or self.stdin_pipe:
            leitura.append(0)

        while self.rodando:
            prontos, _, _ = select.select(leitura, [], [], 0.05)

            if self.master_fd in prontos:
                try:
                    dados = os.read(self.master_fd, 256)
                except OSError:
                    dados = b""
                if not dados:
                    self.conectado = False
                else:
                    self.buffer += dados.decode("utf-8", errors="replace")
                    while "\n" in self.buffer:
                        linha, self.buffer = self.buffer.split("\n", 1)
                        self.processar_comando(linha)

            if 0 in prontos:
                self.tratar_tecla(os.read(0, 1))

            agora = time.monotonic()
            # pyserial descarta a fila no open(), entao o banner e' reemitido
            # ate o primeiro comando do cliente
            if not self.recebeu_comando and (agora - self.ultimo_anuncio) >= READY_REANUNCIO_S:
                self.enviar("READY:GUARDIAO_ELETRICO")
                self.ultimo_anuncio = agora

            desde = (agora - self.ultimo_evento) * 1000
            if self.mao_detectada and self.vibracao and desde >= EVENT_COOLDOWN_MS:
                self.enviar(
                    f"EVENT:possible_intrusion;V:1;M:1;H:{self.hora_atual}"
                )
                self.ultimo_evento = agora
                self.avisar("[evento] EVENT emitido")

            self.flush()

        self.encerrar()

    def encerrar(self) -> None:
        for fd in (self.master_fd, self.slave_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if self.stdin_tty and self.stdin_anterior is not None:
            termios.tcsetattr(sys.stdin, termios.TCSANOW, self.stdin_anterior)
        if os.path.exists(PORT_FILE):
            os.remove(PORT_FILE)
        self.avisar("ESP32 simulado encerrado")


if __name__ == "__main__":
    Esp32Simulado().run()
