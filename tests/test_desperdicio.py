"""Definição de desperdício operacional.

REAL: a viatura saiu, chegou no local e NÃO removeu o paciente.
EVITADO: saiu e foi mitigada no trajeto, sem chegar.
Fora dos dois: PCR, óbito e hipoglicemia.
"""

import pandas as pd
import pytest

from app.modules.indicadores import desperdicio, nucleo
from app.modules.indicadores.constants import (SITUACOES_COM_REMOCAO,
                                               SITUACOES_EXCLUIDAS_DO_REAL)


def _linha(**campos):
    base = {"motivo": "PCC1 DOR TORACICA", "dt_inicio_deslocamento": pd.Timestamp("2026-08-01 10:00"),
            "dt_chegada_no_local": pd.Timestamp("2026-08-01 10:20"),
            "situacao_atendimento": "Atendimento Pré-Hospitalar Com Atendimento No Local"}
    base.update(campos)
    return base


def _mascaras(linhas):
    df = pd.DataFrame(linhas)
    base = desperdicio.universo(df)
    real, evitado = desperdicio.mascaras(base)
    return base, real, evitado


def test_chegou_e_nao_removeu_e_desperdicio_real():
    _, real, evitado = _mascaras([_linha()])
    assert bool(real.iloc[0]) and not bool(evitado.iloc[0])


def test_remocao_do_paciente_nao_e_desperdicio():
    """O contraexemplo direto da regra: houve transporte."""
    for situacao in SITUACOES_COM_REMOCAO:
        _, real, _ = _mascaras([_linha(situacao_atendimento=situacao.title())])
        assert not bool(real.iloc[0]), situacao


def test_pcr_obito_e_hipoglicemia_ficam_de_fora():
    for motivo in ("PCC3 PCR/ÓBITO", "PCG3 DIABETES/HIPOGLICEMIA"):
        base, real, evitado = _mascaras([_linha(motivo=motivo)])
        assert base.empty, motivo          # nem entra no universo
    # óbito registrado como situação também não conta
    for situacao in SITUACOES_EXCLUIDAS_DO_REAL:
        _, real, _ = _mascaras([_linha(situacao_atendimento=situacao.title())])
        assert not bool(real.iloc[0]), situacao


def test_sem_chegada_nao_e_real():
    _, real, evitado = _mascaras([_linha(dt_chegada_no_local=pd.NaT,
                                         situacao_atendimento="Desistência do Solicitante")])
    assert not bool(real.iloc[0])
    assert bool(evitado.iloc[0])           # foi mitigada no trajeto


def test_sem_saida_nao_entra_no_universo():
    base, _, _ = _mascaras([_linha(dt_inicio_deslocamento=pd.NaT)])
    assert base.empty


def test_situacao_em_branco_nao_vira_desperdicio():
    """Desfecho desconhecido não sustenta a afirmação de que houve desperdício."""
    _, real, _ = _mascaras([_linha(situacao_atendimento="")])
    assert not bool(real.iloc[0])


def test_desfecho_novo_do_vsky_entra_como_desperdicio():
    """A regra é lista de EXCLUSÃO: situação nova sem remoção conta, em vez de
    sumir por não estar numa lista de permitidos."""
    _, real, _ = _mascaras([_linha(situacao_atendimento="Situação Inédita No Vsky")])
    assert bool(real.iloc[0])


def test_real_e_evitado_sao_disjuntos_na_base_real():
    df = nucleo.carregar(1)
    if df.empty:
        pytest.skip("sem dados importados")
    base = desperdicio.universo(df)
    real, evitado = desperdicio.mascaras(base)
    assert not (real & evitado).any()
    assert int(real.sum()) > 0 and int(evitado.sum()) > 0


def test_as_duas_telas_usam_a_mesma_definicao():
    """Painel de Gestão e Reunião de Indicadores já divergiram por calcular
    isto cada um por si."""
    from app.modules.painel_gestao.service import PainelGestaoService
    from app.modules.reuniao_indicadores.service import (
        ReuniaoIndicadoresService)

    painel = PainelGestaoService(1).montar()
    deck = ReuniaoIndicadoresService(1).montar()
    if not painel["secoes"] or not deck["slides"]:
        pytest.skip("sem dados importados")

    import re
    sec = next(s for s in painel["secoes"] if s["id"] == "desperdicio")
    slide = next(s for s in deck["slides"]
                 if s["titulo"].startswith("Desperdícios operacionais"))
    achado = re.search(r"(\d+) de (\d+) saídas",
                       sec["blocos"][0]["kpis"][0]["sub"])
    real_painel = int(achado.group(1))
    real_deck = int(next(k["valor"] for k in slide["kpis"]
                         if k["label"].startswith("Desperdício REAL ·")))
    assert real_painel == real_deck
