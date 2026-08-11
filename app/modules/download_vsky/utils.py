"""Utilitários do módulo Download vSky (§35.2)."""


def human_size(tamanho: int) -> str:
    """Formata bytes em unidade legível (B, KB, MB)."""
    if tamanho >= 1024 * 1024:
        return f"{tamanho / (1024 * 1024):.1f} MB"
    if tamanho >= 1024:
        return f"{tamanho / 1024:.1f} KB"
    return f"{tamanho} B"
