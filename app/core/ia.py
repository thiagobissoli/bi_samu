"""Cliente de IA multi-provedor (§39).

Interface única sobre OpenAI, Anthropic e Ollama (local). A escolha e as
credenciais ficam em Configurações (§22):

    ia_provedor   openai | anthropic | ollama
    ia_modelo     ex.: gpt-4o-mini, claude-sonnet-4-5, llama3.1
    ia_api_key    criptografada (§39.29) — não usada pelo Ollama
    ia_base_url   endpoint do Ollama (padrão http://localhost:11434)

Usa httpx direto, sem SDKs: são três chamadas HTTP simples e assim o
sistema não ganha dependências novas nem fica preso a versões de SDK.

PRIVACIDADE: openai e anthropic enviam o conteúdo para fora da rede.
Quando o texto contiver dados de paciente, use o Ollama (local) ou
anonimize antes — quem chama é responsável por isso (ver
`anonimizar_texto`).
"""

from __future__ import annotations

import json
import re

import httpx
from sqlalchemy.orm import Session

from app.core.config_service import get_config

CONFIG_PROVEDOR = "ia_provedor"
CONFIG_MODELO = "ia_modelo"
CONFIG_API_KEY = "ia_api_key"          # "key" -> criptografada (§39.29)
CONFIG_BASE_URL = "ia_base_url"

PROVEDORES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "ollama": "Ollama (local)",
}
MODELOS_SUGERIDOS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
    "ollama": "llama3.1",
}
OLLAMA_PADRAO = "http://localhost:11434"
TIMEOUT = 180.0


class IAError(RuntimeError):
    """Falha ao consultar o provedor de IA (mensagem pronta para a tela)."""


def configuracao(db: Session, empresa_id: int = 1) -> dict:
    """Provedor, modelo e endpoint configurados (sem expor a chave)."""
    provedor = (get_config(db, CONFIG_PROVEDOR, empresa_id=empresa_id) or "").strip()
    modelo = (get_config(db, CONFIG_MODELO, empresa_id=empresa_id) or "").strip()
    chave = get_config(db, CONFIG_API_KEY, empresa_id=empresa_id)
    base_url = (get_config(db, CONFIG_BASE_URL, empresa_id=empresa_id)
                or OLLAMA_PADRAO).strip()
    return {
        "provedor": provedor,
        "modelo": modelo or MODELOS_SUGERIDOS.get(provedor, ""),
        "base_url": base_url,
        "chave_definida": bool(chave),
        "local": provedor == "ollama",
        # ollama não exige chave; os demais sim
        "pronto": bool(provedor and (provedor == "ollama" or chave)),
    }


def gerar(db: Session, prompt: str, sistema: str = "",
          empresa_id: int = 1, json_esperado: bool = False) -> str:
    """Envia o prompt ao provedor configurado e devolve o texto da resposta."""
    cfg = configuracao(db, empresa_id)
    if not cfg["provedor"]:
        raise IAError("Nenhum provedor de IA configurado — escolha um em "
                      "Investigação de Eventos > Configuração da IA.")
    if not cfg["pronto"]:
        raise IAError(f"A chave de API do provedor {PROVEDORES.get(cfg['provedor'], cfg['provedor'])} "
                      "não está configurada.")
    chave = get_config(db, CONFIG_API_KEY, empresa_id=empresa_id) or ""

    try:
        if cfg["provedor"] == "openai":
            return _openai(cfg, chave, prompt, sistema, json_esperado)
        if cfg["provedor"] == "anthropic":
            return _anthropic(cfg, chave, prompt, sistema)
        if cfg["provedor"] == "ollama":
            return _ollama(cfg, prompt, sistema, json_esperado)
    except httpx.TimeoutException as exc:
        raise IAError(f"O provedor não respondeu em {int(TIMEOUT)}s. "
                      "Tente um modelo menor ou aumente o tempo.") from exc
    except httpx.HTTPStatusError as exc:
        raise IAError(_erro_http(exc)) from exc
    except httpx.HTTPError as exc:
        raise IAError(f"Falha de rede ao consultar a IA: {exc}") from exc
    raise IAError(f"Provedor desconhecido: {cfg['provedor']}")


