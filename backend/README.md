# Backend do Guardião Elétrico

API FastAPI + SQLite para registrar ocorrências detectadas pelo sistema.

## Executar no NixOS

```bash
cd ~/Documents/Guardiao_eletrico/GuardiaoEletrico/backend
nix-shell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Abra:

```text
http://127.0.0.1:8000/docs
```

## Integração

O programa Python envia automaticamente um `POST /api/v1/events` quando o ESP32 informa um evento `EVENT:...`.

Variáveis opcionais:

```bash
export GUARDIAO_API_URL=http://127.0.0.1:8000
export GUARDIAO_SERIAL_URL=rfc2217://localhost:4000
export GUARDIAO_BAUDRATE=115200
export GUARDIAO_CAMERA=0
export GUARDIAO_DEVICE_ID=guardiao-001
```

O banco `guardiao.db` é criado automaticamente na pasta `backend/`.

Ainda não exponha essa API diretamente à internet. Autenticação, HTTPS e hospedagem segura entram na próxima etapa.
