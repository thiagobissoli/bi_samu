"""Testes do módulo Indicadores."""

import pytest
from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app
from app.modules.indicadores.constants import TEMAS

client = TestClient(app)


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def test_requer_login():
    resp = client.get("/indicadores/", headers={"accept": "text/html"},
                      follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_index():
    _login()
    resp = client.get("/indicadores/", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "Indicadores" in resp.text


def test_todas_as_paginas_renderizam():
    _login()
    for tema in TEMAS:
        resp = client.get(f"/indicadores/{tema}", headers={"accept": "text/html"})
        assert resp.status_code == 200, f"falha em {tema}"
        assert TEMAS[tema][0] in resp.text, f"título ausente em {tema}"


def test_api_todos_os_temas():
    _login()
    for tema in TEMAS:
        resp = client.get(f"/indicadores/api/{tema}")
        assert resp.status_code == 200, f"falha em {tema}"
        corpo = resp.json()
        assert corpo["success"] is True, f"success falso em {tema}"
        assert "charts" in corpo["data"], f"payload sem charts em {tema}"


def test_filtros_aplicam():
    _login()
    resp = client.get("/indicadores/api/processos"
                      "?data_inicial=2026-07-27&data_final=2026-07-28"
                      "&convenio=1&transporte=Pré-hospitalar")
    assert resp.status_code == 200
    dados = resp.json()["data"]
    assert dados["total_filtrado"] >= 0


def test_filtro_recurso_usa_usb():
    _login()
    total = client.get("/indicadores/api/unidade").json()["data"]["total_filtrado"]
    usa = client.get("/indicadores/api/unidade?recurso=USA").json()["data"]["total_filtrado"]
    usb = client.get("/indicadores/api/unidade?recurso=USB").json()["data"]["total_filtrado"]
    assert usa + usb <= total
    # a página renderiza o novo filtro
    resp = client.get("/indicadores/unidade", headers={"accept": "text/html"})
    assert 'name="recurso"' in resp.text


def test_filtro_codigo_da_ocorrencia():
    _login()
    total = client.get("/indicadores/api/codigos").json()["data"]["total_filtrado"]
    verm = client.get("/indicadores/api/codigos?codigo=Vermelho").json()["data"]["total_filtrado"]
    assert 0 <= verm <= total
    resp = client.get("/indicadores/codigos", headers={"accept": "text/html"})
    assert 'name="codigo"' in resp.text


def test_filtros_multipla_selecao():
    _login()
    verm = client.get("/indicadores/api/codigos?codigo=Vermelho").json()["data"]["total_filtrado"]
    amar = client.get("/indicadores/api/codigos?codigo=Amarelo").json()["data"]["total_filtrado"]
    ambos = client.get("/indicadores/api/codigos?codigo=Vermelho&codigo=Amarelo"
                       ).json()["data"]["total_filtrado"]
    assert ambos == verm + amar
    # múltiplos filtros combinados (AND entre campos, OR dentro do campo)
    usa_usb = client.get("/indicadores/api/unidade?recurso=USA&recurso=USB"
                         ).json()["data"]["total_filtrado"]
    so_usa = client.get("/indicadores/api/unidade?recurso=USA").json()["data"]["total_filtrado"]
    assert usa_usb >= so_usa


def test_selecao_de_profissionais():
    from urllib.parse import quote

    _login()
    geral = client.get("/indicadores/api/prof-tarm").json()["data"]
    if not geral["profissionais_opcoes"]:
        return  # sem dados importados
    nomes = geral["profissionais_opcoes"][:2]
    qs = "&".join("profissional=" + quote(n) for n in nomes)
    selecao = client.get(f"/indicadores/api/prof-tarm?{qs}").json()["data"]
    # séries temporais com um dataset por profissional selecionado
    assert selecao["profissionais_selecionados"] == nomes
    volume_semanal = selecao["charts"][0]
    assert volume_semanal["tipo"] == "line"
    assert [ds["label"] for ds in volume_semanal["datasets"]] == nomes
    assert len(selecao["tables"][0]["linhas"]) == len(nomes)
    # sem seleção: uma única linha "Geral"
    assert [ds["label"] for ds in geral["charts"][0]["datasets"]] == ["Geral"]
    # indicadores gerais permanecem sobre o papel inteiro
    assert selecao["kpis"][0]["valor"] == geral["kpis"][0]["valor"]
    # seletor só aparece nos dashboards de profissional
    pagina = client.get("/indicadores/prof-tarm",
                        headers={"accept": "text/html"}).text
    assert 'name="profissional"' in pagina
    outra = client.get("/indicadores/tempo-central",
                       headers={"accept": "text/html"}).text
    assert 'name="profissional"' not in outra


def test_botoes_de_exportacao():
    _login()
    page = client.get("/indicadores/processos", headers={"accept": "text/html"}).text
    # botões de exportação nos gráficos e tabelas
    assert page.count('data-fmt="png"') >= 2
    assert page.count('data-fmt="pdf"') >= 2
    assert page.count('data-fmt="xlsx"') >= 2
    assert 'id="tabela-1"' in page
    # bibliotecas vendorizadas referenciadas e servidas
    for asset in ["vendor/export/xlsx.full.min.js",
                  "vendor/export/jspdf.umd.min.js",
                  "vendor/export/jspdf.plugin.autotable.min.js",
                  "vendor/export/html2canvas.min.js"]:
        assert asset in page
        resp = client.get(f"/static/{asset}")
        assert resp.status_code == 200, asset


def test_filtros_unidade_cidade_risco():
    _login()
    total = client.get("/indicadores/api/processos").json()["data"]["total_filtrado"]
    por_cidade = client.get("/indicadores/api/processos?cidade=SERRA"
                            ).json()["data"]["total_filtrado"]
    assert 0 < por_cidade < total
    combinado = client.get(
        "/indicadores/api/processos?cidade=SERRA&cidade=VITORIA"
        "&risco=Emergência").json()["data"]["total_filtrado"]
    assert 0 <= combinado <= total
    page = client.get("/indicadores/processos", headers={"accept": "text/html"}).text
    for campo in ('name="unidade"', 'name="cidade"', 'name="risco"'):
        assert campo in page


def test_p4_p41_p42():
    _login()
    d = client.get("/indicadores/api/processos").json()["data"]
    rotulos = [k["label"] for k in d["kpis"]]
    assert "P4 — Chegada" in rotulos
    assert "P4.1 — Saída de base" in rotulos
    assert "P4.2 — Deslocamento" in rotulos
    formulas = {l[0]: l[1] for l in d["tables"][0]["linhas"]}
    assert formulas["P4 — Chegada"] == "Chegada no local − Data controlador"
    assert formulas["P4.1 — Saída de base"] == "Início deslocamento − Data controlador"
    assert formulas["P4.2 — Deslocamento"] == "Chegada no local − Início deslocamento"


def test_tempo_resposta_primeira_chegada():
    """Ocorrência com N empenhos: só a primeira chegada tem tempo_resposta."""
    import pandas as pd

    from app.modules.indicadores import nucleo

    df = nucleo.carregar(1)
    if df.empty:
        return
    com_tr_possivel = df[df["dt_chegada_no_local"].notna()
                         & df["ocorrencia"].notna()]
    multi = com_tr_possivel.groupby("ocorrencia").size()
    multi = multi[multi > 1]
    if multi.empty:
        return
    # em toda ocorrência multi-empenho, exatamente 1 linha carrega o tempo
    amostra = multi.index[:20]
    for oc in amostra:
        grupo = df[df["ocorrencia"] == oc]
        assert grupo["tempo_resposta"].notna().sum() == 1, oc
        linha = grupo[grupo["tempo_resposta"].notna()].iloc[0]
        assert linha["dt_chegada_no_local"] == grupo["dt_chegada_no_local"].min()
    # total de tempos = total de ocorrências com chegada (+ sem número)
    esperado = com_tr_possivel["ocorrencia"].nunique() + int(
        (df["dt_chegada_no_local"].notna() & df["ocorrencia"].isna()).sum())
    assert int(df["tempo_resposta"].notna().sum()) == esperado


def test_pagina_desempenho():
    from app.modules.indicadores.constants import (DIMENSOES_DESEMPENHO,
                                                   METRICAS_DESEMPENHO)

    _login()
    page = client.get("/indicadores/desempenho", headers={"accept": "text/html"})
    assert page.status_code == 200
    assert "Análise de Desempenho" in page.text

    # API: padrão (tempo-resposta × unidade) e uma combinação profissional
    d = client.get("/indicadores/api/desempenho").json()["data"]
    assert d["metrica"] == "tempo-resposta" and d["dimensao"] == "unidade"
    if d["chart_bar"]:
        dados_bar = d["chart_bar"]["datasets"][0]["data"]
        assert dados_bar == sorted(dados_bar, reverse=True)  # pior primeiro
        assert "#dc3545" in d["chart_bar"]["datasets"][0]["colors"]
        assert d["chart_gauss"]["datasets"][0]["label"].startswith("Geral")

    d2 = client.get("/indicadores/api/desempenho?metrica=cena"
                    "&dimensao=condutor&min_n=20").json()["data"]
    assert d2["rotulo_metrica"] == METRICAS_DESEMPENHO["cena"][1]
    assert d2["rotulo_dimensao"] == DIMENSOES_DESEMPENHO["condutor"][1]

    # métrica/dimensão inválidas caem no padrão
    d3 = client.get("/indicadores/api/desempenho?metrica=x&dimensao=y"
                    ).json()["data"]
    assert d3["metrica"] == "tempo-resposta" and d3["dimensao"] == "unidade"


def test_tema_invalido_redireciona():
    _login()
    resp = client.get("/indicadores/nao-existe", headers={"accept": "text/html"},
                      follow_redirects=False)
    assert resp.status_code == 303


def test_news_modificada():
    import pandas as pd

    from app.modules.indicadores.nucleo import _derivar_news

    df = pd.DataFrame({
        "fr": [16.0, 26.0, None, 16.0],
        "fc": [80.0, 135.0, 80.0, 80.0],
        "pas": [120.0, 85.0, 120.0, 120.0],
        "glasgow": [15.0, 7.0, 15.0, 14.0],
        "glicemia": [100.0, 35.0, None, None],
    })
    _derivar_news(df)
    # caso 1: tudo normal -> 0 pontos, risco Baixo
    assert df.loc[0, "news_total"] == 0
    assert df.loc[0, "news_risco"] == "Baixo"
    # caso 2: FR 3 + FC 3 + PAS 3 + GCS 3 + glicemia 3 = 15 -> Alto
    assert df.loc[1, "news_total"] == 15
    assert df.loc[1, "news_risco"] == "Alto"
    # caso 3: núcleo incompleto (sem FR) -> sem escore
    assert pd.isna(df.loc[2, "news_total"])
    # caso 4: Glasgow 14 -> 1 ponto, Baixo
    assert df.loc[3, "news_total"] == 1
    assert df.loc[3, "news_risco"] == "Baixo"


def test_ranking_saida_base():
    """Tabela de ranking mensal de P4.1 por unidade (verde ≤ 2 min)."""
    _login()
    dados = client.get("/indicadores/api/tempo-saida-base").json()["data"]
    ranking = [t for t in dados["tables"]
               if t["titulo"].startswith("Ranking de Saída de Base")]
    assert ranking, "tabela de ranking ausente"
    t = ranking[0]
    assert t["colunas"][0] == "Unidade"
    assert t["colunas"][1] == "P4.1 (média)"
    assert "Posição" in t["colunas"][2] and "Variação" in t["colunas"][3]
    # posições em ordem crescente (1..N) e células com cor
    posicoes = [linha[2] for linha in t["linhas"]]
    assert posicoes == list(range(1, len(posicoes) + 1))
    cores = {linha[1]["cls"] for linha in t["linhas"]}
    assert cores <= {"table-success", "table-danger"}
    # verde só até 2 min: primeiro é verde, e todo vermelho vem após verde
    assert t["linhas"][0][1]["cls"] == "table-success"


def test_temas_volume():
    """Páginas de Total de Saídas de Ambulâncias e Total de Regulações."""
    _login()
    for tema, dataset0 in (("saidas-ambulancia", "Total"),
                           ("regulacoes", "Regulações")):
        dados = client.get(f"/indicadores/api/{tema}").json()["data"]
        titulos = [c["titulo"] for c in dados["charts"]]
        assert any("por dia" in x for x in titulos)
        assert any("por semana" in x for x in titulos)
        assert any("por mês" in x for x in titulos)
        assert dados["charts"][0]["datasets"][0]["label"] == dataset0
        assert dados["kpis"], tema
    # saídas: datasets Total/USA/USB
    dados = client.get("/indicadores/api/saidas-ambulancia").json()["data"]
    assert [d["label"] for d in dados["charts"][0]["datasets"]] == \
        ["Total", "USA", "USB"]


def test_desconto_p41():
    """Desconto de transmissão (rede móvel/GPS) aplicado ao P4.1."""
    import pandas as pd

    from app.modules.indicadores.nucleo import (DESCONTO_P41_PADRAO,
                                                _com_desconto, desconto_p41)

    assert DESCONTO_P41_PADRAO == 45
    bruto = pd.Series([100.0, 46.0, 45.0, 30.0, 0.0, -5.0, None])
    ajustado = _com_desconto(bruto, 45)
    assert ajustado[0] == 55.0        # acima do atraso: subtrai
    assert ajustado[1] == 1.0
    # Abaixo (ou igual) ao próprio atraso o desconto NÃO se aplica: a
    # marcação não passou por ele. Achatar num piso fabricaria valor e
    # inverteria a ordem entre registros.
    assert ajustado[2] == 45.0
    assert ajustado[3] == 30.0
    assert ajustado[4] == 0.0         # inválidos permanecem como estavam
    assert ajustado[5] == -5.0
    assert pd.isna(ajustado[6])
    # nenhum valor é fabricado: o que não recebe desconto sai como medido
    curtos = pd.Series([1.0, 9.0, 44.0])
    assert _com_desconto(curtos, 45).tolist() == curtos.tolist()
    # desconto 0 = passthrough
    assert _com_desconto(bruto, 0) is bruto
    # leitura da configuração devolve inteiro >= 0
    assert isinstance(desconto_p41(1), int) and desconto_p41(1) >= 0


def test_relacao_news_codigo_risco():
    """Relação NEWS × código × risco inicial no dashboard sinais-vitais."""
    _login()
    dados = client.get("/indicadores/api/sinais-vitais").json()["data"]
    titulos = [c["titulo"] for c in dados["charts"]]
    assert any("NEWS médio por código da ocorrência" in t for t in titulos)
    assert any("NEWS médio por risco inicial" in t for t in titulos)
    # a restrição da base (só quem tem NEWS) é declarada nos títulos
    assert all("pacientes com NEWS aferida" in t
               for t in titulos if "NEWS médio por" in t or "Bandas NEWS" in t)
    empilhados = [c for c in dados["charts"] if c.get("stacked")]
    assert len(empilhados) == 2
    for c in empilhados:
        assert c["max_y"] == 100
        assert [d["label"] for d in c["datasets"]] == \
            ["Baixo", "Baixo-Médio", "Médio", "Alto"]
        # cada categoria soma ~100%
        for i in range(len(c["labels"])):
            soma = sum(d["data"][i] for d in c["datasets"])
            assert 99.0 <= soma <= 101.0, (c["labels"][i], soma)
    # tabela cruzada com células coloridas
    cruzada = [t for t in dados["tables"]
               if "Risco inicial (triagem) × Código" in t["titulo"]]
    assert cruzada
    ultima = cruzada[0]["linhas"][-1]
    assert ultima[0] == "Todos"
    assert isinstance(ultima[-1], dict) and ultima[-1]["cls"].startswith("table-")
    # KPIs: cobertura declarada + antecipação/subtriagem da regulação
    rotulos = [k["label"] for k in dados["kpis"]]
    assert "Cobertura da NEWS" in rotulos
    assert "NEWS Alto → triagem grave" in rotulos
    assert "NEWS Alto no risco leve" in rotulos


def test_limpeza_de_vazios_independe_da_versao_do_pandas():
    """'' e '---' têm de virar nulo, seja qual for o dtype do pandas.

    No pandas 3 as colunas de texto deixam de ser `object`; testar só por
    object fazia a limpeza ser pulada inteira — e 350 mil registros sem
    óbito passavam a contar como óbito constatado.
    """
    import pandas as pd

    from app.modules.indicadores import nucleo

    df = nucleo.carregar(1)
    for coluna in ("obito", "risco_inicial", "transporte",
                   "situacao_atendimento", "codigo_da_ocorrencia"):
        valores = {str(v).strip() for v in df[coluna].dropna().unique()}
        assert not (valores & {"", "---", "nan", "none", "null"}), coluna

    # o derivado de óbito só conta quem tem registro de óbito de fato
    obitos = df[df["obito_constatado"]]
    assert len(obitos) > 0
    assert obitos["obito"].notna().all()
    assert not obitos["obito"].astype(str).str.strip().eq("").any()
    # e nunca marca "Não houve óbito" como óbito
    assert not obitos["obito"].map(
        lambda v: nucleo.norm_txt(v) == "NAO HOUVE OBITO").any()

    # a limpeza precisa pegar o dtype de texto nativo do pandas 3
    serie = pd.Series(["", "---", "ok"], dtype="str")
    assert (pd.api.types.is_string_dtype(serie)
            or serie.dtype == object), "checagem de dtype não cobre este pandas"


def test_p4_1_mostra_a_memoria_de_calculo():
    """O P4.1 exibido tem de fechar com os horários mostrados na tela.

    O valor já vem com o desconto do atraso de transmissão; sem declarar
    o bruto e o desconto, quem confere pela cadeia do chamado encontra
    uma diferença inexplicada.
    """
    import pandas as pd

    from app.modules.indicadores import nucleo
    from app.modules.indicadores.ocorrencia import (indicadores_da_ocorrencia,
                                                    mmss)

    df = nucleo.carregar(1)
    desconto = nucleo.desconto_p41()
    validos = df[df["dt_inicio_deslocamento"].notna()
                 & df["dt_data_controlador"].notna()]
    bruto = (validos["dt_inicio_deslocamento"]
             - validos["dt_data_controlador"]).dt.total_seconds()

    # caso comum: bruto acima do desconto
    normal = validos[bruto > desconto + 60]
    if not normal.empty:
        r = normal.iloc[0]
        item = next(i for i in indicadores_da_ocorrencia(1, int(r["id"]))
                    if i["rotulo"].startswith("P4.1"))
        b = (r["dt_inicio_deslocamento"]
             - r["dt_data_controlador"]).total_seconds()
        assert mmss(b) in item["sub"], item["sub"]
        assert mmss(desconto) in item["sub"]
        # o valor exibido é exatamente bruto − desconto
        assert item["valor"] == mmss(b - desconto)

    # bruto abaixo do desconto: o valor medido vale como está, e o
    # subtítulo explica por que não houve subtração
    curto = validos[(bruto > 0) & (bruto < desconto)]
    if not curto.empty:
        r = curto.iloc[0]
        b = (r["dt_inicio_deslocamento"]
             - r["dt_data_controlador"]).total_seconds()
        item = next(i for i in indicadores_da_ocorrencia(1, int(r["id"]))
                    if i["rotulo"].startswith("P4.1"))
        assert "sem desconto" in item["sub"], item["sub"]
        assert item["valor"] == mmss(b)     # preserva o medido


# ------------------------------------------------ Auditoria de Ocorrências

def test_municipio_da_base_sai_do_nome_da_unidade():
    """"USA 10 - VITORIA" tem base VITORIA; complemento que não é município
    (aeromédico, NEP, VIR-01) não vira base."""
    from app.modules.indicadores import nucleo

    df = nucleo.carregar(1)
    if df.empty:
        pytest.skip("sem dados importados")
    com_sufixo = df[df["unidade"].fillna("").str.contains(" - ")]
    assert not com_sufixo.empty

    amostra = com_sufixo[com_sufixo["unidade"].str.endswith("VITORIA")]
    if not amostra.empty:
        assert (amostra["municipio_base"] == "VITORIA").all()

    # complementos que não são município ficam sem base
    for nome in ("USA - AEROMEDICO", "USA - NEP 33", "VIR - 01"):
        linhas = df[df["unidade"] == nome]
        if not linhas.empty:
            assert linhas["municipio_base"].isna().all(), nome


def test_fora_do_municipio_e_nulo_quando_falta_um_dos_lados():
    """Sem base ou sem cidade não dá para afirmar nada — tem que ser nulo,
    nunca False (que contaria como atendimento do próprio município)."""
    from app.modules.indicadores import nucleo

    df = nucleo.carregar(1)
    if df.empty:
        pytest.skip("sem dados importados")
    incompleto = df[df["municipio_base"].isna() | df["cidade_norm"].isna()]
    assert incompleto["fora_do_municipio"].isna().all()

    completo = df[df["municipio_base"].notna() & df["cidade_norm"].notna()]
    assert completo["fora_do_municipio"].notna().all()
    # e o valor confere com a comparação direta
    esperado = completo["municipio_base"] != completo["cidade_norm"]
    assert (completo["fora_do_municipio"].astype(bool) == esperado).all()


def test_auditoria_conta_uma_linha_por_ocorrencia():
    """Ocorrência com vários empenhos conta uma vez, pela viatura que atendeu."""
    import pandas as pd

    from app.modules.indicadores.service import IndicadoresService

    service = IndicadoresService(1)
    df = nucleo_df()
    if df.empty:
        pytest.skip("sem dados importados")
    principal = service._auditoria_principal(df)
    com_numero = principal[principal["ocorrencia"].notna()]
    assert not com_numero["ocorrencia"].duplicated().any()

    # a escolhida é a que chegou primeiro, quando alguma chegou
    empenhos = df[df["unidade"].notna()]
    multiplos = empenhos[empenhos.duplicated("ocorrencia", keep=False)
                         & empenhos["ocorrencia"].notna()]
    chegaram = multiplos[multiplos["dt_chegada_no_local"].notna()]
    if not chegaram.empty:
        numero = chegaram.iloc[0]["ocorrencia"]
        grupo = chegaram[chegaram["ocorrencia"] == numero]
        escolhida = principal[principal["ocorrencia"] == numero]
        assert len(escolhida) == 1
        assert (escolhida.iloc[0]["dt_chegada_no_local"]
                == grupo["dt_chegada_no_local"].min())


def nucleo_df():
    from app.modules.indicadores import nucleo
    return nucleo.carregar(1)


def test_dashboard_auditoria_ocorrencias():
    from app.modules.indicadores.service import IndicadoresService

    dados = IndicadoresService(1).dashboard("auditoria-ocorrencias", {})
    if not dados["kpis"]:
        pytest.skip("sem dados importados")

    rotulos = [k["label"] for k in dados["kpis"]]
    assert "Viatura da casa" in rotulos and "Viatura de fora" in rotulos
    # os dois percentuais de cobertura somam 100%
    casa = float(next(k for k in dados["kpis"]
                      if k["label"] == "Viatura da casa")["valor"].rstrip("%"))
    fora = float(next(k for k in dados["kpis"]
                      if k["label"] == "Viatura de fora")["valor"].rstrip("%"))
    assert abs(casa + fora - 100) < 0.2

    titulos = [t["titulo"] for t in dados["tables"]]
    assert any("Cobertura por município" in t for t in titulos)
    assert any("Descumprimento de meta" in t for t in titulos)


def test_auditoria_indicadores_traz_meta_e_referencia():
    """Cada linha mostra a meta, o % que a ultrapassou e o que o serviço
    realmente pratica (mediana e p90)."""
    import re

    from app.modules.indicadores.service import IndicadoresService

    dados = IndicadoresService(1).dashboard("auditoria-ocorrencias", {})
    tabelas = [t for t in dados["tables"] if "Descumprimento" in t["titulo"]]
    if not tabelas:
        pytest.skip("sem dados importados")
    tabela = tabelas[0]
    assert tabela["colunas"][-2:] == ["Mediana do serviço", "p90 do serviço"]

    rotulos = [linha[0] for linha in tabela["linhas"]]
    for esperado in ("P1 · Atendimento TARM", "P4.1 · Saída de base",
                     "Tempo de Resposta"):
        assert any(r.startswith(esperado) for r in rotulos), esperado

    for linha in tabela["linhas"]:
        _, meta, n, pct, mediana, p90 = linha
        assert n > 0
        for tempo in (mediana, p90):
            assert re.fullmatch(r"\d{2,}:\d{2}", tempo), tempo
        if isinstance(meta, dict):          # P8 não tem meta
            assert meta["v"] == "sem meta" and pct["v"] == "—"
        else:
            assert re.fullmatch(r"\d{1,2}\.\d%", pct["v"]), pct["v"]
            assert pct["cls"] in ("table-success", "table-warning",
                                  "table-danger")


def test_cor_do_indicador_segue_a_referencia_do_servico():
    """Vermelho só quando a mediana já estourou a meta; amarelo quando
    apenas o p90 estoura; verde quando nem o p90 estoura."""
    from app.modules.indicadores.service import IndicadoresService

    dados = IndicadoresService(1).dashboard("auditoria-ocorrencias", {})
    tabelas = [t for t in dados["tables"] if "Descumprimento" in t["titulo"]]
    if not tabelas:
        pytest.skip("sem dados importados")

    def segundos(mmss: str) -> int:
        m, s = mmss.split(":")
        return int(m) * 60 + int(s)

    metas = IndicadoresService(1)._metas_tempo()
    for linha in tabelas[0]["linhas"]:
        rotulo, meta, _, pct, mediana, p90 = linha
        if isinstance(meta, dict) or "P2 ·" in rotulo:
            continue                       # sem meta / meta variável por cor
        limite = segundos(meta)
        assert limite in metas.values()
        if segundos(mediana) > limite:
            assert pct["cls"] == "table-danger", rotulo
        elif segundos(p90) > limite:
            assert pct["cls"] == "table-warning", rotulo
        else:
            assert pct["cls"] == "table-success", rotulo


def test_meta_ajustavel_em_configuracoes():
    """A meta pode ser mudada em /configuracoes sem tocar no código."""
    from app.core.config_service import set_config
    from app.core.database import SessionLocal
    from app.modules.indicadores.constants import PREFIXO_CONFIG_META
    from app.modules.indicadores.service import IndicadoresService

    chave = f"{PREFIXO_CONFIG_META}tempo_resposta_segundos"
    service = IndicadoresService(1)
    assert service._metas_tempo()["tempo_resposta"] == 600
    db = SessionLocal()
    try:
        set_config(db, chave, "900", 1)
        assert service._metas_tempo()["tempo_resposta"] == 900
        set_config(db, chave, None, 1)
        assert service._metas_tempo()["tempo_resposta"] == 600
    finally:
        set_config(db, chave, None, 1)
        db.close()


# ------------------------------------------- Tempo de Deslocamento (P4.2)

def test_dashboard_tempo_deslocamento():
    from app.modules.indicadores.service import IndicadoresService

    dados = IndicadoresService(1).dashboard("tempo-deslocamento", {})
    assert dados["titulo"] == "Tempo de Deslocamento (P4.2)"
    if not dados["kpis"]:
        pytest.skip("sem dados importados")

    titulos = [c["titulo"] for c in dados["charts"]]
    # cortes que respondem por trânsito e por distância
    for esperado in ("por hora do dia", "por dia da semana", "por plantão",
                     "por cidade", "por unidade"):
        assert any(esperado in t for t in titulos), esperado
    assert all("Deslocamento (P4.2)" in t for t in titulos)


def test_comparacao_de_deslocamento_exclui_viatura_de_outro_municipio():
    """Viatura que veio de fora demora por distância, não por desempenho —
    deixá-la na tabela a colocaria no vermelho sem ter culpa."""
    from app.modules.indicadores.service import IndicadoresService

    service = IndicadoresService(1)
    df = nucleo_df()
    if df.empty:
        pytest.skip("sem dados importados")
    tabela = service._tabela_deslocamento_por_cidade(df)
    if tabela is None:
        pytest.skip("sem deslocamentos válidos")

    # nenhuma dupla cidade × unidade da tabela pode ser de outro município
    de_fora = df[df["fora_do_municipio"].eq(True)]
    pares_de_fora = set(zip(de_fora["cidade"], de_fora["unidade_curta"]))
    for linha in tabela["linhas"]:
        cidade, unidade = linha[0], linha[1]
        if (cidade, unidade) in pares_de_fora:
            # o par só é aceitável se a mesma unidade também atende dali
            proprios = df[(df["cidade"] == cidade)
                          & (df["unidade_curta"] == unidade)
                          & df["fora_do_municipio"].eq(False)]
            assert not proprios.empty, f"{unidade} não é de {cidade}"


def test_deslocamento_compara_com_a_mediana_da_propria_cidade():
    from app.modules.indicadores.service import IndicadoresService

    service = IndicadoresService(1)
    df = nucleo_df()
    if df.empty:
        pytest.skip("sem dados importados")
    tabela = service._tabela_deslocamento_por_cidade(df)
    if tabela is None:
        pytest.skip("sem deslocamentos válidos")

    def segundos(mmss: str) -> int:
        m, s = mmss.split(":")
        return int(m) * 60 + int(s)

    por_cidade = {}
    for linha in tabela["linhas"]:
        cidade, _, n, unidade_mediana, cidade_mediana, diferenca = linha
        assert n >= 5
        # a referência é a mesma para todas as unidades da cidade
        por_cidade.setdefault(cidade, cidade_mediana)
        assert por_cidade[cidade] == cidade_mediana, cidade
        # e a diferença fecha com as duas medianas
        esperado = segundos(unidade_mediana["v"]) - segundos(cidade_mediana)
        sinal = -1 if diferenca["v"].startswith("−") else 1
        assert abs(sinal * segundos(diferenca["v"][1:]) - esperado) <= 1
        # acima da mediana nunca sai verde
        if esperado > 0:
            assert diferenca["cls"] in ("table-warning", "table-danger")


# --------------------------------------------- Calendários de Indicadores

def test_pagina_de_calendarios_renderiza():
    _login()
    resp = client.get("/indicadores/calendarios?unidades=3",
                      headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert "Calendários de Indicadores" in resp.text
    # os cinco indicadores estão oferecidos
    for rotulo in ("T. Resposta", "T. Saída de base (P4.1)",
                   "T. Deslocamento (P4.2)", "T. Cena (P5-7)",
                   "Transf. Cuidados (P9)"):
        assert rotulo in resp.text, rotulo
    assert "Pareto desta unidade" in resp.text


def test_calendario_agrupa_por_dia_de_plantao_e_turno():
    """A média de cada célula tem que bater com a média calculada à mão."""
    import pandas as pd

    from app.modules.indicadores.service import IndicadoresService

    service = IndicadoresService(1)
    dados = service.calendarios({}, ["tempo-resposta"], "mes", False, 7,
                                unidades=3)
    if not dados["unidades"]:
        pytest.skip("sem dados importados")

    df = nucleo_df()
    unidade = dados["unidades"][0]
    alvo = df[(df["unidade_curta"] == unidade["unidade"])
              & (df["tempo_resposta"] > 0)
              & (df["tempo_resposta"] < 10800)]

    conferidas = 0
    for semana in unidade["grade"]:
        for dia in semana:
            if dia["fora"]:
                continue
            data = pd.Timestamp(dia["iso"]).date()
            for faixa in dia["faixas"]:
                for turno, marca in (("diurno", "Diurno"),
                                     ("noturno", "Noturno")):
                    if faixa[turno] == "—":
                        continue
                    recorte = alvo[(alvo["plantao_data"] == data)
                                   & (alvo["turno"] == marca)]
                    assert len(recorte) == faixa[f"{turno}_n"], (data, turno)
                    esperado = recorte["tempo_resposta"].mean() / 60
                    minutos = int(faixa[turno].split(":")[0]) \
                        + int(faixa[turno].split(":")[1]) / 60
                    # mm:ss arredonda ao segundo: meio segundo de folga
                    assert abs(minutos - esperado) < 0.009, (data, turno)
                    conferidas += 1
    assert conferidas > 0, "nenhuma célula preenchida para conferir"


def test_pareto_marca_os_20_por_cento_piores():
    from app.modules.indicadores.service import IndicadoresService

    limite = IndicadoresService._pareto_limite
    valores = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    # p80 exato: o 8º valor em ordem crescente
    assert limite(valores, False) == 8
    # aproximado: k = max(3, 20% de 10) = 3 piores -> começa no 8
    assert limite(valores, True) == 8
    # com poucas medições o p80 não destacaria ninguém; o modo aproximado
    # garante ao menos 3
    assert limite([5, 9], False) == 9
    assert limite([5, 9], True) == 5
    assert limite([], False) is None


def test_pareto_e_por_unidade_nao_do_servico():
    """Cada unidade é comparada consigo mesma — quem atende área extensa não
    pode ser cobrada pelo tempo de quem atende área urbana."""
    from app.modules.indicadores.service import IndicadoresService

    dados = IndicadoresService(1).calendarios({}, ["deslocamento"], "mes",
                                              False, 31, unidades=8)
    if len(dados["unidades"]) < 2:
        pytest.skip("dados insuficientes")
    limites = {u["unidade"]: u["limites"]["deslocamento"]
               for u in dados["unidades"]
               if u["limites"]["deslocamento"] is not None}
    assert len(set(limites.values())) > 1, \
        "todas as unidades com o mesmo limite sugere Pareto global"


def test_calendario_respeita_teto_de_unidades_e_avisa():
    from app.modules.indicadores.service import IndicadoresService

    dados = IndicadoresService(1).calendarios({}, None, "mes", False, 31,
                                              unidades=2)
    if not dados["unidades"]:
        pytest.skip("sem dados importados")
    assert len(dados["unidades"]) == 2
    assert dados["unidades_omitidas"] == dados["unidades_no_filtro"] - 2
    assert dados["unidades_omitidas"] > 0

    _login()
    html = client.get("/indicadores/calendarios?unidades=2",
                      headers={"accept": "text/html"}).text
    assert "fora da página" in html


def test_calendario_modo_semana_tem_uma_linha_de_sete_dias():
    from app.modules.indicadores.service import IndicadoresService

    dados = IndicadoresService(1).calendarios({}, ["tempo-resposta"], "semana",
                                              False, 31, unidades=2)
    if not dados["unidades"]:
        pytest.skip("sem dados importados")
    grade = dados["unidades"][0]["grade"]
    assert len(grade) == 1 and len(grade[0]) == 7
    assert [c["rotulo"] for c in grade[0]] == [
        "Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"]


def test_calendario_com_filtro_sem_resultado():
    from app.modules.indicadores.service import IndicadoresService

    dados = IndicadoresService(1).calendarios(
        {"data_inicial": "2000-01-01", "data_final": "2000-01-02"})
    assert dados["unidades"] == [] and dados["periodo"] is None

    _login()
    html = client.get("/indicadores/calendarios"
                      "?data_inicial=2000-01-01&data_final=2000-01-02",
                      headers={"accept": "text/html"}).text
    assert "Nenhum atendimento" in html


def test_calendario_tem_filtro_de_tipo_de_transporte():
    """USA/USB — o 'recurso', que a coluna Unidade identifica."""
    _login()
    html = client.get("/indicadores/calendarios?unidades=2",
                      headers={"accept": "text/html"}).text
    assert 'id="recurso"' in html and "Tipo de transporte" in html
    assert 'value="USA"' in html and 'value="USB"' in html


def test_calendario_filtrado_por_recurso_traz_so_aquele_tipo():
    from app.modules.indicadores.service import IndicadoresService

    service = IndicadoresService(1)
    for tipo in ("USA", "USB"):
        dados = service.calendarios({"recurso": [tipo]}, ["tempo-resposta"],
                                    "mes", False, 31, unidades=200)
        if not dados["unidades"]:
            continue
        nomes = [u["unidade"] for u in dados["unidades"]]
        assert all(n.startswith(tipo) for n in nomes), (tipo, nomes[:5])
