"""Testes do módulo Download vSky."""

import re

import pytest
from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app

client = TestClient(app)

LINHA_A = {
    "ocorrencia": "2710199", "codigo_da_ocorrencia": "Queda de Ligação",
    "status_da_ocorrencia": "Encerrada", "sexo": "M",
    "telefone": "27996920323", "data_ocorrencia": "06/08/2026 00:03:31",
}
LINHA_B = {
    "ocorrencia": "2710213", "codigo_da_ocorrencia": "Trauma",
    "status_da_ocorrencia": "Encerrada", "sexo": "F",
    "telefone": "27996450771", "data_ocorrencia": "06/08/2026 00:27:39",
}


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def _configurar_credenciais():
    from app.core.config_service import set_config
    from app.core.database import SessionLocal
    from app.modules.download_vsky.constants import CONFIG_SENHA, CONFIG_USUARIO

    db = SessionLocal()
    try:
        set_config(db, CONFIG_USUARIO, "usuario.teste", empresa_id=1)
        set_config(db, CONFIG_SENHA, "senha-teste", empresa_id=1)
    finally:
        db.close()


def _limpar_credenciais():
    from app.core.config_service import set_config
    from app.core.database import SessionLocal
    from app.modules.download_vsky.constants import CONFIG_SENHA, CONFIG_USUARIO

    db = SessionLocal()
    try:
        set_config(db, CONFIG_USUARIO, None, empresa_id=1)
        set_config(db, CONFIG_SENHA, None, empresa_id=1)
    finally:
        db.close()


