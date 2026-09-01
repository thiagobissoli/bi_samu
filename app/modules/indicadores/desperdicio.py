"""Definição única de desperdício operacional (§35.16).

Universo: saída efetiva de viatura (há início de deslocamento).

ÓBITO e HIPOGLICEMIA nunca são desperdício:
  - óbito  = a coluna Óbito da ficha traz um dos desfechos de morte;
  - hipoglicemia = motivo PCG3/SCG2 (diabetes) OU glicemia medida < 80.

REAL     = chegou ao local (Chegada no local) e não removeu o paciente
           (sem Saída para hospital).
EVITADO  = não chegou ao local.

Duas regras que a especificação não fixa e vieram de decisão do serviço:
  - o real exige tempo de resposta, que o núcleo atribui só à PRIMEIRA
    viatura a chegar. Sem isso, uma viatura de apoio que chegou depois e não
    removeu contava como desperdício mesmo quando a primeira havia removido
    o paciente;
  - PCC3 (PCR/óbito) não é exclusão por si: vale o que a coluna Óbito diz.

Este módulo existe porque as três telas — Indicadores, Painel de Gestão e
Reunião de Indicadores — calculavam o mesmo indicador cada uma por si, e
chegaram a mostrar números diferentes para a mesma semana.
"""

from __future__ import annotations

import pandas as pd

from app.modules.indicadores.constants import (LIMITE_HIPOGLICEMIA,
                                               MOTIVOS_HIPOGLICEMIA)


def universo(df: pd.DataFrame) -> pd.DataFrame:
    """Saídas efetivas de viatura — o denominador das taxas."""
    return df[df["dt_inicio_deslocamento"].notna()]


def obito(base: pd.DataFrame) -> pd.Series:
    """Coluna Óbito com desfecho de morte (qualquer momento)."""
    return base["obito_constatado"].fillna(False)


def hipoglicemia(base: pd.DataFrame) -> pd.Series:
    """Motivo de diabetes/hipoglicemia ou glicemia medida abaixo do limite.

    Glicemia não medida (0 na ficha, nula aqui) não afirma hipoglicemia.
    """
    codigo = base["motivo"].fillna("").str.split(" ").str[0].str.upper()
    glicemia = pd.to_numeric(base["glicemia"], errors="coerce")
    return codigo.isin(MOTIVOS_HIPOGLICEMIA) | (glicemia < LIMITE_HIPOGLICEMIA)


def mascaras(base: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(real, evitado) para um universo já filtrado por `universo()`."""
    fora = obito(base) | hipoglicemia(base)
    chegou = base["dt_chegada_no_local"].notna()
    removeu = base["dt_saida_para_hospital"].notna()

    real = chegou & ~removeu & ~fora & base["tempo_resposta"].notna()
    evitado = ~chegou & ~fora
    return real, evitado
