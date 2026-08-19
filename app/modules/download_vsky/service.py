"""Regras de negócio do módulo Download vSky (§35.16).

Fluxo obrigatório: View -> Service -> Repository -> Database (§35.3).

`importar_periodo` executa o ciclo completo:
1. autentica no portal vSky (credenciais do ConfigService);
2. gera o relatório "Total de Registros Analítico" para o período;
3. grava o XLS em uploads/empresa_<id>/download_vsky/ (§20, §36.12);
4. importa as linhas, descartando duplicadas (hash da linha inteira).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.download_vsky.constants import (
    MODULE_NAME,
    STATUS_CONCLUIDO,
    STATUS_ERRO,
)
from app.modules.download_vsky.importer import (
    data_ocorrencia_dt,
    linha_hash,
    parse_xls,
)
from app.modules.download_vsky.models import VskyImportacao
from app.modules.download_vsky.repository import (
    VskyImportacaoRepository,
    VskyRegistroRepository,
)
from app.modules.download_vsky.validators import validar_periodo
from app.modules.download_vsky.vsky_client import VskyClient, VskyError


class DownloadVskyService:
    def __init__(self, session: Session, empresa_id: int = 1):
        self.empresa_id = empresa_id
        self.session = session
        self.importacoes = VskyImportacaoRepository(session, empresa_id)
        self.registros = VskyRegistroRepository(session, empresa_id)

    # ------------------------------------------------------------ consultas

    def query(self, search: str | None = None):
        return self.importacoes.query(search)

    def query_registros(self, search: str | None = None):
        return self.registros.query(search)

    def total_registros(self) -> int:
        return self.registros.total()

    def calendario_cobertura(self) -> dict:
        """Cobertura diária dos registros: meses com o status de cada dia
        (com registros / SEM registros / futuro), do primeiro dia com dados
        até hoje — os dias vermelhos indicam períodos a importar do vSky."""
        import calendar as _cal
        from datetime import date as _date

        contagens = self.registros.contagem_por_dia()
        hoje = _date.today()
        if not contagens:
            return {"meses": [], "dias_sem": 0, "inicio": None, "fim": None}
        inicio = min(contagens)
        nomes_mes = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio",
                     "Junho", "Julho", "Agosto", "Setembro", "Outubro",
                     "Novembro", "Dezembro"]
        meses, dias_sem = [], 0
        ano, mes = inicio.year, inicio.month
        while (ano, mes) <= (hoje.year, hoje.month):
            semanas = []
            for semana in _cal.monthcalendar(ano, mes):
                linha = []
                for dia in semana:
                    if dia == 0:
                        linha.append(None)
                        continue
                    d = _date(ano, mes, dia)
                    n = contagens.get(d, 0)
                    if d > hoje or d < inicio:
                        status = "fora"
                    elif n > 0:
                        status = "com"
                    else:
                        status = "sem"
                        dias_sem += 1
                    linha.append({"dia": dia, "iso": d.isoformat(),
                                  "n": n, "status": status})
                semanas.append(linha)
            meses.append({"nome": f"{nomes_mes[mes - 1]}/{ano}",
                          "semanas": semanas})
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
        return {"meses": meses, "dias_sem": dias_sem,
                "inicio": inicio.strftime("%d/%m/%Y"),
                "fim": hoje.strftime("%d/%m/%Y")}

    def get(self, item_id: int) -> VskyImportacao | None:
        return self.importacoes.get(item_id)

    def delete(self, item_id: int) -> bool:
        item = self.importacoes.get(item_id)
        if item is None:
            return False
        self.importacoes.soft_delete(item)
        return True

    # ----------------------------------------------------------- importação

    def importar_periodo(
        self,
        data_inicial: str,
        data_final: str,
        base_url: str,
        usuario_vsky: str,
        senha_vsky: str,
        cliente_id: str | None = None,
        created_by: int | None = None,
    ) -> VskyImportacao:
        """Gera o relatório no vSky e importa as linhas. Nunca lança por
        falha remota: o resultado (inclusive erro) fica no registro."""
        data_inicial, data_final = validar_periodo(data_inicial, data_final)
        item = self.importacoes.create({
            "data_inicial": data_inicial,
            "data_final": data_final,
            "created_by": created_by,
        })
        try:
            with VskyClient(base_url, usuario_vsky, senha_vsky) as client:
                client.login()
                content = client.gerar_total_registros_analitico(
                    data_inicial, data_final, cliente_id)
            item.caminho = _salvar_xls(content, self.empresa_id,
                                       data_inicial, data_final)
            item.tamanho = len(content)
            novas, duplicadas, total = self._inserir_linhas(
                parse_xls(content), item)
            item.total_linhas = total
            item.linhas_novas = novas
            item.linhas_duplicadas = duplicadas
            item.status = STATUS_CONCLUIDO
            item.erro = None
        except (VskyError, httpx.HTTPError, ValueError, OSError) as exc:
            item.status = STATUS_ERRO
            item.erro = str(exc)[:1000]
        self.session.commit()
        return item

    def _inserir_linhas(
        self, linhas: list[dict[str, str]], item: VskyImportacao,
    ) -> tuple[int, int, int]:
        """Insere linhas inéditas; devolve (novas, duplicadas, total)."""
        candidatos: dict[str, dict[str, str]] = {}
        duplicadas_no_arquivo = 0
        for valores in linhas:
            h = linha_hash(valores)
            if h in candidatos:
                duplicadas_no_arquivo += 1
            else:
                candidatos[h] = valores

        existentes = self.registros.hashes_existentes(list(candidatos))
        novos = []
        for h, valores in candidatos.items():
            if h in existentes:
                continue
            novos.append({
                **valores,
                "linha_hash": h,
                "importacao_id": item.id,
                "data_ocorrencia_dt": data_ocorrencia_dt(valores),
                "created_by": item.created_by,
            })
        if novos:
            self.registros.bulk_insert(novos)
        total = len(linhas)
        duplicadas = duplicadas_no_arquivo + len(existentes)
        return len(novos), duplicadas, total


logger = logging.getLogger("download_vsky")


def prontuario_path(empresa_id: int, numero: str) -> Path:
    """Caminho do PDF do prontuário em cache no disco."""
    seguro = "".join(c for c in str(numero) if c.isalnum()) or "sem_numero"
    return (Path(settings.upload_dir) / f"empresa_{empresa_id}"
            / MODULE_NAME / "prontuarios" / f"{seguro}.pdf")


def obter_prontuario(db: Session, empresa_id: int, numero: str) -> Path:
    """Devolve o caminho do PDF do prontuário, baixando do vSky se preciso.

    Cacheia em uploads/empresa_<id>/download_vsky/prontuarios/<num>.pdf
    (como o Desperdicio). Levanta ValueError com mensagem clara em falha.
    """
    from app.core.config_service import get_config
    from app.modules.download_vsky.constants import (
        CONFIG_BASE_URL, CONFIG_SENHA, CONFIG_USUARIO, DEFAULT_BASE_URL,
    )
    from app.modules.download_vsky.prontuario_client import (
        ProntuarioClient, ProntuarioError,
    )

    numero = str(numero).strip()
    if not numero:
        raise ValueError("Número de ocorrência ausente.")
    destino = prontuario_path(empresa_id, numero)
    if destino.is_file() and destino.stat().st_size > 0:
        registrar_prontuario(db, empresa_id, numero, destino)
        return destino

    usuario = get_config(db, CONFIG_USUARIO, empresa_id=empresa_id)
    senha = get_config(db, CONFIG_SENHA, empresa_id=empresa_id)
    if not (usuario and senha):
        raise ValueError("Credenciais do vSky não configuradas — configure em "
                         "Download vSky > Configuração.")
    base_url = get_config(db, CONFIG_BASE_URL, DEFAULT_BASE_URL, empresa_id)
    try:
        with ProntuarioClient(base_url, usuario, senha) as client:
            client.login()
            fichas = client.baixar_prontuario(numero)
    except ProntuarioError as exc:
        raise ValueError(str(exc)) from exc
    except (httpx.HTTPError, OSError) as exc:
        raise ValueError(f"Falha ao baixar o prontuário: {exc}") from exc

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(_juntar_fichas(fichas))
    registrar_prontuario(db, empresa_id, numero, destino, forcar=True)
    return destino


def _juntar_fichas(fichas: list[bytes]) -> bytes:
    """Uma ocorrência com várias viaturas tem uma ficha por equipe.

    Vira um PDF só, na ordem em que o portal listou: o investigador lê o
    atendimento inteiro num arquivo, e o visualizador embutido, a extração
    de texto e o registro no banco continuam valendo para a ocorrência.
    """
    if len(fichas) <= 1:
        return fichas[0] if fichas else b""
    from io import BytesIO

    from pypdf import PdfWriter

    escritor = PdfWriter()
    try:
        for ficha in fichas:
            escritor.append(BytesIO(ficha))
    except Exception:  # noqa: BLE001 — ficha corrompida não pode perder o resto
        logger.exception("Falha ao juntar as fichas; fica só a primeira")
        return fichas[0]
    saida = BytesIO()
    escritor.write(saida)
    return saida.getvalue()


def _extrair_texto_pdf(caminho: Path) -> tuple[str, int]:
    """Texto e nº de páginas do PDF (vazio se a extração falhar)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(caminho))
        texto = "\n".join((pg.extract_text() or "") for pg in reader.pages)
        return texto.strip(), len(reader.pages)
    except Exception:
        return "", 0