class _ClientFake:
    """Substitui VskyClient nos testes — devolve um 'XLS' sintético."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def login(self):
        pass

    def gerar_total_registros_analitico(self, data_inicial, data_final,
                                        cliente_id=None):
        return b"xls-fake"


def _stub_client(monkeypatch, linhas):
    from app.modules.download_vsky import service as svc

    monkeypatch.setattr(svc, "VskyClient", _ClientFake)
    monkeypatch.setattr(svc, "parse_xls", lambda content: [dict(l) for l in linhas])


def test_requer_login():
    response = client.get("/download_vsky/", headers={"accept": "text/html"},
                          follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_index():
    _login()
    response = client.get("/download_vsky/", headers={"accept": "text/html"})
    assert response.status_code == 200
    assert "Download vSky" in response.text


def test_config_page():
    _login()
    response = client.get("/download_vsky/config", headers={"accept": "text/html"})
    assert response.status_code == 200
    assert "vSky" in response.text


def test_validar_periodo():
    from app.modules.download_vsky.validators import data_iso_para_br, validar_periodo

    assert validar_periodo("01/08/2026", "06/08/2026") == ("01/08/2026", "06/08/2026")
    assert data_iso_para_br("2026-08-01") == "01/08/2026"
    with pytest.raises(ValueError):
        validar_periodo("06/08/2026", "01/08/2026")
    with pytest.raises(ValueError):
        validar_periodo("2026-13-45", "01/08/2026")


def test_normalizar_base_url():
    from app.modules.download_vsky.validators import normalizar_base_url

    assert normalizar_base_url(
        "https://es.vskysamu.com.br/vskymanagement/login.xhtml"
    ) == "https://es.vskysamu.com.br"
    assert normalizar_base_url("gestao-es.vskysamu.com.br") == \
        "https://gestao-es.vskysamu.com.br"
    assert normalizar_base_url("https://gestao-es.vskysamu.com.br/") == \
        "https://gestao-es.vskysamu.com.br"
    assert normalizar_base_url("") == ""


def test_linha_hash_considera_linha_inteira():
    from app.modules.download_vsky.importer import linha_hash

    assert linha_hash(LINHA_A) == linha_hash(dict(LINHA_A))
    alterada = dict(LINHA_A, telefone="27000000000")
    assert linha_hash(LINHA_A) != linha_hash(alterada)


def test_importar_sem_credenciais():
    _limpar_credenciais()
    _login()
    response = client.post("/download_vsky/importar",
                           data={"data_inicial": "2026-08-01",
                                 "data_final": "2026-08-06"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "erro=" in response.headers["location"]


def _limpar_registros_de_teste():
    """dev.db persiste entre execuções — remove as linhas destes testes."""
    from sqlalchemy import delete
    from app.core.database import SessionLocal
    from app.modules.download_vsky.models import VskyRegistroAnalitico

    db = SessionLocal()
    try:
        db.execute(delete(VskyRegistroAnalitico).where(
            VskyRegistroAnalitico.ocorrencia.in_(
                [LINHA_A["ocorrencia"], LINHA_B["ocorrencia"]])))
        db.commit()
    finally:
        db.close()


def test_importacao_e_dedupe(monkeypatch):
    _stub_client(monkeypatch, [LINHA_A, LINHA_B, LINHA_A])  # A duplicada no arquivo
    _limpar_registros_de_teste()
    _configurar_credenciais()
    _login()

    response = client.post("/download_vsky/importar",
                           data={"data_inicial": "2026-08-01",
                                 "data_final": "2026-08-06"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "msg=" in response.headers["location"]

    payload = client.get("/download_vsky/api").json()
    ultima = payload["data"][0]
    assert ultima["status"] == "concluido"
    assert ultima["total_linhas"] == 3
    assert ultima["linhas_novas"] == 2
    assert ultima["linhas_duplicadas"] == 1

    # Reimportar o mesmo período: nada novo, tudo duplicado.
    response = client.post("/download_vsky/api",
                           json={"data_inicial": "2026-08-01",
                                 "data_final": "2026-08-06"})
    assert response.status_code == 201
    dados = response.json()["data"]
    assert dados["linhas_novas"] == 0
    assert dados["linhas_duplicadas"] == 3

    # Busca pela ocorrência: independe da posição na paginação (o dev.db
    # compartilhado pode ter registros com datas mais recentes).
    registros = client.get("/download_vsky/registros?q=2710199",
                           headers={"accept": "text/html"})
    assert registros.status_code == 200
    assert "2710199" in registros.text


def test_download_automatico_agendamento():
    """Salvar a configuração cria/remove o job agendado conforme o toggle."""
    from app.core.config_service import get_config, invalidate_config, set_config
    from app.core.database import SessionLocal
    from app.modules.download_vsky import scheduler

    _login()
    db = SessionLocal()
    chaves = ["vsky_base_url", "vsky_usuario", "vsky_senha", "vsky_cliente_id",
              "vsky_auto_ativo", "vsky_auto_modo", "vsky_auto_hora",
              "vsky_auto_intervalo", "vsky_auto_dias"]
    orig = {k: get_config(db, k, empresa_id=1) for k in chaves}
    try:
        # liga: diariamente às 05:45, últimos 3 dias
        resp = client.post("/download_vsky/config", data={
            "base_url": orig["vsky_base_url"] or "https://gestao-es.vskysamu.com.br",
            "usuario_vsky": orig["vsky_usuario"] or "u", "senha_vsky": "",
            "cliente_id": orig["vsky_cliente_id"] or "",
            "auto_ativo": "1", "auto_modo": "diario", "auto_hora": "05:45",
            "auto_dias": "3"}, follow_redirects=False)
        invalidate_config()
        assert resp.status_code == 303
        assert "05%3A45" in resp.headers["location"] or "05:45" in resp.headers["location"]
        assert get_config(db, "vsky_auto_ativo", empresa_id=1) == "1"
        proxima = scheduler.proxima_execucao()
        assert proxima is not None and "05:45" in proxima

        # intervalo abaixo do mínimo é elevado ao mínimo
        client.post("/download_vsky/config", data={
            "base_url": orig["vsky_base_url"] or "https://gestao-es.vskysamu.com.br",
            "usuario_vsky": orig["vsky_usuario"] or "u", "senha_vsky": "",
            "auto_ativo": "1", "auto_modo": "intervalo", "auto_intervalo": "1",
            "auto_dias": "2"}, follow_redirects=False)
        invalidate_config()
        assert int(get_config(db, "vsky_auto_intervalo", empresa_id=1)) >= 15

        # desliga: job removido
        client.post("/download_vsky/config", data={
            "base_url": orig["vsky_base_url"] or "https://gestao-es.vskysamu.com.br",
            "usuario_vsky": orig["vsky_usuario"] or "u", "senha_vsky": "",
            "auto_modo": "diario"}, follow_redirects=False)
        invalidate_config()
        assert scheduler.proxima_execucao() is None
    finally:
        for k, v in orig.items():
            set_config(db, k, v, empresa_id=1)
        invalidate_config()
        scheduler.sincronizar()
        db.close()


def test_calendario_de_cobertura():
    """A página inicial exibe o calendário com dias com/sem registros."""
    _login()
    resp = client.get("/download_vsky/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "Cobertura de dados por dia" in resp.text
    # havendo registros importados, há células de dia com registros
    from app.core.database import SessionLocal
    from app.modules.download_vsky.service import DownloadVskyService

    db = SessionLocal()
    try:
        cal = DownloadVskyService(db, 1).calendario_cobertura()
    finally:
        db.close()
    if cal["meses"]:
        assert "cal-com" in resp.text
        # todo dia entre o início e hoje é classificado (com/sem)
        total_dias = sum(1 for m in cal["meses"] for s in m["semanas"]
                         for d in s if d and d["status"] in ("com", "sem"))
        assert total_dias > 0
        # dias sem registro aparecem como célula clicável
        if cal["dias_sem"]:
            assert "cal-sem" in resp.text


def test_importacao_com_falha_no_portal(monkeypatch):
    from app.modules.download_vsky import service as svc
    from app.modules.download_vsky.vsky_client import VskyError

    class _ClientFalho(_ClientFake):
        def login(self):
            raise VskyError("Autenticação no vSky recusada — confira usuário e senha.")

    monkeypatch.setattr(svc, "VskyClient", _ClientFalho)
    _configurar_credenciais()
    _login()

    response = client.post("/download_vsky/api",
                           json={"data_inicial": "2026-08-01",
                                 "data_final": "2026-08-06"})
    assert response.status_code == 502
    payload = response.json()
    assert payload["success"] is False
    assert "recusada" in payload["data"]["erro"]


def test_periodo_invalido_na_api(monkeypatch):
    _stub_client(monkeypatch, [])
    _configurar_credenciais()
    _login()
    response = client.post("/download_vsky/api",
                           json={"data_inicial": "2026-08-10",
                                 "data_final": "2026-08-01"})
    assert response.status_code == 422
    assert response.json()["success"] is False


def test_download_automatico_usa_formato_de_data_aceito(monkeypatch):
    """O job agendado deve chamar a importação no formato dd/mm/aaaa.

    Passar ISO (aaaa-mm-dd) fazia toda execução automática falhar com
    'Datas devem estar no formato dd/mm/aaaa' — e o erro só aparecia no
    status da configuração, nunca na importação manual.
    """
    from app.core.config_service import get_config, set_config
    from app.core.database import SessionLocal
    from app.modules.download_vsky import scheduler
    from app.modules.download_vsky.constants import (CONFIG_AUTO_STATUS,
                                                     STATUS_CONCLUIDO)
    from app.modules.download_vsky.validators import validar_periodo

    recebido = {}

    class ServicoFalso:
        def __init__(self, db, empresa_id):
            pass

        def importar_periodo(self, data_inicial, data_final, *a, **k):
            # o validador real é quem reprovava as datas do agendador
            recebido["periodo"] = validar_periodo(data_inicial, data_final)

            class Item:
                status = STATUS_CONCLUIDO
                linhas_novas = 3
                linhas_superadas = 2
                linhas_duplicadas = 1
                erro = None
            return Item()

    import app.modules.download_vsky.service as servico_mod
    monkeypatch.setattr(servico_mod, "DownloadVskyService", ServicoFalso)

    db = SessionLocal()
    try:
        set_config(db, "vsky_usuario", "u", empresa_id=1)
        set_config(db, "vsky_senha", "s", empresa_id=1)
    finally:
        db.close()

    scheduler.executar_download_automatico(1)

    assert "periodo" in recebido, "a importação não chegou a ser chamada"
    inicial, final = recebido["periodo"]
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", inicial), inicial
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", final), final

    db = SessionLocal()
    try:
        status = get_config(db, CONFIG_AUTO_STATUS, empresa_id=1) or ""
    finally:
        db.close()
    assert status.startswith("sucesso"), status


def _pdf_de_teste(texto: str, paginas: int = 1) -> bytes:
    """PDF mínimo em memória, para exercitar a junção das fichas."""
    from io import BytesIO

    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf)
    for n in range(paginas):
        c.drawString(72, 720, f"{texto} — página {n + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def test_consulta_encontra_o_botao_de_pdf_de_cada_viatura():
    """Ocorrência com duas viaturas devolve duas linhas, cada uma com a sua
    ficha; parar na primeira deixaria a outra equipe de fora."""
    from app.modules.download_vsky.prontuario_client import _botoes_por_titulo

    html = """
    <table><tbody>
      <tr><td>2731303</td>
          <td><a id="frm:tbl:0:pdfCompleta" title="Ficha de Atendimento Completa"></a></td></tr>
      <tr><td>2731303</td>
          <td><a title="Ficha de Atendimento Completa" id="frm:tbl:1:pdfCompleta"></a></td></tr>
    </tbody></table>"""
    achados = _botoes_por_titulo(html, "Ficha de Atendimento Completa")
    assert achados == ["frm:tbl:0:pdfCompleta", "frm:tbl:1:pdfCompleta"]
    # e não repete o mesmo id quando os dois padrões de atributo casam
    assert len(achados) == len(set(achados))


def test_fichas_de_varias_viaturas_viram_um_pdf_so():
    from pypdf import PdfReader

    from app.modules.download_vsky.service import _juntar_fichas

    usa = _pdf_de_teste("USA 100", paginas=3)
    usb = _pdf_de_teste("USB 46", paginas=2)
    juntas = _juntar_fichas([usa, usb])

    from io import BytesIO
    leitor = PdfReader(BytesIO(juntas))
    assert len(leitor.pages) == 5
    texto = "\n".join(p.extract_text() or "" for p in leitor.pages)
    assert "USA 100" in texto and "USB 46" in texto
    # a ordem é a da consulta
    assert texto.index("USA 100") < texto.index("USB 46")


def test_ficha_unica_nao_e_reprocessada():
    from app.modules.download_vsky.service import _juntar_fichas

    unica = _pdf_de_teste("USB 46")
    assert _juntar_fichas([unica]) == unica
    assert _juntar_fichas([]) == b""


def test_ficha_corrompida_nao_derruba_o_download():
    """Melhor entregar a ficha que veio inteira do que falhar o download."""
    from app.modules.download_vsky.service import _juntar_fichas

    boa = _pdf_de_teste("USA 100")
    assert _juntar_fichas([boa, b"nao sou um pdf"]) == boa


# ------------------- correções vindas do vSky entre dois downloads

def _linha_minima(**campos) -> dict:
    """Linha do relatório com todas as colunas, para exercitar o importador."""
    from app.modules.download_vsky.constants import COLUNAS

    linha = {slug: "" for slug, _ in COLUNAS}
    linha.update(campos)
    return linha


def _servico(db):
    from app.modules.download_vsky.service import DownloadVskyService

    return DownloadVskyService(db, empresa_id=1)


def _importacao(db, rotulo: str):
    """Importação de fachada. A data 2099 marca o que é de teste, para a
    limpeza no fim não encostar em importação de verdade."""
    from app.modules.download_vsky.models import VskyImportacao

    item = VskyImportacao(empresa_id=1, data_inicial="01/01/2099",
                          data_final="02/01/2099", status="concluido")
    db.add(item)
    db.commit()
    return item


def _limpar_importacoes_de_teste(db) -> None:
    from sqlalchemy import delete

    from app.modules.download_vsky.models import VskyImportacao

    db.execute(delete(VskyImportacao).where(
        VskyImportacao.data_inicial == "01/01/2099"))
    db.commit()


def _vivos(db, ocorrencia: str):
    from sqlalchemy import select

    from app.modules.download_vsky.models import VskyRegistroAnalitico as R

    return db.scalars(select(R).where(R.ocorrencia == ocorrencia,
                                      R.deleted_at.is_(None))
                      .order_by(R.id)).all()


def test_correcao_do_vsky_substitui_a_versao_anterior():
    """Mesma ocorrência e unidade voltando com o status mudado é atualização,
    não registro novo — senão o empenho conta duas vezes nos painéis."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    numero = "9900001"
    try:
        primeiro = _importacao(db, "1º download")
        novas, _, superadas, _ = _servico(db)._inserir_linhas(
            [_linha_minima(ocorrencia=numero, unidade="USB 99 - TESTE",
                           status_da_ocorrencia="Em Atendimento",
                           data_ocorrencia="01/01/2099 08:00:00")], primeiro)
        assert (novas, superadas) == (1, 0)

        segundo = _importacao(db, "2º download")
        novas, _, superadas, _ = _servico(db)._inserir_linhas(
            [_linha_minima(ocorrencia=numero, unidade="USB 99 - TESTE",
                           status_da_ocorrencia="Encerrada",
                           data_ocorrencia="01/01/2099 08:00:00",
                           atendimento_encerrado="01/01/2099 09:10:00")], segundo)
        assert (novas, superadas) == (1, 1)

        vivos = _vivos(db, numero)
        assert len(vivos) == 1, "a versão antiga continuou contando"
        assert vivos[0].status_da_ocorrencia == "Encerrada"
        assert vivos[0].atendimento_encerrado == "01/01/2099 09:10:00"
    finally:
        _limpar_teste(db, numero)


