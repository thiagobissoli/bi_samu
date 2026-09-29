#!/usr/bin/env python3
"""Converte o banco MySQL do projeto para um arquivo SQLite.

Rode NA SUA MÁQUINA, com o venv do projeto:

    .venv/bin/python deploy/converter_para_sqlite.py                 # tudo
    .venv/bin/python deploy/converter_para_sqlite.py --sem-pessoais  # sem dados de paciente
    .venv/bin/python deploy/converter_para_sqlite.py --desde 2026-01-01

O arquivo sai em transferencia/dados.sqlite3, pronto para subir ao
PythonAnywhere e ser apontado por DATABASE_URL.

ATENÇÃO — este banco contém dados de saúde identificáveis (prontuários,
registros de atendimento, investigações nominais). Levá-lo para um servidor
de terceiros é decisão do controlador dos dados, com implicações de LGPD.
A opção --sem-pessoais existe para gerar uma base utilizável para
demonstração e homologação sem transferir esse conteúdo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Com --sem-pessoais estas tabelas são criadas vazias. A lista foi montada
# lendo o schema, não por suposição: cobre dado de paciente, dado pessoal de
# equipe e credenciais.
TABELAS_PESSOAIS = {
    # Pacientes
    "vsky_prontuarios",            # PDFs de prontuário
    "vsky_registros_analiticos",   # paciente, endereço, telefone
    "investigacao_analises",       # análises nominais
    # Equipe
    "usuarios",                    # nome, e-mail, telefone, senha_hash
    "ncps_gestores",               # nomes de gestores
    "auditoria",                   # usuario_nome, IP de quem operou
    "notificacoes",                # mensagens dirigidas a pessoas
    # Vínculos de usuário: sem as pessoas, apontam para ids inexistentes — e o
    # seed recria o administrador com id 1, que herdaria perfis de outra pessoa.
    "usuarios_perfis",
    "ncps_setor_usuarios",
}

# Credenciais: nunca vão, nem sem --sem-pessoais. Levar sessões ativas para
# outro servidor permitiria assumir a sessão de quem está logado aqui.
TABELAS_CREDENCIAIS = {"sessoes", "tokens", "api_keys"}


def converter(destino: Path, sem_pessoais: bool, desde: str | None) -> None:
    from sqlalchemy import (BigInteger, Boolean, DateTime, Float, Integer,
                            LargeBinary, MetaData, Text, create_engine, select)

    from app.core.config import settings

    origem = create_engine(settings.database_url)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.unlink(missing_ok=True)
    alvo = create_engine(f"sqlite:///{destino}")

    md = MetaData()
    md.reflect(bind=origem)

    # Tipos do MySQL que o SQLite não conhece
    equivalentes = {
        "LONGBLOB": LargeBinary, "MEDIUMBLOB": LargeBinary, "BLOB": LargeBinary,
        "TINYBLOB": LargeBinary, "LONGTEXT": Text, "MEDIUMTEXT": Text,
        "TINYTEXT": Text, "TEXT": Text, "TINYINT": Boolean, "SMALLINT": Integer,
        "MEDIUMINT": Integer, "BIGINT": BigInteger, "INTEGER": Integer,
        "DOUBLE": Float, "DECIMAL": Float, "NUMERIC": Float,
        "DATETIME": DateTime, "TIMESTAMP": DateTime,
    }
    for tabela in md.sorted_tables:
        for coluna in tabela.columns:
            novo = equivalentes.get(type(coluna.type).__name__)
            if novo is not None:
                coluna.type = novo()
            # No SQLite só INTEGER PRIMARY KEY incrementa sozinho: um
            # BIGINT PRIMARY KEY faria todo INSERT sem id explícito falhar
            # com "NOT NULL constraint failed". É a mesma razão pela qual os
            # modelos usam BigInteger().with_variant(Integer, "sqlite").
            if coluna.primary_key and isinstance(coluna.type, (BigInteger, Integer)):
                coluna.type = Integer()
            # As colações do MySQL não existem no SQLite
            if getattr(coluna.type, "collation", None):
                coluna.type.collation = None
        # No SQLite o nome do índice é global, não por tabela
        for indice in tabela.indexes:
            if not indice.name.startswith(tabela.name):
                indice.name = f"{tabela.name}_{indice.name}"

    md.create_all(alvo)
    print(f"schema criado: {len(md.tables)} tabelas")

    copiadas = ignoradas = 0
    with origem.connect() as src, alvo.begin() as dst:
        for tabela in md.sorted_tables:
            if tabela.name in TABELAS_CREDENCIAIS:
                print(f"  {tabela.name}: vazia (credenciais nunca são copiadas)")
                ignoradas += 1
                continue

            if sem_pessoais and tabela.name in TABELAS_PESSOAIS:
                print(f"  {tabela.name}: vazia (--sem-pessoais)")
                ignoradas += 1
                continue

            consulta = select(tabela)
            if desde and "created_at" in tabela.columns:
                consulta = consulta.where(tabela.c.created_at >= desde)

            linhas = [dict(l) for l in src.execute(consulta).mappings().all()]

            # Configurações cifradas dependem da SECRET_KEY desta máquina: no
            # destino não decifram. Vão embora em vez de ficar como lixo.
            if tabela.name == "configuracoes":
                antes = len(linhas)
                linhas = [l for l in linhas
                          if not str(l.get("valor") or "").startswith("enc:")]
                if antes != len(linhas):
                    print(f"  configuracoes: {antes - len(linhas)} chaves cifradas omitidas")

            for inicio in range(0, len(linhas), 5000):
                dst.execute(tabela.insert(), linhas[inicio:inicio + 5000])
            copiadas += len(linhas)

    tamanho = destino.stat().st_size / 1048576
    print(f"\n{copiadas} linhas copiadas, {ignoradas} tabelas criadas vazias")
    if sem_pessoais:
        print("Sem dados de paciente, de equipe nem credenciais.")
        print("O primeiro acesso cria o administrador padrão pelos seeds.")
    print(f"arquivo: {destino}  ({tamanho:.0f} MB)")
    if tamanho > 450:
        print("\nAVISO: o plano Beginner do PythonAnywhere dá 512 MB no total,")
        print("e o código já ocupa ~25 MB. Considere --sem-pessoais ou --desde.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sem-pessoais", action="store_true", dest="sem_pessoais",
                        help="cria as tabelas de dados de paciente vazias")
    parser.add_argument("--desde", metavar="AAAA-MM-DD",
                        help="copia só registros criados a partir desta data")
    parser.add_argument("--saida", type=Path,
                        default=RAIZ / "transferencia" / "dados.sqlite3")
    args = parser.parse_args()
    converter(args.saida, args.sem_pessoais, args.desde)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
