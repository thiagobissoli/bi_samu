"""Relatório de Gestão em PDF — gerador único (§35.19).

É a mesma fonte para o botão da tela e para o envio automático por
e-mail: os dois chamam `gerar_pdf()`, então o documento nunca divergem
entre os dois caminhos.

Os gráficos são desenhados com matplotlib a partir das MESMAS
especificações que o Chart.js usa na tela (`chart.labels`,
`chart.datasets`), sem captura de tela — daí o texto sair vetorial e
legível em qualquer zoom.
"""

from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")   # sem display: roda em servidor e em job agendado

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402

MARGEM = 36
RODAPE = 30
PALETA = ["#0d6efd", "#dc3545", "#198754", "#ffc107", "#6f42c1",
          "#fd7e14", "#20c997", "#6c757d", "#0dcaf0", "#d63384"]
HEX_SECAO = {"primary": "#0d6efd", "success": "#198754", "info": "#0dcaf0",
             "warning": "#ffc107", "danger": "#dc3545",
             "secondary": "#6c757d", "dark": "#212529"}
ALTURA_GRAFICO = 210      # pontos reservados a cada gráfico no PDF


def _mmss(valor: float) -> str:
    """Minutos decimais -> mm:ss (eixos dos indicadores de tempo)."""
    if valor is None:
        return ""
    total = int(round(float(valor) * 60))
    return f"{total // 60:02d}:{total % 60:02d}"


def _png_do_grafico(spec: dict, largura_pt: float) -> bytes | None:
    """Renderiza um chart spec do painel como PNG (mesmas cores da tela)."""
    labels = spec.get("labels") or []
    datasets = spec.get("datasets") or []
    if not labels or not datasets:
        return None

    horizontal = bool(spec.get("horizontal"))
    tipo = spec.get("tipo", "bar")
    # 150 dpi: nítido no papel sem inflar o arquivo
    polegadas = largura_pt / 72
    altura = ALTURA_GRAFICO / 72
    fig, ax = plt.subplots(figsize=(polegadas, altura), dpi=150)

    series = [ds for ds in datasets if any(v is not None for v in ds["data"])]
    if not series:
        plt.close(fig)
        return None

    posicoes = range(len(labels))
    if tipo == "line":
        for i, ds in enumerate(series):
            cor = ds.get("color") or PALETA[i % len(PALETA)]
            ax.plot(list(posicoes), ds["data"], marker="o", markersize=2.5,
                    linewidth=1.6, color=cor, label=ds.get("label") or "")
    else:
        n = len(series)
        largura_barra = 0.8 / n
        for i, ds in enumerate(series):
            desloc = (i - (n - 1) / 2) * largura_barra
            cores = ds.get("colors") or (ds.get("color")
                                         or PALETA[i % len(PALETA)])
            base = [p + desloc for p in posicoes]
            if horizontal:
                ax.barh(base, ds["data"], height=largura_barra, color=cores,
                        label=ds.get("label") or "")
            else:
                ax.bar(base, ds["data"], width=largura_barra, color=cores,
                       label=ds.get("label") or "")

    eixo_cat = ax.yaxis if horizontal else ax.xaxis
    eixo_val = ax.xaxis if horizontal else ax.yaxis
    (ax.set_yticks if horizontal else ax.set_xticks)(list(posicoes))
    rot = 0 if horizontal else (45 if len(labels) > 6 else 0)
    (ax.set_yticklabels if horizontal else ax.set_xticklabels)(
        [str(x) for x in labels], rotation=rot, fontsize=5.5,
        ha="right" if rot else "center")
    eixo_val.set_tick_params(labelsize=5.5)

    if spec.get("unidade_y") == "min":
        eixo_val.set_major_formatter(FuncFormatter(lambda v, _: _mmss(v)))
    if spec.get("max_y"):
        (ax.set_xlim if horizontal else ax.set_ylim)(0, spec["max_y"])
    elif tipo != "line":
        # barras partem do zero (comparação de volume); linhas mantêm a
        # escala ajustada à faixa, como na tela
        if horizontal:
            ax.set_xlim(left=0)
        else:
            ax.set_ylim(bottom=0)

    ax.grid(axis="x" if horizontal else "y", linewidth=.4, alpha=.35)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    if len(series) > 1:
        ax.legend(fontsize=5.5, frameon=False, ncol=min(len(series), 4),
                  loc="upper center", bbox_to_anchor=(0.5, 1.16))
    eixo_cat.set_tick_params(length=0)
    fig.tight_layout(pad=0.4)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