def test_duas_vitimas_no_mesmo_arquivo_continuam_dois_registros():
    """Uma ocorrência com duas vítimas traz duas linhas iguais em (ocorrência,
    unidade) no MESMO arquivo — nenhuma delas é versão velha da outra."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    numero = "9900002"
    try:
        item = _importacao(db, "download único")
        novas, _, superadas, _ = _servico(db)._inserir_linhas([
            _linha_minima(ocorrencia=numero, unidade="USB 99 - TESTE",
                          paciente="VITIMA A", sexo="M",
                          data_ocorrencia="01/01/2099 08:00:00"),
            _linha_minima(ocorrencia=numero, unidade="USB 99 - TESTE",
                          paciente="VITIMA B", sexo="F",
                          data_ocorrencia="01/01/2099 08:00:00"),
        ], item)
        assert (novas, superadas) == (2, 0)
        assert len(_vivos(db, numero)) == 2

        # o mesmo arquivo reimportado não muda nada
        novas, _, superadas, _ = _servico(db)._inserir_linhas([
            _linha_minima(ocorrencia=numero, unidade="USB 99 - TESTE",
                          paciente="VITIMA A", sexo="M",
                          data_ocorrencia="01/01/2099 08:00:00"),
            _linha_minima(ocorrencia=numero, unidade="USB 99 - TESTE",
                          paciente="VITIMA B", sexo="F",
                          data_ocorrencia="01/01/2099 08:00:00"),
        ], _importacao(db, "reimportação"))
        assert (novas, superadas) == (0, 0)
        assert len(_vivos(db, numero)) == 2
    finally:
        _limpar_teste(db, numero)


def test_reimportar_o_mesmo_arquivo_nao_aposenta_nada():
    """Reimportação é rotina (o agendador rebaixa os últimos dias): não pode
    trocar ids nem marcar exclusões a cada passada."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    numero = "9900003"
    try:
        linha = _linha_minima(ocorrencia=numero, unidade="USA 99 - TESTE",
                              status_da_ocorrencia="Encerrada",
                              data_ocorrencia="01/01/2099 08:00:00")
        _servico(db)._inserir_linhas([linha], _importacao(db, "1º"))
        ids_antes = [r.id for r in _vivos(db, numero)]

        novas, duplicadas, superadas, _ = _servico(db)._inserir_linhas(
            [linha], _importacao(db, "2º"))
        assert (novas, superadas) == (0, 0) and duplicadas == 1
        assert [r.id for r in _vivos(db, numero)] == ids_antes
    finally:
        _limpar_teste(db, numero)


