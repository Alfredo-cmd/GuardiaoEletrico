# Guardião Elétrico

Sistema de detecção de possíveis furtos de fios de cobre com ESP32, câmera/MediaPipe e backend FastAPI.

## Requisitos no Windows

Instale o Python 3.11 ou superior e marque a opção **Add Python to PATH** durante a instalação.

### Programa Python (câmera + MediaPipe)

No **PowerShell**:

```powershell
cd Guardiao_eletrico\python
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python Guardiao_eletrico.py
```

Se o PowerShell bloquear a ativação do ambiente virtual, execute uma vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

No **Prompt de Comando (CMD)**:

```bat
cd Guardiao_eletrico\python
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python Guardiao_eletrico.py
```

### Backend (FastAPI + SQLite)

No **PowerShell**:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

No **Prompt de Comando (CMD)**:

```bat
cd backend
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

A documentação da API fica em `http://127.0.0.1:8000/docs`.

O modelo `hand_landmarker.task` já está incluído em `Guardiao_eletrico/python/`.
