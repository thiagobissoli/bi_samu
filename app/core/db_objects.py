"""Objetos de banco: Views, Materialized Views, funções e triggers (§36.15–36.18).

Tudo aqui é **idempotente** e sensível ao dialeto: o que o SQLite não suporta
(materialized views, funções PL/pgSQL, triggers) simplesmente não é criado, e
o desenvolvimento continua funcionando com o mesmo código de produção.

Aplicado automaticamente pelo `init_db()`. Para recriar manualmente:

    python manage.py db-objects
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

# --- Views (§36.15) ---
# Consultas frequentes, já com o soft delete aplicado (§36.7).

VIEWS: dict[str, str] = {
    "vw_usuarios": """
        SELECT u.id, u.empresa_id, u.nome, u.email, u.ativo,
               u.email_confirmado, u.mfa_habilitado, u.ultimo_login,
               e.nome_fantasia AS empresa
          FROM usuarios u
          LEFT JOIN empresas e ON e.id = u.empresa_id
         WHERE u.deleted_at IS NULL
    """,
    "vw_permissoes": """
        SELECT u.id AS usuario_id, u.empresa_id, u.nome AS usuario,
               pf.nome AS perfil, pm.codigo AS permissao, pm.modulo
          FROM usuarios u
          JOIN usuarios_perfis up ON up.usuario_id = u.id
          JOIN perfis pf ON pf.id = up.perfil_id
          JOIN perfis_permissoes pp ON pp.perfil_id = pf.id
          JOIN permissoes pm ON pm.id = pp.permissao_id
         WHERE u.deleted_at IS NULL AND pf.deleted_at IS NULL AND pf.ativo = 1
    """,
    "vw_notificacoes": """
        SELECT n.id, n.empresa_id, n.usuario_id, u.nome AS usuario,
               n.titulo, n.tipo, n.lida, n.created_at
          FROM notificacoes n
          JOIN usuarios u ON u.id = n.usuario_id
         WHERE n.deleted_at IS NULL
    """,
    "vw_dashboard": """
        SELECT e.id AS empresa_id, e.nome_fantasia AS empresa,
               (SELECT COUNT(*) FROM usuarios u
                 WHERE u.empresa_id = e.id AND u.deleted_at IS NULL) AS total_usuarios,
               (SELECT COUNT(*) FROM auditoria a
                 WHERE a.empresa_id = e.id) AS total_eventos,
               (SELECT COUNT(*) FROM logs l
                 WHERE l.empresa_id = e.id AND l.nivel IN ('ERROR','CRITICAL')) AS total_erros,
               (SELECT COUNT(*) FROM arquivos f
                 WHERE f.empresa_id = e.id AND f.deleted_at IS NULL) AS total_arquivos
          FROM empresas e
         WHERE e.deleted_at IS NULL
    """,
}

# --- Materialized Views (§36.16) — só PostgreSQL ---

MATERIALIZED_VIEWS: dict[str, str] = {
    "mvw_auditoria_diaria": """
        SELECT empresa_id,
               DATE(created_at) AS dia,
               tabela,
               acao,
               COUNT(*) AS total
          FROM auditoria
         GROUP BY empresa_id, DATE(created_at), tabela, acao
    """,
}

# --- Funções (§36.17) — PostgreSQL ---

FUNCOES_POSTGRES: list[str] = [
    """
    CREATE OR REPLACE FUNCTION calcular_idade(nascimento DATE)
    RETURNS INTEGER AS $$
        SELECT EXTRACT(YEAR FROM AGE(CURRENT_DATE, nascimento))::INTEGER;
    $$ LANGUAGE SQL IMMUTABLE;
    """,
    """
    CREATE OR REPLACE FUNCTION formatar_documento(documento TEXT)
    RETURNS TEXT AS $$
    DECLARE limpo TEXT;
    BEGIN
        limpo := regexp_replace(COALESCE(documento, ''), '\\D', '', 'g');
        IF length(limpo) = 11 THEN
            RETURN substr(limpo,1,3)||'.'||substr(limpo,4,3)||'.'||
                   substr(limpo,7,3)||'-'||substr(limpo,10,2);
        ELSIF length(limpo) = 14 THEN
            RETURN substr(limpo,1,2)||'.'||substr(limpo,3,3)||'.'||
                   substr(limpo,6,3)||'/'||substr(limpo,9,4)||'-'||substr(limpo,13,2);
        END IF;
        RETURN documento;
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;
    """,
    """
    CREATE OR REPLACE FUNCTION proximo_numero(p_empresa BIGINT, p_tabela TEXT)
    RETURNS BIGINT AS $$
    DECLARE proximo BIGINT;
    BEGIN
        EXECUTE format('SELECT COALESCE(MAX(id), 0) + 1 FROM %I WHERE empresa_id = $1',
                       p_tabela)
           INTO proximo USING p_empresa;
        RETURN proximo;
    END;
    $$ LANGUAGE plpgsql;
    """,
    """
    CREATE OR REPLACE FUNCTION gerar_codigo(prefixo TEXT, tamanho INTEGER DEFAULT 8)
    RETURNS TEXT AS $$
        SELECT prefixo || upper(substr(md5(random()::text), 1, tamanho));
    $$ LANGUAGE SQL VOLATILE;
    """,
]

# --- Triggers (§36.18) — PostgreSQL ---
# O ORM já cuida de updated_at e version (§15). Estas triggers garantem o mesmo
# quando alguém escreve por fora da aplicação (script, carga, correção manual).

TRIGGERS_POSTGRES_FUNCAO = """
CREATE OR REPLACE FUNCTION atualizar_auditoria_basica()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    IF NEW.version IS NOT DISTINCT FROM OLD.version THEN
        NEW.version := COALESCE(OLD.version, 0) + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TABELAS_COM_TRIGGER = (
    "empresas", "usuarios", "perfis", "permissoes",
    "configuracoes", "notificacoes", "arquivos", "api_keys",
)


