"""Diagrama de Ishikawa (espinha de peixe) — geometria e SVG.

A posição de cada elemento é calculada aqui uma única vez e reaproveitada
pela tela (SVG) e pelo PDF (desenho no ReportLab), para que os dois saiam
idênticos.

Layout clássico 6M: espinha horizontal apontando para o efeito, três
categorias acima e três abaixo, cada uma com suas causas em linhas
sublinhadas ligadas à espinha diagonal.
"""

from __future__ import annotations

from html import escape

# Ordem canônica dos 6M — categorias fora desta lista entram ao final
ORDEM_6M = ["Método", "Máquina", "Material",        # braços de cima
            "Mão de obra", "Medida", "Meio ambiente"]  # braços de baixo
ACIMA = ["Método", "Máquina", "Material"]

AZUL = "#1a4b8c"
AZUL_CLARO = "#2f6fd0"
TEXTO = "#212529"

LARGURA = 1080
MARGEM_X = 20
CAIXA_EFEITO_L = 190       # largura da caixa do efeito
ESPACO_CAUSA = 15          # altura de CADA LINHA de texto de causa
LARGURA_CAUSA = 160        # largura útil do texto da causa
TAMANHO_CAUSA = 8.5
ALTURA_MINIMA_BRACO = 118
T_MIN, T_MAX = 0.38, 0.98   # trecho do braço ocupado pelas causas
INCLINACAO = 62            # deslocamento horizontal da diagonal


def _normalizar(espinhas: list[dict]) -> list[tuple[str, list[str]]]:
    """Casa as categorias devolvidas pela IA com os 6M, na ordem canônica."""
    por_nome: dict[str, list[str]] = {}
    for e in espinhas or []:
        cat = str((e or {}).get("categoria") or "").strip()
        causas = [str(c).strip() for c in (e or {}).get("causas") or []
                  if str(c).strip()]
        if not cat or not causas:
            continue
        alvo = next((m for m in ORDEM_6M
                     if m.casefold() == cat.casefold()), cat)
        por_nome.setdefault(alvo, []).extend(causas)

    ordenadas = [(m, por_nome.pop(m)) for m in ORDEM_6M if m in por_nome]
    ordenadas += sorted(por_nome.items())
    return ordenadas


def layout(efeito: str, espinhas: list[dict]) -> dict | None:
    """Coordenadas do diagrama. None quando não há causa nenhuma."""
    grupos = _normalizar(espinhas)
    if not grupos:
        return None

    de_cima = [g for g in grupos if g[0] in ACIMA]
    de_baixo = [g for g in grupos if g[0] not in ACIMA]
    # Sem nada embaixo o desenho fica torto; reequilibra
    while len(de_cima) - len(de_baixo) > 1:
        de_baixo.insert(0, de_cima.pop())
    while len(de_baixo) - len(de_cima) > 1:
        de_cima.append(de_baixo.pop(0))

    def linhas_da_causa(causa: str) -> int:
        return len(_quebrar(causa, LARGURA_CAUSA, TAMANHO_CAUSA))

    def altura_lado(lado):
        # espaço vem do texto renderizado: causa que quebra em duas linhas
        # precisa do dobro, senão colide com a de baixo
        maior = max((sum(linhas_da_causa(c) for c in causas)
                     for _, causas in lado), default=0)
        n_causas = max((len(c) for _, c in lado), default=0)
        return max(ALTURA_MINIMA_BRACO,
                   56 + maior * ESPACO_CAUSA + n_causas * 6)

    alt_cima, alt_baixo = altura_lado(de_cima), altura_lado(de_baixo)
    y_espinha = alt_cima + 20
    altura = y_espinha + alt_baixo + 20

    x_fim = LARGURA - MARGEM_X - CAIXA_EFEITO_L - 10
    x_inicio = MARGEM_X + 30
    util = x_fim - x_inicio

    linhas, textos, caixas = [], [], []

    # espinha principal, com a seta apontando para o efeito
    linhas.append({"x1": x_inicio, "y1": y_espinha, "x2": x_fim,
                   "y2": y_espinha, "largura": 4, "cor": AZUL})

    caixas.append({"x": x_fim + 10, "y": y_espinha - 34,
                   "largura": CAIXA_EFEITO_L, "altura": 68,
                   "titulo": "EFEITO / PROBLEMA",
                   "texto": efeito or "—"})

    def braco(grupos_lado, para_cima: bool):
        if not grupos_lado:
            return
        # Distribui os braços da esquerda para a direita, na ordem dos 6M
        # (Método primeiro), como no diagrama clássico.
        n = len(grupos_lado)
        passo = util / (n + 0.6)
        for i, (categoria, causas) in enumerate(grupos_lado):
            xa = x_fim - passo * (n - i - 0.3)
            sentido = -1 if para_cima else 1
            alt = (alt_cima if para_cima else alt_baixo) - 30
            yb = y_espinha + sentido * alt
            xb = xa - INCLINACAO
            linhas.append({"x1": xa, "y1": y_espinha, "x2": xb, "y2": yb,
                           "largura": 3.5, "cor": AZUL})
            textos.append({"x": xb, "y": yb + (-10 if para_cima else 18),
                           "texto": categoria.upper(), "tamanho": 11,
                           "cor": AZUL_CLARO, "negrito": True,
                           "ancora": "middle"})
            # Causas presas à diagonal, de fora para dentro. O passo é
            # proporcional às linhas de cada texto para não haver colisão.
            blocos = [(c, linhas_da_causa(c)) for c in causas]
            total_linhas = sum(n for _, n in blocos)
            acumulado = 0
            for causa, n_linhas in blocos:
                acumulado += n_linhas
                # Mantém as causas no trecho externo do braço (38%–98%):
                # coladas na espinha elas colidiriam com as do outro lado.
                fracao = (acumulado - n_linhas / 2) / total_linhas
                t = T_MIN + (T_MAX - T_MIN) * fracao
                px = xa + (xb - xa) * t
                py = y_espinha + (yb - y_espinha) * t
                linhas.append({"x1": px - LARGURA_CAUSA - 5, "y1": py,
                               "x2": px, "y2": py, "largura": 1, "cor": TEXTO})
                # texto assentado sobre a linha, subindo conforme quebra
                topo = py - 5 - (n_linhas - 1) * (TAMANHO_CAUSA + 2)
                textos.append({"x": px - LARGURA_CAUSA - 3, "y": topo,
                               "texto": causa, "tamanho": TAMANHO_CAUSA,
                               "cor": TEXTO, "negrito": False,
                               "ancora": "start",
                               "largura_max": LARGURA_CAUSA})

    braco(de_cima, True)
    braco(de_baixo, False)
    return {"largura": LARGURA, "altura": altura, "linhas": linhas,
            "textos": textos, "caixas": caixas, "y_espinha": y_espinha,
            "x_fim": x_fim}


