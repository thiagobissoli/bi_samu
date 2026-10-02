"""Documento "Encaminhamentos do SAMU" a partir do relatório 115 do vReport."""

import io
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app
from app.modules.sesa import encaminhamentos as E

client = TestClient(app)
HTML = {"accept": "text/html"}
PLANILHA = (Path(__file__).parent / "fixtures" / "vsky_relatorio_115.xls").read_bytes()
COMP = "2031-10"


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def _texto_docx(conteudo: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(conteudo))
    partes = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        partes += [c.text for row in t.rows for c in row.cells]
    return "\n".join(partes)


# ------------------------------------------------------------------ funções puras

def test_le_o_relatorio_com_cabecalho_repetido():
    linhas = E.ler_relatorio(PLANILHA)
    hec = next(l for l in linhas if l["hospital"].endswith("- HEC"))
    assert (hec["total"], hec["pre"], hec["inter"], hec["municipio"]) == (197, 61, 136, "VITORIA")
    assert not any(l["hospital"] == "Hospital" for l in linhas)
    assert len({l["hospital"] for l in linhas}) == len(linhas)
    assert all(l["total"] == l["pre"] + l["inter"] for l in linhas
               if l["hospital"] != "PACIENTE NÃO REMOVIDO")


def test_planilha_invalida():
    with pytest.raises(ValueError):
        E.ler_relatorio(b"nao e planilha")


@pytest.mark.parametrize("n, texto", [
    (0, "zero"), (1, "um"), (16, "dezesseis"), (61, "sessenta e um"), (100, "cem"),
    (140, "cento e quarenta"), (201, "duzentos e um"), (1000, "mil"), (1001, "mil e um"),
    (1100, "mil e cem"), (1234, "mil duzentos e trinta e quatro"), (2000, "dois mil"),
])
def test_extenso(n, texto):
    assert E.extenso(n) == texto


def test_nomes_e_siglas():
    assert E.nome_documento("HOSPITAL ESTADUAL CENTRAL - HEC") == ("Hospital Estadual Central", "HEC")
    assert E.nome_documento("HOSPITAL ESTADUAL DE URGENCIA E EMERGENCIA - HEUE") == \
        ("Hospital Estadual de Urgência e Emergência", "HEUE")
    # o que vem depois do hífen nem sempre é sigla
    assert E.nome_documento("HOSPITAL N. SRA DA BOA FAMILIA - ITAGUACU")[1] is None
    assert E.incluir_por_padrao("HOSPITAL EVANGELICO - HEVV")
    assert not E.incluir_por_padrao("PA DA GLORIA")


def test_memoria_de_calculo_como_no_modelo():
    texto = "".join(t for t, *_ in E.memoria("Hospital Estadual Central", "HEC", 201, 61, 140))
    assert "o HEC recebeu 201 (duzentos e um) pacientes pelo SAMU 192." in texto
    assert "140 (cento e quarenta) pacientes foram provenientes de Atendimento secundário" in texto
    assert "e 61 (sessenta e um) provenientes de Atendimento primário (APH)." in texto
    sublinhado = [t for t, negrito, sub in E.memoria("X", "HEC", 201, 61, 140) if sub]
    assert sublinhado == ["HEC recebeu 201 (duzentos e um) pacientes pelo SAMU 192"]
    um = "".join(t for t, *_ in E.memoria("Maternidade Pro Matre", None, 1, 1, 0))
    assert "a Maternidade Pro Matre recebeu 1 (um) paciente pelo" in um


def test_docx_uma_pagina_por_hospital():
    paginas = [{"nome": "Hospital Estadual Central", "sigla": "HEC", "total": 197, "pre": 61,
                "inter": 136},
               {"nome": "Hospital Evangélico", "sigla": "HEVV", "total": 83, "pre": 23,
                "inter": 60}]
    texto = _texto_docx(E.gerar_docx(paginas, "setembro/2026"))
    assert "Hospital Estadual Central (HEC)" in texto and "Hospital Evangélico (HEVV)" in texto
    assert texto.count("Memória de Cálculo:") == 2 and "Relatório do NERUE" in texto
    assert "HEVV recebeu 83 (oitenta e três) pacientes" in texto


