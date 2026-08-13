"""Configuração da suíte de testes.

Os testes rodam contra o banco da aplicação (não há base separada), e
vários deles precisam gravar configurações — credenciais do vSky, SMTP,
destinatários do relatório. Sem proteção, rodar a suíte **destrói a
configuração real**: foi o que aconteceu com as credenciais do vSky,
sobrescritas por 'usuario.teste' e 'u'/'s'.

A fixture abaixo tira uma foto da tabela `configuracoes` antes da
suíte e a restaura ao final, byte a byte (valores sensíveis continuam
cifrados na foto — nada é decifrado aqui). Chaves criadas durante os
testes são removidas.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def preservar_configuracoes():
    """Restaura a tabela `configuracoes` ao estado anterior à suíte."""
    from sqlalchemy import select

    from app.core.config_service import invalidate_config
    from app.core.database import SessionLocal
    from app.models import Configuracao

    db = SessionLocal()
    try:
        antes = {
            (c.empresa_id, c.chave): (c.valor, c.deleted_at)
            for c in db.scalars(select(Configuracao))
        }
    finally:
        db.close()

    yield

    db = SessionLocal()
    try:
        for item in db.scalars(select(Configuracao)):
            chave = (item.empresa_id, item.chave)
            if chave in antes:
                item.valor, item.deleted_at = antes[chave]
            else:
                db.delete(item)          # chave criada pelos testes
        db.commit()
    finally:
        db.close()
    invalidate_config()                  # cache em memória volta ao real
