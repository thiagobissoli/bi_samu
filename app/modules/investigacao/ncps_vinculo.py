"""Ligação entre a Investigação de Eventos e as notificações NCPS.

Uma investigação pode começar por uma ocorrência do vSky ou por uma NCPS.
Quando a NCPS informa o número da ocorrência, a investigação segue pela
ocorrência (cadeia do chamado, indicadores, prontuário) e leva o relato da
notificação junto — inclusive para a análise por IA.

Regras de acesso: vale a visibilidade do módulo NCPS (permissions.py de lá).
Notificações sigilosas (violência/assédio) nunca entram numa investigação:
o relato não pode circular fora da Comissão de Integridade nem ir para um
provedor de IA.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session


def normalizar_ocorrencia(valor) -> str:
    """"2.715.799", " 2715799 " → "2715799"."""
    return re.sub(r"\D", "", str(valor or ""))


def _pode_usar(n, usuario) -> bool:
    from app.modules.ncps.permissions import pode_ver

    return (usuario is not None and "ncps.listar" in usuario.permissoes
            and not n.confidencial and pode_ver(n, usuario))


def resumo(n) -> dict:
    from app.modules.ncps import constants as cat

    classificacao = []
    if n.natureza == "paciente":
        for campo, (rotulo, opcoes) in cat.CLASSIFICACAO_PACIENTE.items():
            valor = getattr(n, campo)
            if valor not in (None, "0", "99"):
                classificacao.append((rotulo, opcoes.get(valor, valor)))
    elif n.tipo_evento_trab:
        classificacao.append(("Tipo de evento",
                              cat.TIPO_EVENTO_TRABALHADOR.get(n.tipo_evento_trab,
                                                              n.tipo_evento_trab)))
    return {
        "id": n.id,
        "natureza": cat.NATUREZA.get(n.natureza, n.natureza),
        "status": cat.STATUS.get(n.status, n.status),
        "registrado_em": n.registrado_em,
        "data_evento": (n.data_hora_ocorrencia.strftime("%d/%m/%Y %H:%M")
                        if n.data_hora_ocorrencia else None),
        "local": n.local,
        "id_ocorrencia": normalizar_ocorrencia(n.id_ocorrencia) or None,
        "descricao": n.descricao or "",
        "sugestao": n.sugestao or "",
        "classificacao": classificacao,
    }


def carregar(db: Session, usuario, protocolo) -> tuple[object | None, str | None]:
    """NCPS pelo protocolo, se o usuário puder usá-la numa investigação."""
    from app.modules.ncps.models import Ncps

    if "ncps.listar" not in usuario.permissoes:
        return None, "Seu perfil não tem acesso às notificações NCPS."
    try:
        protocolo = int(str(protocolo).strip().lstrip("#"))
    except ValueError:
        return None, "Informe o número do protocolo da NCPS."
    n = db.scalar(select(Ncps).where(
        Ncps.id == protocolo, Ncps.empresa_id == usuario.empresa_id,
        Ncps.deleted_at.is_(None)))
    if n is None or not _visivel(n, usuario):
        return None, f"NCPS #{protocolo} não encontrada."
    if n.confidencial:
        return None, (f"A NCPS #{protocolo} é sigilosa (violência/assédio) e é "
                      "tratada só pela Comissão de Integridade, fora da "
                      "investigação de eventos.")
    return n, None


def _visivel(n, usuario) -> bool:
    from app.modules.ncps.permissions import pode_ver
    return pode_ver(n, usuario)


def da_ocorrencia(db: Session, usuario, numero: str) -> list[dict]:
    """NCPS (não sigilosas, visíveis ao usuário) que citam a ocorrência."""
    from app.modules.ncps.models import Ncps

    numero = normalizar_ocorrencia(numero)
    if not numero or usuario is None or "ncps.listar" not in usuario.permissoes:
        return []
    candidatas = db.scalars(select(Ncps).where(
        Ncps.empresa_id == usuario.empresa_id, Ncps.deleted_at.is_(None),
        Ncps.confidencial.is_(False), Ncps.id_ocorrencia.isnot(None),
        Ncps.id_ocorrencia.contains(numero)).order_by(Ncps.id))
    return [resumo(n) for n in candidatas
            if normalizar_ocorrencia(n.id_ocorrencia) == numero
            and _pode_usar(n, usuario)]


def bloco_prompt(ncps: list[dict]) -> list[str]:
    """Trecho do material da IA com as notificações ligadas à ocorrência."""
    if not ncps:
        return []
    partes = ["", "# Notificações NCPS sobre este atendimento",
              "Relatos feitos por profissionais no sistema de notificação de "
              "eventos. São a percepção de quem notificou: trate como "
              "indício a confirmar, sem atribuir culpa individual."]
    for n in ncps:
        partes.append(f"## NCPS #{n['id']} — {n['natureza']} · situação: {n['status']}")
        if n["classificacao"]:
            partes.append("Classificação: " + "; ".join(
                f"{r}: {v}" for r, v in n["classificacao"]))
        partes.append("Relato: " + n["descricao"][:4000])
        if n["sugestao"]:
            partes.append("Ação realizada / sugestão: " + n["sugestao"][:2000])
    return partes


PREFIXO = "NCPS-"


def chave_rac(ncps_id: int) -> str:
    """Identificador do RAC de uma NCPS sem ocorrência (campo `ocorrencia`
    das análises): "NCPS-123". Ocorrências do vSky são só dígitos, então
    não há colisão."""
    return f"{PREFIXO}{int(ncps_id)}"


def id_da_chave(numero: str) -> int | None:
    if not str(numero or "").upper().startswith(PREFIXO):
        return None
    try:
        return int(str(numero)[len(PREFIXO):])
    except ValueError:
        return None


def tratativa(n) -> str:
    """O que a equipe já registrou na NCPS, em texto para a IA."""
    from app.modules.ncps import constants as cat

    partes = []
    a = n.analise
    if a:
        for rotulo, valor in (("Cronologia", a.cronologia),
                              ("Problemas identificados", a.problemas),
                              ("Fontes consultadas", a.fontes),
                              ("Barreiras", a.barreiras),
                              ("Recomendações", a.recomendacoes)):
            if valor:
                partes.append(f"{rotulo}: {valor}")
    for c in n.causas:
        categorias = cat.METODOS_CAUSA.get(c.metodo, {})
        partes.append(f"Causa ({'Londres' if c.metodo == 'londres' else 'Ishikawa'}"
                      f" · {categorias.get(c.categoria, c.categoria)})"
                      f"{' [causa raiz]' if c.causa_raiz else ''}: {c.descricao}")
    for r in n.riscos:
        nivel = r.nivel
        partes.append(f"Risco {r.momento} (matriz PGR): P{r.probabilidade} × "
                      f"S{r.severidade} = {nivel['rotulo'] if nivel else '—'}"
                      + (f" — {r.justificativa}" if r.justificativa else ""))
    for acao in n.acoes:
        partes.append(f"Ação ({cat.STATUS_ACAO.get(acao.status, acao.status)}): "
                      f"{acao.descricao}")
    return "\n".join(partes)


def dossie(db: Session, usuario, ncps_id: int) -> dict:
    """Dossiê de uma NCPS sem ocorrência no vSky, no formato do dossiê da
    ocorrência — as telas, a IA e o PDF do RAC usam o mesmo caminho."""
    from app.modules.investigacao.ia_analise import historico, ultima_analise

    n, erro = carregar(db, usuario, ncps_id) if usuario is not None else (
        None, "Acesso à NCPS não verificado.")
    if n is None:
        return {"investigacao": {"erro": erro}}
    r = resumo(n)
    numero = chave_rac(n.id)
    registrado = r["registrado_em"]
    inv = {
        "origem": "ncps", "ncps_id": n.id, "ocorrencia": numero,
        "momento": r["data_evento"] or (registrado.strftime("%d/%m/%Y %H:%M")
                                        if registrado else ""),
        "cidade": None, "situacao": r["status"], "com_empenho": False,
        "codigo": "; ".join(f"{a}: {b}" for a, b in r["classificacao"]) or None,
        "risco": None, "motivo": None, "tipo": r["natureza"],
        "cadeia": [], "equipe": [], "situacoes": [], "veredito": "",
        "paciente": "", "paciente_iniciais": "", "idade": "", "sexo": "",
        "endereco": r["local"] or "", "unidade": None,
        "municipio_unidade": None, "fora_do_municipio": False,
        "tempo_resposta": None, "registro_id": None,
    }
    cronologia = []
    if r["data_evento"]:
        cronologia.append({"quando": r["data_evento"],
                           "evento": "Evento relatado na notificação",
                           "origem": f"NCPS #{n.id}"})
    if registrado:
        cronologia.append({"quando": registrado.strftime("%d/%m/%Y %H:%M"),
                           "evento": "Notificação registrada",
                           "origem": f"NCPS #{n.id}"})
    versoes = historico(db, usuario.empresa_id, numero)
    return {
        "origem": "ncps", "investigacao": inv, "ncps": [r],
        "tratativa_ncps": tratativa(n),
        "indicadores": [], "atraso": {}, "fatores_tr": {}, "prontuario": None,
        "cronologia": cronologia,
        "analise_ia": ultima_analise(db, usuario.empresa_id, numero),
        "relatos": (versoes[0].relatos or "") if versoes else "",
        "versoes": [{
            "id": v.id, "versao": v.versao, "status": v.status,
            "gerado_em": v.gerado_em.strftime("%d/%m/%Y %H:%M") if v.gerado_em else "",
            "feedback": v.feedback,
            "aprovado_em": v.aprovado_em.strftime("%d/%m/%Y %H:%M") if v.aprovado_em else None,
            "aprovado_nome": v.aprovado_nome,
        } for v in versoes],
    }
