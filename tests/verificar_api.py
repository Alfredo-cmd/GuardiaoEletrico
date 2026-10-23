#!/usr/bin/env python3
"""Teste da API do Guardiao Eletrico. Nao precisa de dependencias externas.

    python tests/verificar_api.py

Precisa da API no ar:

    cd backend && nix-shell --run 'uvicorn app.main:app --host 127.0.0.1 --port 8000'

Usa um device_id proprio e apaga tudo no final, entao nao suja o banco.
Saida: 0 = passou, 1 = falha, 2 = pre-requisito faltando.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API_URL = os.getenv("GUARDIAO_API_URL", "http://127.0.0.1:8000")
DEVICE = "teste-verificacao"


class Falha(Exception):
    pass


def chamar(metodo, caminho, corpo=None, esperado=200):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    request = urllib.request.Request(
        f"{API_URL}{caminho}",
        data=dados,
        headers={"Content-Type": "application/json"} if dados else {},
        method=metodo,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            status, texto = r.status, r.read()
    except urllib.error.HTTPError as exc:
        status, texto = exc.code, exc.read()

    if status != esperado:
        raise Falha(
            f"{metodo} {caminho} -> {status} (esperava {esperado}): {texto[:200].decode(errors='replace')}"
        )
    return json.loads(texto) if texto else None


def q(valor: str) -> str:
    return urllib.parse.quote(valor, safe="")


def checar(condicao, mensagem):
    if not condicao:
        raise Falha(mensagem)
    print(f"    ok: {mensagem}")


def evento(tipo, detalhe, vibra, mao, status="info"):
    return {
        "device_id": DEVICE,
        "event_type": tipo,
        "detail": detalhe,
        "vibration_detected": vibra,
        "hand_detected": mao,
        "status": status,
    }


def testar():
    print("\n1) criacao de evento")
    invasao = chamar(
        "POST",
        "/api/v1/events",
        evento("possible_intrusion", "vibracao_com_mao", True, True, "needs_review"),
        201,
    )
    checar(invasao["id"] > 0, f"invasao criada (id={invasao['id']})")
    checar(invasao["detail"] == "vibracao_com_mao", "detail preservado")
    checar(invasao["vibration_detected"] and invasao["hand_detected"], "flags gravadas")

    legado = chamar(
        "POST",
        "/api/v1/events",
        {
            "device_id": DEVICE,
            "vibration_detected": False,
            "hand_detected": True,
        },
        201,
    )
    checar(legado["event_type"] == "possible_intrusion", "payload antigo ainda aceito")

    chamar(
        "POST",
        "/api/v1/events",
        evento("sensor_change", "hand_detected", False, True),
        201,
    )
    chamar(
        "POST",
        "/api/v1/events",
        evento("sensor_change", "hand_cleared", False, False),
        201,
    )

    print("\n2) validacao")
    chamar(
        "POST",
        "/api/v1/events",
        evento("evento_invalido", None, False, False),
        422,
    )
    checar(True, "event_type invalido devolvido 422")
    chamar("POST", "/api/v1/events", evento("sensor_change", "x", False, False, "status_burro"), 422)
    checar(True, "status invalido devolvido 422")
    chamar("GET", "/api/v1/events/99999999", esperado=404)
    checar(True, "evento inexistente devolve 404")

    print("\n3) listagem e paginacao")
    pagina = chamar("GET", "/api/v1/events?device_id=teste-verificacao&limit=2")
    checar(pagina["count"] == 2, f"limit respeitado ({pagina['count']})")
    checar(pagina["has_more"] is True, "has_more sinalizado")
    checar(pagina["next_before_id"] == pagina["items"][-1]["id"], "next_before_id correto")

    ids = [item["id"] for item in pagina["items"]]
    checar(ids == sorted(ids, reverse=True), "ordem mais recente primeiro")

    proxima = chamar(
        "GET", f"/api/v1/events?device_id={DEVICE}&limit=2&before_id={pagina['next_before_id']}"
    )
    checar(
        all(i < pagina["next_before_id"] for i in [x["id"] for x in proxima["items"]]),
        "cursor before_id nao repete itens",
    )

    intrusoes = chamar(
        "GET", f"/api/v1/events?device_id={DEVICE}&event_type=possible_intrusion"
    )
    checar(
        all(i["event_type"] == "possible_intrusion" for i in intrusoes["items"]),
        "filtro event_type funciona",
    )
    checar(intrusoes["count"] == 2, f"filtro event_type ({intrusoes['count']} de 4)")

    por_status = chamar("GET", f"/api/v1/events?device_id={DEVICE}&status=info")
    checar(por_status["count"] == 2, f"filtro status ({por_status['count']})")

    inexistente = chamar("GET", "/api/v1/events?device_id=nao-existe")
    checar(inexistente["count"] == 0, "device_id sem eventos devolve lista vazia")

    passado = datetime.now(timezone.utc) - timedelta(minutes=5)
    futuro = datetime.now(timezone.utc) + timedelta(hours=1)
    janela = chamar(
        "GET", f"/api/v1/events?device_id={DEVICE}&since={q(passado.isoformat())}&until={q(futuro.isoformat())}"
    )
    checar(janela["count"] == 4, f"filtro since/until ({janela['count']})")

    vazia = chamar(
        "GET", f"/api/v1/events?device_id={DEVICE}&since={q(futuro.isoformat())}"
    )
    checar(vazia["count"] == 0, "since no futuro nao devolve nada")

    print("\n4) revisao de evento")
    revisado = chamar("PATCH", f"/api/v1/events/{invasao['id']}", {"status": "confirmed"})
    checar(revisado["status"] == "confirmed", "PATCH marca como confirmed")
    chamar("PATCH", f"/api/v1/events/{invasao['id']}", {"status": "nope"}, 422)
    checar(True, "PATCH com status invalido devolvido 422")
    chamar("PATCH", "/api/v1/events/99999999", {"status": "confirmed"}, 404)
    checar(True, "PATCH em evento inexistente devolve 404")

    print("\n5) dispositivos e estado")
    dispositivos = chamar("GET", "/api/v1/devices")
    checar(
        any(d["device_id"] == DEVICE for d in dispositivos),
        "device aparece na lista",
    )
    meu = next(d for d in dispositivos if d["device_id"] == DEVICE)
    checar(meu["hand_detected"] is False, "estado mais recente vem do ultimo evento")
    checar(meu["last_event_type"] == "sensor_change", "ultimo tipo de evento correto")

    estado = chamar("GET", f"/api/v1/devices/{DEVICE}/state")
    checar(estado["events_24h"] == 4, f"contagem de 24h ({estado['events_24h']})")
    checar(estado["intrusions_24h"] == 2, f"intrusoes de 24h ({estado['intrusions_24h']})")
    checar(estado["last_intrusion_at"] is not None, "ultima invasao informada")
    chamar("GET", "/api/v1/devices/nao-existe/state", esperado=404)
    checar(True, "estado de dispositivo sem eventos devolve 404")

    print("\n6) resumo")
    resumo = chamar("GET", "/api/v1/summary?hours=24")
    checar(resumo["total"] >= 4, f"total na janela ({resumo['total']})")
    checar(resumo["by_type"].get("possible_intrusion", 0) >= 2, "contagem por tipo")
    checar(resumo["by_status"].get("confirmed", 0) >= 1, "contagem por status")
    checar(resumo["last_intrusion_at"] is not None, "ultima invasao no resumo")
    chamar("GET", "/api/v1/summary?hours=99999", esperado=422)
    checar(True, "janela absurda devolvida 422")

    print("\n7) limpeza")
    apagados = chamar("DELETE", f"/api/v1/events?device_id={DEVICE}")
    checar(apagados["deleted"] == 4, f"apagou {apagados['deleted']} eventos de teste")
    vazio = chamar("GET", f"/api/v1/events?device_id={DEVICE}")
    checar(vazio["count"] == 0, "banco sem residuos do teste")


def main():
    print("=" * 68)
    print("Guardiao Eletrico - verificacao da API")
    print("=" * 68)
    try:
        health = chamar("GET", "/api/v1/health")
        print(f"API: {API_URL} (version {health.get('version')})")
    except (urllib.error.URLError, TimeoutError, OSError, Falha):
        print(f"\nAPI FORA DO AR em {API_URL}.")
        print("Suba com:")
        print("  cd backend")
        print("  nix-shell --run 'uvicorn app.main:app --host 127.0.0.1 --port 8000'")
        return 2

    try:
        testar()
    except Falha as exc:
        print(f"\nFALHOU: {exc}")
        return 1
    finally:
        try:
            chamar("DELETE", f"/api/v1/events?device_id={DEVICE}")
        except Exception:
            pass

    print("\n" + "=" * 68)
    print("TUDO OK")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())