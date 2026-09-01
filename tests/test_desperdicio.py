"""Definição de desperdício operacional.

Universo: saída efetiva de viatura.
Nunca é desperdício: óbito (coluna Óbito) ou hipoglicemia (motivo PCG3/SCG2
ou glicemia medida < 80).
REAL: chegou ao local e não removeu o paciente (sem Saída para hospital).
EVITADO: não chegou ao local.
"""

import pandas as pd
import pytest

from app.modules.indicadores import desperdicio, nucleo


def _linha(**campos):
    """Saída que chegou, não removeu, sem óbito e com glicemia normal."""
    base = {"motivo": "PCC1 DOR TORACICA",
            "dt_inicio_deslocamento": pd.Timestamp("2026-08-01 10:00"),
            "dt_chegada_no_local": pd.Timestamp("2026-08-01 10:20"),
            "dt_saida_para_hospital": pd.NaT,
            "tempo_resposta": 1200.0,      # é a 1ª viatura a chegar
            "obito_constatado": False,
            "glicemia": 110.0}
    base.update(campos)
    return base


def _mascaras(linhas):
    df = pd.DataFrame(linhas)
    base = desperdicio.universo(df)
    real, evitado = desperdicio.mascaras(base)
    return base, real, evitado


# ------------------------------------------------------------ universo

def test_sem_saida_nao_entra_no_universo():
    base, _, _ = _mascaras([_linha(dt_inicio_deslocamento=pd.NaT)])
    assert base.empty


# ------------------------------------------------------------- o real

def test_chegou_e_nao_removeu_e_desperdicio_real():
    _, real, evitado = _mascaras([_linha()])
    assert bool(real.iloc[0]) and not bool(evitado.iloc[0])


def test_saida_para_hospital_significa_remocao():
    """O critério de remoção é o campo, não a situação da ocorrência."""
    _, real, evitado = _mascaras([
        _linha(dt_saida_para_hospital=pd.Timestamp("2026-08-01 10:40"))])
    assert not bool(real.iloc[0]) and not bool(evitado.iloc[0])


def test_viatura_de_apoio_que_chegou_depois_nao_e_desperdicio_real():
    """Sem tempo de resposta o empenho é apoio, não a viatura da ocorrência."""
    _, real, _ = _mascaras([_linha(tempo_resposta=None)])
    assert not bool(real.iloc[0])


# ---------------------------------------------------------- o evitado

def test_nao_chegar_ao_local_e_desperdicio_evitado():
    _, real, evitado = _mascaras([_linha(dt_chegada_no_local=pd.NaT,
                                         tempo_resposta=None)])
    assert not bool(real.iloc[0]) and bool(evitado.iloc[0])


def test_evitado_nao_depende_da_situacao_registrada():
    for situacao in ("Trote", "Situação Inédita No Vsky",
                     "Indisponibilidade De Recurso"):
        _, _, evitado = _mascaras([_linha(dt_chegada_no_local=pd.NaT,
                                          tempo_resposta=None,
                                          situacao_atendimento=situacao)])
        assert bool(evitado.iloc[0]), situacao


# ------------------------------------------------------------- óbito

def test_obito_nunca_e_desperdicio():
    for lado in ({}, {"dt_chegada_no_local": pd.NaT, "tempo_resposta": None}):
        _, real, evitado = _mascaras([_linha(obito_constatado=True, **lado)])
        assert not bool(real.iloc[0]) and not bool(evitado.iloc[0])


def test_todos_os_desfechos_de_morte_contam_como_obito():
    """Os cinco valores da coluna Óbito que significam morte."""
    valores = ("Constatado Óbito", "Antes do Atendimento",
               "Durante Transporte Pré-Hospitalar",
               "Óbito durante o atendimento no local",
               "Durante Transporte Inter-Hospitalar")
    df = nucleo.carregar(1)
    if df.empty:
        pytest.skip("sem dados importados")
    for valor in valores:
        linhas = df[df["obito"] == valor]
        if linhas.empty:
            continue
        assert linhas["obito_constatado"].all(), valor
    # e o contraexemplo
    nao = df[df["obito"] == "Não houve óbito"]
    if not nao.empty:
        assert not nao["obito_constatado"].any()


# ------------------------------------------------------ hipoglicemia

def test_motivo_de_diabetes_e_hipoglicemia():
    for motivo in ("PCG3 DIABETES/HIPOGLICEMIA", "SCG2 CETOACIDOSE DIABÉTICA"):
        _, real, _ = _mascaras([_linha(motivo=motivo)])
        assert not bool(real.iloc[0]), motivo


def test_glicemia_abaixo_de_80_e_hipoglicemia():
    _, real, _ = _mascaras([_linha(glicemia=79.0)])
    assert not bool(real.iloc[0])
    _, real, _ = _mascaras([_linha(glicemia=80.0)])
    assert bool(real.iloc[0]), "80 não é hipoglicemia"