def _existe_tabela(conn, nome: str) -> bool:
    from sqlalchemy import inspect

    return nome in inspect(conn).get_table_names()


def aplicar(engine: Engine) -> list[str]:
    """Cria/atualiza os objetos suportados pelo banco atual. Idempotente."""
    dialeto = engine.dialect.name
    criados: list[str] = []

    with engine.begin() as conn:
        # Views — suportadas por SQLite, PostgreSQL e MySQL
        for nome, corpo in VIEWS.items():
            try:
                if not _existe_tabela(conn, "usuarios"):
                    break  # banco ainda sem as tabelas base
                conn.execute(text(f"DROP VIEW IF EXISTS {nome}"))
                conn.execute(text(f"CREATE VIEW {nome} AS {corpo}"))
                criados.append(f"view: {nome}")
            except Exception:  # noqa: BLE001 — uma view quebrada não impede o boot
                continue

        if dialeto != "postgresql":
            return criados

        for instrucao in FUNCOES_POSTGRES:
            try:
                conn.execute(text(instrucao))
                criados.append("função")
            except Exception:  # noqa: BLE001
                continue

        for nome, corpo in MATERIALIZED_VIEWS.items():
            try:
                conn.execute(text(f"CREATE MATERIALIZED VIEW IF NOT EXISTS {nome} AS {corpo}"))
                criados.append(f"materialized view: {nome}")
            except Exception:  # noqa: BLE001
                continue

        try:
            conn.execute(text(TRIGGERS_POSTGRES_FUNCAO))
            for tabela in TABELAS_COM_TRIGGER:
                if not _existe_tabela(conn, tabela):
                    continue
                conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{tabela}_auditoria ON {tabela}"))
                conn.execute(text(
                    f"CREATE TRIGGER trg_{tabela}_auditoria BEFORE UPDATE ON {tabela} "
                    "FOR EACH ROW EXECUTE FUNCTION atualizar_auditoria_basica()"
                ))
                criados.append(f"trigger: {tabela}")
        except Exception:  # noqa: BLE001
            pass

    return criados


def atualizar_materialized_views(engine: Engine) -> list[str]:
    """REFRESH das materialized views (§36.16) — chame pelo scheduler."""
    if engine.dialect.name != "postgresql":
        return []
    atualizadas = []
    with engine.begin() as conn:
        for nome in MATERIALIZED_VIEWS:
            try:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW {nome}"))
                atualizadas.append(nome)
            except Exception:  # noqa: BLE001
                continue
    return atualizadas


def registrar_funcoes_sqlite(engine: Engine) -> None:
    """Equivalentes Python das funções do banco, para o SQLite (§36.17).

    Assim a mesma consulta SQL roda em desenvolvimento e em produção.
    """
    if engine.dialect.name != "sqlite":
        return

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _registrar(conexao, _registro):  # noqa: ANN001
        from datetime import date, datetime

        def calcular_idade(nascimento):
            if not nascimento:
                return None
            if isinstance(nascimento, str):
                try:
                    nascimento = datetime.strptime(nascimento[:10], "%Y-%m-%d").date()
                except ValueError:
                    return None
            hoje = date.today()
            return hoje.year - nascimento.year - (
                (hoje.month, hoje.day) < (nascimento.month, nascimento.day)
            )

        def formatar_documento(documento):
            from app.core.helpers import MaskHelper

            return MaskHelper.documento(documento)

        def gerar_codigo(prefixo, tamanho=8):
            import secrets

            return f"{prefixo}{secrets.token_hex(tamanho)[:tamanho].upper()}"

        conexao.create_function("calcular_idade", 1, calcular_idade)
        conexao.create_function("formatar_documento", 1, formatar_documento)
        conexao.create_function("gerar_codigo", 2, gerar_codigo)