def test_ocorrencia_de_outro_periodo_nao_e_tocada():
    """O download cobre uma janela: chave fora do arquivo fica como está."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    fora, dentro = "9900004", "9900005"
    try:
        _servico(db)._inserir_linhas(
            [_linha_minima(ocorrencia=fora, unidade="USB 99 - TESTE",
                           data_ocorrencia="01/01/2099 08:00:00")],
            _importacao(db, "janela antiga"))
        assert len(_vivos(db, fora)) == 1

        _servico(db)._inserir_linhas(
            [_linha_minima(ocorrencia=dentro, unidade="USB 99 - TESTE",
                           data_ocorrencia="02/01/2099 08:00:00")],
            _importacao(db, "janela nova"))
        assert len(_vivos(db, fora)) == 1, "registro fora da janela foi mexido"
        assert len(_vivos(db, dentro)) == 1
    finally:
        _limpar_teste(db, fora)
        _limpar_teste(db, dentro)


def test_linha_sem_numero_de_ocorrencia_nao_e_reconciliada():
    """Sem número não há identidade — reconciliar apagaria linhas boas."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        item = _importacao(db, "sem número")
        novas, _, superadas, _ = _servico(db)._inserir_linhas([
            _linha_minima(ocorrencia="", unidade="USB 99 - TESTE",
                          paciente="SEM NUMERO 1",
                          data_ocorrencia="03/01/2099 08:00:00"),
        ], item)
        assert (novas, superadas) == (1, 0)

        novas, _, superadas, _ = _servico(db)._inserir_linhas([
            _linha_minima(ocorrencia="", unidade="USB 99 - TESTE",
                          paciente="SEM NUMERO 2",
                          data_ocorrencia="03/01/2099 09:00:00"),
        ], _importacao(db, "sem número 2"))
        assert superadas == 0, "linha sem número foi aposentada indevidamente"
    finally:
        _limpar_sem_numero(db)


