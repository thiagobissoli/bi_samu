"""Testes do módulo Reunião de Indicadores."""

import pandas as pd
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
                # o contrato é uma ficha por viatura envolvida
                return [b"%PDF-1.4\nfake prontuario\n%%EOF"]
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


def test_drill_mostra_tempo_acima_do_teto_de_validade():
    """O teto tira o valor das médias, não da lista: quem abre o drill quer
    justamente enxergar a linha extrema."""
    from app.modules.indicadores import nucleo
    from app.modules.indicadores.constants import CAP_TEMPO

    _login()
    df = nucleo.carregar(1)
    if df.empty:
        return
    acima = df[(df["t_p3"] >= CAP_TEMPO["t_p3"]) & df["dt_ocorr"].notna()]
    if acima.empty:
        return

    deck = client.get("/reuniao_indicadores/api").json()["data"]
    ultimo = len(deck["slides"][1]["chart"]["labels"]) - 1
    corpo = client.get(f"/reuniao_indicadores/drill?chave=1:0:{ultimo}").json()
    linhas = {o["ocorrencia"]: o for o in corpo["data"]["ocorrencias"]}

    numeros = set(acima["ocorrencia"].dropna()) & set(linhas)
    if not numeros:
        return          # nenhum caso extremo neste recorte do drill
    alvo = linhas[sorted(numeros)[0]]
    assert alvo["p3"] is not None, "P3 medido sumiu da lista"


def test_drill_omite_apenas_o_que_nao_tem_marcacao():
    """None na lista significa ausência de marcação, não valor descartado."""
    from app.modules.indicadores import nucleo

    _login()
    deck = client.get("/reuniao_indicadores/api").json()["data"]
    ultimo = len(deck["slides"][1]["chart"]["labels"]) - 1
    corpo = client.get(f"/reuniao_indicadores/drill?chave=1:0:{ultimo}").json()
    linhas = corpo["data"]["ocorrencias"]
    if not linhas:
        return

    df = nucleo.carregar(1).set_index("id")
    for linha in linhas[:40]:
        bruto = df.loc[linha["id"], "t_p3"]
        if linha["p3"] is None:
            assert pd.isna(bruto) or float(bruto) <= 0, linha["ocorrencia"]
        else:
            assert float(bruto) > 0, linha["ocorrencia"]


# ------------------------------------- slides de desperdício (10 a 13)

def _universo_desperdicio():
    """Mesmo recorte do deck, calculado por fora para servir de referência."""
    from app.modules.indicadores import nucleo
    from app.modules.indicadores.constants import (
        MOTIVOS_EXCLUIDOS_DESPERDICIO, SITUACOES_DESPERDICIO)

    df = nucleo.carregar(1)
    if df.empty:
        return None
    cod = df["motivo"].fillna("").str.split(" ").str[0].str.upper()
    uni = df[df["dt_inicio_deslocamento"].notna()
             & ~cod.isin(MOTIVOS_EXCLUIDOS_DESPERDICIO)]
    sit = uni["situacao_atendimento"].fillna("").map(nucleo.norm_txt)
    cand = sit.isin(SITUACOES_DESPERDICIO)
    return {
        "universo": uni,
        "real": cand & uni["dt_chegada_no_local"].notna(),
        "evitado": cand & uni["dt_chegada_no_local"].isna(),
    }


def _slide(deck, inicio_do_titulo):
    return next(s for s in deck["slides"]
                if s["titulo"].startswith(inicio_do_titulo))


def test_slide_10_real_e_evitado_batem_com_o_calculo_direto():
    from app.modules.reuniao_indicadores.service import (
        ReuniaoIndicadoresService)

    dados = _universo_desperdicio()
    if dados is None:
        return
    deck = ReuniaoIndicadoresService(1).montar()
    semana = deck["semana"]
    na_semana = dados["universo"]["semana_iso"] == semana

    slide = _slide(deck, "Desperdícios operacionais")
    kpis = {k["label"].split(" ·")[0]: k["valor"] for k in slide["kpis"]}
    assert int(kpis["Desperdício REAL"]) == int((dados["real"] & na_semana).sum())
    assert int(kpis["Desperdício EVITADO"]) == int(
        (dados["evitado"] & na_semana).sum())
    assert int(kpis["Saídas efetivas"].replace(".", "")) == int(na_semana.sum())

    # real e evitado são recortes disjuntos do mesmo universo
    assert not (dados["real"] & dados["evitado"]).any()


