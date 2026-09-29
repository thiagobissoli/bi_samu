"""Permissões do módulo NCPS (§9, §38.9) e regras de quem vê, tria e trata.

No sistema anterior as regras eram por nome de perfil; aqui viram
permissões, e cada perfil recebe as que precisar:

| Perfil antigo              | Permissões                                          |
|----------------------------|-----------------------------------------------------|
| Qualidade                  | listar, triar_paciente, exportar, cadastros         |
| SESMT                      | listar, triar_trabalhador, exportar, pgr            |
| Comissão de Integridade    | listar, sigilosas                                   |
| Coordenador (analista)     | listar, coordenar — e vínculo a um ou mais setores  |
| Qualquer colaborador       | notificar                                           |
| Administrador              | todas (o seed garante)                              |

Regras (as mesmas do sistema anterior):

- Violência/assédio (sigilosa) → só quem tem `ncps.sigilosas`.
- Paciente → triagem por `ncps.triar_paciente`; trabalhador → `ncps.triar_trabalhador`.
- A triagem encaminha a NCPS a um **setor**; os usuários vinculados ao setor
  (em Cadastros NCPS) fazem a análise (classificação, causas, risco, ações).
- Quem não faz triagem (analistas com `ncps.coordenar`, por exemplo) vê e
  lista **somente** as NCPS encaminhadas ao seu setor — nem as de outros
  setores, nem as que ainda aguardam triagem.
- NCPS importadas do sistema anterior continuam com o coordenador de lá.

As funções abaixo são puras (usuário + notificação → bool) para poderem
ser reaproveitadas tanto nas consultas quanto nas telas.
"""

from sqlalchemy import or_

PERMISSIONS = [
    "ncps.notificar",
    "ncps.listar",
    "ncps.triar_paciente",
    "ncps.triar_trabalhador",
    "ncps.sigilosas",
    "ncps.coordenar",
    "ncps.exportar",
    "ncps.cadastros",
    "ncps.pgr",
]

TRIAGEM = {
    "paciente": "ncps.triar_paciente",
    "trabalhador": "ncps.triar_trabalhador",
}


def setores_do_usuario(usuario) -> set[int]:
    """Ids dos setores a que o usuário pertence (cacheado no objeto).

    Objetos de teste podem trazer `setores_ncps` pronto.
    """
    ja = getattr(usuario, "setores_ncps", None)
    if ja is not None:
        return set(ja)
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.modules.ncps.models import NcpsSetor, ncps_setor_usuarios

    db = SessionLocal()
    try:
        ids = set(db.scalars(select(ncps_setor_usuarios.c.setor_id).join(
            NcpsSetor, NcpsSetor.id == ncps_setor_usuarios.c.setor_id).where(
            ncps_setor_usuarios.c.usuario_id == usuario.id,
            NcpsSetor.ativo.is_(True), NcpsSetor.deleted_at.is_(None))))
    finally:
        db.close()
    try:
        usuario.setores_ncps = ids
    except AttributeError:
        pass
    return ids


def _do_meu_setor(ncps, usuario) -> bool:
    return (ncps.setor_id is not None
            and ncps.setor_id in setores_do_usuario(usuario)) \
        or (ncps.coordenador_id is not None and ncps.coordenador_id == usuario.id)


def naturezas_triagem(permissoes: set[str]) -> list[str]:
    """Naturezas que o usuário tria (vazio para quem não tria)."""
    return [nat for nat, perm in TRIAGEM.items() if perm in permissoes]


def naturezas_visiveis(permissoes: set[str]) -> list[str]:
    """Naturezas que o usuário vê por inteiro: só as que ele tria. Os demais
    veem apenas as NCPS encaminhadas ao seu setor."""
    return sorted(naturezas_triagem(permissoes))


def filtrar_visiveis(consulta, usuario):
    """Restringe um select(Ncps) ao que o usuário pode ver."""
    from app.modules.ncps.models import Ncps

    permissoes = usuario.permissoes
    ve_sigilosas = "ncps.sigilosas" in permissoes
    naturezas = naturezas_visiveis(permissoes)

    condicoes = []
    if ve_sigilosas:
        condicoes.append(Ncps.confidencial.is_(True))
    comuns = [Ncps.coordenador_id == usuario.id]
    setores = setores_do_usuario(usuario)
    if setores:
        comuns.append(Ncps.setor_id.in_(setores))
    if naturezas:
        comuns.append(Ncps.natureza.in_(naturezas))
    condicoes.append(Ncps.confidencial.is_(False) & or_(*comuns))
    return consulta.where(or_(*condicoes))


def pode_ver(ncps, usuario) -> bool:
    permissoes = usuario.permissoes
    if ncps.confidencial:
        return "ncps.sigilosas" in permissoes
    return ncps.natureza in naturezas_visiveis(permissoes) \
        or _do_meu_setor(ncps, usuario)


def pode_triar(ncps, usuario) -> bool:
    """Classificar a procedência, encaminhar ao setor e mudar o status."""
    permissoes = usuario.permissoes
    if ncps.confidencial:
        return "ncps.sigilosas" in permissoes
    return TRIAGEM.get(ncps.natureza) in permissoes


def pode_tratar(ncps, usuario) -> bool:
    """Registrar classificação, análise de causas, matriz de risco e ações."""
    if pode_triar(ncps, usuario):
        return True
    return not ncps.confidencial and _do_meu_setor(ncps, usuario)


# ------------------------------------------------------------------ tramitação

def do_setor(ncps, usuario) -> bool:
    """O usuário é analista do setor a que a NCPS está encaminhada."""
    return (not ncps.confidencial and ncps.setor_id is not None
            and ncps.setor_id in setores_do_usuario(usuario))


def aberta(ncps) -> bool:
    from app.modules.ncps.constants import STATUS_ABERTOS
    return ncps.status in STATUS_ABERTOS


def pode_assumir(ncps, usuario) -> bool:
    """Analista do setor pega a NCPS para si."""
    return aberta(ncps) and do_setor(ncps, usuario) \
        and ncps.responsavel_id != usuario.id


def pode_atribuir(ncps, usuario) -> bool:
    """Escolher quem, no setor, cuida da NCPS: a triagem ou o próprio setor."""
    return aberta(ncps) and ncps.setor_id is not None and not ncps.confidencial \
        and (pode_triar(ncps, usuario) or do_setor(ncps, usuario))


def pode_devolver(ncps, usuario) -> bool:
    """O setor devolve à triagem (ex.: não é do setor), com justificativa."""
    return aberta(ncps) and do_setor(ncps, usuario)


def pode_concluir(ncps, usuario) -> bool:
    """Quem analisa sinaliza que terminou; a triagem é avisada para revisar."""
    return aberta(ncps) and not ncps.confidencial and ncps.setor_id is not None \
        and (do_setor(ncps, usuario) or pode_triar(ncps, usuario))
