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
