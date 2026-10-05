"""Relatórios operacionais da SESA (Saída de Ambulância por Município/Código,
Tempo de Deslocamento), calculados dos dados do vSky."""

import io
from datetime import date, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app
from app.modules.sesa import prazos, relatorios_op as RO, service

client = TestClient(app)
HTML = {"accept": "text/html"}


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def _df(linhas: list[dict]) -> pd.DataFrame:
    base = {"dt_ocorr": pd.NaT, "dia": None, "unidade_curta": None,
            "dt_inicio_deslocamento": pd.NaT, "recurso": None, "codigo_cor": None,
            "cidade": None, "t_deslocamento": None}
    return pd.DataFrame([{**base, **l} for l in linhas])


def _l(dia, unidade, recurso, cor, cidade, desloc_s=None, saiu=True):
    d = datetime(dia.year, dia.month, dia.day, 8)
    return {"dt_ocorr": d, "dia": dia, "unidade_curta": unidade, "recurso": recurso,
            "codigo_cor": cor, "cidade": cidade, "t_deslocamento": desloc_s,
            "dt_inicio_deslocamento": d if saiu else pd.NaT}


AMOSTRA = _df([
    _l(date(2026, 9, 1), "USA 10", "USA", "vermelho", "VITORIA", 600),
    _l(date(2026, 9, 1), "USB 42", "USB", "amarelo", "SERRA", 900),
    _l(date(2026, 9, 2), "USB 44", "USB", "amarelo", "SERRA", 300),
    _l(date(2026, 9, 2), "USB 50", "USB", "verde", "VILA VELHA", 1200),
    _l(date(2026, 9, 3), "USA 20", "USA", "vermelho", "CARIACICA", None),   # sem tempo
    _l(date(2026, 9, 3), "USA 30", "USA", "vermelho", "SERRA", 240, saiu=False),  # não saiu
])


def test_saida_por_municipio():
    d = RO.calcular("saida-municipio", AMOSTRA, date(2026, 9, 1), date(2026, 9, 30))
    assert d["resumo"] == {"total": 5, "usa": 2, "usb": 3}
    linhas = {l["rotulo"]: l for l in d["linhas"]}
    assert linhas["SERRA"]["total"] == 2 and linhas["SERRA"]["usb"] == 2
    assert linhas["VITORIA"]["usa"] == 1
    # ordenado por total desc
    assert d["linhas"][0]["total"] >= d["linhas"][-1]["total"]


def test_saida_por_codigo():
    d = RO.calcular("saida-codigo", AMOSTRA, date(2026, 9, 1), date(2026, 9, 30))
    linhas = {l["rotulo"]: l for l in d["linhas"]}
    assert linhas["Vermelho"]["total"] == 2 and linhas["Amarelo"]["total"] == 2
    assert linhas["Verde"]["total"] == 1
    # ordem: vermelho antes de amarelo antes de verde
    assert [l["rotulo"] for l in d["linhas"]] == ["Vermelho", "Amarelo", "Verde"]


def test_tempo_de_deslocamento():
    d = RO.calcular("tempo-deslocamento", AMOSTRA, date(2026, 9, 1), date(2026, 9, 30))
    linhas = {l["rotulo"]: l for l in d["linhas"]}
    # Serra urgente: só o USB 42 (900s=15min); USA 30 não saiu, USB 44 é amarelo 300s
    assert linhas["Serra"]["n"] == 2 and linhas["Serra"]["media"] == 10.0   # (900+300)/2=600s=10min
    assert linhas["Vitoria"]["media"] == 10.0                               # 600s
    assert linhas["Cariacica"]["n"] == 0 and linhas["Cariacica"]["media"] is None  # sem tempo
    # verde não entra em urgentes
    assert d["geral"]["n"] == 3


def test_xlsx_das_tres():
    from openpyxl import load_workbook

    for tipo in ("saida-municipio", "saida-codigo", "tempo-deslocamento"):
        d = RO.calcular(tipo, AMOSTRA, date(2026, 9, 1), date(2026, 9, 30))
        wb = load_workbook(io.BytesIO(RO.gerar_xlsx(d, "setembro/2026")))
        ws = wb.active
        assert ws.cell(1, 1).value.startswith(RO.TIPOS[tipo]["titulo"])


@pytest.mark.parametrize("tipo, item_chave", [
    ("saida-municipio", "i04"), ("saida-codigo", "i05"), ("tempo-deslocamento", "i06")])
def test_fluxo_gera_e_anexa(tipo, item_chave, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.core.database import SessionLocal

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    comp = "2026-10"
    _login()
    html = client.get(f"/sesa/operacional/{tipo}/{comp}?para=dados_mensais", headers=HTML).text
    assert RO.TIPOS[tipo]["titulo"] in html and "Gerar planilha e anexar" in html

    r = client.post(f"/sesa/operacional/{tipo}/{comp}/gerar", data={"para": "dados_mensais"},
                    follow_redirects=False)
    assert r.headers["location"].startswith(f"/sesa/dados_mensais/{comp}")

    db = SessionLocal()
    try:
        o = service.obrigacao_por_chave(db, 1, "dados_mensais")
        dados = service.detalhe(db, 1, o, prazos.competencia_de(comp), date(2026, 10, 5))
        linha = next(l for l in dados["linhas"] if l["item"].chave == item_chave)
        assert linha["gerador"] == f"/sesa/operacional/{tipo}/{comp}?para=dados_mensais"
        assert linha["anexo"] is not None
        assert linha["anexo"].arquivo.nome_original.endswith("- 09-2026.xlsx")
    finally:
        db.close()