def test_periodo_e_o_mes_anterior_ao_envio():
    assert E.periodo_dos_dados(date(2026, 10, 1)) == (date(2026, 9, 1), date(2026, 9, 30))
    assert E.periodo_dos_dados(date(2027, 1, 1)) == (date(2026, 12, 1), date(2026, 12, 31))


# ------------------------------------------------------------------ fluxo

@pytest.fixture()
def upload_temporario(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    return tmp_path


def test_fluxo_planilha_ate_o_anexo(upload_temporario):
    from app.core.database import SessionLocal
    from app.modules.sesa import prazos, service

    _login()
    pagina = client.get(f"/sesa/encaminhamentos/{COMP}", headers=HTML).text
    assert "01/09/2031" in pagina and "30/09/2031" in pagina and "METROPOLITANO 1" in pagina

    r = client.post(f"/sesa/encaminhamentos/{COMP}/planilha",
                    files={"arquivo": ("Report.xls", PLANILHA, "application/vnd.ms-excel")},
                    follow_redirects=False)
    destino = r.headers["location"]
    assert "planilha=" in destino
    planilha = int(destino.split("planilha=")[1])
    html = client.get(destino, headers=HTML).text
    assert "Hospital Estadual Central" in html and "PA DA GLORIA" in html

    # monta o formulário: só HEC e HEVV marcados, com HEVV renomeado
    db = SessionLocal()
    try:
        cadastro = service.hospitais(db, 1)
    finally:
        db.close()
    form = {"planilha": str(planilha)}
    for nome_vsky, h in cadastro.items():
        form[f"hosp_{h.id}_nome"] = h.nome_documento
        form[f"hosp_{h.id}_sigla"] = h.sigla or ""
        if nome_vsky.endswith("- HEC") or nome_vsky.endswith("- HEVV"):
            form[f"hosp_{h.id}_incluir"] = "1"
        if nome_vsky.endswith("- HEVV"):
            form[f"hosp_{h.id}_nome"] = "Hospital Evangélico de Vila Velha"
    r = client.post(f"/sesa/encaminhamentos/{COMP}/gerar", data=form, follow_redirects=False)
    assert r.headers["location"].startswith(f"/sesa/adversidades/{COMP}")

    db = SessionLocal()
    try:
        o = service.obrigacao_por_chave(db, 1, "adversidades")
        dados = service.detalhe(db, 1, o, prazos.competencia_de(COMP), date(2031, 10, 1))
        linha = next(l for l in dados["linhas"] if l["item"].chave == "i01")
        assert linha["gerador"] == f"/sesa/encaminhamentos/{COMP}?para=adversidades"
        anexo = linha["anexo"]
        assert anexo.arquivo.nome_original == "Encaminhamentos do SAMU - 09-2031.docx"
        from app.core.storage import absolute_path
        texto = _texto_docx(absolute_path(anexo.arquivo).read_bytes())
        assert "Hospital Evangélico de Vila Velha (HEVV)" in texto
        assert "HEC recebeu 197 (cento e noventa e sete) pacientes" in texto
        assert texto.count("Memória de Cálculo:") == 2
        # a seleção ficou salva para o próximo mês
        marcados = {h.nome_vsky for h in service.hospitais(db, 1).values() if h.incluir}
        assert marcados == {n for n in cadastro if n.endswith(("- HEC", "- HEVV"))}
    finally:
        db.close()

    envio = client.get(f"/sesa/adversidades/{COMP}", headers=HTML).text
    assert "Gerar a partir do vSky" in envio


def test_gerar_sem_planilha_valida_volta_com_erro():
    _login()
    r = client.post(f"/sesa/encaminhamentos/{COMP}/gerar", data={"planilha": "999999"},
                    follow_redirects=False)
    assert "erro=" in r.headers["location"]
