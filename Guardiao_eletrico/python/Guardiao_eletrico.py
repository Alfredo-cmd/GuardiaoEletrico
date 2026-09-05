import cv2
import mediapipe as mp
import serial
from datetime import datetime
from pathlib import Path

# ================= CONFIGURAÇÕES =================

SERIAL_URL = "rfc2217://localhost:4000"
BAUDRATE = 9600
CAMERA = 1

# ================= SERIAL =================

ser = serial.serial_for_url(SERIAL_URL, baudrate=BAUDRATE)

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

detector = mp.tasks.vision.HandLandmarker.create_from_options(options)

# ================= CÂMERA =================

cap = cv2.VideoCapture(CAMERA, cv2.CAP_DSHOW)

if not cap.isOpened():
    raise RuntimeError("Não foi possível abrir a câmera")
cv2.namedWindow("Guardiao Eletrico", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Guardiao Eletrico", 1000, 700)

# ================= LOOP =================

estado_anterior = None

try:
    while True:
        success, img = cap.read()

        if not success:
            break

        # OpenCV: BGR -> MediaPipe: RGB
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=img_rgb
        )

        results = detector.detect(mp_image)

        # 1 = mão detectada | 0 = nenhuma mão
        estado = b"1" if results.hand_landmarks else b"0"

        # Envia apenas se o estado mudou
        if estado != estado_anterior:
            ser.write(estado)
            estado_anterior = estado

            hora_atual = datetime.now().strftime("%H:%M:%S")
            ser.write(f"H:{hora_atual}\n".encode('utf-8'))

            print(
                "MÃO DETECTADA"
                if estado == b"1"
                else "Nenhuma mão"
            )

        # Desenha os pontos da mão
        if results.hand_landmarks:
            altura, largura = img.shape[:2]

            for landmark in results.hand_landmarks[0]:
                x = int(landmark.x * largura)
                y = int(landmark.y * altura)

                cv2.circle(img, (x, y), 5, (0, 255, 0), -1)

        cv2.imshow("Guardiao Eletrico", img)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    cap.release()
    cv2.destroyAllWindows()
    detector.close()
    ser.close()