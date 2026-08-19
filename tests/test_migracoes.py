"""Migrações aplicadas ao subir a aplicação.

Atualizar o código sem atualizar o schema derrubou a instalação em produção
com "Unknown column 'linhas_superadas'": create_all() cria tabela que falta,
mas nunca coluna que falta. Estes testes protegem o caminho do boot.
"""

import pytest
from sqlalchemy import inspect, text

from app.core.database import aplicar_migracoes, engine


def _revisao() -> str | None:
    with engine.connect() as conn:
        if not inspect(engine).has_table("alembic_version"):
            return None
        return conn.execute(text("SELECT version_num FROM alembic_version")
                            ).scalar()


def _colunas(tabela: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(tabela)}


def test_banco_fica_no_head_depois_do_boot():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.core.database import _config_alembic

    aplicar_migracoes()
    config: Config = _config_alembic()
    head = ScriptDirectory.from_config(config).get_current_head()
    assert _revisao() == head, "o boot deixou o banco atrás das migrações"


def test_coluna_de_migracao_existe():
    """A coluna que faltava na produção — o caso concreto que quebrou."""
    assert "linhas_superadas" in _colunas("vsky_importacoes")


def test_boot_recupera_banco_sem_carimbo_do_alembic():
    """Instalação anterior ao versionamento: o schema existe, mas nenhuma
    revisão está carimbada. Sem tratar isso, o upgrade tenta recriar tudo e
    morre em "Table 'arquivos' already exists"."""
    if not inspect(engine).has_table("alembic_version"):
        pytest.skip("banco sem tabela de versão")
    antes = _revisao()
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM alembic_version"))
        conn.commit()
    try:
        aplicar_migracoes()
        assert _revisao() is not None, "o banco continuou sem carimbo"
        assert "linhas_superadas" in _colunas("vsky_importacoes")
    finally:
        if antes and _revisao() != antes:
            with engine.connect() as conn:
                conn.execute(text("DELETE FROM alembic_version"))
                conn.execute(text("INSERT INTO alembic_version VALUES (:v)"),
                             {"v": antes})
                conn.commit()


def test_falha_de_migracao_nao_impede_o_boot(monkeypatch, caplog):
    """Melhor subir e registrar o erro do que deixar o serviço fora do ar."""
    import logging

    from alembic import command

    def _explode(*a, **k):
        raise RuntimeError("migração quebrada")

    monkeypatch.setattr(command, "upgrade", _explode)
    with caplog.at_level(logging.ERROR):
        aplicar_migracoes()          # não pode levantar
    assert any("alembic upgrade head" in r.message + str(r.exc_info or "")
               or "migrações" in r.message for r in caplog.records)
