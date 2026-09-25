"""Página inicial: boas-vindas, alertas do usuário e resumo de gestão.

Cada bloco só aparece para quem tem a permissão do módulo de onde ele vem.
Os alertas são consultas leves ao banco; o resumo de gestão, que precisa do
núcleo dos Indicadores (centenas de milhares de linhas), é carregado à parte
pela página (/inicio/api/gestao) para a tela abrir na hora.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import utcnow

NIVEL_ORDEM = {"danger": 0, "warning": 1, "info": 2, "success": 3}


def _agora_local(tz: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def boas_vindas(usuario, tz: str) -> dict:
    agora = _agora_local(tz)
    saudacao = ("Bom dia" if 5 <= agora.hour < 12
                else "Boa tarde" if 12 <= agora.hour < 18 else "Boa noite")
    dias = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo"]
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]
    return {
        "saudacao": f"{saudacao}, {(usuario.nome or '').split(' ')[0]}",
        "data": f"{dias[agora.weekday()]}, {agora.day} de "
                f"{meses[agora.month - 1]} de {agora.year}",
    }


def dados_usuario(usuario) -> dict:
    return {
        "nome": usuario.nome,
        "email": usuario.email,
        "telefone": usuario.telefone,
        "perfis": [p.nome for p in usuario.perfis
                   if p.ativo and p.deleted_at is None],
        "ultimo_login": usuario.ultimo_login,
        "ultimo_ip": usuario.ultimo_ip,
        "mfa": usuario.mfa_habilitado,
        "email_confirmado": usuario.email_confirmado,
    }


# ------------------------------------------------------------------ alertas

def _alerta(nivel, icone, titulo, texto="", link=None, contagem=None,
            grupo="geral") -> dict:
    return {"nivel": nivel, "icone": icone, "titulo": titulo, "texto": texto,
            "link": link, "contagem": contagem, "grupo": grupo}


def alertas(db: Session, usuario) -> list[dict]:
    perms = usuario.permissoes
    lista: list[dict] = []
    for fonte in (_alertas_ncps, _alertas_investigacao, _alertas_vsky,
                  _alertas_notificacoes, _alertas_conta):
        try:
            lista += fonte(db, usuario, perms)
        except Exception:  # noqa: BLE001 — um bloco com erro não derruba a página
            import logging
            logging.getLogger("uvicorn.error").exception(
                "Alerta da página inicial falhou: %s", fonte.__name__)
    return sorted(lista, key=lambda a: NIVEL_ORDEM.get(a["nivel"], 9))


def _alertas_ncps(db, usuario, perms) -> list[dict]:
    if "ncps.listar" not in perms:
        return []
    from app.modules.ncps import constants as cat
    from app.modules.ncps.models import Ncps, NcpsOcupacional
    from app.modules.ncps.permissions import (filtrar_visiveis,
                                              naturezas_triagem, pode_tratar)
    from app.modules.ncps.service import acoes_atrasadas

    base = select(Ncps).where(Ncps.empresa_id == usuario.empresa_id,
                              Ncps.deleted_at.is_(None))
    lista = []

    # 1. aguardando a MINHA triagem
    triagem = naturezas_triagem(perms)
    if triagem or "ncps.sigilosas" in perms:
        q = filtrar_visiveis(select(func.count()).select_from(Ncps).where(
            Ncps.empresa_id == usuario.empresa_id, Ncps.deleted_at.is_(None),
            Ncps.status == "0"), usuario)
        condicoes = []
        if triagem:
            condicoes.append(Ncps.natureza.in_(triagem) & Ncps.confidencial.is_(False))
        if "ncps.sigilosas" in perms:
            condicoes.append(Ncps.confidencial.is_(True))
        from sqlalchemy import or_
        n = db.scalar(q.where(or_(*condicoes))) or 0
        if n:
            lista.append(_alerta(
                "warning", "fa-inbox", f"{n} NCPS aguardando avaliação",
                "Notificações recebidas que ainda não passaram pela triagem.",
                "/ncps/?status=0", n, "ncps"))

    # 2. encaminhadas ao(s) meu(s) setor(es) para análise
    from sqlalchemy import or_ as _ou

    from app.modules.ncps.permissions import setores_do_usuario

    meus = setores_do_usuario(usuario)
    condicoes = [Ncps.coordenador_id == usuario.id]
    if meus:
        condicoes.append(Ncps.setor_id.in_(meus))
    minhas = list(db.scalars(base.where(_ou(*condicoes),
                                        Ncps.confidencial.is_(False),
                                        Ncps.status.in_(cat.STATUS_ABERTOS))))
    if minhas:
        nomes = sorted({n.setor.nome for n in minhas if n.setor})
        lista.append(_alerta(
            "warning", "fa-users-gear",
            f"{len(minhas)} NCPS aguardando análise do seu setor",
            ("Setor " + ", ".join(nomes) + ". " if nomes else "")
            + "Registre a análise e o plano de ação.",
            "/ncps/?atribuidas=1", len(minhas), "ncps"))

    # 3. ações do plano com prazo vencido, nas NCPS que posso tratar
    abertas = db.scalars(filtrar_visiveis(
        base.where(Ncps.status.in_(("0", "1", "2"))), usuario))
    atrasadas = [(n, a) for n in abertas if pode_tratar(n, usuario)
                 for a in acoes_atrasadas(n)]
    if atrasadas:
        ncps_ids = sorted({n.id for n, _ in atrasadas})
        link = f"/ncps/{ncps_ids[0]}#acoes" if len(ncps_ids) == 1 else "/ncps/"
        lista.append(_alerta(
            "danger", "fa-calendar-xmark",
            f"{len(atrasadas)} ação(ões) de plano de ação atrasada(s)",
            "NCPS: " + ", ".join(f"#{i}" for i in ncps_ids[:8])
            + ("…" if len(ncps_ids) > 8 else ""), link, len(atrasadas), "ncps"))

    # 4. revisão do inventário do PGR após acidente (NR-1 1.5.4.4.6 "d")
    if "ncps.triar_trabalhador" in perms:
        n = db.scalar(select(func.count()).select_from(NcpsOcupacional).join(
            Ncps, Ncps.id == NcpsOcupacional.ncps_id).where(
            Ncps.empresa_id == usuario.empresa_id, Ncps.deleted_at.is_(None),
            NcpsOcupacional.revisar_pgr.is_(True),
            NcpsOcupacional.pgr_revisado_em.is_(None))) or 0
        if n:
            lista.append(_alerta(
                "warning", "fa-helmet-safety",
                f"Revisão do PGR pendente em {n} NCPS",
                "Acidente ou doença do trabalho exige revisar a avaliação de "
                "riscos (NR-1 1.5.4.4.6 \"d\").",
                "/ncps/?natureza=trabalhador", n, "ncps"))
    return lista


def respostas_ncps(db: Session, usuario, dias: int = 30) -> list[dict]:
    """NCPS que o usuário registrou (identificado) e que já tiveram retorno."""
    if "ncps.notificar" not in usuario.permissoes:
        return []
    from app.modules.ncps import constants as cat
    from app.modules.ncps.models import Ncps

    desde = utcnow() - timedelta(days=dias)
    itens = db.scalars(select(Ncps).where(
        Ncps.empresa_id == usuario.empresa_id, Ncps.deleted_at.is_(None),
        Ncps.notificante_id == usuario.id, Ncps.status != "0",
        Ncps.updated_at >= desde).order_by(Ncps.updated_at.desc()).limit(8))
    resultado = []
    for n in itens:
        rotulo, texto, etapa = cat.SITUACAO_ACOMPANHAMENTO.get(
            n.status, ("Em análise", "", 2))
        acoes = [a for a in n.acoes if a.status != "cancelada"]
        resultado.append({
            "id": n.id, "situacao": rotulo, "texto": texto, "etapa": etapa,
            "resumo": (n.descricao or "")[:90],
            "atualizada_em": n.updated_at,
            "acoes": len(acoes),
            "acoes_concluidas": sum(1 for a in acoes if a.status == "concluida"),
        })
    return resultado


def _alertas_investigacao(db, usuario, perms) -> list[dict]:
    if "investigacao.aprovar" not in perms:
        return []
    from app.modules.investigacao.models import (STATUS_PENDENTE,
                                                 AnaliseOcorrencia)

    n = db.scalar(select(func.count(func.distinct(AnaliseOcorrencia.ocorrencia)))
                  .where(AnaliseOcorrencia.empresa_id == usuario.empresa_id,
                         AnaliseOcorrencia.deleted_at.is_(None),
                         AnaliseOcorrencia.status == STATUS_PENDENTE)) or 0
    if not n:
        return []
    return [_alerta("info", "fa-file-shield",
                    f"{n} relatório(s) RAC aguardando aprovação",
                    "Investigações de eventos com relatório gerado e ainda não aprovado.",
                    "/investigacao/relatorios?status=pendente", n, "qualidade")]


def _alertas_vsky(db, usuario, perms) -> list[dict]:
    if "download_vsky.listar" not in perms:
        return []
    from app.core.config_service import get_config
    from app.modules.download_vsky.constants import (CONFIG_AUTO_ATIVO,
                                                     CONFIG_AUTO_STATUS,
                                                     STATUS_CONCLUIDO)
    from app.modules.download_vsky.models import (VskyImportacao,
                                                  VskyRegistroAnalitico)

    lista = []
    emp = usuario.empresa_id
    ultimo = db.scalar(select(func.max(VskyRegistroAnalitico.data_ocorrencia_dt))
                       .where(VskyRegistroAnalitico.empresa_id == emp,
                              VskyRegistroAnalitico.deleted_at.is_(None)))
    if ultimo is None:
        lista.append(_alerta("warning", "fa-cloud-arrow-down",
                             "Nenhum dado do vSky importado",
                             "Os indicadores dependem da importação do vSky.",
                             "/download_vsky/", grupo="dados"))
    else:
        atraso = (date.today() - ultimo.date()).days
        if atraso >= 2:
            lista.append(_alerta(
                "warning", "fa-clock",
                f"Dados do vSky desatualizados há {atraso} dias",
                f"Última ocorrência importada: {ultimo.strftime('%d/%m/%Y %H:%M')}.",
                "/download_vsky/", grupo="dados"))
    if get_config(db, CONFIG_AUTO_ATIVO, empresa_id=emp) == "1":
        status = get_config(db, CONFIG_AUTO_STATUS, empresa_id=emp) or ""
        if status.startswith("erro"):
            lista.append(_alerta("danger", "fa-triangle-exclamation",
                                 "Falha no download automático do vSky",
                                 status[:200], "/download_vsky/", grupo="dados"))
    erro = db.scalar(select(VskyImportacao).where(
        VskyImportacao.empresa_id == emp, VskyImportacao.deleted_at.is_(None))
        .order_by(VskyImportacao.id.desc()).limit(1))
    if erro is not None and erro.status != STATUS_CONCLUIDO and erro.erro:
        lista.append(_alerta("danger", "fa-file-circle-xmark",
                             "A última importação do vSky falhou",
                             f"{erro.data_inicial} a {erro.data_final}: {erro.erro[:160]}",
                             "/download_vsky/", grupo="dados"))
    return lista


def _alertas_notificacoes(db, usuario, perms) -> list[dict]:
    from app.models import Notificacao

    n = db.scalar(select(func.count()).select_from(Notificacao).where(
        Notificacao.usuario_id == usuario.id, Notificacao.lida.is_(False),
        Notificacao.deleted_at.is_(None))) or 0
    if not n:
        return []
    return [_alerta("info", "fa-bell", f"{n} notificação(ões) não lida(s)",
                    "", "/notificacoes/", n, "geral")]


def _alertas_conta(db, usuario, perms) -> list[dict]:
    lista = []
    if not usuario.mfa_habilitado:
        lista.append(_alerta(
            "info", "fa-shield-halved", "Ative a autenticação em duas etapas",
            "Protege sua conta mesmo que a senha vaze.", "/mfa",
            grupo="conta"))
    return lista


def notificacoes_recentes(db: Session, usuario, limite: int = 5) -> list:
    from app.models import Notificacao

    return list(db.scalars(select(Notificacao).where(
        Notificacao.usuario_id == usuario.id, Notificacao.deleted_at.is_(None))
        .order_by(Notificacao.id.desc()).limit(limite)))


# ------------------------------------------------------------------ gestão

_cache_gestao: dict = {}


def gestao(empresa_id: int) -> dict:
    """Última semana operacional completa × a anterior, para a página inicial."""
    from app.modules.indicadores import desperdicio, nucleo
    from app.modules.indicadores.constants import ADEQUACAO, CAP_TEMPO, SLA_P1

    chave = (empresa_id, nucleo.marca_cache(empresa_id))
    if chave in _cache_gestao:
        return _cache_gestao[chave]

    df = nucleo.carregar(empresa_id)
    semanas = nucleo.semanas_completas(df) if not df.empty else []
    if not semanas:
        return {"semana": None, "kpis": []}
    atual = semanas[-1]
    anterior = semanas[-2] if len(semanas) > 1 else None

    def medir(sem):
        if sem is None:
            return None
        d = df[df["semana_iso"] == sem]
        tr = d["tempo_resposta"]
        tr = tr[(tr > 0) & (tr < CAP_TEMPO["tempo_resposta"])]
        p1 = d["t_p1"]
        p1 = p1[(p1 > 0) & (p1 < CAP_TEMPO["t_p1"])]
        aph = d[(d["transporte"] == "Pré-hospitalar")
                & d["codigo_cor"].isin(ADEQUACAO) & d["risco_cor"].notna()]
        ok = sum(((aph["codigo_cor"] == cor) & aph["risco_cor"].isin(r)).sum()
                 for cor, r in ADEQUACAO.items())
        universo = desperdicio.universo(d)
        real, _ = desperdicio.mascaras(universo)
        return {
            "saidas": int(d["dt_inicio_deslocamento"].notna().sum()),
            "tr_media": float(tr.mean()) if len(tr) else None,
            "tr_10": float((tr <= 600).mean() * 100) if len(tr) else None,
            "sla_p1": float((p1 <= SLA_P1).mean() * 100) if len(p1) else None,
            "assertividade": float(ok / len(aph) * 100) if len(aph) else None,
            "desperdicio": float(real.sum() / len(universo) * 100)
            if len(universo) else None,
        }

    a, b = medir(atual), medir(anterior)

    def mmss(s):
        return "--:--" if s is None else f"{int(s // 60):02d}:{int(s % 60):02d}"

    def pct(v):
        return "—" if v is None else f"{v:.1f}%".replace(".", ",")

    # (chave, rótulo, formatador, maior_e_melhor, link)
    specs = [
        ("saidas", "Saídas de viatura", lambda v: f"{v:,}".replace(",", "."),
         None, "/indicadores/saidas-ambulancia"),
        ("tr_media", "Tempo de resposta (média)", mmss, False,
         "/indicadores/tempo-resposta"),
        ("tr_10", "Resposta em até 10 min", pct, True,
         "/indicadores/tempo-resposta"),
        ("sla_p1", "SLA P1 (≤ 1,5 min)", pct, True, "/indicadores/processos"),
        ("assertividade", "Assertividade", pct, True,
         "/indicadores/assertividade"),
        ("desperdicio", "Desperdício real", pct, False,
         "/indicadores/desperdicio"),
    ]
    kpis = []
    for chave_k, rotulo, fmt, maior_melhor, link in specs:
        va = a[chave_k]
        vb = b[chave_k] if b else None
        tendencia = None
        if va is not None and vb is not None and vb != 0:
            melhorou = None if maior_melhor is None else (
                (va > vb) == maior_melhor if va != vb else None)
            if fmt is pct:   # taxa: diferença em pontos percentuais
                variacao = f"{va - vb:+.1f} p.p."
            else:
                variacao = f"{(va - vb) / abs(vb) * 100:+.1f}%"
            tendencia = {"variacao": variacao.replace(".", ",", 1),
                         "subiu": va > vb, "melhorou": melhorou}
        kpis.append({"rotulo": rotulo, "valor": fmt(va) if va is not None else "—",
                     "anterior": fmt(vb) if vb is not None else None,
                     "tendencia": tendencia, "link": link})

    ano, num = atual.split("-S")
    inicio = date.fromisocalendar(int(ano), int(num), 1) - timedelta(days=1)
    resultado = {"semana": f"{inicio.strftime('%d/%m')} a "
                           f"{(inicio + timedelta(days=6)).strftime('%d/%m/%Y')}",
                 "kpis": kpis}
    if len(_cache_gestao) > 8:
        _cache_gestao.clear()
    _cache_gestao[chave] = resultado
    return resultado
