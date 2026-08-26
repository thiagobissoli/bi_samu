"""Definição única de desperdício operacional (§35.16).

Desperdício REAL: a viatura saiu, CHEGOU no local e NÃO removeu o paciente.
Desperdício EVITADO: saiu sem necessidade e foi mitigada no trajeto, sem
chegar ao local.

Em ambos ficam de fora as causas clínicas que não são desperdício: PCR,
óbito e hipoglicemia (motivos PCC3 e PCG3, mais a situação "óbito
informado", que é o mesmo desfecho registrado do outro lado).

Este módulo existe porque a Reunião de Indicadores e o Painel de Gestão
calculavam o mesmo indicador cada um por si, e as duas telas chegaram a
mostrar números diferentes para a mesma semana.
"""

from __future__ import annotations

import pandas as pd

from app.modules.indicadores import nucleo
from app.modules.indicadores.constants import (MOTIVOS_EXCLUIDOS_DESPERDICIO,
                                               SITUACOES_COM_REMOCAO,
                                               SITUACOES_DESPERDICIO,
                                               SITUACOES_EXCLUIDAS_DO_REAL)


def universo(df: pd.DataFrame) -> pd.DataFrame:
    """Saídas efetivas que podem ser desperdício (exclui PCR/óbito/hipoglicemia)."""
    codigo = df["motivo"].fillna("").str.split(" ").str[0].str.upper()
    return df[df["dt_inicio_deslocamento"].notna()
              & ~codigo.isin(MOTIVOS_EXCLUIDOS_DESPERDICIO)]


def mascaras(base: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(real, evitado) para um universo já filtrado por `universo()`."""
    situacao = base["situacao_atendimento"].fillna("").map(nucleo.norm_txt)
    chegou = base["dt_chegada_no_local"].notna()

    # REAL = chegou e não removeu. A lista é a das situações em que HOUVE
    # remoção — assim um desfecho novo no vSky entra como desperdício e
    # aparece, em vez de sumir por não estar numa lista de permitidos.
    # Situação em branco fica de fora: desfecho desconhecido não sustenta a
    # afirmação de que houve desperdício.
    real = (chegou & situacao.ne("")
            & ~situacao.isin(SITUACOES_COM_REMOCAO)
            & ~situacao.isin(SITUACOES_EXCLUIDAS_DO_REAL))

    # EVITADO = não chegou. Aqui não há remoção para servir de critério, e
    # nem toda saída interrompida é desperdício (redirecionamento para caso
    # mais grave, por exemplo), então vale a lista curada de desfechos.
    evitado = ~chegou & situacao.isin(SITUACOES_DESPERDICIO)
    return real, evitado
