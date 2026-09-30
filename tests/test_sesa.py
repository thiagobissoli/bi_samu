"""Envios à SESA: prazos em dias úteis, leitura das certidões e o fluxo mensal."""

import io
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app
from app.modules.sesa import extrator, prazos, service

client = TestClient(app)
HTML = {"accept": "text/html"}
CNPJ = "28.141.190/0011-58"
COMP = "2031-03"                      # competência longe dos dados reais


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def _pdf(texto: str) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    y = 800
    for linha in texto.split("\n"):
        c.drawString(40, y, linha)
        y -= 16
    c.save()
    return buffer.getvalue()


ESTADUAL = ("Certidao Negativa de Debitos para com a Fazenda Publica Estadual - MOD. 2\n"
            "Certidão Nº 20310001437974\n"
            "Identificação do Requerente: CNPJ Nº 28.141.190/0011-58\n"
            "Certidão emitida em 27/02/2031, válida até 28/05/2031.")


# ------------------------------------------------------------------ prazos

def test_pascoa_e_feriados_moveis():
    assert prazos.pascoa(2026) == date(2026, 4, 5)
    f = prazos.feriados(2026)
    assert date(2026, 2, 17) in f            # Carnaval
    assert date(2026, 4, 3) in f             # Paixão
    assert date(2026, 4, 13) in f            # N. Sra. da Penha (ES)
    assert date(2026, 6, 4) in f             # Corpus Christi


def test_dias_uteis():
    assert prazos.enesimo_dia_util(2026, 10, 1) == date(2026, 10, 1)
    assert prazos.enesimo_dia_util(2026, 10, 5) == date(2026, 10, 7)
    assert prazos.enesimo_dia_util(2026, 11, 1) == date(2026, 11, 3)    # 2/11 feriado
    assert prazos.enesimo_dia_util(2026, 10, 1, ["01/10"]) == date(2026, 10, 2)


def test_prazo_corrido_passa_para_o_proximo_dia_util():
    # 10/10/2026 é sábado; 12/10 é feriado → 13/10
    assert prazos.prazo(date(2026, 10, 1), "corrido", 10) == date(2026, 10, 13)


