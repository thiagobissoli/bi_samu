"""Importa as NCPS do sistema Flask anterior (MySQL) para este banco.

Uso (na raiz do projeto, com o venv ativo):

    python -m app.modules.ncps.importar_legado --origem "mysql+pymysql://u:s@host:3306/samu"
    python -m app.modules.ncps.importar_legado --origem "..." --aplicar

Sem `--aplicar` só simula e mostra o que seria feito. É idempotente:
notificações já importadas (mesmo `legado_id`) são ignoradas, então pode
rodar de novo para trazer as registradas depois da última carga.

O que acontece:

- O **id** de lá é mantido — é o protocolo que quem notificou anotou. Se o
  id já estiver ocupado por uma notificação criada aqui, ela recebe id novo
  e aparece no relatório final.
- Gestores, locais, GHE e perigos são casados pelo nome/código e criados
  se faltarem.
- Coordenador e notificante são casados pelo **e-mail** do usuário. Quem
  não existir aqui fica registrado pelo nome no bloco "sistema anterior".
- Datas de registro estavam no horário de Brasília sem fuso; aqui viram UTC.
- O código de acompanhamento das sigilosas é guardado só como hash.
- Excluídas no sistema antigo não são importadas.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, inspect, select, text

BRASILIA = ZoneInfo("America/Sao_Paulo")
NIVEL_LEGADO = {"1": "Alto", "2": "Baixo"}   # impacto/probabilidade/controle


def _linhas(conn, tabelas: set[str], tabela: str) -> list[dict]:
    if tabela not in tabelas:
        return []
    return [dict(r._mapping) for r in conn.execute(text(f"SELECT * FROM `{tabela}`"))]


def _codigo(valor) -> str:
    valor = "" if valor is None else str(valor).strip()
    return valor or "0"


def _utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BRASILIA)
    return dt.astimezone(timezone.utc)


def importar(origem: str, empresa_id: int = 1, aplicar: bool = False) -> dict:
    import app.main  # noqa: F401 — cria o schema e registra todos os modelos
    from app.core.database import SessionLocal, engine
    from app.models import Usuario
    from app.modules.ncps import constants as cat
    from app.modules.ncps import service
    from app.modules.ncps.models import (Ncps, NcpsAcao, NcpsAnalise,
                                         NcpsCausa, NcpsGestor, NcpsGhe,
                                         NcpsLocal, NcpsOcupacional,
                                         NcpsPerigo, NcpsRisco)

    legado = create_engine(origem)
    with legado.connect() as conn:
        tabelas = set(inspect(conn).get_table_names())
        if "ncps" not in tabelas:
            raise SystemExit("A origem não tem a tabela 'ncps'.")
        dados = {t: _linhas(conn, tabelas, t) for t in (
            "ncps", "ncps_analise", "ncps_ocupacional", "ncps_causa",
            "ncps_risco", "ncps_acao", "ghe", "perigo", "gestor", "local",
            "user")}

    def agrupar(tabela):
        grupos: dict[int, list[dict]] = {}
        for linha in dados[tabela]:
            grupos.setdefault(linha["ncps_id"], []).append(linha)
        return grupos

    analises, ocupacionais = agrupar("ncps_analise"), agrupar("ncps_ocupacional")
    causas, riscos, acoes = agrupar("ncps_causa"), agrupar("ncps_risco"), agrupar("ncps_acao")
    usuarios_leg = {u["id"]: u for u in dados["user"]}
    ghe_leg = {g["id"]: g for g in dados["ghe"]}
    perigo_leg = {p["id"]: p for p in dados["perigo"]}
    gestor_leg = {g["id"]: g for g in dados["gestor"]}
    local_leg = {l["id"]: l for l in dados["local"]}

    rel = {"lidas": len(dados["ncps"]), "importadas": 0, "ja_importadas": 0,
           "excluidas_ignoradas": 0, "id_trocado": [], "usuarios_sem_par": set(),
           "gestores_criados": 0, "locais_criados": 0}

    db = SessionLocal()
    try:
        service.garantir_catalogo_pgr(db, empresa_id)
        ja = set(db.scalars(select(Ncps.legado_id).where(
            Ncps.empresa_id == empresa_id, Ncps.legado_id.isnot(None))))
        ocupados = set(db.scalars(select(Ncps.id)))
        usuarios = {u.email.lower(): u.id for u in db.scalars(select(Usuario))}

        def usuario_id(leg_id):
            u = usuarios_leg.get(leg_id)
            if not u:
                return None, None
            novo = usuarios.get((u.get("email") or "").lower())
            if novo is None:
                rel["usuarios_sem_par"].add(u.get("email") or u.get("name"))
            return novo, u.get("name")

        cache: dict[tuple, int] = {}

        def por_nome(modelo, nome, contador):
            nome = (nome or "").strip()[:120]
            if not nome:
                return None
            chave = (modelo.__tablename__, nome.lower())
            if chave not in cache:
                item = db.scalar(select(modelo).where(
                    modelo.empresa_id == empresa_id, modelo.nome == nome,
                    modelo.deleted_at.is_(None)))
                if item is None:
                    item = modelo(empresa_id=empresa_id, nome=nome)
                    db.add(item)
                    db.flush()
                    rel[contador] += 1
                cache[chave] = item.id
            return cache[chave]

        def ghe_id(leg_id):
            g = ghe_leg.get(leg_id)
            if not g:
                return None
            chave = ("ghe", g["codigo"])
            if chave not in cache:
                item = db.scalar(select(NcpsGhe).where(
                    NcpsGhe.empresa_id == empresa_id, NcpsGhe.codigo == g["codigo"],
                    NcpsGhe.deleted_at.is_(None)))
                if item is None:
                    item = NcpsGhe(empresa_id=empresa_id, codigo=g["codigo"],
                                   nome=g["nome"], cargos=g.get("cargos"),
                                   ativo=bool(g.get("ativo", True)))
                    db.add(item)
                    db.flush()
                cache[chave] = item.id
            return cache[chave]

        def perigo_id(leg_id):
            p = perigo_leg.get(leg_id)
            if not p:
                return None
            chave = ("perigo", p["grupo"], p["nome"])
            if chave not in cache:
                item = db.scalar(select(NcpsPerigo).where(
                    NcpsPerigo.empresa_id == empresa_id,
                    NcpsPerigo.grupo == p["grupo"], NcpsPerigo.nome == p["nome"],
                    NcpsPerigo.deleted_at.is_(None)))
                if item is None:
                    item = NcpsPerigo(empresa_id=empresa_id, grupo=p["grupo"],
                                      nome=p["nome"], fonte=p.get("fonte"),
                                      dano=p.get("dano"), ativo=bool(p.get("ativo", True)))
                    db.add(item)
                    db.flush()
                cache[chave] = item.id
            return cache[chave]

        for leg in sorted(dados["ncps"], key=lambda r: r["id"]):
            if leg.get("deleted"):
                rel["excluidas_ignoradas"] += 1
                continue
            if leg["id"] in ja:
                rel["ja_importadas"] += 1
                continue

            coord_id, coord_nome = usuario_id(leg.get("coordenador_id"))
            notif_id, notif_nome = usuario_id(leg.get("notificante_id"))
            extras = {
                "Impacto": NIVEL_LEGADO.get(_codigo(leg.get("impacto"))),
                "Probabilidade": NIVEL_LEGADO.get(_codigo(leg.get("probabilidade"))),
                "Controle": NIVEL_LEGADO.get(_codigo(leg.get("controle"))),
                "Causa raiz": cat.FATORES_LONDRES.get(_codigo(leg.get("causa"))),
                "Tipo de ação": cat.TIPO_ACAO.get(
                    cat.TIPO_ACAO_LEGADO.get(_codigo(leg.get("acao")), "")),
                "Plano de ação": (leg.get("plano") or "").strip() or None,
                "Prazo": leg["prazo"].strftime("%d/%m/%Y") if leg.get("prazo") else None,
                "Coordenador": coord_nome if coord_nome and not coord_id else None,
                "Notificante": notif_nome if notif_nome and not notif_id else None,
            }
            extras = {k: v for k, v in extras.items() if v}
            natureza = leg.get("natureza") or "paciente"
            n = Ncps(
                empresa_id=empresa_id,
                natureza=natureza if natureza in cat.NATUREZA else "paciente",
                descricao=leg.get("descricao") or "(sem descrição)",
                local=(leg.get("local") or None) and str(leg["local"])[:100],
                id_ocorrencia=(leg.get("id_ocorrencia") or None) and str(leg["id_ocorrencia"])[:100],
                data_hora_ocorrencia=leg.get("data_hora_ocorrencia"),
                sugestao=leg.get("sugestao"),
                registrado_em=_utc(leg.get("data_hora_registro")),
                notificante_id=notif_id,
                anonima=bool(leg.get("anonima")) or not leg.get("notificante_id"),
                confidencial=bool(leg.get("confidencial")),
                codigo_hash=service.hash_codigo(service.normalizar_codigo(
                    leg["codigo_acompanhamento"])) if leg.get("codigo_acompanhamento") else None,
                status=_codigo(leg.get("status")),
                procedente=_codigo(leg.get("procedente")),
                local_id=por_nome(NcpsLocal, (local_leg.get(leg.get("local_padronizado_id")) or {}).get("nome"), "locais_criados"),
                gestor_id=por_nome(NcpsGestor, (gestor_leg.get(leg.get("gestor_id")) or {}).get("nome"), "gestores_criados"),
                coordenador_id=coord_id,
                classificacao_incidente=_codigo(leg.get("classificacao_incidente")),
                dano=_codigo(leg.get("dano")),
                macroprocesso=_codigo(leg.get("macroprocesso")),
                seguranca=_codigo(leg.get("seguranca")),
                sentinela=_codigo(leg.get("sentinela")),
                tipo_evento_trab=leg.get("tipo_evento_trab"),
                ghe_id=ghe_id(leg.get("ghe_id")),
                houve_lesao=leg.get("houve_lesao"),
                legado_id=leg["id"],
                legado=json.dumps(extras, ensure_ascii=False) if extras else None,
            )
            if leg["id"] in ocupados:
                rel["id_trocado"].append(leg["id"])
            else:
                n.id = leg["id"]
                ocupados.add(leg["id"])

            for a in analises.get(leg["id"], [])[:1]:
                n.analise = NcpsAnalise(empresa_id=empresa_id, **{
                    k: a.get(k) for k in ("cronologia", "problemas", "fontes",
                                          "barreiras", "recomendacoes")})
            for o in ocupacionais.get(leg["id"], [])[:1]:
                n.ocupacional = NcpsOcupacional(
                    empresa_id=empresa_id, grupo_risco=o.get("grupo_risco"),
                    perigo_id=perigo_id(o.get("perigo_id")),
                    natureza_lesao=o.get("natureza_lesao"),
                    parte_corpo=o.get("parte_corpo"), afastamento=o.get("afastamento"),
                    dias_afastamento=o.get("dias_afastamento"),
                    cat_emitida=o.get("cat_emitida"), cat_numero=o.get("cat_numero"),
                    cat_data=o.get("cat_data"), revisar_pgr=bool(o.get("revisar_pgr")),
                    pgr_revisado_em=o.get("pgr_revisado_em"))
            if n.natureza == "trabalhador" and n.ocupacional is None:
                n.ocupacional = NcpsOcupacional(empresa_id=empresa_id)
            for c in causas.get(leg["id"], []):
                n.causas.append(NcpsCausa(
                    empresa_id=empresa_id, metodo=c["metodo"], categoria=c["categoria"],
                    descricao=c["descricao"], causa_raiz=bool(c.get("causa_raiz"))))
            for r in riscos.get(leg["id"], []):
                n.riscos.append(NcpsRisco(
                    empresa_id=empresa_id, momento=r["momento"],
                    probabilidade=r["probabilidade"], severidade=r["severidade"],
                    justificativa=r.get("justificativa")))
            for a in acoes.get(leg["id"], []):
                n.acoes.append(NcpsAcao(
                    empresa_id=empresa_id, descricao=a["descricao"], tipo=a.get("tipo"),
                    responsavel=a.get("responsavel"), prazo=a.get("prazo"),
                    status=a.get("status") or "pendente", concluida_em=a.get("concluida_em"),
                    eficacia=a.get("eficacia") or "nao_verificada",
                    observacao=a.get("observacao")))
            db.add(n)
            rel["importadas"] += 1

        if aplicar:
            db.commit()
            if engine.dialect.name == "postgresql":   # ids explícitos não avançam a sequência
                db.execute(text("SELECT setval(pg_get_serial_sequence('ncps', 'id'), "
                                "(SELECT MAX(id) FROM ncps))"))
                db.commit()
        else:
            db.rollback()
    finally:
        db.close()
    rel["usuarios_sem_par"] = sorted(x for x in rel["usuarios_sem_par"] if x)
    return rel


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--origem", required=True,
                        help="URL SQLAlchemy do banco do sistema anterior")
    parser.add_argument("--empresa", type=int, default=1)
    parser.add_argument("--aplicar", action="store_true",
                        help="grava de fato (sem isso, só simula)")
    args = parser.parse_args(argv)

    rel = importar(args.origem, args.empresa, args.aplicar)
    print("SIMULAÇÃO — nada foi gravado (use --aplicar)" if not args.aplicar
          else "Importação concluída")
    print(f"  lidas no sistema anterior: {rel['lidas']}")
    print(f"  importadas agora:          {rel['importadas']}")
    print(f"  já importadas antes:       {rel['ja_importadas']}")
    print(f"  excluídas (ignoradas):     {rel['excluidas_ignoradas']}")
    print(f"  gestores / locais criados: {rel['gestores_criados']} / {rel['locais_criados']}")
    if rel["id_trocado"]:
        print(f"  ATENÇÃO: {len(rel['id_trocado'])} protocolo(s) já ocupado(s) aqui "
              f"receberam id novo: {rel['id_trocado'][:20]}")
    if rel["usuarios_sem_par"]:
        print(f"  usuários sem cadastro aqui (guardados pelo nome): "
              f"{', '.join(rel['usuarios_sem_par'])}")


if __name__ == "__main__":
    main(sys.argv[1:])
