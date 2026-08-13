"""Aparência do sistema (§22, §24, §37) — template AdminLTE por empresa.

Todas as opções de layout do AdminLTE 4 são configuráveis por empresa via
Configurações, incluindo a logo (armazenada via módulo de Uploads §20).

Chaves utilizadas:
    brand_nome         Nome exibido na sidebar (padrão: nome da aplicação)
    logo_arquivo_id    Id do arquivo da logo (tabela arquivos)
    tema               Tema padrão: claro | escuro (usuário pode sobrepor)
    sidebar_tema       auto (acompanha o tema) | escuro (sempre escura)
    layout_fixo        Sidebar fixa (classe layout-fixed): sim | nao
    header_fixo        Navbar fixa (fixed-header): sim | nao
    footer_fixo        Rodapé fixo (fixed-footer): sim | nao
    sidebar_mini       Colapsa para ícones (sidebar-mini): sim | nao
    sidebar_colapsada  Inicia colapsada (sidebar-collapse): sim | nao
    cor_primaria       Cor primária em hex (vazio = padrão Bootstrap)
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.config_service import get_config

APPEARANCE_KEYS = [
    "brand_nome", "logo_arquivo_id", "tema", "sidebar_tema", "layout_fixo",
    "header_fixo", "footer_fixo", "sidebar_mini", "sidebar_colapsada", "cor_primaria",
]

DEFAULTS = {
    "brand_nome": "",
    "logo_arquivo_id": "",
    "tema": "claro",
    "sidebar_tema": "auto",
    "layout_fixo": "sim",
    "header_fixo": "nao",
    "footer_fixo": "nao",
    "sidebar_mini": "sim",
    "sidebar_colapsada": "nao",
    "cor_primaria": "",
}


def hex_darken(color: str, factor: float = 0.85) -> str:
    """Escurece uma cor hex (para estados hover/active)."""
    color = color.lstrip("#")
    if len(color) != 6:
        return "#" + color
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return "#{:02x}{:02x}{:02x}".format(
        int(r * factor), int(g * factor), int(b * factor)
    )


def hex_rgb(color: str) -> str:
    color = color.lstrip("#")
    if len(color) != 6:
        return "13,110,253"
    return ",".join(str(int(color[i:i + 2], 16)) for i in (0, 2, 4))


def get_appearance(db: Session, empresa_id: int = 1) -> dict:
    a = {
        chave: get_config(db, chave, DEFAULTS[chave], empresa_id) or DEFAULTS[chave]
        for chave in APPEARANCE_KEYS
    }
    a["brand_nome"] = a["brand_nome"] or settings.app_name

    classes = ["sidebar-expand-lg", "bg-body-tertiary"]
    if a["layout_fixo"] == "sim":
        classes.insert(0, "layout-fixed")
    if a["header_fixo"] == "sim":
        classes.append("fixed-header")
    if a["footer_fixo"] == "sim":
        classes.append("fixed-footer")
    if a["sidebar_mini"] == "sim":
        classes.append("sidebar-mini")
    if a["sidebar_colapsada"] == "sim":
        classes.append("sidebar-collapse")
    a["body_class"] = " ".join(classes)

    cor = a["cor_primaria"]
    if cor:
        a["cor_hover"] = hex_darken(cor)
        a["cor_rgb"] = hex_rgb(cor)
    return a


def default_appearance() -> dict:
    a = dict(DEFAULTS)
    a["brand_nome"] = settings.app_name
    a["body_class"] = "layout-fixed sidebar-expand-lg bg-body-tertiary sidebar-mini"
    return a