class _Documento:
    """Cursor de escrita no PDF, com quebra de página automática."""

    def __init__(self, pdf: rl_canvas.Canvas, largura: float, altura: float):
        self.pdf, self.largura, self.altura = pdf, largura, altura
        self.util = largura - 2 * MARGEM
        self.y = altura - MARGEM

    def espaco(self, necessario: float) -> None:
        if self.y - necessario < RODAPE:
            self.pdf.showPage()
            self.y = self.altura - MARGEM

    def texto(self, txt: str, tamanho: float = 9, negrito: bool = False,
              cor: str = "#212529", recuo: float = 0) -> None:
        self.pdf.setFont("Helvetica-Bold" if negrito else "Helvetica", tamanho)
        self.pdf.setFillColor(colors.HexColor(cor))
        for linha in _quebrar(self.pdf, txt, self.util - recuo, tamanho,
                              negrito):
            self.espaco(tamanho + 3)
            self.y -= tamanho + 2
            self.pdf.drawString(MARGEM + recuo, self.y, linha)


def _quebrar(pdf, texto: str, largura: float, tamanho: float,
             negrito: bool) -> list[str]:
    """Divide o texto em linhas que caibam na largura disponível."""
    fonte = "Helvetica-Bold" if negrito else "Helvetica"
    linhas, atual = [], ""
    for palavra in str(texto).split():
        teste = f"{atual} {palavra}".strip()
        if pdf.stringWidth(teste, fonte, tamanho) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas or [""]


