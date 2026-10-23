import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import cv2
import mediapipe as mp
import customtkinter
import serial

# ================= CONFIGURAÇÕES =================

SERIAL_URL = os.getenv("GUARDIAO_SERIAL_URL", "rfc2217://localhost:4000")
BAUDRATE = int(os.getenv("GUARDIAO_BAUDRATE", "115200"))
CAMERA = int(os.getenv("GUARDIAO_CAMERA", "0"))
API_URL = os.getenv("GUARDIAO_API_URL", "http://127.0.0.1:8000")
DEVICE_ID = os.getenv("GUARDIAO_DEVICE_ID", "guardiao-001")

# ================= SERIAL =================


class GuardiaoApp(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        self.title("Guardião Elétrico")
        self.geometry("400x220")
        self.protocol("WM_DELETE_WINDOW", self.button_end_callback)

        self.grid_columnconfigure(0, weight=1)

        self.status_label = customtkinter.CTkLabel(
            self,
            text="Sistema parado",
            font=customtkinter.CTkFont(size=16, weight="bold"),
        )
        self.status_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")

        self.button_init = customtkinter.CTkButton(
            self,
            text="Iniciar Vigilância",
            command=self.button_init_callback,
        )
        self.button_init.grid(row=1, column=0, padx=20, pady=8, sticky="ew")

        self.button_end = customtkinter.CTkButton(
            self,
            text="Desligar Vigilância",
            command=self.button_end_callback,
            state="disabled",
        )
        self.button_end.grid(row=2, column=0, padx=20, pady=8, sticky="ew")

        self.ser = None
        self.running = False
        self.serial_thread = None
        self.detector = None
        self.cap = None
        self.estado_anterior = None

    # ================= API =================

    def enviar_evento_api(self, vibration_detected: bool, hand_detected: bool) -> None:
        payload = {
            "device_id": DEVICE_ID,
            "event_type": "possible_intrusion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vibration_detected": vibration_detected,
            "hand_detected": hand_detected,
            "status": "needs_review",
        }

        request = urllib.request.Request(
            f"{API_URL.rstrip('/')}/api/v1/events",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                if response.status == 201:
                    print("Evento enviado para a API")
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"API indisponível: {exc}")
        except Exception as exc:
            print(f"Erro ao enviar evento para a API: {exc}")

    # ================= SERIAL RX =================

    def iniciar_leitor_serial(self) -> None:
        self.serial_thread = threading.Thread(
            target=self.ler_serial,
            name="guardiao-serial",
            daemon=True,
        )
        self.serial_thread.start()

    def ler_serial(self) -> None:
        while self.running and self.ser is not None:
            try:
                linha = self.ser.readline().decode("utf-8", errors="replace").strip()
            except (serial.SerialException, OSError) as exc:
                if self.running:
                    print(f"Erro na leitura serial: {exc}")
                break

            if not linha:
                continue

            print(f"ESP32: {linha}")

            if linha.startswith("EVENT:"):
                self.enviar_evento_api(
                    vibration_detected=True,
                    hand_detected=True,
                )
                self.after(0, self.atualizar_status, "⚠ Evento suspeito registrado")

    # ================= BOTÃO INICIAR =================

    def button_init_callback(self):
        if self.running:
            return

        print("GUARDIÃO ELÉTRICO INICIADO")

        model_path = Path(__file__).with_name("hand_landmarker.task")
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.3,
            min_hand_presence_confidence=0.3,
        )

        self.detector = mp.tasks.vision.HandLandmarker.create_from_options(options)
        self.cap = cv2.VideoCapture(CAMERA)

        if not self.cap.isOpened():
            self.detector.close()
            self.detector = None
            self.cap = None
            raise RuntimeError("Não foi possível abrir a câmera")

        try:
            self.ser = serial.serial_for_url(SERIAL_URL, baudrate=BAUDRATE, timeout=0.5)
        except (serial.SerialException, ValueError) as exc:
            self.cap.release()
            self.cap = None
            self.detector.close()
            self.detector = None
            raise RuntimeError(f"Não foi possível abrir a serial: {exc}") from exc

        cv2.namedWindow("Guardiao Eletrico", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Guardiao Eletrico", 1000, 700)

        self.estado_anterior = None
        self.running = True
        self.button_init.configure(state="disabled")
        self.button_end.configure(state="normal")
        self.atualizar_status("Vigilância ativa")
        self.iniciar_leitor_serial()
        self.processar_frame()

    # ================= PROCESSAMENTO =================

    def processar_frame(self):
        if not self.running or self.cap is None or self.detector is None:
            return

        success, img = self.cap.read()
        if not success:
            self.after(30, self.processar_frame)
            return

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
        results = self.detector.detect(mp_image)

        estado = b"M:1\n" if results.hand_landmarks else b"M:0\n"

        if estado != self.estado_anterior and self.ser is not None:
            try:
                self.ser.write(estado)
                hora_atual = datetime.now().strftime("%H:%M:%S")
                self.ser.write(f"H:{hora_atual}\n".encode("utf-8"))
                self.estado_anterior = estado

                print("MÃO DETECTADA" if estado == b"M:1\n" else "Nenhuma mão")
            except (serial.SerialException, OSError) as exc:
                print(f"Erro ao enviar pela serial: {exc}")

        if results.hand_landmarks:
            altura, largura = img.shape[:2]
            for hand in results.hand_landmarks:
                for landmark in hand:
                    x = int(landmark.x * largura)
                    y = int(landmark.y * altura)
                    cv2.circle(img, (x, y), 5, (0, 255, 0), -1)

        cv2.imshow("Guardiao Eletrico", img)
        cv2.waitKey(1)
        self.after(10, self.processar_frame)

    # ================= UI =================

    def atualizar_status(self, texto: str) -> None:
        self.status_label.configure(text=texto)

    # ================= BOTÃO DESLIGAR =================

    def button_end_callback(self):
        if not self.running:
            self.destroy()
            return

        print("GUARDIÃO ELÉTRICO DESLIGADO")
        self.running = False

        if self.cap is not None:
            self.cap.release()
            self.cap = None

        cv2.destroyAllWindows()

        if self.detector is not None:
            self.detector.close()
            self.detector = None

        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

        self.button_init.configure(state="normal")
        self.button_end.configure(state="disabled")
        self.atualizar_status("Sistema parado")
        self.destroy()


# ================= INICIA O APP =================

if __name__ == "__main__":
    app = GuardiaoApp()
    app.mainloop()