def registrar_prontuario(db: Session, empresa_id: int, numero: str,
                         destino: Path, forcar: bool = False):
    """Garante o registro do prontuário no banco (com texto extraído).

    `forcar=True` reprocessa mesmo que já exista (download novo);
    sem forçar, um registro existente do mesmo arquivo é reaproveitado.
    """
    from sqlalchemy import select

    from app.modules.download_vsky.models import VskyProntuario

    tamanho = destino.stat().st_size
    registro = db.scalar(select(VskyProntuario).where(
        VskyProntuario.empresa_id == empresa_id,
        VskyProntuario.ocorrencia == numero,
        VskyProntuario.deleted_at.is_(None)))
    if registro is not None and not forcar and registro.tamanho == tamanho:
        return registro

    texto, paginas = _extrair_texto_pdf(destino)
    if registro is None:
        registro = VskyProntuario(empresa_id=empresa_id, ocorrencia=numero)
        db.add(registro)
    registro.caminho = str(destino.relative_to(Path(settings.upload_dir)))
    registro.tamanho = tamanho
    registro.paginas = paginas
    registro.texto = texto[:1_000_000] or None
    registro.baixado_em = datetime.now(timezone.utc)
    db.commit()
    return registro


def absolute_path(item: VskyImportacao) -> Path:
    return Path(settings.upload_dir) / (item.caminho or "")


def _salvar_xls(content: bytes, empresa_id: int,
                data_inicial: str, data_final: str) -> str:
    """Grava o XLS no disco e devolve o caminho relativo (§36.12)."""
    now = datetime.now(timezone.utc)
    periodo = f"{data_inicial}_{data_final}".replace("/", "-")
    nome_servidor = f"registros_analitico_{periodo}_{uuid.uuid4().hex[:8]}.xls"
    relative = Path(f"empresa_{empresa_id}") / MODULE_NAME / f"{now.year}" / f"{now.month:02d}"
    directory = Path(settings.upload_dir) / relative
    directory.mkdir(parents=True, exist_ok=True)
    (directory / nome_servidor).write_bytes(content)
    return str(relative / nome_servidor)
