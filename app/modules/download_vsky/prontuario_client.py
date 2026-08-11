"""Download do prontuário PDF ("Detalhes do Atendimento") de uma ocorrência.

Reproduz por HTTP (JSF/PrimeFaces) o mesmo caminho que o sistema Desperdicio
faz por Selenium: após o login (reaproveitado do VskyClient), abre a tela
`consultar_ocorrencia.xhtml`, pesquisa pelo número da ocorrência (limpando o
período pré-preenchido) e aciona o botão "Gerar Detalhes do Atendimento",
recebendo o PDF em bytes.

Como no relatório, todos os ids gerados pelo JSF (ViewState, botões
`j_idtNN`) são extraídos das próprias páginas a cada execução — o que muda
aqui é a tela e o gatilho, não a mecânica.
"""

from __future__ import annotations

import html as html_lib
import re

from app.modules.download_vsky.constants import (
    CAMPO_CONSULTA_DATA_INICIAL,
    CAMPO_NUMERO_OCORRENCIA,
    CONSULTA_OCORRENCIA_PATH,
    PRONTUARIO_PDF_LABEL,
    PRONTUARIO_TIMEOUT,
)
from app.modules.download_vsky.vsky_client import (
    VskyClient,
    VskyError,
    _first,
    _menu_source,
    _mensagem_erro,
    _viewstate,
)

FORM_CONSULTA = "frm_consultar_ocorrencias"


class ProntuarioError(VskyError):
    """Falha ao localizar ou gerar o prontuário PDF no vSky."""


class ProntuarioClient(VskyClient):
    def __init__(self, base_url: str, usuario: str, senha: str):
        super().__init__(base_url, usuario, senha, timeout=PRONTUARIO_TIMEOUT)

    def baixar_prontuario(self, numero: str) -> bytes:
        """Devolve os bytes do PDF "Detalhes do Atendimento" da ocorrência.

        Requer sessão autenticada (chame login() antes). Levanta
        ProntuarioError com mensagem clara em qualquer falha estrutural.
        """
        numero = str(numero).strip()

        page = self.http.get(CONSULTA_OCORRENCIA_PATH)
        if page.status_code == 404:
            raise ProntuarioError(
                "Tela de consulta de ocorrências não encontrada no portal "
                "(consultar_ocorrencia.xhtml). A navegação do vSky pode ter "
                "mudado.")
        page.raise_for_status()
        html = page.text
        if "it_password" in html:  # sessão caiu -> voltou ao login
            raise ProntuarioError("Sessão do vSky expirada durante a consulta.")

        viewstate = _viewstate(html)
        if viewstate is None:
            raise ProntuarioError("ViewState ausente na tela de consulta.")
        campos = _campos_do_form(html, FORM_CONSULTA)

        # Preenche o número e limpa o período inicial pré-preenchido (senão a
        # busca por número filtra pelo período padrão e não retorna nada).
        campos[CAMPO_NUMERO_OCORRENCIA] = numero
        for chave in list(campos):
            if "DataInicial" in chave and chave.endswith("_input"):
                campos[chave] = ""
        campos[FORM_CONSULTA] = FORM_CONSULTA
        campos["javax.faces.ViewState"] = viewstate

        botao_pesquisar = _botao_por_label(html, ("pesquisar", "consultar"))
        if botao_pesquisar is None:
            raise ProntuarioError("Botão de pesquisa não encontrado na consulta.")
        campos[botao_pesquisar] = campos.get(botao_pesquisar, "")

        resultado = self.http.post(CONSULTA_OCORRENCIA_PATH, data=campos)
        resultado.raise_for_status()
        html_res = resultado.text
        viewstate = _viewstate(html_res) or viewstate

        gatilho = _menu_source(html_res, PRONTUARIO_PDF_LABEL) \
            or _botao_por_titulo(html_res, PRONTUARIO_PDF_LABEL)
        if gatilho is None:
            if numero not in html_res:
                raise ProntuarioError(
                    f"Ocorrência {numero} não encontrada na consulta do vSky.")
            raise ProntuarioError(
                'Botão "Gerar Detalhes do Atendimento" não localizado para a '
                f"ocorrência {numero}.")

        # Aciona o gatilho de geração — POST completo do formulário devolve o
        # PDF (Content-Disposition: attachment). Preserva o estado do form.
        campos_pdf = _campos_do_form(html_res, FORM_CONSULTA) or campos
        campos_pdf[CAMPO_NUMERO_OCORRENCIA] = numero
        campos_pdf[FORM_CONSULTA] = FORM_CONSULTA
        campos_pdf["javax.faces.ViewState"] = viewstate
        campos_pdf[gatilho] = campos_pdf.get(gatilho, "")

        pdf = self.http.post(CONSULTA_OCORRENCIA_PATH, data=campos_pdf)
        pdf.raise_for_status()
        tipo = pdf.headers.get("content-type", "")
        if "pdf" in tipo or pdf.content[:5] == b"%PDF-":
            return pdf.content
        raise ProntuarioError(
            _mensagem_erro(pdf.text)
            or "O vSky não devolveu o PDF do prontuário.")


