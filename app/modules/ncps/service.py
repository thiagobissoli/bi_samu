"""Regras de negócio do módulo NCPS.

Separadas das rotas de propósito: recebem dados simples (dict/FormData,
usuário) e devolvem objetos ou dicts, sem nada de HTTP. Rotas e testes
usam as mesmas funções.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections import Counter
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.modules.ncps import constants as cat
from app.modules.ncps.models import (Ncps, NcpsAcao, NcpsAnalise, NcpsCausa,
                                     NcpsGestor, NcpsGhe, NcpsLocal,
                                     NcpsOcupacional, NcpsPerigo, NcpsRisco)
from app.modules.ncps.permissions import (filtrar_visiveis, pode_tratar,
                                          pode_triar)


class NcpsErro(ValueError):
    """Dado inválido enviado pelo formulário (mensagem para o usuário)."""


class NcpsProibido(PermissionError):
    """O usuário não pode alterar esta seção da notificação."""


# ------------------------------------------------------------------ utilidades

def fuso(db: Session, empresa_id: int) -> ZoneInfo:
    from app.core.config import settings
    from app.core.config_service import get_config

    nome = get_config(db, "timezone", settings.timezone, empresa_id) or "UTC"
    try:
        return ZoneInfo(nome)
    except Exception:  # noqa: BLE001 — fuso inválido não pode quebrar a tela
        return ZoneInfo("UTC")


def _texto(form, nome: str, limite: int | None = None) -> str | None:
    valor = (form.get(nome) or "").strip()
    if limite:
        valor = valor[:limite]
    return valor or None


def _escolha(form, nome: str, opcoes) -> str | None:
    valor = form.get(nome) or ""
    return valor if valor in opcoes else None


def _inteiro(form, nome: str) -> int | None:
    try:
        return int(form.get(nome))
    except (TypeError, ValueError):
        return None


def _data(form, nome: str) -> date | None:
    try:
        return date.fromisoformat(form.get(nome) or "")
    except ValueError:
        return None


def _data_hora(form, nome: str) -> datetime | None:
    valor = (form.get(nome) or "").strip()
    for formato in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor, formato)
        except ValueError:
            pass
    return None


def _sim_nao(form, nome: str) -> bool | None:
    return {"sim": True, "nao": False}.get(form.get(nome))


def hash_codigo(codigo: str) -> str:
    return hashlib.sha256(codigo.encode()).hexdigest()


def normalizar_codigo(codigo: str | None) -> str:
    """Aceita o código digitado com espaços, hífens ou minúsculas."""
    return "".join(ch for ch in (codigo or "").upper() if ch.isalnum())


def gerar_codigo() -> str:
    return "".join(secrets.choice(cat.ALFABETO_CODIGO)
                   for _ in range(cat.TAMANHO_CODIGO))


# ------------------------------------------------------------------ catálogos

def garantir_catalogo_pgr(db: Session, empresa_id: int) -> None:
    """Carga inicial de GHE e perigos do PGR, na primeira vez que se precisa."""
    tem_ghe = db.scalar(select(func.count()).select_from(NcpsGhe).where(
        NcpsGhe.empresa_id == empresa_id))
    if not tem_ghe:
        for codigo, nome, cargos in cat.GHE_PGR:
            db.add(NcpsGhe(empresa_id=empresa_id, codigo=codigo, nome=nome,
                           cargos=cargos))
    tem_perigo = db.scalar(select(func.count()).select_from(NcpsPerigo).where(
        NcpsPerigo.empresa_id == empresa_id))
    if not tem_perigo:
        for grupo, nome, fonte, dano in cat.PERIGOS_PGR:
            db.add(NcpsPerigo(empresa_id=empresa_id, grupo=grupo, nome=nome,
                              fonte=fonte, dano=dano))
    if not (tem_ghe and tem_perigo):
        db.commit()


def ghes(db: Session, empresa_id: int, incluir_id: int | None = None):
    """GHE ativos + o já selecionado (mesmo desativado, para não perdê-lo)."""
    garantir_catalogo_pgr(db, empresa_id)
    return list(db.scalars(select(NcpsGhe).where(
        NcpsGhe.empresa_id == empresa_id, NcpsGhe.deleted_at.is_(None),
        or_(NcpsGhe.ativo.is_(True), NcpsGhe.id == incluir_id),
    ).order_by(NcpsGhe.codigo)))


def perigos(db: Session, empresa_id: int, incluir_id: int | None = None):
    garantir_catalogo_pgr(db, empresa_id)
    return list(db.scalars(select(NcpsPerigo).where(
        NcpsPerigo.empresa_id == empresa_id, NcpsPerigo.deleted_at.is_(None),
        or_(NcpsPerigo.ativo.is_(True), NcpsPerigo.id == incluir_id),
    ).order_by(NcpsPerigo.grupo, NcpsPerigo.nome)))


def cadastro(db: Session, modelo, empresa_id: int, incluir_id=None,
             so_ativos=True):
    """Gestores ou locais, em ordem alfabética."""
    consulta = select(modelo).where(modelo.empresa_id == empresa_id,
                                    modelo.deleted_at.is_(None))
    if so_ativos:
        consulta = consulta.where(or_(modelo.ativo.is_(True),
                                      modelo.id == incluir_id))
    return list(db.scalars(consulta.order_by(modelo.nome)))


def coordenadores(db: Session, empresa_id: int):
    """Usuários que podem ser atribuídos como coordenador responsável."""
    from app.models import Perfil, Permissao, Usuario
    from app.models.entities import perfis_permissoes, usuarios_perfis

    return list(db.scalars(
        select(Usuario).join(usuarios_perfis).join(
            Perfil, Perfil.id == usuarios_perfis.c.perfil_id).join(
            perfis_permissoes, perfis_permissoes.c.perfil_id == Perfil.id).join(
            Permissao, Permissao.id == perfis_permissoes.c.permissao_id).where(
            Permissao.codigo == "ncps.coordenar", Perfil.ativo.is_(True),
            Perfil.deleted_at.is_(None), Usuario.ativo.is_(True),
            Usuario.deleted_at.is_(None), Usuario.empresa_id == empresa_id,
        ).distinct().order_by(Usuario.nome)))


# ------------------------------------------------------------------ registro

def validar_notificacao(form) -> dict[str, str]:
    """Erros por campo; vazio se o formulário está válido."""
    erros = {}
    natureza = form.get("natureza")
    if natureza not in cat.NATUREZA:
        erros["natureza"] = ("Escolha se a notificação é sobre o paciente ou "
                             "o trabalhador.")
    if not (form.get("descricao") or "").strip():
        erros["descricao"] = "Descreva o que aconteceu."
    if natureza == "trabalhador" and (
            form.get("tipo_evento_trab") not in cat.TIPO_EVENTO_TRABALHADOR):
        erros["tipo_evento_trab"] = "Informe o tipo de evento com o trabalhador."
    if (form.get("data_hora_ocorrencia") or "").strip() and not _data_hora(
            form, "data_hora_ocorrencia"):
        erros["data_hora_ocorrencia"] = "Data e hora inválidas."
    return erros


def registrar(db: Session, empresa_id: int, form, usuario=None) -> tuple[Ncps, str]:
    """Grava a notificação e devolve (ncps, código de acompanhamento).

    `usuario` None = formulário público: sempre anônimo. O código só é
    devolvido aqui; no banco fica apenas o hash.
    """
    erros = validar_notificacao(form)
    if erros:
        raise NcpsErro(next(iter(erros.values())))

    trabalhador = form.get("natureza") == "trabalhador"
    tipo = form.get("tipo_evento_trab") if trabalhador else None
    confidencial = tipo == cat.EVENTO_CONFIDENCIAL
    anonima = usuario is None or (confidencial and bool(form.get("anonima")))
    ghe_id = _inteiro(form, "ghe_id") if trabalhador else None
    if ghe_id and not db.scalar(select(NcpsGhe.id).where(
            NcpsGhe.id == ghe_id, NcpsGhe.empresa_id == empresa_id)):
        ghe_id = None

    codigo = gerar_codigo()
    n = Ncps(
        empresa_id=empresa_id,
        natureza=form.get("natureza"),
        descricao=_texto(form, "descricao", 20_000),
        local=_texto(form, "local", 100),
        id_ocorrencia=_texto(form, "id_ocorrencia", 100),
        data_hora_ocorrencia=_data_hora(form, "data_hora_ocorrencia"),
        sugestao=_texto(form, "sugestao", 20_000),
        registrado_em=utcnow(),
        tipo_evento_trab=tipo,
        ghe_id=ghe_id,
        houve_lesao=_sim_nao(form, "houve_lesao") if trabalhador else None,
        confidencial=confidencial,
        anonima=anonima,
        notificante_id=None if anonima else usuario.id,
        codigo_hash=hash_codigo(codigo),
        created_by=None if anonima else usuario.id,
    )
    if trabalhador:
        n.ocupacional = NcpsOcupacional(
            empresa_id=empresa_id,
            revisar_pgr=tipo in cat.EVENTOS_ACIDENTE)
    db.add(n)
    db.commit()
    return n, codigo


def buscar_acompanhamento(db: Session, empresa_id: int, protocolo,
                          codigo: str | None) -> Ncps | None:
    """Consulta de quem notificou, pelo protocolo e código.

    Notificações registradas aqui sempre têm código, e ele é exigido.
    As importadas do sistema anterior sem código (só as não sigilosas
    não tinham) continuam consultáveis só pelo protocolo, como lá.
    """
    try:
        protocolo = int(protocolo)
    except (TypeError, ValueError):
        return None
    n = db.scalar(select(Ncps).where(
        Ncps.id == protocolo, Ncps.empresa_id == empresa_id,
        Ncps.deleted_at.is_(None)))
    if n is None:
        return None
    if n.codigo_hash:
        informado = hash_codigo(normalizar_codigo(codigo))
        return n if hmac.compare_digest(informado, n.codigo_hash) else None
    return None if n.confidencial else n


# ------------------------------------------------------------------ consulta

def filtros_da_requisicao(params) -> dict:
    """Filtros da lista/painel a partir da query string."""
    return {
        "natureza": params.get("natureza") if params.get("natureza") in cat.NATUREZA else "",
        "status": params.get("status") if params.get("status") in cat.STATUS else "",
        "gestor_id": params.get("gestor_id", ""),
        "local_id": params.get("local_id", ""),
        "inicio": params.get("inicio", ""),
        "fim": params.get("fim", ""),
        "q": (params.get("q") or "").strip()[:100],
        "atribuidas": params.get("atribuidas") == "1",
        "sigilosas": params.get("sigilosas") == "1",
    }


def consulta(db: Session, usuario, filtros: dict):
    """select(Ncps) com visibilidade do usuário e os filtros aplicados."""
    q = select(Ncps).where(Ncps.empresa_id == usuario.empresa_id,
                           Ncps.deleted_at.is_(None))
    q = filtrar_visiveis(q, usuario)

    if filtros.get("natureza"):
        q = q.where(Ncps.natureza == filtros["natureza"])
    if filtros.get("status"):
        q = q.where(Ncps.status == filtros["status"])
    for campo in ("gestor_id", "local_id"):
        try:
            valor = int(filtros.get(campo) or 0)
        except ValueError:
            valor = 0
        if valor:
            q = q.where(getattr(Ncps, campo) == valor)
    if filtros.get("atribuidas"):
        q = q.where(Ncps.coordenador_id == usuario.id)
    if filtros.get("sigilosas"):
        q = q.where(Ncps.confidencial.is_(True))

    zona = fuso(db, usuario.empresa_id)
    for chave, limite in (("inicio", time.min), ("fim", time.max)):
        try:
            dia = date.fromisoformat(filtros.get(chave) or "")
        except ValueError:
            continue
        instante = datetime.combine(dia, limite, zona).astimezone(timezone.utc)
        q = q.where(Ncps.registrado_em >= instante if chave == "inicio"
                    else Ncps.registrado_em <= instante)

    texto = filtros.get("q")
    if texto:
        condicoes = [Ncps.descricao.ilike(f"%{texto}%"),
                     Ncps.id_ocorrencia.ilike(f"%{texto}%"),
                     Ncps.local.ilike(f"%{texto}%")]
        if texto.isdigit():
            condicoes.append(Ncps.id == int(texto))
        q = q.where(or_(*condicoes))
    return q.order_by(Ncps.registrado_em.desc(), Ncps.id.desc())


def obter(db: Session, empresa_id: int, ncps_id: int) -> Ncps | None:
    return db.scalar(select(Ncps).where(
        Ncps.id == ncps_id, Ncps.empresa_id == empresa_id,
        Ncps.deleted_at.is_(None)))


def acoes_atrasadas(n: Ncps, hoje: date | None = None) -> list[NcpsAcao]:
    hoje = hoje or date.today()
    return [a for a in n.acoes
            if a.prazo and a.prazo < hoje and a.status in cat.STATUS_ACAO_ABERTOS]


# ------------------------------------------------------------------ tratativa

def salvar_secao(db: Session, n: Ncps, secao: str, form, usuario) -> str:
    """Aplica a seção enviada pela tela de análise; devolve a aba de retorno.

    Levanta NcpsProibido se o usuário não pode alterar a seção e NcpsErro
    para dados inválidos.
    """
    triagem = secao == "triagem"
    if (triagem and not pode_triar(n, usuario)) or (
            not triagem and not pode_tratar(n, usuario)):
        raise NcpsProibido("Você não pode alterar esta etapa da notificação.")

    if triagem:
        _salvar_triagem(db, n, form, usuario)
        aba = "triagem"
    elif secao == "classificacao":
        _salvar_classificacao(db, n, form)
        aba = "classificacao"
    elif secao == "risco":
        _salvar_risco(db, n, form)
        aba = "risco"
    elif secao == "analise":
        a = n.analise or NcpsAnalise(empresa_id=n.empresa_id)
        for campo in ("cronologia", "problemas", "fontes", "barreiras",
                      "recomendacoes"):
            setattr(a, campo, _texto(form, campo, 50_000))
        n.analise = a
        aba = "analise"
    elif secao in ("causa_add", "causa_del", "causa_raiz"):
        aba = _salvar_causa(db, n, secao, form)
    elif secao in ("acao_add", "acao_update", "acao_del"):
        _salvar_acao(db, n, secao, form)
        aba = "acoes"
    else:
        raise NcpsErro("Seção desconhecida.")

    n.updated_by = usuario.id
    db.commit()
    return aba


def _salvar_triagem(db: Session, n: Ncps, form, usuario) -> None:
    natureza = _escolha(form, "natureza", cat.NATUREZA)
    if natureza and natureza != n.natureza and not n.confidencial:
        n.natureza = natureza
        if natureza == "trabalhador" and not n.ocupacional:
            n.ocupacional = NcpsOcupacional(empresa_id=n.empresa_id)
    n.procedente = _escolha(form, "procedente", cat.PROCEDENTE) or n.procedente
    status_anterior = n.status
    n.status = _escolha(form, "status", cat.STATUS) or n.status
    if n.status != status_anterior and n.notificante_id and not n.anonima:
        _avisar_notificante(db, n)

    local_id, gestor_id = _inteiro(form, "local_id"), _inteiro(form, "gestor_id")
    n.local_id = local_id if local_id and db.scalar(select(NcpsLocal.id).where(
        NcpsLocal.id == local_id, NcpsLocal.empresa_id == n.empresa_id)) else None
    n.gestor_id = gestor_id if gestor_id and db.scalar(select(NcpsGestor.id).where(
        NcpsGestor.id == gestor_id, NcpsGestor.empresa_id == n.empresa_id)) else None

    coord_id = _inteiro(form, "coordenador_id")
    validos = {u.id for u in coordenadores(db, n.empresa_id)}
    novo = coord_id if coord_id in validos else None
    if n.confidencial:
        novo = None           # sigilosa é tratada pela Comissão, não por coordenador
    if novo and novo != n.coordenador_id:
        from app.core.notifications import notify

        db.flush()
        notify(db, novo, f"NCPS #{n.id} atribuída a você",
               "Você é o coordenador responsável pela tratativa desta "
               "notificação. Acesse NCPS para registrar a análise.",
               tipo="warning", empresa_id=n.empresa_id)
    n.coordenador_id = novo


def _avisar_notificante(db: Session, n: Ncps) -> None:
    """Retorno a quem notificou de forma identificada: a situação mudou."""
    from app.core.notifications import notify

    rotulo, texto, _etapa = cat.SITUACAO_ACOMPANHAMENTO.get(
        n.status, ("Em análise", "", 2))
    db.flush()
    notify(db, n.notificante_id, f"Sua NCPS #{n.id}: {rotulo}", texto,
           tipo="success" if n.status in ("2", "3", "4") else "info",
           empresa_id=n.empresa_id)


def _salvar_classificacao(db: Session, n: Ncps, form) -> None:
    if n.natureza == "paciente":
        for campo, (_rotulo, opcoes) in cat.CLASSIFICACAO_PACIENTE.items():
            valor = _escolha(form, campo, opcoes)
            if valor is not None:
                setattr(n, campo, valor)
        return

    tipo = _escolha(form, "tipo_evento_trab", cat.TIPO_EVENTO_TRABALHADOR)
    # mudar para/de assédio muda quem pode ver: exige nova notificação
    if tipo and not n.confidencial and tipo != cat.EVENTO_CONFIDENCIAL:
        n.tipo_evento_trab = tipo
    ghe_id = _inteiro(form, "ghe_id")
    n.ghe_id = ghe_id if ghe_id and db.scalar(select(NcpsGhe.id).where(
        NcpsGhe.id == ghe_id, NcpsGhe.empresa_id == n.empresa_id)) else None
    n.houve_lesao = _sim_nao(form, "houve_lesao")

    o = n.ocupacional or NcpsOcupacional(empresa_id=n.empresa_id)
    o.grupo_risco = _escolha(form, "grupo_risco", cat.GRUPO_RISCO)
    perigo_id = _inteiro(form, "perigo_id")
    perigo = db.scalar(select(NcpsPerigo).where(
        NcpsPerigo.id == perigo_id,
        NcpsPerigo.empresa_id == n.empresa_id)) if perigo_id else None
    o.perigo_id = perigo.id if perigo else None
    if perigo and not o.grupo_risco:
        o.grupo_risco = perigo.grupo
    o.natureza_lesao = _texto(form, "natureza_lesao", 150)
    o.parte_corpo = _escolha(form, "parte_corpo", cat.PARTE_CORPO)
    o.afastamento = _sim_nao(form, "afastamento")
    dias = _inteiro(form, "dias_afastamento")
    o.dias_afastamento = dias if o.afastamento and dias and dias > 0 else None
    o.cat_emitida = _sim_nao(form, "cat_emitida")
    o.cat_numero = _texto(form, "cat_numero", 40) if o.cat_emitida else None
    o.cat_data = _data(form, "cat_data") if o.cat_emitida else None
    # NR-1 1.5.4.4.6 "d": acidente ou doença exige revisão do inventário do PGR
    o.revisar_pgr = bool(form.get("revisar_pgr")) or (
        n.tipo_evento_trab in cat.EVENTOS_ACIDENTE)
    o.pgr_revisado_em = _data(form, "pgr_revisado_em")
    n.ocupacional = o


def _salvar_risco(db: Session, n: Ncps, form) -> None:
    for momento in cat.MOMENTO_RISCO:
        try:          # célula da matriz no formato "P-S"
            p, s = (int(x) for x in (form.get(f"{momento}_ps") or "").split("-"))
        except ValueError:
            p = s = None
        atual = n.risco(momento)
        if form.get(f"{momento}_limpar") and atual:
            n.riscos.remove(atual)
        elif p in cat.PROBABILIDADE and s in cat.SEVERIDADE:
            r = atual or NcpsRisco(empresa_id=n.empresa_id, momento=momento)
            r.probabilidade, r.severidade = p, s
            r.justificativa = _texto(form, f"{momento}_justificativa", 5_000)
            if atual is None:
                n.riscos.append(r)


def _salvar_causa(db: Session, n: Ncps, secao: str, form) -> str:
    if secao == "causa_add":
        metodo = _escolha(form, "metodo", cat.METODOS_CAUSA)
        categoria = _escolha(form, "categoria",
                             cat.METODOS_CAUSA.get(metodo, {}))
        descricao = _texto(form, "descricao", 2_000)
        if not (metodo and categoria and descricao):
            raise NcpsErro("Informe a categoria e a descrição da causa.")
        n.causas.append(NcpsCausa(
            empresa_id=n.empresa_id, metodo=metodo, categoria=categoria,
            descricao=descricao, causa_raiz=bool(form.get("causa_raiz"))))
    else:
        causa_id = _inteiro(form, "causa_id")
        c = next((c for c in n.causas if c.id == causa_id), None)
        if c is None:
            raise NcpsErro("Causa não encontrada.")
        metodo = c.metodo
        if secao == "causa_del":
            n.causas.remove(c)
        else:
            c.causa_raiz = not c.causa_raiz
    return "analise" if metodo == "londres" else "ishikawa"


def _salvar_acao(db: Session, n: Ncps, secao: str, form) -> None:
    if secao == "acao_add":
        descricao = _texto(form, "descricao", 2_000)
        if not descricao:
            raise NcpsErro("Descreva a ação.")
        n.acoes.append(NcpsAcao(
            empresa_id=n.empresa_id, descricao=descricao,
            tipo=_escolha(form, "tipo", cat.TIPO_ACAO),
            responsavel=_texto(form, "responsavel", 120),
            prazo=_data(form, "prazo")))
        return
    acao_id = _inteiro(form, "acao_id")
    a = next((a for a in n.acoes if a.id == acao_id), None)
    if a is None:
        raise NcpsErro("Ação não encontrada.")
    if secao == "acao_del":
        n.acoes.remove(a)
        return
    a.status = _escolha(form, "status", cat.STATUS_ACAO) or a.status
    a.eficacia = _escolha(form, "eficacia", cat.EFICACIA_ACAO) or a.eficacia
    a.observacao = _texto(form, "observacao", 2_000)
    if a.status == "concluida" and not a.concluida_em:
        a.concluida_em = date.today()
    elif a.status != "concluida":
        a.concluida_em = None


def excluir(db: Session, n: Ncps, usuario) -> None:
    """Exclusão lógica — só quem faz a triagem da notificação."""
    if not pode_triar(n, usuario):
        raise NcpsProibido("Somente quem faz a triagem desta notificação "
                           "pode excluí-la.")
    n.deleted_at = utcnow()
    n.deleted_by = usuario.id
    db.commit()


# ------------------------------------------------------------------ indicadores

def _contagem(valores, rotulos: dict, ignorar=("0",)) -> list[dict]:
    """[{'rotulo', 'total'}] em ordem decrescente, sem os códigos ignorados."""
    c = Counter(v for v in valores if v is not None and v not in ignorar)
    return [{"codigo": k, "rotulo": rotulos.get(k, k), "total": t}
            for k, t in c.most_common()]


def indicadores(db: Session, usuario, filtros: dict) -> dict:
    """Números do painel sobre as notificações visíveis ao usuário."""
    lista = list(db.scalars(consulta(db, usuario, filtros)))
    zona = fuso(db, usuario.empresa_id)
    hoje = date.today()

    def mes(n):
        instante = n.registrado_em
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.astimezone(zona).strftime("%Y-%m")

    pacientes = [n for n in lista if n.natureza == "paciente"]
    trabalhadores = [n for n in lista if n.natureza == "trabalhador"]
    acoes = [a for n in lista for a in n.acoes]
    atrasadas = [a for a in acoes
                 if a.prazo and a.prazo < hoje and a.status in cat.STATUS_ACAO_ABERTOS]

    # Os 12 meses corridos até o último com registro — mês sem notificação
    # aparece zerado, senão o eixo pula meses e a série engana
    meses = []
    if lista:
        ano, m = map(int, max(mes(n) for n in lista).split("-"))
        for _ in range(12):
            meses.insert(0, f"{ano:04d}-{m:02d}")
            ano, m = (ano, m - 1) if m > 1 else (ano - 1, 12)
    por_mes = {m: {"paciente": 0, "trabalhador": 0} for m in meses}
    for n in lista:
        m = mes(n)
        if m in por_mes:
            por_mes[m][n.natureza] = por_mes[m].get(n.natureza, 0) + 1

    def idade_dias(n):
        instante = n.registrado_em
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return (utcnow() - instante).days

    abertas = [n for n in lista if n.status in cat.STATUS_ABERTOS]
    ocup = [n.ocupacional for n in trabalhadores if n.ocupacional]
    riscos = [n.risco("inicial").nivel["rotulo"] for n in lista
              if n.risco("inicial")]

    return {
        "total": len(lista),
        "paciente": len(pacientes),
        "trabalhador": len(trabalhadores),
        "sigilosas": sum(1 for n in lista if n.confidencial),
        "abertas": len(abertas),
        "abertas_30d": sum(1 for n in abertas if idade_dias(n) > 30),
        "aguardando_triagem": sum(1 for n in lista if n.status == "0"),
        "sem_coordenador": sum(1 for n in abertas
                               if not n.coordenador_id and not n.confidencial),
        "eventos_adversos": sum(1 for n in pacientes
                                if n.classificacao_incidente == "4"),
        "danos_graves": sum(1 for n in pacientes if n.dano in ("4", "5")),
        "sentinelas": sum(1 for n in pacientes
                          if n.sentinela not in ("0", "99", None)),
        "acoes": {
            "total": len(acoes),
            "abertas": sum(1 for a in acoes if a.status in cat.STATUS_ACAO_ABERTOS),
            "atrasadas": len(atrasadas),
            "concluidas": sum(1 for a in acoes if a.status == "concluida"),
            "eficacia": _contagem([a.eficacia for a in acoes
                                   if a.status == "concluida"],
                                  cat.EFICACIA_ACAO, ignorar=()),
        },
        "ocupacional": {
            "afastamentos": sum(1 for o in ocup if o.afastamento),
            "dias_afastamento": sum(o.dias_afastamento or 0 for o in ocup),
            "cats": sum(1 for o in ocup if o.cat_emitida),
            "pgr_pendente": sum(1 for o in ocup
                                if o.revisar_pgr and not o.pgr_revisado_em),
        },
        "por_mes": [{"mes": m, **v} for m, v in por_mes.items()],
        "por_status": _contagem([n.status for n in lista], cat.STATUS,
                                ignorar=()),
        "por_classificacao": _contagem(
            [n.classificacao_incidente for n in pacientes],
            cat.CLASSIFICACAO_INCIDENTE),
        "por_dano": _contagem([n.dano for n in pacientes], cat.DANO),
        "por_macroprocesso": _contagem([n.macroprocesso for n in pacientes],
                                       cat.MACROPROCESSO, ignorar=("0", "99")),
        "por_meta": _contagem([n.seguranca for n in pacientes],
                              cat.META_SEGURANCA, ignorar=("0", "99")),
        "por_sentinela": _contagem([n.sentinela for n in pacientes],
                                   cat.EVENTO_SENTINELA, ignorar=("0", "99")),
        "por_tipo_trabalhador": _contagem(
            [n.tipo_evento_trab for n in trabalhadores],
            cat.TIPO_EVENTO_TRABALHADOR, ignorar=()),
        "por_risco": _contagem(riscos, {}, ignorar=()),
        "por_local": _contagem(
            [n.local_padronizado.nome if n.local_padronizado else None
             for n in lista], {}, ignorar=())[:10],
        "por_gestor": _contagem(
            [n.gestor.nome if n.gestor else None for n in lista], {},
            ignorar=())[:10],
    }


# ------------------------------------------------------------------ exportação

def linha_exportacao(n: Ncps, zona: ZoneInfo) -> dict:
    """Uma linha da planilha — mesmas colunas do relatório antigo + NR-1."""
    registrado = n.registrado_em
    if registrado and registrado.tzinfo is None:
        registrado = registrado.replace(tzinfo=timezone.utc)
    ri, rr = n.risco("inicial"), n.risco("residual")
    o = n.ocupacional
    acoes = n.acoes
    causa_raiz = "; ".join(c.descricao for c in n.causas if c.causa_raiz)
    return {
        "Protocolo": n.id,
        "Registrada em": registrado.astimezone(zona).replace(tzinfo=None)
        if registrado else None,
        "Natureza": cat.NATUREZA.get(n.natureza, n.natureza),
        "Sigilosa": "Sim" if n.confidencial else "Não",
        "Status": cat.STATUS.get(n.status, n.status),
        "Procedente": cat.PROCEDENTE.get(n.procedente, n.procedente),
        "Descrição": n.descricao,
        "Local informado": n.local,
        "Local padronizado": n.local_padronizado.nome if n.local_padronizado else None,
        "Ocorrência (vSky)": n.id_ocorrencia,
        "Data/hora do evento": n.data_hora_ocorrencia,
        "Ação realizada / sugestão": n.sugestao,
        "Gestor": n.gestor.nome if n.gestor else None,
        "Coordenador": n.coordenador.nome if n.coordenador else None,
        **{rotulo: opcoes.get(getattr(n, campo), getattr(n, campo))
           for campo, (rotulo, opcoes) in cat.CLASSIFICACAO_PACIENTE.items()},
        "Tipo de evento (trabalhador)": cat.TIPO_EVENTO_TRABALHADOR.get(
            n.tipo_evento_trab or "", None),
        "GHE": n.ghe.rotulo if n.ghe else None,
        "Perigo": o.perigo.nome if o and o.perigo else None,
        "Afastamento (dias)": o.dias_afastamento if o and o.afastamento else None,
        "CAT": o.cat_numero if o and o.cat_emitida else None,
        "Risco inicial": f"{ri.nivel['rotulo']} ({ri.nivel['classe']})" if ri else None,
        "Risco residual": f"{rr.nivel['rotulo']} ({rr.nivel['classe']})" if rr else None,
        "Causa raiz": causa_raiz or None,
        "Ações (total)": len(acoes),
        "Ações em aberto": sum(1 for a in acoes
                               if a.status in cat.STATUS_ACAO_ABERTOS),
        "Ações atrasadas": len(acoes_atrasadas(n)),
    }


def gerar_planilha(db: Session, usuario, filtros: dict) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Font

    zona = fuso(db, usuario.empresa_id)
    linhas = [linha_exportacao(n, zona)
              for n in db.scalars(consulta(db, usuario, filtros))]
    wb = Workbook()
    aba = wb.active
    aba.title = "NCPS"
    colunas = list(linhas[0].keys()) if linhas else list(
        linha_exportacao(Ncps(id=0, natureza="paciente", status="0",
                              procedente="0", descricao=""), zona).keys())
    aba.append(colunas)
    for celula in aba[1]:
        celula.font = Font(bold=True)
    for linha in linhas:
        aba.append([linha[c] for c in colunas])
    aba.freeze_panes = "A2"
    saida = BytesIO()
    wb.save(saida)
    return saida.getvalue()


def dados_legados(n: Ncps) -> dict:
    """Campos do formulário antigo sem equivalente (impacto, plano…)."""
    try:
        return json.loads(n.legado) if n.legado else {}
    except ValueError:
        return {}