def gerar_pdf(dados: dict, gerado_em: datetime | None = None) -> bytes:
    """Monta o Relatório de Gestão a partir do payload de `montar()`."""
    gerado_em = gerado_em or datetime.now()
    buf = io.BytesIO()
    largura, altura = A4
    pdf = rl_canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle("Relatório de Gestão")
    doc = _Documento(pdf, largura, altura)

    semana = dados.get("semana") or "—"
    periodo = dados.get("semana_periodo") or ""
    secoes = dados.get("secoes") or []
    assinatura = (f"Relatório de Gestão · semana {semana} · gerado em "
                  f"{gerado_em.strftime('%d/%m/%Y às %H:%M')}")

    # ---------------------------------------------------------- capa
    pdf.setFillColor(colors.HexColor("#212529"))
    pdf.rect(0, altura - 150, largura, 150, stroke=0, fill=1)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 26)
    pdf.drawString(MARGEM, altura - 76, "Relatório de Gestão")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(MARGEM, altura - 100,
                   "Painel de Gestão · indicadores operacionais")

    doc.y = altura - 210
    doc.texto("Período de referência", 11, negrito=True)
    doc.texto(f"Última semana completa: {semana}"
              + (f"  ({periodo})" if periodo else ""))
    doc.texto("Evolução dos gráficos de linha: últimos 12 meses")
    doc.texto("Tempo resposta considera apenas a 1ª ambulância a chegar "
              "na ocorrência.")
    doc.y -= 18
    doc.texto("Conteúdo", 11, negrito=True)
    for i, secao in enumerate(secoes, 1):
        doc.espaco(16)
        doc.y -= 15
        pdf.setFillColor(colors.HexColor(
            HEX_SECAO.get(secao.get("cor"), "#6c757d")))
        pdf.rect(MARGEM, doc.y - 1, 8, 8, stroke=0, fill=1)
        pdf.setFillColor(colors.HexColor("#212529"))
        pdf.setFont("Helvetica", 9)
        pdf.drawString(MARGEM + 16, doc.y, f"{i}.  {secao.get('titulo', '')}")

    # -------------------------------------------------------- seções
    for secao in secoes:
        pdf.showPage()
        doc.y = altura - MARGEM
        cor = HEX_SECAO.get(secao.get("cor"), "#6c757d")

        doc.y -= 24
        pdf.setFillColor(colors.HexColor(cor))
        pdf.rect(MARGEM, doc.y, doc.util, 24, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(MARGEM + 8, doc.y + 8, secao.get("titulo", ""))
        doc.y -= 6
        if secao.get("nota"):
            doc.texto(secao["nota"], 8, cor="#6e6e6e")
        doc.y -= 6

        for bloco in secao.get("blocos") or []:
            chart = bloco.get("chart") or {}
            kpis = bloco.get("kpis") or []
            png = _png_do_grafico(chart, doc.util)
            altura_img = ALTURA_GRAFICO if png else 0
            doc.espaco(20 + (46 if kpis else 0) + altura_img + 10)

            doc.texto(chart.get("titulo", ""), 10, negrito=True)
            doc.y -= 4

            if kpis:
                largura_kpi = doc.util / len(kpis)
                topo = doc.y
                for i, kpi in enumerate(kpis):
                    x = MARGEM + i * largura_kpi
                    pdf.setStrokeColor(colors.HexColor(cor))
                    pdf.setLineWidth(1)
                    pdf.roundRect(x + 2, topo - 42, largura_kpi - 4, 40,
                                  3, stroke=1, fill=0)
                    centro = x + largura_kpi / 2
                    pdf.setFillColor(colors.HexColor(cor))
                    pdf.setFont("Helvetica-Bold", 13)
                    pdf.drawCentredString(centro, topo - 20,
                                          str(kpi.get("valor", "")))
                    pdf.setFillColor(colors.HexColor("#212529"))
                    pdf.setFont("Helvetica", 6.5)
                    pdf.drawCentredString(centro, topo - 30, _cortar(
                        pdf, kpi.get("label", ""), largura_kpi - 8, 6.5))
                    pdf.setFillColor(colors.HexColor("#828282"))
                    pdf.setFont("Helvetica", 5.5)
                    pdf.drawCentredString(centro, topo - 38, _cortar(
                        pdf, kpi.get("sub", ""), largura_kpi - 8, 5.5))
                doc.y = topo - 46

            if png:
                imagem = ImageReader(io.BytesIO(png))
                iw, ih = imagem.getSize()
                larg_img = doc.util
                alt_img = ih * larg_img / iw
                if alt_img > ALTURA_GRAFICO:
                    alt_img = ALTURA_GRAFICO
                    larg_img = iw * alt_img / ih
                pdf.drawImage(imagem, MARGEM, doc.y - alt_img,
                              width=larg_img, height=alt_img)
                doc.y -= alt_img + 10
            else:
                doc.texto("(sem dados no período)", 8, cor="#828282")

    # -------------------------------------------------------- rodapés
    pdf.save()
    return _com_rodapes(buf.getvalue(), assinatura)


def _cortar(pdf, texto: str, largura: float, tamanho: float) -> str:
    """Trunca com reticências o que não couber na largura."""
    texto = str(texto or "")
    if pdf.stringWidth(texto, "Helvetica", tamanho) <= largura:
        return texto
    while texto and pdf.stringWidth(texto + "…", "Helvetica",
                                    tamanho) > largura:
        texto = texto[:-1]
    return texto + "…" if texto else ""


def _com_rodapes(pdf_bytes: bytes, assinatura: str) -> bytes:
    """Escreve 'assinatura + pág. X/N' em todas as páginas.

    Só é possível depois de fechar o documento, quando o total de
    páginas é conhecido.
    """
    from pypdf import PdfReader, PdfWriter

    leitor = PdfReader(io.BytesIO(pdf_bytes))
    total = len(leitor.pages)
    escritor = PdfWriter()
    for numero, pagina in enumerate(leitor.pages, 1):
        largura = float(pagina.mediabox.width)
        selo = io.BytesIO()
        c = rl_canvas.Canvas(selo, pagesize=(largura,
                                             float(pagina.mediabox.height)))
        c.setFont("Helvetica", 7.5)
        c.setFillColor(colors.HexColor("#8c8c8c"))
        c.drawString(MARGEM, 16, assinatura)
        c.drawRightString(largura - MARGEM, 16, f"Pág. {numero}/{total}")
        c.save()
        selo.seek(0)
        pagina.merge_page(PdfReader(selo).pages[0])
        escritor.add_page(pagina)
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()
