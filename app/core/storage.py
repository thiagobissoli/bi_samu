"""Armazenamento de arquivos (§20, §36.12).

Conteúdo no disco em uploads/empresa_<id>/<modulo>/<ano>/<mes>/;
o banco guarda apenas metadados (tabela arquivos).
"""

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Arquivo

ALLOWED_MIME_PREFIXES = ("image/", "application/pdf", "application/vnd", "text/")
MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB


def save_upload(
    db: Session,
    file: UploadFile,
    empresa_id: int,
    modulo: str = "geral",
    created_by: int | None = None,
) -> Arquivo:
    content = file.file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise ValueError("Arquivo excede o tamanho máximo de 25 MB.")
    mime = file.content_type or "application/octet-stream"
    if not mime.startswith(ALLOWED_MIME_PREFIXES):
        raise ValueError(f"Tipo de arquivo não permitido: {mime}")

    now = datetime.now(timezone.utc)
    extension = Path(file.filename or "arquivo").suffix[:10]
    nome_servidor = f"{uuid.uuid4().hex}{extension}"
    relative = Path(f"empresa_{empresa_id}") / modulo / f"{now.year}" / f"{now.month:02d}"
    directory = Path(settings.upload_dir) / relative
    directory.mkdir(parents=True, exist_ok=True)
    (directory / nome_servidor).write_bytes(content)

    item = Arquivo(
        empresa_id=empresa_id,
        nome_original=(file.filename or "arquivo")[:255],
        nome_servidor=nome_servidor,
        mime_type=mime[:100],
        tamanho=len(content),
        hash=hashlib.sha256(content).hexdigest(),
        caminho=str(relative / nome_servidor),
        modulo=modulo,
        created_by=created_by,
    )
    db.add(item)
    db.commit()
    return item


def absolute_path(arquivo: Arquivo) -> Path:
    return Path(settings.upload_dir) / arquivo.caminho