def test_glicemia_nao_medida_nao_afirma_hipoglicemia():
    """0 na ficha vira nulo no núcleo: sem medida não há como afirmar."""
    _, real, _ = _mascaras([_linha(glicemia=None)])
    assert bool(real.iloc[0])


def test_pcr_nao_e_exclusao_por_si():
    """PCC3 sem óbito registrado conta; com óbito, não (decisão do serviço)."""
    _, real, _ = _mascaras([_linha(motivo="PCC3 PCR/ÓBITO")])
    assert bool(real.iloc[0])
    _, real, _ = _mascaras([_linha(motivo="PCC3 PCR/ÓBITO",
                                   obito_constatado=True)])
    assert not bool(real.iloc[0])


def test_pcr_respiratorio_nao_e_confundido_com_parada():
    """PCR1..PCR9 são problema respiratório."""
    for motivo in ("PCR1 ASMA/CRISE", "PCR2 DISPNEIA", "PCR3 ENGASGO / OVACE"):
        _, real, _ = _mascaras([_linha(motivo=motivo)])
        assert bool(real.iloc[0]), motivo


# --------------------------------------------- invariantes na base real

def test_real_e_evitado_sao_disjuntos():
    df = nucleo.carregar(1)
    if df.empty:
        pytest.skip("sem dados importados")
    base = desperdicio.universo(df)
    real, evitado = desperdicio.mascaras(base)
    assert not (real & evitado).any()
    assert int(real.sum()) > 0 and int(evitado.sum()) > 0


def test_invariante_do_tempo_de_resposta():
    """Todo real tem tempo de resposta; nenhum evitado tem, pois não chegou."""
    df = nucleo.carregar(1)
    if df.empty:
        pytest.skip("sem dados importados")
    base = desperdicio.universo(df)
    real, evitado = desperdicio.mascaras(base)
    tr = base["tempo_resposta"]
    assert int((real & tr.isna()).sum()) == 0
    assert int((evitado & tr.notna()).sum()) == 0


def test_nenhum_desperdicio_com_obito_ou_hipoglicemia():
    df = nucleo.carregar(1)
    if df.empty:
        pytest.skip("sem dados importados")
    base = desperdicio.universo(df)
    real, evitado = desperdicio.mascaras(base)
    fora = desperdicio.obito(base) | desperdicio.hipoglicemia(base)
    assert int((real & fora).sum()) == 0
    assert int((evitado & fora).sum()) == 0


def test_nenhum_real_tem_saida_para_hospital():
    df = nucleo.carregar(1)
    if df.empty:
        pytest.skip("sem dados importados")
    base = desperdicio.universo(df)
    real, _ = desperdicio.mascaras(base)
    assert int((real & base["dt_saida_para_hospital"].notna()).sum()) == 0


# ------------------------------------------- as três telas do sistema

def test_as_tres_telas_usam_a_mesma_definicao():
    """Indicadores, Painel de Gestão e Reunião calculavam isto cada um por si
    e chegaram a divergir na mesma semana."""
    from app.modules.indicadores.service import IndicadoresService
    from app.modules.painel_gestao.service import PainelGestaoService
    from app.modules.reuniao_indicadores.service import (
        ReuniaoIndicadoresService)

    df = nucleo.carregar(1)
    if df.empty:
        pytest.skip("sem dados importados")
    base = desperdicio.universo(df)
    real, evitado = desperdicio.mascaras(base)

    # Indicadores — página de desperdício, período inteiro
    dados = IndicadoresService(1).dashboard("desperdicio", {})
    kpis = {k["label"]: k["valor"] for k in dados["kpis"]}
    assert int(kpis["Desperdício real"]) == int(real.sum())
    assert int(kpis["Desperdício evitado"]) == int(evitado.sum())
    assert int(kpis["Saídas no universo"]) == len(base)

    # Painel e Reunião — última semana completa
    import re
    painel = PainelGestaoService(1).montar()
    deck = ReuniaoIndicadoresService(1).montar()
    assert painel["semana"] == deck["semana"]
    na_semana = base["semana_iso"] == painel["semana"]
    esperado = int((real & na_semana).sum())

    sec = next(s for s in painel["secoes"] if s["id"] == "desperdicio")
    achado = re.search(r"(\d+) de (\d+) saídas",
                       sec["blocos"][0]["kpis"][0]["sub"])
    assert int(achado.group(1)) == esperado

    slide = next(s for s in deck["slides"]
                 if s["titulo"].startswith("Desperdícios operacionais"))
    assert int(next(k["valor"] for k in slide["kpis"]
                    if k["label"].startswith("Desperdício REAL ·"))) == esperado
