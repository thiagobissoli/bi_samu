"""NCPS: quem é avisado (sistema + e-mail) e quem vê o quê."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import Notificacao, Perfil, Permissao, Usuario
from app.modules.ncps import avisos
from app.modules.ncps.models import Ncps, NcpsSetor

HTML = {"accept": "text/html"}
SENHA = "Senha-teste-avisos-123"
PERFIS = {
    "triagem": ["ncps.listar", "ncps.notificar", "ncps.triar_paciente"],
    "comissao": ["ncps.listar", "ncps.sigilosas"],
    "analista": ["ncps.listar", "ncps.notificar", "ncps.coordenar"],
    "colaborador": ["ncps.notificar"],
}


@pytest.fixture()
def equipe(monkeypatch):
    """Usuários de papéis diferentes, dois setores; tudo apagado ao final."""
    emails = []
    monkeypatch.setattr(avisos, "_enviar",
                        lambda msgs, emp: emails.extend(m[0] for m in msgs))
    db = SessionLocal()
    perms = {p.codigo: p for p in db.scalars(select(Permissao))}
    perfis, pessoas = {}, {}
    for nome, codigos in PERFIS.items():
        perfil = Perfil(empresa_id=1, nome=f"Teste avisos {nome}", ativo=True)
        perfil.permissoes = [perms[c] for c in codigos]
        db.add(perfil)
        perfis[nome] = perfil
    for nome in ("triagem", "comissao", "analista", "outro_analista", "colaborador"):
        u = Usuario(empresa_id=1, nome=f"Teste {nome}", ativo=True,
                    email=f"teste.avisos.{nome}@exemplo.com",
                    senha_hash=hash_password(SENHA))
        u.perfis = [perfis["analista" if nome == "outro_analista" else nome]]
        db.add(u)
        pessoas[nome] = u
    setor = NcpsSetor(empresa_id=1, nome="Teste avisos — setor A", ativo=True)
    setor.usuarios = [pessoas["analista"]]
    outro = NcpsSetor(empresa_id=1, nome="Teste avisos — setor B", ativo=True)
    outro.usuarios = [pessoas["outro_analista"]]
    db.add_all([setor, outro])
    db.commit()
    ids = {k: u.id for k, u in pessoas.items()}
    ids.update(setor=setor.id, outro=outro.id)
    db.close()
    yield {"ids": ids, "emails": emails}

    db = SessionLocal()
    uids = [ids[k] for k in pessoas]
    for n in db.scalars(select(Notificacao).where(Notificacao.usuario_id.in_(uids))):
        db.delete(n)
    for n in db.scalars(select(Ncps).where(Ncps.setor_id.in_([ids["setor"], ids["outro"]]))):
        db.delete(n)
    for n in db.scalars(select(Ncps).where(Ncps.notificante_id.in_(uids))):
        db.delete(n)
    for sid in (ids["setor"], ids["outro"]):
        s = db.get(NcpsSetor, sid)
        s.usuarios = []
        db.delete(s)
    for uid in uids:
        u = db.get(Usuario, uid)
        u.perfis = []
        db.delete(u)
    for p in db.scalars(select(Perfil).where(Perfil.nome.like("Teste avisos %"))):
        p.permissoes = []
        db.delete(p)
    db.commit()
    db.close()


def _cliente(nome):
    c = TestClient(app)
    c.post("/login", data={"email": f"teste.avisos.{nome}@exemplo.com", "senha": SENHA})
    return c


def _avisos_de(uid):
    db = SessionLocal()
    try:
        return [n.titulo for n in db.scalars(select(Notificacao).where(
            Notificacao.usuario_id == uid))]
    finally:
        db.close()


def _notificar(cliente, **campos) -> int:
    from app.modules.ncps.service import buscar_acompanhamento
    html = cliente.post("/ncps/notificar", data={
        "natureza": "paciente", "descricao": "Teste de avisos", **campos}).text
    codigo = re.search(r'font-monospace[^>]*>([A-Z0-9]{8})<', html).group(1)
    db = SessionLocal()
    try:
        return buscar_acompanhamento(db, 1, codigo).id
    finally:
        db.close()


def test_nova_ncps_avisa_so_quem_faz_a_triagem(equipe):
    ids, emails = equipe["ids"], equipe["emails"]
    nid = _notificar(_cliente("colaborador"))
    titulo = f"Nova NCPS #{nid} aguardando triagem"
    assert titulo in _avisos_de(ids["triagem"])
    assert "teste.avisos.triagem@exemplo.com" in emails
    for outro in ("analista", "comissao", "colaborador"):
        assert titulo not in _avisos_de(ids[outro])


def test_sigilosa_avisa_so_a_comissao(equipe):
    ids = equipe["ids"]
    nid = _notificar(_cliente("colaborador"), natureza="trabalhador",
                     tipo_evento_trab="violencia_assedio")
    assert f"Nova NCPS sigilosa #{nid}" in _avisos_de(ids["comissao"])
    assert not [t for t in _avisos_de(ids["triagem"]) if f"#{nid}" in t]


def test_email_nao_leva_o_relato():
    class N:           # NCPS mínima
        id, natureza, confidencial, empresa_id = 7, "paciente", False, 1
    corpo = avisos._corpo("t", ["Tipo: Segurança do paciente."],
                          "https://x/ncps/7", "Abrir")
    assert "Teste de avisos" not in corpo and "https://x/ncps/7" in corpo
    assert N.id == 7


def test_encaminhar_avisa_o_setor_e_retorno_ao_notificante(equipe):
    ids, emails = equipe["ids"], equipe["emails"]
    nid = _notificar(_cliente("colaborador"))
    emails.clear()
    triagem = _cliente("triagem")
    r = triagem.post(f"/ncps/{nid}", data={"secao": "triagem", "natureza": "paciente",
                                           "procedente": "2", "status": "1",
                                           "setor_id": ids["setor"]},
                     follow_redirects=False)
    assert r.status_code == 303
    enc = f"NCPS #{nid} encaminhada ao setor Teste avisos — setor A"
    assert enc in _avisos_de(ids["analista"])
    assert enc not in _avisos_de(ids["outro_analista"])
    assert enc not in _avisos_de(ids["triagem"])          # quem fez não é avisado
    assert "teste.avisos.analista@exemplo.com" in emails
    # mudança de status: quem notificou é avisado, também por e-mail
    assert f"Sua NCPS #{nid}: Em análise" in _avisos_de(ids["colaborador"])
    assert "teste.avisos.colaborador@exemplo.com" in emails


def test_quem_nao_faz_triagem_so_lista_o_proprio_setor(equipe):
    ids = equipe["ids"]
    colaborador, triagem = _cliente("colaborador"), _cliente("triagem")
    do_setor = _notificar(colaborador, descricao="NCPS do setor A")
    de_outro = _notificar(colaborador, descricao="NCPS do setor B")
    sem_setor = _notificar(colaborador, descricao="NCPS aguardando triagem")
    for nid, sid in ((do_setor, ids["setor"]), (de_outro, ids["outro"])):
        triagem.post(f"/ncps/{nid}", data={"secao": "triagem", "natureza": "paciente",
                                           "status": "1", "setor_id": sid})

    analista = _cliente("analista")
    lista = analista.get("/ncps/", headers=HTML).text
    assert f'/ncps/{do_setor}"' in lista
    assert f'/ncps/{de_outro}"' not in lista and f'/ncps/{sem_setor}"' not in lista
    assert "Você vê somente as NCPS encaminhadas ao seu setor" in lista
    assert analista.get(f"/ncps/{de_outro}", headers=HTML).status_code == 404
    assert analista.get(f"/ncps/{sem_setor}", headers=HTML).status_code == 404
    assert analista.get(f"/ncps/{do_setor}", headers=HTML).status_code == 200
    # indicadores e busca seguem a mesma regra
    assert analista.get("/ncps/api/indicadores").json()["data"]["total"] == 1
    assert f'/ncps/{de_outro}"' not in analista.get(
        "/ncps/?q=setor+B", headers=HTML).text
    # quem faz a triagem continua vendo todas as do paciente
    tudo = triagem.get("/ncps/", headers=HTML).text
    assert all(f'/ncps/{n}"' in tudo for n in (do_setor, de_outro, sem_setor))