def _limpar_teste(db, ocorrencia: str) -> None:
    from sqlalchemy import delete

    from app.modules.download_vsky.models import VskyRegistroAnalitico as R

    db.execute(delete(R).where(R.ocorrencia == ocorrencia))
    db.commit()
    _limpar_importacoes_de_teste(db)


def _limpar_sem_numero(db) -> None:
    from sqlalchemy import delete

    from app.modules.download_vsky.models import VskyRegistroAnalitico as R

    db.execute(delete(R).where(R.paciente.like("SEM NUMERO%")))
    db.commit()
    _limpar_importacoes_de_teste(db)


# ------------------- substituir todo o período (apaga e reinsere)

def _vivos_no_periodo(db, inicio: str, fim: str) -> int:
    from datetime import datetime, timedelta

    from sqlalchemy import func, select

    from app.modules.download_vsky.models import VskyRegistroAnalitico as R

    ini = datetime.strptime(inicio, "%d/%m/%Y")
    f = datetime.strptime(fim, "%d/%m/%Y") + timedelta(days=1)
    return db.scalar(select(func.count()).select_from(R).where(
        R.deleted_at.is_(None), R.data_ocorrencia_dt >= ini,
        R.data_ocorrencia_dt < f)) or 0


def _fake_client(conteudo: bytes | None, erro: Exception | None = None):
    class _Fake:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self): pass
        def gerar_total_registros_analitico(self, *a, **k):
            if erro is not None:
                raise erro
            return conteudo
    return lambda *a, **k: _Fake()


