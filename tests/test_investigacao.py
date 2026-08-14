"""Testes do módulo Investigação de Eventos."""

import re

from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app
from app.modules.investigacao.service import InvestigacaoService

client = TestClient(app)


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def test_requer_login():
    resp = client.get("/investigacao/", headers={"accept": "text/html"},
                      follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_timeline_do_dia():
    """Ocupação por viatura, posicionada na régua de 24h."""
    _login()
    service = InvestigacaoService(1)
    dia = service.opcoes()["dia_max"]
    dados = client.get(f"/investigacao/api/timeline?dia={dia}").json()["data"]

    assert dados["dia"] == dia
    assert dados["unidades"], "nenhuma viatura na timeline"
    for unidade in dados["unidades"]:
        assert unidade["periodos"]
        for p in unidade["periodos"]:
            # posição dentro do dia (0–100%) e largura visível
            assert 0 <= p["esquerda"] <= 100
            assert 0 < p["largura"] <= 100
            assert p["esquerda"] + p["largura"] <= 100.5
            assert re.fullmatch(r"\d{2}/\d{2} \d{2}:\d{2}", p["inicio"])
            assert isinstance(p["fora"], bool)


def test_timeline_filtra_por_municipio():
    _login()
    service = InvestigacaoService(1)
    dia = service.opcoes()["dia_max"]
    todos = service.timeline_dia(dia)
    municipio = todos["unidades"][0]["municipio"]
    filtrado = service.timeline_dia(dia, municipios=[municipio])
    assert filtrado["unidades"]
    assert all(u["municipio"] == municipio for u in filtrado["unidades"])
    assert filtrado["total_unidades"] <= todos["total_unidades"]


def test_investigar_empenho_de_outro_municipio():
    """O caso de uso central: viatura de fora atendeu — as locais estavam ocupadas?"""
    _login()
    service = InvestigacaoService(1)
    dia = service.opcoes()["dia_max"]
    casos = service.cruzamentos(dia)["casos"]
    if not casos:
        return
    alvo = casos[0]

    dados = client.get(
        f"/investigacao/api/investigar?ocorrencia={alvo['ocorrencia']}"
    ).json()["data"]

    assert dados["ocorrencia"] == alvo["ocorrencia"]
    assert dados["fora_do_municipio"] is True
    # a sede da viatura difere do município da ocorrência
    assert dados["municipio_unidade"] != dados["cidade"]
    assert dados["veredito"]
    # cada viatura do município tem um estado conclusivo no instante
    for s in dados["situacoes"]:
        assert s["status"] in ("ocupada", "atendeu", "sem_empenho")
        if s["status"] == "ocupada":
            assert s["ocorrencia"] and s["desde"] and s["ate"]
    assert dados["n_ocupadas"] + dados["n_livres"] <= len(dados["situacoes"])


def test_investigar_ocorrencia_inexistente():
    _login()
    corpo = client.get("/investigacao/api/investigar?ocorrencia=000000").json()
    assert corpo["success"] is False
    assert "não encontrada" in corpo["message"]


def test_ocupada_no_instante_bate_com_a_timeline():
    """Uma viatura marcada 'ocupada' tem período cobrindo o acionamento."""
    from datetime import datetime

    service = InvestigacaoService(1)
    dia = service.opcoes()["dia_max"]
    for caso in service.cruzamentos(dia)["casos"]:
        dados = service.investigar(caso["ocorrencia"])
        ocupadas = [s for s in dados["situacoes"] if s["status"] == "ocupada"]
        if not ocupadas:
            continue
        momento = datetime.strptime(dados["momento"], "%d/%m/%Y %H:%M")
        for s in ocupadas:
            desde = datetime.strptime(f"{s['desde']}/{momento.year}",
                                      "%d/%m %H:%M/%Y")
            ate = datetime.strptime(f"{s['ate']}/{momento.year}",
                                    "%d/%m %H:%M/%Y")
            assert desde <= momento <= ate, (s["unidade"], s["desde"], s["ate"])
        return   # um caso com ocupadas basta


def test_pagina_e_menu():
    _login()
    pagina = client.get("/investigacao/", headers={"accept": "text/html"})
    assert pagina.status_code == 200
    assert "Investigar ocorrência" in pagina.text
    assert "tl-periodo" in pagina.text          # barras da timeline
    assert "Empenhos de outro município" in pagina.text
    # a ressalva sobre o significado de "sem empenho" é obrigatória
    assert "fora de escala" in pagina.text

    home = client.get("/", headers={"accept": "text/html"})
    assert "Investigação de Eventos" in home.text


def test_indicadores_e_atraso_no_dossie():
    """A página traz os indicadores medidos e a decomposição do tempo."""
    from app.core.database import SessionLocal

    service = InvestigacaoService(1)
    dia = service.opcoes()["dia_max"]
    casos = service.cruzamentos(dia)["casos"]
    if not casos:
        return
    db = SessionLocal()
    try:
        dossie = service.dossie(db, casos[0]["ocorrencia"])
    finally:
        db.close()

    assert dossie["indicadores"], "sem indicadores"
    rotulos = [i["rotulo"] for i in dossie["indicadores"]]
    assert any(r.startswith("P1") for r in rotulos)
    assert any(r.startswith("P4.1") for r in rotulos)

    atraso = dossie["atraso"]
    assert atraso["etapas"]
    for e in atraso["etapas"]:
        assert e["situacao"] in ("ok", "ruim", "sem_dado")
        if e["valor"]:
            # comparação sempre ancorada em algo verificável
            assert e["referencia"] or e["meta"]
            assert e["amostra"] >= 0
    assert atraso["resumo"]
    # as etapas apontadas como contribuintes são de fato do tempo de resposta
    assert all(e["resposta"] for e in atraso["contribuintes"])


def test_cobertura_do_atraso_e_honesta():
    """Quando faltam marcações, o resumo diz quanto do tempo não é explicado."""
    from app.modules.indicadores import nucleo
    from app.modules.investigacao.analise import decompor_atraso

    df = nucleo.carregar(1)
    # empenho com tempo de resposta válido mas alguma etapa sem marcação
    alvo = df[df["tempo_resposta"].notna() & df["t_p2"].isna()
              & df["t_p4_1"].notna()]
    if alvo.empty:
        return
    d = decompor_atraso(1, int(alvo.iloc[0]["id"]))
    if d.get("cobertura") and d["cobertura"]["nao_explicado"]:
        assert "sem marcação" in d["resumo"]
        assert d["cobertura"]["pct"] <= 100


def test_pagina_mostra_secoes_do_dossie():
    _login()
    service = InvestigacaoService(1)
    casos = service.cruzamentos(service.opcoes()["dia_max"])["casos"]
    if not casos:
        return
    pagina = client.get(f"/investigacao/?ocorrencia={casos[0]['ocorrencia']}",
                        headers={"accept": "text/html"})
    assert pagina.status_code == 200
    for marca in ("Indicadores desta ocorrência", "Onde o tempo foi consumido",
                  "Prontuário do atendimento", "referência do serviço"):
        assert marca in pagina.text, marca


def test_analise_ia_fluxo_completo(monkeypatch):
    """Prompt montado, JSON persistido e exibido — sem chamar provedor real."""
    import json

    from app.core import ia
    from app.core.config_service import set_config
    from app.core.database import SessionLocal
    from app.modules.investigacao.ia_analise import analisar, montar_prompt

    service = InvestigacaoService(1)
    casos = service.cruzamentos(service.opcoes()["dia_max"])["casos"]
    if not casos:
        return
    numero = casos[0]["ocorrencia"]

    resposta = {
        "sintese": "resumo de teste",
        "londres": {"incidente": "x",
                    "fatores_contribuintes": [
                        {"categoria": "Organização e gestão", "fator": "f",
                         "evidencia": "e"}],
                    "recomendacoes": [{"acao": "a", "prazo": "curto",
                                       "tipo": "processo",
                                       "responsavel_sugerido": "r"}]},
        "ishikawa": {"efeito": "y",
                     "espinhas": [{"categoria": "Método", "causas": ["c"]}]},
        "matriz_risco": {"probabilidade": "possivel", "impacto": "moderado",
                         "nivel": "alto", "justificativa": "j",
                         "mitigacoes": ["m"]},
        "lacunas_de_dados": ["l"],
    }
    capturado = {}

    def fake_gerar(db, prompt, sistema="", empresa_id=1, json_esperado=False):
        capturado["prompt"] = prompt
        capturado["sistema"] = sistema
        return "```json\n" + json.dumps(resposta) + "\n```"

    monkeypatch.setattr(ia, "gerar", fake_gerar)

    db = SessionLocal()
    try:
        set_config(db, ia.CONFIG_PROVEDOR, "ollama", empresa_id=1)
        set_config(db, ia.CONFIG_MODELO, "modelo-teste", empresa_id=1)
        dossie = service.dossie(db, numero)

        # o prompt leva os dados verificáveis, não só o texto livre
        prompt = montar_prompt(dossie, "")
        assert "Indicadores medidos" in prompt
        assert "Decomposição do tempo" in prompt
        assert "Disponibilidade das viaturas" in prompt
        assert "Protocolo de Londres" in prompt

        resultado = analisar(db, 1, dossie, "", anonimizar=True)
        assert resultado["matriz_risco"]["nivel"] == "alto"
        assert resultado["provedor"] == "Ollama (local)"
        # instruções antifabulação chegaram ao modelo
        assert "Não invente" in capturado["sistema"]

        # persistiu e é recuperado na próxima abertura da página
        novo = service.dossie(db, numero)
        assert novo["analise_ia"]["sintese"] == "resumo de teste"
    finally:
        db.close()


def test_anonimizacao_remove_identificadores():
    from app.core.ia import anonimizar_texto

    texto = ("Paciente JOAO DA SILVA SANTOS, CPF 111.222.333-44, "
             "telefone (27) 98888-7777, CNS 123456789012345, "
             "atendido às 14:35 na ocorrência 2717192")
    limpo = anonimizar_texto(texto, ["JOAO DA SILVA SANTOS"])
    assert "JOAO" not in limpo and "SILVA" not in limpo
    assert "111.222.333-44" not in limpo
    assert "98888-7777" not in limpo
    assert "123456789012345" not in limpo
    # dados clínicos/operacionais úteis não podem ser destruídos
    assert "14:35" in limpo and "2717192" in limpo


def test_fatores_do_tempo_resposta():
    """Meta de 10 min: separa distância, percurso, horário e processo."""
    from app.modules.indicadores import nucleo
    from app.modules.investigacao.analise import (META_TEMPO_RESPOSTA,
                                                  fatores_tempo_resposta)

    assert META_TEMPO_RESPOSTA == 600
    service = InvestigacaoService(1)
    df = nucleo.carregar(1)
    encontrou_acima = encontrou_dentro = False

    for caso in service.cruzamentos(service.opcoes()["dia_max"])["casos"][:12]:
        inv = service.investigar(caso["ocorrencia"])
        if inv.get("erro"):
            continue
        f = fatores_tempo_resposta(1, inv["registro_id"], inv)
        if not f.get("aplicavel"):
            continue
        assert f["meta"] == "10:00"
        assert isinstance(f["dentro_da_meta"], bool)
        for x in f["fatores"]:
            assert x["tipo"] in ("distancia", "percurso", "transito",
                                 "recurso", "processo", "dado")
            # toda afirmação vem com o número que a sustenta
            assert x["evidencia"] and len(x["evidencia"]) > 20
            assert x["impacto"] >= 0
        if f["dentro_da_meta"]:
            encontrou_dentro = True
            assert "dentro da meta" in f["resumo"]
        else:
            encontrou_acima = True
            assert "acima da meta" in f["resumo"]
            # empenho de outro município sempre rende o fator de origem
            # quando há histórico das viaturas locais
            tipos = {x["tipo"] for x in f["fatores"]}
            assert tipos, "nenhum fator apontado"
    assert encontrou_acima or encontrou_dentro, "nenhum caso avaliado"


def test_fator_distancia_versus_percurso():
    """Trajeto dentro do usual = distância; muito acima = percurso."""
    from app.modules.indicadores import nucleo
    from app.modules.investigacao.analise import fatores_tempo_resposta

    df = nucleo.carregar(1)
    # rota com histórico robusto, para a comparação ser possível
    validos = df[(df["t_p4_2"] > 0) & (df["t_p4_2"] < 14400)
                 & df["unidade"].notna() & df["cidade"].notna()
                 & df["tempo_resposta"].notna()]
    contagem = validos.groupby(["unidade", "cidade"]).size()
    rotas = contagem[contagem >= 30]
    if rotas.empty:
        return
    unidade, cidade = rotas.index[0]
    rota = validos[(validos["unidade"] == unidade)
                   & (validos["cidade"] == cidade)].sort_values("t_p4_2")

    rapido = fatores_tempo_resposta(1, int(rota.iloc[0]["id"]))
    lento = fatores_tempo_resposta(1, int(rota.iloc[-1]["id"]))
    tipos_rapido = {f["tipo"] for f in rapido.get("fatores", [])}
    tipos_lento = {f["tipo"] for f in lento.get("fatores", [])}
    # o caso mais lento da rota não pode ser classificado como distância
    # estrutural se está muito acima da mediana daquela mesma rota
    assert "percurso" in tipos_lento or "distancia" not in tipos_lento
    # e o mais rápido nunca é "percurso anômalo"
    assert "percurso" not in tipos_rapido


def test_prompt_pede_foco_no_tempo_resposta():
    from app.core.database import SessionLocal
    from app.modules.investigacao.ia_analise import montar_prompt

    service = InvestigacaoService(1)
    casos = service.cruzamentos(service.opcoes()["dia_max"])["casos"]
    if not casos:
        return
    db = SessionLocal()
    try:
        prompt = montar_prompt(service.dossie(db, casos[0]["ocorrencia"]), "")
    finally:
        db.close()
    assert "meta de tempo de resposta do serviço é 10 minutos" in prompt
    assert "Tempo de resposta frente à meta de 10 minutos" in prompt
    for termo in ("distância", "trânsito", "rota", "origem da viatura",
                  "indisponibilidade"):
        assert termo in prompt, termo


def test_investigar_chamado_sem_viatura_despachada():
    """Chamado resolvido sem despacho (orientação médica, cancelado…).

    Ainda há o que analisar: a cadeia do chamado, até onde o fluxo
    avançou e se havia viatura disponível no momento da decisão.
    """
    from app.modules.indicadores import nucleo

    df = nucleo.carregar(1)
    sem_viatura = df[df["unidade"].isna() & df["dt_data_regulador"].notna()
                     & df["cidade"].notna()]
    if sem_viatura.empty:
        return
    numero = sem_viatura.iloc[0]["ocorrencia"]

    dados = InvestigacaoService(1).investigar(numero)
    assert not dados.get("erro"), dados.get("erro")
    assert dados["com_empenho"] is False
    assert dados["momento"]
    assert "sem despacho de viatura" in dados["veredito"]

    # cadeia mostra o que existe e o que falta
    marcados = [m for m in dados["cadeia"] if m["hora"]]
    ausentes = [m for m in dados["cadeia"] if not m["hora"]]
    assert marcados and ausentes
    assert any(m["rotulo"] == "Abertura do chamado" for m in marcados)
    assert any(m["rotulo"] == "Chegada no local" for m in ausentes)
    # intervalos entre marcações presentes
    assert any(m["desde_anterior"] for m in marcados[1:])


def test_pagina_de_chamado_sem_viatura():
    _login()
    from app.modules.indicadores import nucleo

    df = nucleo.carregar(1)
    sem_viatura = df[df["unidade"].isna() & df["dt_data_regulador"].notna()
                     & df["cidade"].notna()]
    if sem_viatura.empty:
        return
    numero = sem_viatura.iloc[0]["ocorrencia"]

    pagina = client.get(f"/investigacao/?ocorrencia={numero}",
                        headers={"accept": "text/html"})
    assert pagina.status_code == 200
    assert "sem viatura despachada" in pagina.text
    assert "Cadeia do chamado" in pagina.text
    assert "O fluxo parou antes do despacho" in pagina.text
    # não inventa tempo de resposta para quem não teve viatura
    assert "Tempo de resposta</dt>" not in pagina.text


def test_prompt_de_chamado_sem_viatura_muda_o_foco():
    from app.core.database import SessionLocal
    from app.modules.indicadores import nucleo
    from app.modules.investigacao.ia_analise import montar_prompt

    df = nucleo.carregar(1)
    sem_viatura = df[df["unidade"].isna() & df["dt_data_regulador"].notna()
                     & df["cidade"].notna()]
    if sem_viatura.empty:
        return
    db = SessionLocal()
    try:
        dossie = InvestigacaoService(1).dossie(
            db, sem_viatura.iloc[0]["ocorrencia"])
        prompt = montar_prompt(dossie, "")
    finally:
        db.close()
    assert "SEM despacho de viatura" in prompt
    assert "Cadeia de marcações do chamado" in prompt
    assert "SEM REGISTRO" in prompt
    # não pede análise de tempo de resposta para quem não teve viatura
    assert "meta de 10 minutos" not in prompt
    assert "Não avalie tempo de resposta" in prompt


def test_matriz_de_risco_do_formulario():
    """C = A × B e as faixas de cor do FOR.SAMU.038."""
    from app.modules.investigacao.constants import (CONSEQUENCIA,
                                                    PROBABILIDADE,
                                                    nivel_de_risco)
    from app.modules.investigacao.ia_analise import _preparar_risco

    assert [p for p, _, _ in PROBABILIDADE] == [5, 4, 3, 2, 1]
    assert [c for c, _, _ in CONSEQUENCIA] == [16, 8, 4, 2, 1]
    # faixas conferidas contra os valores impressos no formulário
    assert nivel_de_risco(64)[0] == "Extremo"
    assert nivel_de_risco(20)[0] == "Extremo"
    assert nivel_de_risco(16)[0] == "Elevado"
    assert nivel_de_risco(10)[0] == "Elevado"
    assert nivel_de_risco(8)[0] == "Moderado"
    assert nivel_de_risco(4)[0] == "Moderado"
    assert nivel_de_risco(3)[0] == "Baixo"

    # o produto é recalculado no servidor, não aceito da IA
    risco = _preparar_risco({"probabilidade": 4, "consequencia": 16,
                             "classificacao": 999})
    assert risco["classificacao"] == 64
    assert risco["nivel"] == "Extremo"
    # combinações fora da escala do formulário são recusadas
    assert _preparar_risco({"probabilidade": 9, "consequencia": 16}) is None
    assert _preparar_risco({"probabilidade": 3, "consequencia": 5}) is None
    assert _preparar_risco(None) is None


def test_fatores_contribuintes_seguem_a_lista_do_formulario():
    """As 7 categorias sempre aparecem; item inventado é descartado."""
    from app.modules.investigacao.constants import FATORES_CONTRIBUINTES
    from app.modules.investigacao.ia_analise import _preparar_fatores

    resposta_da_ia = [
        {"categoria": "Fatores do Paciente",
         "itens": ["Condição (complexidade e gravidade)",
                   "Item que não existe no formulário"],
         "descricao": "paciente grave"},
        {"categoria": "Categoria inventada", "itens": ["x"], "descricao": "y"},
    ]
    fatores = _preparar_fatores(resposta_da_ia)

    assert len(fatores) == len(FATORES_CONTRIBUINTES) == 7
    assert [f["categoria"] for f in fatores] == [c for c, _ in FATORES_CONTRIBUINTES]

    paciente = fatores[0]
    marcados = [i["texto"] for i in paciente["itens"] if i["marcado"]]
    assert marcados == ["Condição (complexidade e gravidade)"]
    assert paciente["tem_marcado"] is True
    assert paciente["descricao"] == "paciente grave"

    # categoria sem evidência recebe o texto padrão do formulário
    vazia = fatores[1]
    assert vazia["tem_marcado"] is False
    assert vazia["descricao"] == "Não foi identificado."
    assert all(not i["marcado"] for i in vazia["itens"])


def test_prompt_no_formato_rac():
    from app.core.database import SessionLocal
    from app.modules.investigacao.ia_analise import montar_prompt

    service = InvestigacaoService(1)
    casos = service.cruzamentos(service.opcoes()["dia_max"])["casos"]
    if not casos:
        return
    db = SessionLocal()
    try:
        prompt = montar_prompt(service.dossie(db, casos[0]["ocorrencia"]), "")
    finally:
        db.close()

    assert "FOR.SAMU.038" in prompt
    assert "Protocolo de Londres" in prompt
    # a lista fechada de fatores vai no prompt
    for categoria in ("Fatores do Paciente", "Fatores da Tarefa e Tecnologia",
                      "Fatores do Contexto Institucional"):
        assert categoria in prompt, categoria
    # escala da matriz e as duas avaliações de risco
    assert "1 (Raro) a 5 (Quase certo)" in prompt
    assert "risco residual" in prompt
    for campo in ("dados_gerais", "fatores_contribuintes", "plano_acao",
                  "risco_antes", "risco_depois", "informacoes_a_coletar"):
        assert campo in prompt, campo
    # a cronologia é montada pelo sistema; a IA só acrescenta o que o
    # prontuário narrar
    assert "eventos_do_prontuario" in prompt
    assert '"cronologia"' not in prompt


def test_pagina_renderiza_o_rac(monkeypatch):
    """Com análise gravada, a página mostra o formulário completo."""
    import json

    from app.core import ia
    from app.core.config_service import set_config
    from app.core.database import SessionLocal

    from app.modules.investigacao.ia_analise import analisar

    _login()
    service = InvestigacaoService(1)
    casos = service.cruzamentos(service.opcoes()["dia_max"])["casos"]
    if not casos:
        return
    numero = casos[0]["ocorrencia"]

    resposta = {
        "dados_gerais": {"titulo_investigacao": "Título de teste",
                         "descricao_incidente": "Descrição de teste",
                         "gravidade": "Moderada",
                         "gravidade_justificativa": "just",
                         "nivel_investigacao": "Análise de Causa Raiz"},
        "risco_antes": {"probabilidade": 4, "probabilidade_rotulo": "Provável",
                        "consequencia": 16,
                        "consequencia_rotulo": "Catastrófica",
                        "justificativa": "j"},
        "risco_depois": {"probabilidade": 2,
                         "probabilidade_rotulo": "Improvável",
                         "consequencia": 16,
                         "consequencia_rotulo": "Catastrófica",
                         "justificativa": "j2"},
        "cronologia": [{"quando": "11/08/2026, às 07h22", "evento": "abertura"}],
        "fatores_contribuintes": [
            {"categoria": "Fatores do Ambiente de Trabalho",
             "itens": ["Manutenção, design e disponibilidade de equipamentos"],
             "descricao": "descrição do fator"}],
        "conclusao": "Conclusão de teste",
        "plano_acao": [{"numero": 1, "acao": "Ação de teste",
                        "tipo": "processo", "prazo": "curto",
                        "responsavel_sugerido": "NEP"}],
        "informacoes_a_coletar": ["Relato dos envolvidos"],
        "lacunas_de_dados": ["marcação ausente"],
    }
    monkeypatch.setattr(ia, "gerar",
                        lambda *a, **k: json.dumps(resposta))

    db = SessionLocal()
    try:
        set_config(db, ia.CONFIG_PROVEDOR, "ollama", empresa_id=1)
        set_config(db, ia.CONFIG_MODELO, "teste", empresa_id=1)
        analisar(db, 1, service.dossie(db, numero), "", anonimizar=True)
    finally:
        db.close()

    pagina = client.get(f"/investigacao/?ocorrencia={numero}",
                        headers={"accept": "text/html"}).text
    assert "FOR.SAMU.038" in pagina
    assert "Título de teste" in pagina
    assert "Conclusão de teste" in pagina
    assert "Ação de teste" in pagina
    assert "Relato dos envolvidos" in pagina
    # matriz: 64 antes (extremo) e 32 depois, ambos na escala do formulário
    assert "64 — risco extremo" in pagina
    assert "32 — risco extremo" in pagina
    # as sete categorias saem no formulário, marcadas ou não
    assert pagina.count("Não foi identificado.") >= 6
    assert "Manutenção, design e disponibilidade de equipamentos" in pagina


def _mock_ia(monkeypatch, resposta=None):
    """Configura a IA com um provedor falso que devolve `resposta`."""
    import json

    from app.core import ia
    from app.core.config_service import set_config
    from app.core.database import SessionLocal

    padrao = {
        "dados_gerais": {"titulo_investigacao": "Título RAC",
                         "descricao_incidente": "Descrição",
                         "gravidade": "Moderada",
                         "nivel_investigacao": "Análise de Causa Raiz"},
        "risco_antes": {"probabilidade": 3, "consequencia": 4,
                        "probabilidade_rotulo": "Possível",
                        "consequencia_rotulo": "Moderada",
                        "justificativa": "j"},
        "risco_depois": {"probabilidade": 2, "consequencia": 4,
                         "probabilidade_rotulo": "Improvável",
                         "consequencia_rotulo": "Moderada",
                         "justificativa": "residual"},
        "fatores_contribuintes": [], "conclusao": "Conclusão",
        "plano_acao": [{"numero": 1, "acao": "Ação", "prazo": "curto",
                        "tipo": "processo", "responsavel_sugerido": "NEP"}],
        "informacoes_a_coletar": ["Relatos"], "lacunas_de_dados": [],
    }
    capturado = {}

    def fake(db, prompt, sistema="", empresa_id=1, json_esperado=False):
        capturado["prompt"] = prompt
        return json.dumps(resposta or padrao)

    monkeypatch.setattr(ia, "gerar", fake)
    db = SessionLocal()
    try:
        set_config(db, ia.CONFIG_PROVEDOR, "ollama", empresa_id=1)
        set_config(db, ia.CONFIG_MODELO, "teste", empresa_id=1)
    finally:
        db.close()
    return capturado


def _ocorrencia_para_rac() -> str:
    service = InvestigacaoService(1)
    casos = service.cruzamentos(service.opcoes()["dia_max"])["casos"]
    return casos[0]["ocorrencia"] if casos else ""


def test_cronologia_vem_das_marcacoes_nao_da_ia():
    """Datas do relatório saem do vSky — a IA já errou o ano ao gerá-las."""
    from app.core.database import SessionLocal

    numero = _ocorrencia_para_rac()
    if not numero:
        return
    db = SessionLocal()
    try:
        dossie = InvestigacaoService(1).dossie(db, numero)
    finally:
        db.close()

    cronologia = dossie["cronologia"]
    assert cronologia, "cronologia vazia"
    marcados = {m["hora"] for m in dossie["investigacao"]["cadeia"]
                if m["hora"]}
    for evento in cronologia:
        assert evento["quando"] in marcados      # horário real, não gerado
        assert evento["origem"] == "marcação do sistema"
    # o esquema da IA não pede mais cronologia
    from app.modules.investigacao.ia_analise import ESQUEMA
    assert '"cronologia"' not in ESQUEMA
    assert "eventos_do_prontuario" in ESQUEMA


def test_rac_em_pdf():
    """PDF no layout do formulário, com cabeçalho e seções."""
    import io

    from pypdf import PdfReader

    from app.core.database import SessionLocal
    from app.modules.investigacao.rac_pdf import gerar_rac_pdf

    numero = _ocorrencia_para_rac()
    if not numero:
        return
    db = SessionLocal()
    try:
        dossie = InvestigacaoService(1).dossie(db, numero)
    finally:
        db.close()

    pdf = gerar_rac_pdf(dossie)
    assert pdf.startswith(b"%PDF")
    leitor = PdfReader(io.BytesIO(pdf))
    assert len(leitor.pages) >= 2
    texto = " ".join(" ".join((p.extract_text() or "").split())
                     for p in leitor.pages)
    for marca in ("FOR.SAMU.038", "DADOS GERAIS",
                  "AVALIAÇÃO DO RISCO GERAL ANTES DA INVESTIGAÇÃO",
                  "FATORES CONTRIBUINTES", "PLANO DE AÇÃO",
                  "ANEXO — DADOS OPERACIONAIS APURADOS PELO SISTEMA"):
        assert marca in texto, marca
    # campos de apuração humana ficam em branco, não inventados
    assert "Nome do Paciente:" in texto
    assert "Time de Investigação:" in texto


def test_aprovacao_registra_risco_da_equipe_e_guarda_pdf(monkeypatch):
    """Aprovar grava status, risco da equipe e o PDF imutável no banco."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.modules.investigacao.ia_analise import analisar, historico
    from app.modules.investigacao.models import (STATUS_APROVADO,
                                                 AnaliseOcorrencia)

    _login()
    _mock_ia(monkeypatch)
    numero = _ocorrencia_para_rac()
    if not numero:
        return

    db = SessionLocal()
    try:
        analisar(db, 1, InvestigacaoService(1).dossie(db, numero), "")
    finally:
        db.close()

    resp = client.post("/investigacao/aprovar", data={
        "ocorrencia": numero, "risco_pos_probabilidade": "2",
        "risco_pos_consequencia": "4",
        "risco_pos_justificativa": "Risco residual aceitável"})
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        atual = historico(db, 1, numero)[0]
        assert atual.status == STATUS_APROVADO
        assert atual.aprovado_em is not None
        assert atual.aprovado_nome
        # risco registrado pela equipe, não o da IA
        assert atual.risco_pos_probabilidade == 2
        assert atual.risco_pos_consequencia == 4
        assert atual.risco_pos_justificativa == "Risco residual aceitável"
        # PDF do aprovado guardado no banco
        assert atual.pdf and atual.pdf.startswith(b"%PDF")
    finally:
        db.close()

    # a página passa a mostrar o risco da equipe e o PDF aprovado
    pagina = client.get(f"/investigacao/?ocorrencia={numero}",
                        headers={"accept": "text/html"}).text
    assert "Risco registrado pela equipe" in pagina
    assert "Abrir PDF aprovado" in pagina
    # 2 × 4 = 8, moderado
    assert "8 — risco moderado" in pagina


def test_risco_pos_fora_da_escala_e_recusado(monkeypatch):
    from app.core.database import SessionLocal
    from app.modules.investigacao.ia_analise import analisar, historico

    _login()
    _mock_ia(monkeypatch)
    numero = _ocorrencia_para_rac()
    if not numero:
        return
    db = SessionLocal()
    try:
        analisar(db, 1, InvestigacaoService(1).dossie(db, numero), "")
    finally:
        db.close()

    client.post("/investigacao/aprovar", data={
        "ocorrencia": numero, "risco_pos_probabilidade": "9",
        "risco_pos_consequencia": "5", "risco_pos_justificativa": ""})
    db = SessionLocal()
    try:
        atual = historico(db, 1, numero)[0]
        # valores inválidos não entram; a aprovação em si vale
        assert atual.risco_pos_probabilidade is None
        assert atual.risco_pos_consequencia is None
    finally:
        db.close()


def test_ajuste_gera_nova_versao_com_historico(monkeypatch):
    """Reprovar com feedback cria versão nova que conhece as anteriores."""
    from app.core.database import SessionLocal
    from app.modules.investigacao.ia_analise import analisar, historico
    from app.modules.investigacao.models import STATUS_SUBSTITUIDO

    _login()
    capturado = _mock_ia(monkeypatch)
    numero = _ocorrencia_para_rac()
    if not numero:
        return

    db = SessionLocal()
    try:
        analisar(db, 1, InvestigacaoService(1).dossie(db, numero), "")
        antes = historico(db, 1, numero)[0].versao
    finally:
        db.close()

    client.post("/investigacao/ajustar", data={
        "ocorrencia": numero, "feedback": "Faltou citar a indisponibilidade"})
    client.post("/investigacao/ajustar", data={
        "ocorrencia": numero, "feedback": "Plano de ação sem prazo"})

    db = SessionLocal()
    try:
        versoes = historico(db, 1, numero)
    finally:
        db.close()

    assert versoes[0].versao == antes + 2
    assert versoes[0].feedback == "Plano de ação sem prazo"
    assert versoes[1].status == STATUS_SUBSTITUIDO   # anterior preservada
    # o prompt da última revisão levou o relatório anterior e o histórico
    prompt = capturado["prompt"]
    assert "# REVISÃO SOLICITADA" in prompt
    assert "## Relatório anterior" in prompt
    assert "Plano de ação sem prazo" in prompt
    assert "Faltou citar a indisponibilidade" in prompt

    # feedback vazio não gera versão
    client.post("/investigacao/ajustar",
                data={"ocorrencia": numero, "feedback": "   "})
    db = SessionLocal()
    try:
        assert historico(db, 1, numero)[0].versao == antes + 2
    finally:
        db.close()


def test_pagina_de_relatorios(monkeypatch):
    _login()
    _mock_ia(monkeypatch)
    numero = _ocorrencia_para_rac()
    if not numero:
        return
    from app.core.database import SessionLocal
    from app.modules.investigacao.ia_analise import analisar

    db = SessionLocal()
    try:
        analisar(db, 1, InvestigacaoService(1).dossie(db, numero), "")
    finally:
        db.close()

    pagina = client.get("/investigacao/relatorios",
                        headers={"accept": "text/html"})
    assert pagina.status_code == 200
    assert "Relatórios de Evento Adverso" in pagina.text
    assert numero in pagina.text
    assert "Título RAC" in pagina.text

    # filtro por status
    filtrado = client.get("/investigacao/relatorios?status=pendente",
                          headers={"accept": "text/html"})
    assert filtrado.status_code == 200
    assert numero in filtrado.text

    # o menu leva à página
    home = client.get("/", headers={"accept": "text/html"})
    assert "Relatórios RAC" in home.text
