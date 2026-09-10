import cv2
import mediapipe as mp
import customtkinter
import serial
from datetime import datetime
from pathlib import Path

# ================= CONFIGURAÇÕES =================

SERIAL_URL = "rfc2217://localhost:4000"
BAUDRATE = 9600
CAMERA = 0

# ================= SERIAL =================

ser = serial.serial_for_url(SERIAL_URL, baudrate=BAUDRATE)


class App(customtkinter.CTk):

    def __init__(self):
        super().__init__()

        self.title("Guardião Elétrico")
        self.geometry("400x150")

        self.grid_columnconfigure(0, weight=1)

        button_init = customtkinter.CTkButton(
            self,
            text="Iniciar Vigilância",
            command=self.button_init_callback
        )

        button_init.grid(
            row=0,
            column=0,
            padx=20,
            pady=20,
            sticky="ew",
            columnspan=2
        )

        button_end = customtkinter.CTkButton(
            self,
            text="Desligar Vigilância",
            command=self.button_end_callback
        )

        button_end.grid(
            row=1,
            column=0,
            padx=20,
            pady=20,
            sticky="ew",
            columnspan=2
        )

    # ================= BOTÃO INICIAR =================

    def button_init_callback(self):

        print("GUARDIÃO ELÉTRICO INICIADO")

        # ================= MEDIAPIPE =================

        MODEL_PATH = Path(__file__).with_name("hand_landmarker.task")

        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(MODEL_PATH)
            ),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.3,
            min_hand_presence_confidence=0.3
        )

        self.detector = mp.tasks.vision.HandLandmarker.create_from_options(
            options
        )

        # ================= CÂMERA =================

        self.cap = cv2.VideoCapture(CAMERA)

        if not self.cap.isOpened():

            self.detector.close()

            raise RuntimeError(
                "Não foi possível abrir a câmera"
            )

        cv2.namedWindow(
            "Guardiao Eletrico",
            cv2.WINDOW_NORMAL
        )

        cv2.resizeWindow(
            "Guardiao Eletrico",
            1000,
            700
        )

        # ================= ESTADO =================

        self.estado_anterior = None

        # Começa a processar os frames

        self.processar_frame()

    # ================= PROCESSAMENTO =================

    def processar_frame(self):

        success, img = self.cap.read()

        if not success:

            return

        # OpenCV: BGR -> MediaPipe: RGB

        img_rgb = cv2.cvtColor(
            img,
            cv2.COLOR_BGR2RGB
        )

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=img_rgb
        )

        results = self.detector.detect(mp_image)

        # 1 = mão detectada | 0 = nenhuma mão

        estado = (
            b"1"
            if results.hand_landmarks
            else b"0"
        )

        # Envia apenas se o estado mudou

        if estado != self.estado_anterior:

            ser.write(estado)

            self.estado_anterior = estado

            hora_atual = datetime.now().strftime(
                "%H:%M:%S"
            )

            ser.write(
                f"H:{hora_atual}\n".encode("utf-8")
            )

            print(
                "MÃO DETECTADA"
                if estado == b"1"
                else "Nenhuma mão"
            )

        # ================= DESENHA A MÃO =================

        if results.hand_landmarks:

            altura, largura = img.shape[:2]

            for landmark in results.hand_landmarks[0]:

                x = int(landmark.x * largura)
                y = int(landmark.y * altura)

                cv2.circle(
                    img,
                    (x, y),
                    5,
                    (0, 255, 0),
                    -1
                )

        cv2.imshow(
            "Guardiao Eletrico",
            img
        )

        cv2.waitKey(1)

        # Processa o próximo frame

        self.after(
            10,
            self.processar_frame
        )

    # ================= BOTÃO DESLIGAR =================

    def button_end_callback(self):

        print("GUARDIÃO ELÉTRICO DESLIGADO")

        if hasattr(self, "cap"):
            self.cap.release()

        cv2.destroyAllWindows()

        if hasattr(self, "detector"):
            self.detector.close()

        ser.close()

        self.destroy()


# ================= INICIA O APP =================

app = App()
app.mainloop()