def _campos_do_form(html: str, form_id: str) -> dict[str, str]:
    """name -> value de todos os inputs (inclusive hidden) do formulário."""
    decoded = html_lib.unescape(html)
    m = re.search(rf'<form[^>]*id="{re.escape(form_id)}".*?</form>',
                  decoded, re.DOTALL | re.IGNORECASE)
    trecho = m.group(0) if m else decoded
    campos: dict[str, str] = {}
    for tag in re.finditer(r'<input\b[^>]*>', trecho, re.IGNORECASE):
        nome = _first(r'name="([^"]+)"', tag.group(0))
        if not nome:
            continue
        campos[nome] = _first(r'value="([^"]*)"', tag.group(0)) or ""
    # selects: mantém a opção selecionada (ou a primeira)
    for sel in re.finditer(r'<select\b[^>]*>.*?</select>', trecho,
                           re.DOTALL | re.IGNORECASE):
        nome = _first(r'name="([^"]+)"', sel.group(0))
        if not nome:
            continue
        opcoes = re.findall(r'<option[^>]*value="([^"]*)"([^>]*)>', sel.group(0))
        valor = next((v for v, a in opcoes if "selected" in a),
                     opcoes[0][0] if opcoes else "")
        campos[nome] = valor
    return campos


def _botao_por_label(html: str, labels: tuple[str, ...]) -> str | None:
    """Nome do botão/submit cujo id/name/value/texto casa com um dos labels."""
    decoded = html_lib.unescape(html)
    candidatos = []
    # <button ...>texto interno (pode ter <span>)</button>
    for m in re.finditer(r'<button\b([^>]*)>(.*?)</button>', decoded,
                         re.IGNORECASE | re.DOTALL):
        attrs, interno = m.group(1), m.group(2)
        nome = _first(r'name="([^"]+)"', attrs)
        if nome:
            texto = re.sub(r"<[^>]+>", " ", interno)
            candidatos.append((nome, attrs + " " + texto))
    # <input type=submit ...>
    for m in re.finditer(r'<input\b([^>]*)>', decoded, re.IGNORECASE):
        attrs = m.group(1)
        nome = _first(r'name="([^"]+)"', attrs)
        if nome and re.search(r'type="(submit|button)"', attrs, re.IGNORECASE):
            candidatos.append((nome, attrs))
    for nome, haystack in candidatos:
        alvo = haystack.casefold()
        if any(lbl in alvo for lbl in labels):
            return nome
    return None


def _botao_por_titulo(html: str, titulo: str) -> str | None:
    """Nome/id do elemento cujo atributo title casa com `titulo`."""
    decoded = html_lib.unescape(html)
    alvo = titulo.casefold()
    for m in re.finditer(
            r'<[^>]*\btitle="([^"]+)"[^>]*\bid="([^"]+)"', decoded, re.IGNORECASE):
        if alvo in m.group(1).casefold():
            return m.group(2)
    for m in re.finditer(
            r'<[^>]*\bid="([^"]+)"[^>]*\btitle="([^"]+)"', decoded, re.IGNORECASE):
        if alvo in m.group(2).casefold():
            return m.group(1)
    return None
