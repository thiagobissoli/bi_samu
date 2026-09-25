"""Registro automático de módulos (§38.4).

Fluxo: Manifest -> Registro -> Rotas -> Menu -> Permissões -> Dashboard
O menu é filtrado pelas permissões do usuário (§37.4) e ordenado pelo
campo "order" do manifest.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from fastapi import FastAPI

MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"

_menu: list[dict] = []
_manifests: list[dict] = []


def discover_modules(app: FastAPI) -> None:
    if not MODULES_DIR.is_dir():
        return

    for manifest_path in sorted(MODULES_DIR.glob("*/manifest.json")):
        module_dir = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _manifests.append(manifest)

        # Importa os modelos para registrá-los no metadata (tabelas §36).
        if (module_dir / "models.py").is_file():
            importlib.import_module(f"app.modules.{module_dir.name}.models")

        routes_file = module_dir / "routes.py"
        if routes_file.is_file():
            module = importlib.import_module(f"app.modules.{module_dir.name}.routes")
            router = getattr(module, "router", None)
            if router is not None:
                app.include_router(router)

        for item in manifest.get("menu", []):
            item.setdefault("order", 50)
            _menu.append(item)

    _menu.sort(key=lambda i: (i.get("order", 50), i.get("label", "")))


# Grupos do menu lateral (seções recolhíveis). Cada item de menu do manifest
# escolhe o seu com a chave "group"; item sem grupo fica solto, no topo.
MENU_GRUPOS = {
    "indicadores": {"label": "Indicadores", "icon": "fa-chart-line", "order": 10},
    "qualidade": {"label": "Qualidade", "icon": "fa-shield-heart", "order": 20},
    "dados": {"label": "Dados", "icon": "fa-database", "order": 30},
    "acesso": {"label": "Usuários e Acesso", "icon": "fa-users-gear", "order": 40},
    "sistema": {"label": "Sistema", "icon": "fa-gears", "order": 50},
}


def agrupar_menu(itens: list[dict], caminho: str = "") -> list[dict]:
    """Monta a árvore do menu: itens soltos e grupos com seus filhos.

    Marca como ativo só o item de URL mais específica que casa com o
    caminho atual (senão /ncps e /ncps/painel acenderiam juntos), e abre
    o grupo que o contém. Grupo sem nenhum item visível não aparece.
    """
    candidatos = [i["url"] for i in itens
                  if caminho == i["url"] or caminho.startswith(i["url"].rstrip("/") + "/")]
    ativo = max(candidatos, key=len) if candidatos else None

    soltos, grupos = [], {}
    for item in itens:
        entrada = {**item, "ativo": item["url"] == ativo}
        chave = item.get("group")
        if chave in MENU_GRUPOS:
            grupos.setdefault(chave, []).append(entrada)
        else:
            soltos.append(entrada)

    arvore = [{"tipo": "item", **i} for i in soltos]
    for chave, filhos in sorted(grupos.items(), key=lambda g: MENU_GRUPOS[g[0]]["order"]):
        arvore.append({"tipo": "grupo", "chave": chave, **MENU_GRUPOS[chave],
                       "itens": filhos, "aberto": any(f["ativo"] for f in filhos)})
    return arvore


def get_menu(usuario=None) -> list[dict]:
    """Itens de menu visíveis — filtrados pelas permissões do usuário."""
    if usuario is None:
        return list(_menu)
    permissoes = usuario.permissoes
    return [
        item
        for item in _menu
        if not item.get("permission") or item["permission"] in permissoes
    ]


def get_manifests() -> list[dict]:
    return _manifests
