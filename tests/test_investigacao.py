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
