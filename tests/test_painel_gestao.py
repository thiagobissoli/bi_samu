"""Testes do módulo Painel de Gestão."""

from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app

client = TestClient(app)


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def test_requer_login():
    resp = client.get("/painel_gestao/", headers={"accept": "text/html"},
                      follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_pagina_renderiza():
    _login()
    resp = client.get("/painel_gestao/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "Painel de Gestão" in resp.text
    # formato próprio: seções coloridas, sem a barra de filtros dos dashboards
    assert 'name="transporte"' not in resp.text
    for secao in ["Tempo Resposta", "Assertividade ISCMV",
                  "Transferência Inter-hospitalar", "Plantão", "Desperdício"]:
        assert secao in resp.text, secao


def test_api_payload():
    _login()
    corpo = client.get("/painel_gestao/api").json()
    assert corpo["success"] is True
    dados = corpo["data"]
    ids = [s["id"] for s in dados["secoes"]]
    assert ids == ["tr", "assertividade", "transferencia", "plantao",
                   "desperdicio"]
    assert dados["semana"]
    # período (segunda a domingo) da última semana completa
    import re
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4} a \d{2}/\d{2}/\d{4}",
                        dados["semana_periodo"])
    # a semana escolhida tem dados em todos os 7 dias (ou ao menos 6)
    from app.modules.indicadores import nucleo
    df = nucleo.carregar(1)
    dias = df[df["semana_iso"] == dados["semana"]]["dia"].nunique()
    assert dias >= 6
    # TR: 3 blocos (Convênio, USA, USB), cada um com UM KPI da última
    # semana + gráfico com as linhas Geral/Diurno/Noturno
    tr = dados["secoes"][0]
    assert len(tr["blocos"]) == 3
    for bloco in tr["blocos"]:
        assert [k["label"] for k in bloco["kpis"]] == ["Última semana"]
        assert bloco["chart"]["tipo"] == "line"
        assert [ds["label"] for ds in bloco["chart"]["datasets"]] == \
            ["Geral", "Diurno", "Noturno"]
    assert len(dados["charts_flat"]) == sum(len(s["blocos"])
                                            for s in dados["secoes"])


def test_menu_e_permissao():
    _login()
    home = client.get("/", headers={"accept": "text/html"})
    assert "Painel de Gestão" in home.text


def test_relatorio_pdf():
    """Botão do painel: PDF gerado no servidor, com capa e seções."""
    import io

    from pypdf import PdfReader

    _login()
    painel = client.get("/painel_gestao/", headers={"accept": "text/html"})
    assert "Relatório de Gestão (PDF)" in painel.text

    resp = client.get("/painel_gestao/relatorio.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    leitor = PdfReader(io.BytesIO(resp.content))
    # capa + uma página por seção (no mínimo)
    assert len(leitor.pages) >= 2
    capa = leitor.pages[0].extract_text() or ""
    assert "Relatório de Gestão" in capa
    assert "Última semana completa" in capa
    # rodapé numerado em todas as páginas
    ultima = leitor.pages[-1].extract_text() or ""
    assert f"Pág. {len(leitor.pages)}/{len(leitor.pages)}" in " ".join(
        ultima.split())


def test_config_envio_automatico_valida():
    """Configuração do envio: destinatários válidos e ativação consistente."""
    _login()
    pagina = client.get("/painel_gestao/config", headers={"accept": "text/html"})
    assert pagina.status_code == 200

    base = {"email_modo": "semanal", "email_dia": "mon", "email_hora": "07:00"}
    ruim = client.post("/painel_gestao/config",
                       data={**base, "email_ativo": "1",
                             "destinatarios": "sem-arroba"})
    assert "E-mail inválido" in ruim.text

    vazio = client.post("/painel_gestao/config",
                        data={**base, "email_ativo": "1", "destinatarios": ""})
    assert "ao menos um destinatário" in vazio.text

    ok = client.post("/painel_gestao/config",
                     data={**base, "destinatarios": "gestor@exemplo.com"},
                     follow_redirects=True)
    assert ok.status_code == 200
    assert "gestor@exemplo.com" in ok.text


def test_envio_relatorio_por_email(monkeypatch):
    """O envio automático anexa o MESMO PDF do botão, via SMTP."""
    import smtplib

    from app.core.config_service import set_config
    from app.core.database import SessionLocal
    from app.modules.painel_gestao import scheduler

    capturadas = []

    class SMTPFalso:
        def __init__(self, host, port, timeout=15):
            capturadas.append({"host": host, "port": port})

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, user, senha):
            pass

        def send_message(self, msg):
            capturadas[-1]["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)

    db = SessionLocal()
    try:
        set_config(db, "smtp_host", "smtp.exemplo.com", empresa_id=1)
        set_config(db, "smtp_from", "samu@exemplo.com", empresa_id=1)
        set_config(db, "relatorio_email_destinatarios",
                   "a@exemplo.com, b@exemplo.com", empresa_id=1)
    finally:
        db.close()

    status = scheduler.enviar_relatorio(1)
    assert status.startswith("sucesso"), status
    assert len(capturadas) == 2                      # um envio por destinatário
    msg = capturadas[0]["msg"]
    assert "Relatório de Gestão" in msg["Subject"]
    anexos = [p for p in msg.iter_attachments()]
    assert len(anexos) == 1
    assert anexos[0].get_content_type() == "application/pdf"
    assert anexos[0].get_filename().endswith(".pdf")
    assert anexos[0].get_payload(decode=True).startswith(b"%PDF")

    # limpa o SMTP para não afetar outros testes
    db = SessionLocal()
    try:
        set_config(db, "smtp_host", None, empresa_id=1)
        set_config(db, "relatorio_email_destinatarios", None, empresa_id=1)
    finally:
        db.close()