def test_substituir_periodo_apaga_e_reinsere(monkeypatch):
    """O caso de uso: ocorrência que o portal removeu some do sistema."""
    from app.core.database import SessionLocal
    from app.modules.download_vsky import service as mod

    db = SessionLocal()
    ini, fim = "01/01/2099", "02/01/2099"
    try:
        # estado inicial: duas ocorrências no período
        antigas = [_linha_minima(ocorrencia="9910001", unidade="USB 99 - TESTE",
                                 data_ocorrencia="01/01/2099 08:00:00"),
                   _linha_minima(ocorrencia="9910002", unidade="USB 99 - TESTE",
                                 data_ocorrencia="01/01/2099 09:00:00")]
        _servico(db)._inserir_linhas(antigas, _importacao(db, "inicial"))
        assert _vivos_no_periodo(db, ini, fim) == 2

        # o vSky agora só tem a primeira, e com o status corrigido
        atual = [_linha_minima(ocorrencia="9910001", unidade="USB 99 - TESTE",
                               data_ocorrencia="01/01/2099 08:00:00",
                               status_da_ocorrencia="Encerrada")]
        monkeypatch.setattr(mod, "parse_xls", lambda _c: atual)
        monkeypatch.setattr(mod, "VskyClient", _fake_client(b"xls"))
        monkeypatch.setattr(mod, "_salvar_xls", lambda *a, **k: None)

        item = _servico(db).substituir_periodo(ini, fim, "u", "us", "se")
        assert item.status == "concluido", item.erro
        assert item.linhas_superadas == 2      # as duas antigas saíram
        assert item.linhas_novas == 1
        assert _vivos_no_periodo(db, ini, fim) == 1

        vivos = _vivos(db, "9910001")
        assert len(vivos) == 1 and vivos[0].status_da_ocorrencia == "Encerrada"
        assert _vivos(db, "9910002") == []     # removida do vSky, sumiu daqui
    finally:
        _limpar_teste(db, "9910001")
        _limpar_teste(db, "9910002")


