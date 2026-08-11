"""Cliente HTTP do portal vSky (JSF/PrimeFaces).

Automatiza o fluxo do navegador:

1. GET  /vskymanagement/login.jsf            -> ViewState + nomes dos campos
2. POST /vskymanagement/login.jsf            -> autentica (cookie JSESSIONID)
3. GET  /vskymanagement/restrito/principal_relatorio.xhtml
4. POST AJAX (menu)  "Total de Registros Analítico" -> renderiza o modal
5. POST completo (frm_relatorios, bt_gerar_report)  -> devolve o XLS

Todos os ids gerados pelo JSF (j_idtNN, ViewState) são extraídos das
próprias páginas a cada execução, para resistir a redeploys do portal.
"""

from __future__ import annotations

import html as html_lib
import re

import httpx

from app.modules.download_vsky.constants import HTTP_TIMEOUT, RELATORIO_MENU_LABEL
from app.modules.download_vsky.validators import normalizar_base_url

LOGIN_PATH = "/vskymanagement/login.jsf"
RELATORIO_PATH = "/vskymanagement/restrito/principal_relatorio.xhtml"

FORM_RELATORIO = "frm_relatorios"
CAMPO_CLIENTE = "frm_relatorios:somCliente_input"
CAMPO_DATA_INICIAL = "frm_relatorios:itDataInicial_input"
CAMPO_DATA_FINAL = "frm_relatorios:itDataFinal_input"
BOTAO_GERAR = "frm_relatorios:bt_gerar_report"


class VskyError(RuntimeError):
    """Falha de comunicação/autenticação/geração no portal vSky."""


class VskyClient:
    def __init__(self, base_url: str, usuario: str, senha: str,
                 timeout: int = HTTP_TIMEOUT):
        # Aceita URL com caminho (ex.: .../vskymanagement/login.xhtml) —
        # só esquema://host é usado; os caminhos são deste cliente.
        self.base_url = normalizar_base_url(base_url)
        self.usuario = usuario
        self.senha = senha
        self.http = httpx.Client(base_url=self.base_url, timeout=timeout,
                                 follow_redirects=True)

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "VskyClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ login

    def login(self) -> None:
        page = self.http.get(LOGIN_PATH)
        page.raise_for_status()
        html = page.text

        form_id = _first(r'<form[^>]*id="([^"]+)"[^>]*class="[^"]*login-form', html) \
            or _first(r'<form[^>]*id="([^"]+)"', html)
        campo_usuario = _first(r'<input[^>]*id="(it_username)"', html) or "it_username"
        campo_senha = _first(r'<input[^>]*id="(it_password)"', html) or "it_password"
        botao = _first(r'<input[^>]*type="submit"[^>]*name="([^"]+)"', html)
        viewstate = _viewstate(html)
        if not (form_id and botao and viewstate):
            raise VskyError("Página de login do vSky em formato inesperado.")

        resp = self.http.post(LOGIN_PATH, data={
            form_id: form_id,
            campo_usuario: self.usuario,
            campo_senha: self.senha,
            botao: "Entrar",
            "javax.faces.ViewState": viewstate,
        })
        resp.raise_for_status()
        # Login com sucesso redireciona para a área restrita;
        # com falha, devolve a própria página de login.
        if "login-form" in resp.text or "it_password" in resp.text:
            raise VskyError("Autenticação no vSky recusada — confira usuário e senha.")

    # ------------------------------------------------- relatório analítico

    def gerar_total_registros_analitico(
        self, data_inicial: str, data_final: str, cliente_id: str | None = None,
    ) -> bytes:
        """Gera o relatório (datas em dd/mm/aaaa) e devolve os bytes do XLS."""
        page = self.http.get(RELATORIO_PATH)
        page.raise_for_status()
        html = page.text
        if "it_password" in html:  # sessão caiu -> voltou para o login
            raise VskyError("Sessão do vSky expirada durante a navegação.")

        menu_id = _menu_source(html, RELATORIO_MENU_LABEL)
        if menu_id is None:
            raise VskyError(
                f'Item de menu "{RELATORIO_MENU_LABEL}" não encontrado no vSky.')
        viewstate = _viewstate(html)
        if viewstate is None:
            raise VskyError("ViewState ausente na página de relatórios do vSky.")

        # Clique AJAX no item de menu — renderiza o modal em frm_relatorios.
        ajax = self.http.post(RELATORIO_PATH, data={
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": menu_id,
            "javax.faces.partial.execute": menu_id,
            "javax.faces.partial.render": FORM_RELATORIO,
            menu_id: menu_id,
            "menu": "menu",
            "javax.faces.ViewState": viewstate,
        }, headers={"Faces-Request": "partial/ajax",
                    "X-Requested-With": "XMLHttpRequest"})
        ajax.raise_for_status()
        parcial = ajax.text
        viewstate = _viewstate_update(parcial) or viewstate
        modal = _update_cdata(parcial, FORM_RELATORIO) or parcial

        data = {
            FORM_RELATORIO: FORM_RELATORIO,
            f"{FORM_RELATORIO}:ih_focus": "",
            f"{FORM_RELATORIO}:somCliente_focus": "",
            CAMPO_CLIENTE: cliente_id or _cliente_selecionado(modal) or "",
            CAMPO_DATA_INICIAL: data_inicial,
            CAMPO_DATA_FINAL: data_final,
            BOTAO_GERAR: "",
            "javax.faces.ViewState": viewstate,
        }
        resp = self.http.post(RELATORIO_PATH, data=data)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "html" in content_type or "xml" in content_type:
            raise VskyError(_mensagem_erro(resp.text)
                            or "O vSky não devolveu o arquivo XLS.")
        return resp.content


# ------------------------------------------------------------------ parsing

def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else None


def _viewstate(html: str) -> str | None:
    return _first(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', html)


def _viewstate_update(partial_xml: str) -> str | None:
    m = re.search(
        r'<update id="[^"]*ViewState[^"]*"><!\[CDATA\[(.*?)\]\]></update>',
        partial_xml, re.DOTALL)
    return m.group(1) if m else None


def _update_cdata(partial_xml: str, component_id: str) -> str | None:
    m = re.search(
        rf'<update id="{re.escape(component_id)}"><!\[CDATA\[(.*?)\]\]></update>',
        partial_xml, re.DOTALL)
    return m.group(1) if m else None


def _menu_source(html: str, label: str) -> str | None:
    """Extrai o id JSF (j_idtNN) do item de menu com o texto `label`."""
    decoded = html_lib.unescape(html)
    for m in re.finditer(
            r'PrimeFaces\.ab\(\{s:"([\w:]+)"[^)]*\)[^>]*>(?:<[^>]+>)*\s*([^<]+)',
            decoded):
        if label.casefold() in m.group(2).casefold():
            return m.group(1)
    return None


def _cliente_selecionado(html: str) -> str | None:
    """Valor selecionado (ou único) do select de cliente no modal."""
    decoded = html_lib.unescape(html)
    sel = re.search(
        rf'<select[^>]*id="{re.escape(CAMPO_CLIENTE)}".*?</select>',
        decoded, re.DOTALL)
    if sel is None:
        return None
    options = re.findall(r'<option[^>]*value="([^"]*)"([^>]*)>', sel.group(0))
    for value, attrs in options:
        if "selected" in attrs:
            return value
    return options[0][0] if options else None


def _mensagem_erro(html: str) -> str | None:
    m = re.search(r'ui-messages?-(?:error|warn)-(?:detail|summary)[^>]*>([^<]+)<',
                  html)
    return html_lib.unescape(m.group(1)).strip() if m else None
