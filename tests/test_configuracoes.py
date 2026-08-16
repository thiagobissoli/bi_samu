"""Testes da tela de Configurações e do catálogo de chaves."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.seeds import ADMIN_EMAIL, ADMIN_SENHA
from app.main import app
from app.modules.configuracoes.catalogo import CATALOGO, catalogadas

client = TestClient(app)
RAIZ = Path(__file__).resolve().parent.parent / "app"


def _login():
    client.post("/login", data={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})


def test_catalogo_cobre_toda_constante_config_do_codigo():
    """Chave nova no código tem que entrar no catálogo — senão some da tela.

    Este teste é o que mantém a promessa de "todas as chaves disponíveis":
    quem criar uma CONFIG_* nova e esquecer o catálogo quebra aqui.
    """
    conhecidas = catalogadas()
    faltando = {}
    for arquivo in RAIZ.rglob("*.py"):
        if "__pycache__" in str(arquivo):
            continue
        for nome, valor in re.findall(
                r'^(CONFIG_[A-Z_0-9]+)\s*=\s*"([a-z0-9_]+)"',
                arquivo.read_text(), re.MULTILINE):
            if valor not in conhecidas:
                faltando.setdefault(valor, []).append(
                    f"{arquivo.relative_to(RAIZ)}:{nome}")
    assert not faltando, (
        "chaves usadas no código e ausentes do catálogo "
        "(app/modules/configuracoes/catalogo.py): " + str(faltando))


def test_catalogo_nao_tem_chave_repetida():
    todas = [c.chave for grupo in CATALOGO for c in grupo.chaves]
    repetidas = {c for c in todas if todas.count(c) > 1}
    assert not repetidas, repetidas


def test_toda_chave_do_catalogo_tem_explicacao():
    """O (?) da tela sai daqui; chave sem texto vira um (?) mudo."""
    sem_ajuda = [c.chave for grupo in CATALOGO for c in grupo.chaves
                 if not c.ajuda.strip()]
    assert not sem_ajuda, sem_ajuda


def test_metas_dos_indicadores_estao_no_catalogo():
    """As metas da Auditoria de Ocorrências são editáveis pela tela."""
    from app.modules.indicadores.constants import (METAS_TEMPO,
                                                   PREFIXO_CONFIG_META)

    conhecidas = catalogadas()
    for col, padrao in METAS_TEMPO.items():
        chave = f"{PREFIXO_CONFIG_META}{col}_segundos"
        assert chave in conhecidas, chave
        assert conhecidas[chave].padrao == str(padrao)
        assert conhecidas[chave].tipo == "numero"


def test_pagina_lista_todas_as_chaves_do_catalogo():
    _login()
    html = client.get("/configuracoes/",
                      headers={"accept": "text/html"}).text
    for chave in catalogadas():
        assert f'name="chave" value="{chave}"' in html, chave
    # e cada uma leva o seu (?)
    assert html.count('data-bs-toggle="popover"') >= len(catalogadas())


def test_pagina_mostra_chave_gravada_fora_do_catalogo():
    """Chave criada à mão não pode sumir da tela por não estar no catálogo."""
    from app.core.config_service import set_config
    from app.core.database import SessionLocal

    _login()
    db = SessionLocal()
    try:
        set_config(db, "chave_de_teste_fora_do_catalogo", "valor", 1)
        html = client.get("/configuracoes/",
                          headers={"accept": "text/html"}).text
        assert "chave_de_teste_fora_do_catalogo" in html
        assert "Outras chaves" in html
    finally:
        _apagar(db, "chave_de_teste_fora_do_catalogo")
        db.close()


def _apagar(db, chave: str) -> None:
    from sqlalchemy import select

    from app.core.config_service import _cache
    from app.models import Configuracao

    item = db.scalar(select(Configuracao).where(
        Configuracao.chave == chave, Configuracao.empresa_id == 1))
    if item is not None:
        db.delete(item)
        db.commit()
    _cache.pop((1, chave), None)


def test_salvar_meta_pela_tela_muda_a_auditoria():
    """Editar a meta na tela altera de fato o julgamento do indicador."""
    from app.core.database import SessionLocal
    from app.modules.indicadores.constants import PREFIXO_CONFIG_META
    from app.modules.indicadores.service import IndicadoresService

    _login()
    chave = f"{PREFIXO_CONFIG_META}t_p1_segundos"
    service = IndicadoresService(1)
    assert service._metas_tempo()["t_p1"] == 90

    db = SessionLocal()
    try:
        resp = client.post("/configuracoes/salvar",
                           data={"chave": chave, "valor": "300"},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert service._metas_tempo()["t_p1"] == 300
    finally:
        _apagar(db, chave)
        db.close()
    assert service._metas_tempo()["t_p1"] == 90


def test_chave_somente_leitura_nao_ganha_campo_de_edicao():
    """Status escrito pelo sistema é exibido, não editável."""
    _login()
    html = client.get("/configuracoes/",
                      headers={"accept": "text/html"}).text
    trecho = html.split('name="chave" value="backup_status"')[1][:400]
    assert "preenchido pelo sistema" in trecho
    assert 'name="valor"' not in trecho


@pytest.mark.parametrize("chave,esperado", [
    ("vsky_senha", True), ("ia_api_key", True), ("smtp_pass", True),
    ("vsky_usuario", False), ("backup_hora", False),
])
def test_chaves_sensiveis_seguem_marcadas(chave, esperado):
    from app.core.crypto import is_sensitive

    assert chave in catalogadas(), chave
    assert is_sensitive(chave) is esperado