def test_competencia_e_meses():
    assert prazos.competencia_de("2026-10") == date(2026, 10, 1)
    assert prazos.competencia_de("lixo", date(2026, 9, 29)) == date(2026, 9, 1)
    assert prazos.somar_meses(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert prazos.aplica("1,4,7,10", date(2026, 10, 1))
    assert not prazos.aplica("1,4,7,10", date(2026, 11, 1))
    assert prazos.aplica(None, date(2026, 11, 1))


# ------------------------------------------------------------------ leitura

@pytest.mark.parametrize("texto, numero, emissao, validade, resultado", [
    (ESTADUAL, "20310001437974", date(2031, 2, 27), date(2031, 5, 28), "Negativa"),
    ("Certidão Negativa de Débitos\nNº da Certidão: 12277624/2026 Data Geração:29/09/2026 "
     "Data Validade:29/11/2026\nCERTIFICAMOS, que não constam débitos. CNPJ / CPF "
     "28.141.190/0011-58", "12277624/2026", date(2026, 9, 29), date(2026, 11, 29), "Negativa"),
    ("Certificado de Regularidade do FGTS - CRF Inscrição: 28.141.190/0011-58 Validade: "
     "08/09/2026 a 07/10/2026 Certificação Número: 2026090816192394888908 Informação "
     "obtida em 29/09/2026 15:12:45", "2026090816192394888908", date(2026, 9, 29),
     date(2026, 10, 7), "Regular"),
    ("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS CNPJ: 28.141.190/0001-77 Certidão nº: "
     "51234567/2026 Expedição: 29/09/2026, às 15:10:22 Validade: 28/03/2027 - 180 dias",
     "51234567/2026", date(2026, 9, 29), date(2027, 3, 28), "Negativa"),
    ("CERTIDÃO POSITIVA COM EFEITOS DE NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS "
     "CNPJ: 28.141.190 Emitida às 15:10:00 do dia 29/09/2026. Válida até 28/03/2027. "
     "Código de controle da certidão: 1A2B.3C4D.5E6F.7G8H", "1A2B.3C4D.5E6F.7G8H",
     date(2026, 9, 29), date(2027, 3, 28), "Positiva com efeitos de negativa"),
])
def test_le_as_cinco_certidoes(texto, numero, emissao, validade, resultado):
    lido = extrator.extrair(texto, CNPJ)
    assert (lido["numero"], lido["emitida_em"], lido["valida_ate"], lido["resultado"]) == \
        (numero, emissao, validade, resultado)
    assert lido["cnpj_confere"] is True


def test_cnpj_de_outra_empresa_e_pdf_sem_texto():
    assert extrator.confere_cnpj("CNPJ 11.222.333/0001-81", CNPJ) is False
    assert extrator.extrair("", CNPJ)["lido"] is False
    assert extrator.extrair_texto(b"nao e pdf") == ""


# ------------------------------------------------------------------ fluxo

@pytest.fixture()
def upload_temporario(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    return tmp_path


def test_matriz_e_catalogo():
    _login()
    html = client.get("/sesa/?ano=2031", headers=HTML).text
    assert "Certidões" in html and "Relatório BPA" in html and "FES 007" in html
    r = client.get(f"/sesa/certidoes?competencia={COMP}", follow_redirects=False)
    assert r.headers["location"] == f"/sesa/certidoes/{COMP}"
    pagina = client.get(f"/sesa/certidoes/{COMP}", headers=HTML).text
    for nome in ("Estadual", "União", "FGTS", "Prefeitura da Serra", "Trabalhista"):
        assert nome in pagina
    assert CNPJ in pagina and "28141190001158" in pagina


def _item(chave_item):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.modules.sesa.models import SesaItem, SesaObrigacao

    db = SessionLocal()
    try:
        o = db.scalar(select(SesaObrigacao).where(SesaObrigacao.chave == "certidoes"))
        return db.scalar(select(SesaItem).where(SesaItem.obrigacao_id == o.id,
                                                SesaItem.chave == chave_item)).id
    finally:
        db.close()


def _detalhe(comp):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        o = service.obrigacao_por_chave(db, 1, "certidoes")
        return service.detalhe(db, 1, o, prazos.competencia_de(comp), date(2031, 2, 27))
    finally:
        db.close()


def test_fluxo_da_certidao(upload_temporario):
    _login()
    client.get(f"/sesa/certidoes/{COMP}", headers=HTML)
    estadual = _item("estadual")

    r = client.post(f"/sesa/certidoes/{COMP}/anexar", data={"item_id": estadual},
                    files={"arquivo": ("cnd.pdf", _pdf(ESTADUAL), "application/pdf")},
                    follow_redirects=False)
    assert "certid" in r.headers["location"] and "lida" in r.headers["location"]
    linha = next(l for l in _detalhe(COMP)["linhas"] if l["item"].id == estadual)
    a = linha["anexo"]
    assert a.numero == "20310001437974" and a.valida_ate == date(2031, 5, 28)
    assert a.cnpj_confere is True and linha["avisos"] == []
    assert linha["serve_proximo"] is True     # 28/05 cobre o prazo de abril

    # correção manual: validade antes do prazo vira aviso
    client.post(f"/sesa/anexos/{a.id}", data={"numero": "X1", "valida_ate": "2031-02-28",
                                             "resultado": "Negativa"})
    linha = next(l for l in _detalhe(COMP)["linhas"] if l["item"].id == estadual)
    assert linha["anexo"].numero == "X1" and "antes do prazo" in linha["avisos"][0]
    client.post(f"/sesa/anexos/{a.id}", data={"numero": "20310001437974",
                                             "valida_ate": "2031-05-28",
                                             "resultado": "Negativa"})

    # mês seguinte: sugere e reaproveita a certidão ainda válida
    seguinte = "2031-04"
    sugestao = next(l for l in _detalhe(seguinte)["linhas"]
                    if l["item"].id == estadual)["sugestao"]
    assert sugestao is not None and sugestao.id == a.id
    client.post(f"/sesa/certidoes/{seguinte}/reaproveitar", data={"anexo_id": a.id})
    novo = next(l for l in _detalhe(seguinte)["linhas"] if l["item"].id == estadual)["anexo"]
    assert novo.reaproveitado_de == a.id and novo.arquivo_id == a.arquivo_id

    # pacote e texto do despacho
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/sesa/certidoes/{COMP}/pacote.zip").content))
    assert z.namelist() == ["01 - Estadual - 03-2031.pdf"]
    pagina = client.get(f"/sesa/certidoes/{COMP}", headers=HTML).text
    assert "nº 20310001437974" in pagina and "válida até 28/05/2031" in pagina

    # registro do envio trava a troca de arquivos
    client.post(f"/sesa/certidoes/{COMP}/enviar",
                data={"enviada_em": "2031-03-03", "protocolo": "2031-XYZ"})
    d = _detalhe(COMP)
    assert d["entrega"].protocolo == "2031-XYZ" and d["situacao"]["estado"] == "enviada"
    assert d["situacao"]["no_prazo"] is True            # 1º dia útil: 03/03/2031
    r = client.post(f"/sesa/anexos/{a.id}/remover", follow_redirects=False)
    assert "erro=" in r.headers["location"]
    client.post(f"/sesa/certidoes/{COMP}/desfazer")
    assert _detalhe(COMP)["entrega"].enviada_em is None

    # remover a origem não quebra quem a reaproveitou
    client.post(f"/sesa/anexos/{a.id}/remover")
    novo = next(l for l in _detalhe(seguinte)["linhas"] if l["item"].id == estadual)["anexo"]
    assert novo is not None and novo.reaproveitado_de is None


def test_certidao_precisa_ser_pdf_ou_imagem(upload_temporario):
    _login()
    r = client.post(f"/sesa/certidoes/{COMP}/anexar", data={"item_id": _item("fgts")},
                    files={"arquivo": ("x.txt", b"oi", "text/plain")},
                    follow_redirects=False)
    assert "erro=" in r.headers["location"]


def test_matriz_mostra_o_envio_registrado():
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        o = service.obrigacao_por_chave(db, 1, "bpa")
        ent = service.entrega(db, 1, o, date(2031, 5, 1), criar=True)
        service.registrar_envio(db, ent, {"enviada_em": "2031-05-20"}, None)
        linha = next(l for l in service.matriz_ano(db, 1, 2031, date(2031, 6, 1))
                     if l["obrigacao"].chave == "bpa")
        maio = linha["meses"][4]
        assert maio["estado"] == "enviada" and maio["no_prazo"] is False
        assert linha["meses"][6]["estado"] == "futura"
        fes = next(l for l in service.matriz_ano(db, 1, 2031, date(2031, 6, 1))
                   if l["obrigacao"].chave == "fes_007")
        assert [m["estado"] != "nao_aplica" for m in fes["meses"]].count(True) == 4
    finally:
        db.close()
    _login()
    html = client.get("/sesa/?ano=2031", headers=HTML).text
    assert "Enviado em 20/05/2031 (fora do prazo)" in html
    pagina = client.get("/sesa/bpa/2031-05", headers=HTML).text
    assert "Desfazer registro" in pagina and "Enviado em 20/05/2031" in pagina


def test_pendencias_para_a_pagina_inicial():
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        # no 1º dia útil de ago/2031 tudo do mês vence em até 5 dias
        todas = service.pendencias(db, 1, date(2031, 8, 1))
        chaves = {p["obrigacao"].chave for p in todas}
        assert "certidoes" in chaves and "fes_007" not in chaves
        # julho sem nada começado não aparece como atrasado
        assert all(p["competencia"] == date(2031, 8, 1) for p in todas)
    finally:
        db.close()


def test_cadastros_editam_prazo_e_itens():
    from app.core.database import SessionLocal
    from app.modules.sesa.models import SesaObrigacao

    _login()
    assert "Dados gerais" in client.get("/sesa/cadastros", headers=HTML).text
    db = SessionLocal()
    try:
        o = service.obrigacao_por_chave(db, 1, "ranking")
        oid, antes = o.id, (o.prazo_dia, o.prazo_tipo, o.destinatario, o.canal)
        itens = [(i.id, i.nome) for i in o.itens]
    finally:
        db.close()
    dados = {"nome": "Ranking de Acionamento", "periodicidade": "mensal", "prazo_dia": "7",
             "prazo_tipo": "util", "canal": "E-mail", "destinatario": "a@b.c", "ativo": "1"}
    for iid, nome in itens:
        dados[f"item_{iid}_nome"] = nome
        dados[f"item_{iid}_ativo"] = "1"
    client.post(f"/sesa/cadastros/obrigacao/{oid}", data=dados)
    db = SessionLocal()
    try:
        o = db.get(SesaObrigacao, oid)
        assert (o.prazo_dia, o.destinatario) == (7, "a@b.c")
        o.prazo_dia, o.prazo_tipo, o.destinatario, o.canal = antes
        db.commit()
    finally:
        db.close()


# ------------------------------------------------------------------ portais e avisos

def test_abrir_portais_pendentes():
    _login()
    d = _detalhe("2032-01")
    assert {i.chave for i in d["portais_pendentes"]} == {
        "estadual", "uniao", "fgts", "serra", "trabalhista"}
    html = client.get("/sesa/certidoes/2032-01", headers=HTML).text
    assert "Abrir portais pendentes (5)" in html and "consulta-crf.caixa.gov.br" in html


TRABALHISTA = ("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS\nCNPJ: 28.141.190/0011-58\n"
               "Certidão nº: 99990001/2031\nExpedição: 01/09/2031\nValidade: 10/09/2031")


def test_aviso_de_vencimento_sai_uma_vez(upload_temporario, monkeypatch):
    from app.core import mail
    from app.core.database import SessionLocal
    from app.modules.sesa import avisos

    enviados = []
    monkeypatch.setattr(mail, "send_mail",
                        lambda db, para, assunto, corpo, **k: enviados.append(assunto))
    _login()
    trab = _item("trabalhista")
    client.post("/sesa/certidoes/2031-09/anexar", data={"item_id": trab},
                files={"arquivo": ("cndt.pdf", _pdf(TRABALHISTA), "application/pdf")})
    # a pendência some da lista de portais: já tem certidão (sem aviso)
    assert "trabalhista" not in {i.chave for i in _detalhe("2031-09")["portais_pendentes"]}

    db = SessionLocal()
    try:
        longe = service.certidoes_a_vencer(db, 1, date(2031, 8, 20), 7)
        assert trab not in {c["item"].id for c in longe}
        pend = service.avisos_pendentes(db, 1, date(2031, 9, 5))
        assert [(c["item"].id, c["dias"]) for c in pend] == [(trab, 5)]
        assert avisos.avisar_vencimentos(db, 1, date(2031, 9, 5)) == 1
        assert enviados and "Trabalhista" in enviados[0]
        # no dia seguinte não repete
        assert avisos.avisar_vencimentos(db, 1, date(2031, 9, 6)) == 0
    finally:
        db.close()

    # certidão nova anexada: a antiga deixa de contar
    novo = TRABALHISTA.replace("99990001", "99990002").replace("10/09/2031", "10/03/2032")
    client.post("/sesa/certidoes/2031-10/anexar", data={"item_id": trab},
                files={"arquivo": ("cndt2.pdf", _pdf(novo), "application/pdf")})
    db = SessionLocal()
    try:
        assert trab not in {c["item"].id for c in
                            service.certidoes_a_vencer(db, 1, date(2031, 9, 5), 7)}
    finally:
        db.close()


def test_job_diario_roda_sem_erro(monkeypatch):
    from app.core import mail
    from app.modules.sesa import scheduler

    monkeypatch.setattr(mail, "send_mail", lambda *a, **k: True)
    assert scheduler.executar() >= 0


def test_cadastros_gerais_guardam_dias_e_endereco():
    from app.core.config_service import get_config
    from app.core.database import SessionLocal

    _login()
    client.post("/sesa/cadastros/geral", data={"cnpj": CNPJ, "feriados": "",
                                               "aviso_dias": "10",
                                               "endereco": "https://q.exemplo/"})
    db = SessionLocal()
    try:
        assert service.dias_aviso_vencimento(db, 1) == 10
        assert get_config(db, service.CONFIG_ENDERECO, "", 1) == "https://q.exemplo"
    finally:
        db.close()