def _erro_http(exc: httpx.HTTPStatusError) -> str:
    codigo = exc.response.status_code
    detalhe = ""
    try:
        corpo = exc.response.json()
        detalhe = (corpo.get("error", {}).get("message")
                   if isinstance(corpo.get("error"), dict)
                   else corpo.get("error") or corpo.get("message") or "")
    except Exception:  # noqa: BLE001 — corpo não-JSON
        detalhe = exc.response.text[:200]
    if codigo in (401, 403):
        return f"Credencial da IA recusada ({codigo}). {detalhe}"
    if codigo == 404:
        return f"Modelo ou endpoint não encontrado ({codigo}). {detalhe}"
    if codigo == 429:
        return f"Limite de uso do provedor atingido ({codigo}). {detalhe}"
    return f"Erro {codigo} do provedor de IA. {detalhe}"


def _openai(cfg: dict, chave: str, prompt: str, sistema: str,
            json_esperado: bool) -> str:
    corpo = {
        "model": cfg["modelo"],
        "messages": ([{"role": "system", "content": sistema}] if sistema else [])
                    + [{"role": "user", "content": prompt}],
    }
    if json_esperado:
        corpo["response_format"] = {"type": "json_object"}
    with httpx.Client(timeout=TIMEOUT) as http:
        resp = http.post("https://api.openai.com/v1/chat/completions",
                         json=corpo,
                         headers={"Authorization": f"Bearer {chave}"})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _anthropic(cfg: dict, chave: str, prompt: str, sistema: str) -> str:
    corpo = {
        "model": cfg["modelo"],
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    if sistema:
        corpo["system"] = sistema
    with httpx.Client(timeout=TIMEOUT) as http:
        resp = http.post("https://api.anthropic.com/v1/messages", json=corpo,
                         headers={"x-api-key": chave,
                                  "anthropic-version": "2023-06-01"})
        resp.raise_for_status()
        partes = [b.get("text", "") for b in resp.json().get("content", [])
                  if b.get("type") == "text"]
        return "\n".join(partes)


def _ollama(cfg: dict, prompt: str, sistema: str, json_esperado: bool) -> str:
    corpo = {
        "model": cfg["modelo"],
        "prompt": prompt,
        "stream": False,
    }
    if sistema:
        corpo["system"] = sistema
    if json_esperado:
        corpo["format"] = "json"
    base = cfg["base_url"].rstrip("/")
    with httpx.Client(timeout=TIMEOUT) as http:
        resp = http.post(f"{base}/api/generate", json=corpo)
        resp.raise_for_status()
        dados = resp.json()
        # Modelos de raciocínio (qwen3, deepseek-r1 etc.) devolvem o
        # conteúdo em `thinking` e deixam `response` vazio.
        return dados.get("response") or dados.get("thinking") or ""


def extrair_json(texto: str) -> dict | None:
    """Recupera o objeto JSON da resposta, tolerando cercas de markdown."""
    if not texto:
        return None
    texto = texto.strip()
    cerca = re.search(r"```(?:json)?\s*(.+?)```", texto, re.DOTALL)
    if cerca:
        texto = cerca.group(1).strip()
    try:
        dados = json.loads(texto)
        return dados if isinstance(dados, dict) else None
    except json.JSONDecodeError:
        pass
    # último recurso: maior bloco entre chaves
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio >= 0 and fim > inicio:
        try:
            dados = json.loads(texto[inicio:fim + 1])
            return dados if isinstance(dados, dict) else None
        except json.JSONDecodeError:
            return None
    return None


# ------------------------------------------------------------ privacidade

_RE_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_RE_TELEFONE = re.compile(r"(?:\(\d{2}\)\s?|\b\d{2}\s)?9?\d{4}[-\s]?\d{4}\b")
_RE_CNS = re.compile(r"\b\d{15}\b")


def anonimizar_texto(texto: str, nomes: list[str] | None = None) -> str:
    """Remove identificadores diretos do paciente antes de enviar à IA.

    Cobre CPF, CNS, telefone e os nomes informados (paciente,
    solicitante). Não é anonimização forte — endereços e narrativas
    ainda podem identificar alguém —, por isso a tela recomenda o
    provedor local para o texto integral do prontuário.
    """
    if not texto:
        return texto
    for nome in nomes or []:
        nome = (nome or "").strip()
        if len(nome) < 4:
            continue
        for parte in [nome] + [p for p in nome.split() if len(p) > 3]:
            texto = re.sub(re.escape(parte), "[NOME]", texto,
                           flags=re.IGNORECASE)
    texto = _RE_CPF.sub("[CPF]", texto)
    texto = _RE_CNS.sub("[CNS]", texto)
    texto = _RE_TELEFONE.sub("[TELEFONE]", texto)
    return texto