def test_falha_do_portal_nao_apaga_nada(monkeypatch):
    """A ordem é o que torna a operação segura: baixa antes de apagar."""
    from app.core.database import SessionLocal
    from app.modules.download_vsky import service as mod
    from app.modules.download_vsky.vsky_client import VskyError

    db = SessionLocal()
    ini, fim = "01/01/2099", "02/01/2099"
    try:
        _servico(db)._inserir_linhas(
            [_linha_minima(ocorrencia="9910003", unidade="USB 99 - TESTE",
                           data_ocorrencia="01/01/2099 08:00:00")],
            _importacao(db, "inicial"))
        assert _vivos_no_periodo(db, ini, fim) == 1

        monkeypatch.setattr(mod, "VskyClient",
                            _fake_client(None, VskyError("portal fora do ar")))
        item = _servico(db).substituir_periodo(ini, fim, "u", "us", "se")

        assert item.status == "erro"
        assert "portal fora do ar" in item.erro
        assert _vivos_no_periodo(db, ini, fim) == 1, "apagou mesmo falhando"
    finally:
        _limpar_teste(db, "9910003")


def test_arquivo_vazio_nao_apaga_o_periodo(monkeypatch):
    """Relatório sem linhas seria a forma silenciosa de zerar um período."""
    from app.core.database import SessionLocal
    from app.modules.download_vsky import service as mod

    db = SessionLocal()
    ini, fim = "01/01/2099", "02/01/2099"
    try:
        _servico(db)._inserir_linhas(
            [_linha_minima(ocorrencia="9910004", unidade="USB 99 - TESTE",
                           data_ocorrencia="01/01/2099 08:00:00")],
            _importacao(db, "inicial"))

        monkeypatch.setattr(mod, "parse_xls", lambda _c: [])
        monkeypatch.setattr(mod, "VskyClient", _fake_client(b"xls"))
        item = _servico(db).substituir_periodo(ini, fim, "u", "us", "se")

        assert item.status == "erro"
        assert "sem linhas" in item.erro
        assert _vivos_no_periodo(db, ini, fim) == 1
    finally:
        _limpar_teste(db, "9910004")


def test_substituicao_nao_toca_fora_do_periodo(monkeypatch):
    from app.core.database import SessionLocal
    from app.modules.download_vsky import service as mod

    db = SessionLocal()
    try:
        _servico(db)._inserir_linhas([
            _linha_minima(ocorrencia="9910005", unidade="USB 99 - TESTE",
                          data_ocorrencia="05/01/2099 08:00:00")],   # fora
            _importacao(db, "fora"))
        _servico(db)._inserir_linhas([
            _linha_minima(ocorrencia="9910006", unidade="USB 99 - TESTE",
                          data_ocorrencia="01/01/2099 08:00:00")],   # dentro
            _importacao(db, "dentro"))

        monkeypatch.setattr(mod, "parse_xls", lambda _c: [
            _linha_minima(ocorrencia="9910007", unidade="USB 99 - TESTE",
                          data_ocorrencia="01/01/2099 10:00:00")])
        monkeypatch.setattr(mod, "VskyClient", _fake_client(b"xls"))
        monkeypatch.setattr(mod, "_salvar_xls", lambda *a, **k: None)
        _servico(db).substituir_periodo("01/01/2099", "02/01/2099",
                                        "u", "us", "se")

        assert len(_vivos(db, "9910005")) == 1, "registro fora do período sumiu"
        assert _vivos(db, "9910006") == []
        assert len(_vivos(db, "9910007")) == 1
    finally:
        for n in ("9910005", "9910006", "9910007"):
            _limpar_teste(db, n)


def test_botao_de_substituir_esta_na_tela_com_confirmacao():
    _login()
    html = client.get("/download_vsky/", headers={"accept": "text/html"}).text
    assert "Atualizar todo o período" in html
    assert 'formaction="/download_vsky/substituir"' in html
    assert "onclick=\"return confirm(" in html
