"""Download do prontuário PDF de uma ocorrência do vSky.

Reproduz por HTTP (JSF/PrimeFaces) o fluxo da tela "Consultar Ocorrências"
(restrito/cadastro/ocorrencia/consultar_ocorrencia.xhtml): após o login
(reaproveitado do VskyClient), pesquisa pelo número — via POST parcial
AJAX, como o botão Pesquisar faz de verdade — e aciona o botão de PDF da
linha do resultado, recebendo o arquivo em bytes.

Detalhes calibrados contra o portal real (ago/2026):
- O formulário tem selects MÚLTIPLOS (status Finalizado/Cancelada/
  Encerrada): todos os valores selecionados precisam ser reenviados, senão
  a pesquisa devolve "Nenhum Registro".
- A pesquisa só popula a lista via requisição parcial (Faces-Request:
  partial/ajax); o POST completo re-renderiza a página sem resultado.
- O botão de PDF depende do perfil do usuário: perfis com a permissão
  recebem "Ficha de Atendimento Completa"; os demais, "Gerar Detalhes do
  Atendimento" (PRONTUARIO_GATILHOS, em ordem de preferência).
- Ids gerados pelo JSF (ViewState, j_idtNN) são extraídos das próprias
  páginas a cada execução.
"""

from __future__ import annotations

import html as html_lib
import re

from app.modules.download_vsky.constants import (
    CAMPO_NUMERO_OCORRENCIA,
    CONSULTA_OCORRENCIA_PATH,
    PRONTUARIO_GATILHOS,
    PRONTUARIO_TIMEOUT,
)
from app.modules.download_vsky.vsky_client import (
    VskyClient,
    VskyError,
    _first,
    _mensagem_erro,
    _viewstate,
    _viewstate_update,
)

FORM_CONSULTA = "frm_consultar_ocorrencias"


class ProntuarioError(VskyError):
    """Falha ao localizar ou gerar o prontuário PDF no vSky."""


class ProntuarioClient(VskyClient):
    def __init__(self, base_url: str, usuario: str, senha: str):
        super().__init__(base_url, usuario, senha, timeout=PRONTUARIO_TIMEOUT)

    def baixar_prontuario(self, numero: str) -> bytes:
        """Devolve os bytes do PDF do prontuário da ocorrência.

        Requer sessão autenticada (chame login() antes). Levanta
        ProntuarioError com mensagem clara em qualquer falha estrutural.
        """
        numero = str(numero).strip()

        page = self.http.get(CONSULTA_OCORRENCIA_PATH)
        if page.status_code == 404:
            raise ProntuarioError(
                "Tela de consulta de ocorrências não encontrada no portal "
                f"({CONSULTA_OCORRENCIA_PATH}). A navegação do vSky pode "
                "ter mudado.")
        page.raise_for_status()
        html = page.text
        if "it_password" in html:  # sessão caiu -> voltou ao login
            raise ProntuarioError("Sessão do vSky expirada durante a consulta.")

        viewstate = _viewstate(html)
        if viewstate is None:
            raise ProntuarioError("ViewState ausente na tela de consulta.")
        campos = _campos_do_form(html, FORM_CONSULTA)
        if not campos:
            raise ProntuarioError("Formulário de consulta não encontrado.")

        # Número da ocorrência + período inicial limpo (senão a busca por
        # número fica restrita ao período padrão pré-preenchido).
        campos[CAMPO_NUMERO_OCORRENCIA] = [numero]
        for chave in campos:
            if "DataInicial" in chave and chave.endswith("_input"):
                campos[chave] = [""]

        botao_pesquisar = _botao_por_label(html, ("pesquisar", "consultar"))
        if botao_pesquisar is None:
            raise ProntuarioError("Botão de pesquisa não encontrado na consulta.")

        # A pesquisa real é AJAX parcial — só ela popula a lista de
        # resultados no estado da view.
        campos.update({
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": botao_pesquisar,
            "javax.faces.partial.execute": FORM_CONSULTA,
            "javax.faces.partial.render": FORM_CONSULTA,
            botao_pesquisar: botao_pesquisar,
            FORM_CONSULTA: FORM_CONSULTA,
            "javax.faces.ViewState": viewstate,
        })
        resultado = self.http.post(CONSULTA_OCORRENCIA_PATH, data=campos,
                                   headers={"Faces-Request": "partial/ajax"})
        resultado.raise_for_status()
        html_res = html_lib.unescape(resultado.text)
        viewstate = _viewstate_update(resultado.text) or viewstate

        gatilho = None
        for titulo in PRONTUARIO_GATILHOS:
            gatilho = _botao_por_titulo(html_res, titulo)
            if gatilho:
                break
        if gatilho is None:
            if numero not in html_res or "Nenhum Registro" in html_res:
                raise ProntuarioError(
                    f"Ocorrência {numero} não encontrada na consulta do vSky.")
            raise ProntuarioError(
                "Botão de PDF não localizado para a ocorrência "
                f"{numero} — o usuário configurado pode não ter a permissão "
                "no vSky.")

        # Clique no botão do PDF: POST completo com o estado do formulário
        # devolvido pela pesquisa (o PDF vem como attachment).
        campos_pdf = _campos_do_form(html_res, FORM_CONSULTA)
        campos_pdf[CAMPO_NUMERO_OCORRENCIA] = [numero]
        campos_pdf[FORM_CONSULTA] = FORM_CONSULTA
        campos_pdf["javax.faces.ViewState"] = viewstate
        campos_pdf[gatilho] = ""

        pdf = self.http.post(CONSULTA_OCORRENCIA_PATH, data=campos_pdf)
        pdf.raise_for_status()
        tipo = pdf.headers.get("content-type", "")
        if "pdf" in tipo or pdf.content[:5] == b"%PDF-":
            return pdf.content
        raise ProntuarioError(
            _mensagem_erro(pdf.text)
            or "O vSky não devolveu o PDF do prontuário.")


def _campos_do_form(html: str, form_id: str) -> dict[str, list[str] | str]:
    """name -> valores de todos os inputs/selects do formulário.

    Valores são listas: selects múltiplos (ex.: status da ocorrência)
    precisam reenviar TODAS as opções selecionadas — colapsar para um
    único valor faz a pesquisa devolver "Nenhum Registro".
    """
    decoded = html_lib.unescape(html)
    m = re.search(rf'<form[^>]*id="{re.escape(form_id)}".*?</form>',
                  decoded, re.DOTALL | re.IGNORECASE)
    if m is None:
        return {}
    trecho = m.group(0)
    campos: dict[str, list[str] | str] = {}
    for tag in re.finditer(r'<input\b[^>]*>', trecho, re.IGNORECASE):
        nome = _first(r'name="([^"]+)"', tag.group(0))
        if not nome:
            continue
        campos.setdefault(nome, [])
        campos[nome].append(_first(r'value="([^"]*)"', tag.group(0)) or "")
    for sel in re.finditer(r'<select\b[^>]*>.*?</select>', trecho,
                           re.DOTALL | re.IGNORECASE):
        nome = _first(r'name="([^"]+)"', sel.group(0))
        if not nome:
            continue
        opcoes = re.findall(r'<option[^>]*value="([^"]*)"([^>]*)>', sel.group(0))
        marcadas = [v for v, attrs in opcoes if "selected" in attrs]
        campos[nome] = marcadas or ([opcoes[0][0]] if opcoes else [""])
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
