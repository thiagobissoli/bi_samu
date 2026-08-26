"""Definição única de desperdício operacional (§35.16).

Desperdício REAL: a viatura saiu, CHEGOU no local e NÃO removeu o paciente.
Desperdício EVITADO: a viatura saiu e NÃO chegou ao local.

Daí a invariante que vale como conferência: todo desperdício real tem tempo
de resposta; nenhum evitado tem, porque não chegou.

Em ambos ficam de fora as causas clínicas que não são desperdício: PCR,
óbito, diabetes e hipoglicemia (motivos PCC3, PCG3 e SCG2, mais a situação
"óbito informado", que é o mesmo desfecho registrado do outro lado).

Este módulo existe porque a Reunião de Indicadores e o Painel de Gestão
calculavam o mesmo indicador cada um por si, e as duas telas chegaram a
mostrar números diferentes para a mesma semana.
"""

from __future__ import annotations

import pandas as pd

from app.modules.indicadores import nucleo
from app.modules.indicadores.constants import (MOTIVOS_EXCLUIDOS_DESPERDICIO,
                                               SITUACOES_COM_REMOCAO,
                                               SITUACOES_EXCLUIDAS_DO_REAL)


def universo(df: pd.DataFrame) -> pd.DataFrame:
    """Saídas efetivas que podem ser desperdício (exclui PCR/óbito/hipoglicemia)."""
    codigo = df["motivo"].fillna("").str.split(" ").str[0].str.upper()
    return df[df["dt_inicio_deslocamento"].notna()
              & ~codigo.isin(MOTIVOS_EXCLUIDOS_DESPERDICIO)]


def mascaras(base: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(real, evitado) para um universo já filtrado por `universo()`.

    REAL = chegou ao local e não removeu o paciente.
    EVITADO = não chegou ao local.

    As duas usam a mesma lista de EXCLUSÃO, não uma lista de permitidos:
    desfecho novo no vSky passa a aparecer como desperdício, em vez de sumir
    por não constar de uma lista.
    """
    situacao = base["situacao_atendimento"].fillna("").map(nucleo.norm_txt)
    chegou = base["dt_chegada_no_local"].notna()

    # Fora dos dois lados: o paciente foi removido (houve transporte) e o
    # óbito, que é a mesma exclusão clínica dos motivos PCC3/PCG3 registrada
    # como situação. Há 498 registros que dizem "com remoção" sem marcação de
    # chegada: falta a marcação, não é desperdício — o paciente foi removido,
    # logo a viatura chegou.
    fora = (situacao.isin(SITUACOES_COM_REMOCAO)
            | situacao.isin(SITUACOES_EXCLUIDAS_DO_REAL))

    # Situação em branco não sustenta a afirmação de que houve desperdício
    # depois de chegar. Do lado do evitado a condição é factual (saiu e não
    # chegou), independente do desfecho registrado.
    #
    # O real exige tempo de resposta, que o núcleo atribui só à PRIMEIRA
    # viatura a chegar na ocorrência. É o que mantém o desperdício sendo da
    # ocorrência e não do empenho: sem isso, uma viatura de apoio que chegou
    # depois e não removeu contava como desperdício mesmo quando a primeira
    # havia removido o paciente (495 casos, 338 deles com remoção).
    real = chegou & situacao.ne("") & ~fora & base["tempo_resposta"].notna()
    evitado = ~chegou & ~fora
    return real, evitado
