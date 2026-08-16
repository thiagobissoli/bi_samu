"""Testes do módulo Reunião de Indicadores."""

from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app

client = TestClient(app)


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def test_requer_login():
    resp = client.get("/reuniao_indicadores/", headers={"accept": "text/html"},
                      follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_apresentacao_renderiza():
    _login()
    resp = client.get("/reuniao_indicadores/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "Reunião de Indicadores de Desempenho" in resp.text
    # motor de slides e navegação
    assert 'class="slide capa"' in resp.text
    assert 'id="btn-prox"' in resp.text


def test_api_deck():
    _login()
    corpo = client.get("/reuniao_indicadores/api").json()
    assert corpo["success"] is True
    deck = corpo["data"]
    assert len(deck["slides"]) == 13
    assert deck["slides"][0]["tipo"] == "capa"
    assert deck["slides"][1]["titulo"] == "Ocorrências Despachadas — Pré-Hospitalar"
    assert deck["slides"][2]["titulo"] == "Ocorrências Despachadas — Inter-Hospitalar"
    tipos = [s["chart"]["tipo"] for s in deck["slides"] if s.get("chart")]
    for esperado in ("line", "bar", "gauss", "matriz", "doughnut"):
        assert esperado in tipos, esperado
    # séries semanais cobrem o período até a última semana completa
    despachos = deck["slides"][1]["chart"]
    assert len(despachos["labels"]) == len(despachos["labels_full"])
    assert despachos["labels_full"][-1] == deck["semana"]


def test_drill_down():
    """Clicar num elemento de gráfico lista as ocorrências que o compõem."""
    _login()
    deck = client.get("/reuniao_indicadores/api").json()["data"]
    # slide 1 (despachos pré-hospitalar), série 0, última semana da série
    ultimo = len(deck["slides"][1]["chart"]["labels"]) - 1
    corpo = client.get(f"/reuniao_indicadores/drill?chave=1:0:{ultimo}").json()
    assert corpo["success"] is True
    dados = corpo["data"]
    assert dados["total"] > 0
    assert 0 < dados["exibidos"] <= 300
    primeira = dados["ocorrencias"][0]
    for campo in ("id", "ocorrencia", "data", "cidade", "motivo", "unidade",
                  "codigo", "tr", "p2", "p3", "p4_1", "p4_2"):
        assert campo in primeira, campo
    # tempos em mm:ss (ou nulos quando ausentes/fora da faixa)
    import re
    for campo in ("tr", "p2", "p3", "p4_1", "p4_2"):
        valor = primeira[campo]
        assert valor is None or re.fullmatch(r"\d{2}:\d{2}", valor), campo
    # data com hora, para distinguir empenhos do mesmo dia
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", primeira["data"])
    # o total do drill bate com o nº de despachos (empenhos) da semana
    assert dados["total"] >= deck["slides"][1]["chart"]["datasets"][0]["data"][ultimo]
    # chave inexistente devolve vazio, sem erro
    vazio = client.get("/reuniao_indicadores/drill?chave=99:9:9").json()
    assert vazio["data"]["total"] == 0


def test_detalhe_ocorrencia():
    """Clicar numa linha do drill abre a ficha completa da ocorrência."""
    _login()
    client.get("/reuniao_indicadores/api")
    drill = client.get("/reuniao_indicadores/drill?chave=1:0:0").json()["data"]
    if not drill["ocorrencias"]:
        return
    alvo = drill["ocorrencias"][0]
    corpo = client.get(f"/reuniao_indicadores/ocorrencia?id={alvo['id']}").json()
    assert corpo["success"] is True
    d = corpo["data"]
    assert d["ocorrencia"] == alvo["ocorrencia"]
    # ficha completa: todas as 61 colunas + tempo resposta calculado
    rotulos = [c["rotulo"] for c in d["campos"]]
    assert len(rotulos) == 62
    for esperado in ("Ocorrência", "Tempo Resposta (este empenho)",
                     "Chegada no local", "Médico", "Micro Região"):
        assert esperado in rotulos, esperado
    # empenhos da mesma ocorrência, com o registro atual marcado
    assert any(e["atual"] for e in d["empenhos"])
    # id inexistente não quebra
    nada = client.get("/reuniao_indicadores/ocorrencia?id=999999999").json()
    assert nada["success"] is False


def test_prontuario_pdf(monkeypatch):
    """Baixa (mock) e serve o PDF do prontuário da ocorrência selecionada."""
    from app.modules.download_vsky import service as dv_service

    _login()
    client.get("/reuniao_indicadores/api")
    alvo = client.get("/reuniao_indicadores/drill?chave=1:0:0"
                      ).json()["data"]["ocorrencias"][0]

    chamadas = {}

    def fake_client(numero):
        # o serviço instancia ProntuarioClient; simulamos a geração do PDF
        class _Fake:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def login(self): chamadas["login"] = True
            def baixar_prontuario(self, num):
                chamadas["numero"] = num
                return b"%PDF-1.4\nfake prontuario\n%%EOF"
        return _Fake()

    import app.modules.download_vsky.prontuario_client as pc
    monkeypatch.setattr(pc, "ProntuarioClient",
                        lambda *a, **k: fake_client(a))
    # credenciais presentes para o serviço prosseguir
    from app.core.config_service import set_config
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        set_config(db, "vsky_usuario", "u", empresa_id=1)
        set_config(db, "vsky_senha", "s", empresa_id=1)
    finally:
        db.close()

    resp = client.get(f"/reuniao_indicadores/prontuario?id={alvo['id']}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    assert chamadas.get("login") is True

    # 2ª chamada usa o cache em disco (não baixa de novo)
    chamadas.clear()
    resp2 = client.get(f"/reuniao_indicadores/prontuario?id={alvo['id']}")
    assert resp2.status_code == 200
    assert "login" not in chamadas

    # limpa o cache em disco criado pelo teste
    from app.modules.download_vsky.service import prontuario_path
    p = prontuario_path(1, alvo["ocorrencia"])
    if p.exists():
        p.unlink()


def test_menu():
    _login()
    home = client.get("/", headers={"accept": "text/html"})
    assert "Reunião de Indicadores" in home.text


def test_indicadores_da_ocorrencia():
    """O modal traz os indicadores calculados do empenho (mesmos do núcleo)."""
    _login()
    client.get("/reuniao_indicadores/api")
    drill = client.get("/reuniao_indicadores/drill?chave=1:0:0").json()["data"]
    if not drill["ocorrencias"]:
        return
    alvo = drill["ocorrencias"][0]
    d = client.get(f"/reuniao_indicadores/ocorrencia?id={alvo['id']}"
                   ).json()["data"]
    inds = d["indicadores"]
    assert inds, "sem indicadores"
    rotulos = [i["rotulo"] for i in inds]
    for esperado in ("Tempo de Central", "P1 · Atendimento TARM",
                     "P4.1 · Saída de base", "Tempo de Resposta", "Plantão"):
        assert esperado in rotulos, esperado
    # todo item traz situação válida para o template colorir
    assert all(i["situacao"] in ("ok", "alerta", "ruim", "neutro")
               for i in inds)
    # os tempos saem em mm:ss (ou "—" quando ausentes)
    import re
    p1 = next(i for i in inds if i["rotulo"].startswith("P1"))
    assert p1["valor"] == "—" or re.fullmatch(r"\d{2}:\d{2}", p1["valor"])
    # o SLA do P1 é avaliado quando há valor
    if p1["valor"] != "—":
        assert p1["situacao"] in ("ok", "ruim")
        assert "meta" in p1["sub"]


def _uma_ocorrencia() -> dict:
    """Uma ocorrência qualquer vinda do drill, para os testes de detalhe."""
    _login()
    deck = client.get("/reuniao_indicadores/api").json()["data"]
    ultimo = len(deck["slides"][1]["chart"]["labels"]) - 1
    drill = client.get(f"/reuniao_indicadores/drill?chave=1:0:{ultimo}"
                       ).json()["data"]
    return drill["ocorrencias"][0]


def test_botao_investigar_no_modal():
    """O modal oferece o caminho para a investigação do evento."""
    _login()
    html = client.get("/reuniao_indicadores/",
                      headers={"accept": "text/html"}).text
    assert 'id="drill-investigar"' in html
    assert "Investigar evento" in html
    # a aba é aberta no clique (gesto do usuário), senão o bloqueador de
    # pop-up barra a abertura que vem depois do fetch
    assert 'window.open("", "_blank")' in html


def test_investigar_baixa_o_pdf_antes_de_abrir(monkeypatch, tmp_path):
    """A ficha em PDF é obtida ANTES de mandar o usuário para a investigação."""
    from app.modules.download_vsky import service as dv

    alvo = _uma_ocorrencia()
    pedidos = []

    def _falso(db, empresa_id, numero):
        pedidos.append(numero)
        arquivo = tmp_path / f"{numero}.pdf"
        arquivo.write_bytes(b"%PDF-1.4 teste")
        return arquivo

    monkeypatch.setattr(dv, "obter_prontuario", _falso)
    corpo = client.get(f"/reuniao_indicadores/investigar?id={alvo['id']}").json()

    assert corpo["success"] is True
    dados = corpo["data"]
    assert pedidos == [alvo["ocorrencia"]], "o PDF não foi pedido ao vSky"
    assert dados["prontuario"] is True
    assert dados["aviso"] is None
    assert dados["destino"] == f"/investigacao/?ocorrencia={alvo['ocorrencia']}"


def test_investigar_segue_mesmo_sem_o_pdf(monkeypatch):
    """Portal fora do ar não pode impedir a investigação — só avisa."""
    from app.modules.download_vsky import service as dv

    alvo = _uma_ocorrencia()
    monkeypatch.setattr(dv, "obter_prontuario", lambda *a, **k: (_ for _ in ()).throw(
        ValueError("Credenciais do vSky não configuradas")))
    corpo = client.get(f"/reuniao_indicadores/investigar?id={alvo['id']}").json()

    assert corpo["success"] is True
    dados = corpo["data"]
    assert dados["prontuario"] is False
    assert "Credenciais" in dados["aviso"]
    # o destino continua oferecido: investigar sem PDF é melhor que não investigar
    assert dados["destino"].endswith(alvo["ocorrencia"])


def test_investigar_com_id_invalido():
    _login()
    resp = client.get("/reuniao_indicadores/investigar?id=99999999")
    assert resp.status_code == 404
    assert resp.json()["success"] is False