def _quebrar(texto: str, largura_max: float, tamanho: float) -> list[str]:
    """Quebra o texto em linhas que cabem na largura (aproximação)."""
    # Estimativa conservadora: melhor quebrar cedo do que o texto
    # invadir a diagonal do braço.
    por_caractere = tamanho * 0.58
    limite = max(int(largura_max / por_caractere), 8)
    palavras, linhas, atual = texto.split(), [], ""
    for p in palavras:
        teste = f"{atual} {p}".strip()
        if len(teste) <= limite:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas[:3] or [""]


def svg(efeito: str, espinhas: list[dict]) -> str | None:
    """Diagrama pronto para embutir na página."""
    d = layout(efeito, espinhas)
    if d is None:
        return None

    partes = [
        f'<svg viewBox="0 0 {d["largura"]} {d["altura"]}" '
        f'width="100%" style="max-width:{d["largura"]}px" '
        'xmlns="http://www.w3.org/2000/svg" '
        'font-family="system-ui, sans-serif">'
    ]
    for l in d["linhas"]:
        partes.append(
            f'<line x1="{l["x1"]:.1f}" y1="{l["y1"]:.1f}" '
            f'x2="{l["x2"]:.1f}" y2="{l["y2"]:.1f}" '
            f'stroke="{l["cor"]}" stroke-width="{l["largura"]}" '
            'stroke-linecap="round"/>')
    for t in d["textos"]:
        peso = ' font-weight="700"' if t["negrito"] else ""
        linhas_txt = (_quebrar(t["texto"], t["largura_max"], t["tamanho"])
                      if t.get("largura_max") else [t["texto"]])
        for n, linha in enumerate(linhas_txt):
            partes.append(
                f'<text x="{t["x"]:.1f}" y="{t["y"] + n * (t["tamanho"] + 2):.1f}" '
                f'fill="{t["cor"]}" font-size="{t["tamanho"]}"{peso} '
                f'text-anchor="{t["ancora"]}">{escape(linha)}</text>')
    for c in d["caixas"]:
        partes.append(
            f'<rect x="{c["x"]:.1f}" y="{c["y"]:.1f}" width="{c["largura"]}" '
            f'height="{c["altura"]}" fill="none" stroke="{AZUL}" '
            'stroke-width="2" rx="3"/>')
        partes.append(
            f'<text x="{c["x"] + 8:.1f}" y="{c["y"] + 16:.1f}" fill="{AZUL_CLARO}" '
            f'font-size="9" font-weight="700">{escape(c["titulo"])}</text>')
        for n, linha in enumerate(_quebrar(c["texto"], c["largura"] - 16, 9)):
            partes.append(
                f'<text x="{c["x"] + 8:.1f}" y="{c["y"] + 32 + n * 12:.1f}" '
                f'fill="{TEXTO}" font-size="9">{escape(linha)}</text>')
    partes.append("</svg>")
    return "".join(partes)