def test_slide_10_kpi_do_periodo_fecha_com_o_proprio_grafico():
    """O KPI contava a semana corrente, ainda pela metade, enquanto o gráfico
    parava na última semana completa: 6.283 "em 34 semanas" ao lado de um
    gráfico de 34 semanas somando 6.235."""
    from app.modules.reuniao_indicadores.service import (
        ReuniaoIndicadoresService)

    deck = ReuniaoIndicadoresService(1).montar()
    slide = _slide(deck, "Desperdícios operacionais")
    periodo = next(k for k in slide["kpis"]
                   if k["label"] == "Desperdício REAL no período")
    total_kpi = int(periodo["valor"].replace(".", ""))

    series = {d["label"]: [x for x in d["data"] if x is not None]
              for d in slide["chart"]["datasets"]}
    real = next(v for k, v in series.items() if k.startswith("Real"))
    evitado = next(v for k, v in series.items() if k.startswith("Evitado"))

    assert total_kpi == sum(real), "KPI do período não fecha com o gráfico"
    assert f"evitado {sum(evitado)}" in periodo["sub"]
    assert f"{len(real)} semanas" in periodo["sub"]


def test_slide_11_usa_mais_usb_nao_passa_do_total_real():
    from app.modules.reuniao_indicadores.service import (
        ReuniaoIndicadoresService)

    deck = ReuniaoIndicadoresService(1).montar()
    slide = _slide(deck, "Distribuição de desperdício por tipo")
    kpis = {k["label"]: int(k["valor"]) for k in slide["kpis"]}
    usa = kpis["USA · real · últ. sem."]
    usb = kpis["USB · real · últ. sem."]
    total = kpis["Total real · última semana"]
    assert usa + usb <= total          # VIR/outros podem existir
    # e o total bate com o slide 10
    dez = _slide(deck, "Desperdícios operacionais")
    assert total == int(next(k["valor"] for k in dez["kpis"]
                             if k["label"].startswith("Desperdício REAL ·")))


def test_slide_12_motivos_sao_do_real_da_ultima_semana():
    """O gráfico mostra o top N; a soma não pode passar do total real."""
    from app.modules.reuniao_indicadores.service import (
        ReuniaoIndicadoresService)

    deck = ReuniaoIndicadoresService(1).montar()
    slide = _slide(deck, "Motivos para o desperdício")
    assert "REAL" in slide["subtitulo"]
    dados = slide["chart"]["datasets"][0]["data"]
    total_real = int(next(k["valor"] for k in
                          _slide(deck, "Desperdícios operacionais")["kpis"]
                          if k["label"].startswith("Desperdício REAL ·")))
    assert 0 < sum(dados) <= total_real
    assert dados == sorted(dados, reverse=True), "top N fora de ordem"


def test_slide_13_tipos_somam_exatamente_o_total_real():
    """Aqui não há corte de top N: toda situação do real entra na rosca."""
    from app.modules.reuniao_indicadores.service import (
        ReuniaoIndicadoresService)

    deck = ReuniaoIndicadoresService(1).montar()
    slide = _slide(deck, "Distribuição de tipos de desperdício")
    dados = slide["chart"]["datasets"][0]["data"]
    total_real = int(next(k["valor"] for k in
                          _slide(deck, "Desperdícios operacionais")["kpis"]
                          if k["label"].startswith("Desperdício REAL ·")))
    assert sum(dados) == total_real
    assert slide["chart"]["centro"]["valor"] == str(total_real)


def test_drill_dos_slides_de_desperdicio_traz_as_ocorrencias_certas():
    """Cada ponto clicado deve listar exatamente as ocorrências que o formam."""
    from app.modules.reuniao_indicadores.service import (
        ReuniaoIndicadoresService)

    _login()
    deck = client.get("/reuniao_indicadores/api").json()["data"]
    servico = ReuniaoIndicadoresService(1)
    indice = next(i for i, s in enumerate(deck["slides"])
                  if s["titulo"].startswith("Desperdícios operacionais"))
    slide = deck["slides"][indice]
    ultimo = len(slide["chart"]["labels"]) - 1

    for dsi, serie in enumerate(slide["chart"]["datasets"]):
        esperado = serie["data"][ultimo]
        ids = servico.ids_drill(f"{indice}:{dsi}:{ultimo}")
        assert len(ids) == esperado, (serie["label"], len(ids), esperado)
