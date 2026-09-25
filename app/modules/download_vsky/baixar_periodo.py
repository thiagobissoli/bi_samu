"""Baixa do vSky um período longo (ex.: 3 anos) em janelas de 25 dias.

O relatório "Total de Registros Analítico" fica pesado e instável para
períodos grandes; por isso o período é quebrado em janelas curtas, e cada
uma é gerada e importada como uma importação normal da tela (aparece em
/download_vsky com status, linhas novas e duplicadas).

Uso (na raiz do projeto, com o venv ativo):

    # últimos 3 anos, de 25 em 25 dias
    python -m app.modules.download_vsky.baixar_periodo --anos 3

    # período explícito
    python -m app.modules.download_vsky.baixar_periodo --inicio 01/01/2023 --fim 31/12/2025

    # só mostra as janelas, sem baixar
    python -m app.modules.download_vsky.baixar_periodo --anos 3 --simular

Pode ser interrompido (Ctrl+C) e rodado de novo: a importação descarta as
linhas já existentes, então repetir uma janela não duplica nada. Para não
repetir o que já foi baixado, use `--a-partir-de` com a data da janela onde
parou (o script imprime essa data a cada janela).

Janela com erro é tentada de novo (`--tentativas`, com espera crescente);
se ainda falhar, o script segue para a próxima e lista as que falharam no
final, com o comando para refazer só elas.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta

from app.modules.download_vsky.constants import DATA_FMT

DIAS_POR_JANELA = 25


def _data(valor: str) -> date:
    for formato in (DATA_FMT, "%Y-%m-%d"):
        try:
            return datetime.strptime(valor.strip(), formato).date()
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"data inválida: {valor!r} (use dd/mm/aaaa ou aaaa-mm-dd)")


def janelas(inicio: date, fim: date, dias: int = DIAS_POR_JANELA):
    """[(início, fim)] consecutivas de `dias` dias cada, cobrindo o período.

    As janelas não se sobrepõem nem deixam buracos; a última termina em
    `fim` e pode ser mais curta.
    """
    if inicio > fim:
        raise ValueError("A data inicial não pode ser posterior à final.")
    if dias < 1:
        raise ValueError("A janela precisa ter pelo menos 1 dia.")
    resultado = []
    atual = inicio
    while atual <= fim:
        ultimo = min(atual + timedelta(days=dias - 1), fim)
        resultado.append((atual, ultimo))
        atual = ultimo + timedelta(days=1)
    return resultado


def _credenciais(db, empresa_id: int) -> dict:
    from app.core.config_service import get_config
    from app.modules.download_vsky.constants import (CONFIG_BASE_URL,
                                                     CONFIG_CLIENTE_ID,
                                                     CONFIG_SENHA,
                                                     CONFIG_USUARIO,
                                                     DEFAULT_BASE_URL)

    cred = {
        "base_url": get_config(db, CONFIG_BASE_URL, DEFAULT_BASE_URL, empresa_id),
        "usuario_vsky": get_config(db, CONFIG_USUARIO, empresa_id=empresa_id),
        "senha_vsky": get_config(db, CONFIG_SENHA, empresa_id=empresa_id),
        "cliente_id": get_config(db, CONFIG_CLIENTE_ID, empresa_id=empresa_id),
    }
    if not (cred["usuario_vsky"] and cred["senha_vsky"]):
        raise SystemExit("Credenciais do vSky não configuradas — "
                         "preencha em /download_vsky/config.")
    return cred


def baixar(inicio: date, fim: date, empresa_id: int = 1,
           dias: int = DIAS_POR_JANELA, tentativas: int = 3,
           pausa: float = 5.0, saida=print) -> dict:
    """Baixa e importa janela por janela. Devolve o resumo."""
    import app.main  # noqa: F401 — schema e modelos registrados
    from app.core.database import SessionLocal
    from app.modules.download_vsky.constants import STATUS_CONCLUIDO
    from app.modules.download_vsky.service import DownloadVskyService

    lista = janelas(inicio, fim, dias)
    resumo = {"janelas": len(lista), "ok": 0, "novas": 0, "atualizadas": 0,
              "duplicadas": 0, "falhas": []}
    db = SessionLocal()
    try:
        cred = _credenciais(db, empresa_id)
        for n, (ini, fin) in enumerate(lista, 1):
            rotulo = (f"[{n}/{len(lista)}] {ini.strftime(DATA_FMT)} a "
                      f"{fin.strftime(DATA_FMT)}")
            for tentativa in range(1, tentativas + 1):
                inicio_t = time.time()
                item = DownloadVskyService(db, empresa_id).importar_periodo(
                    ini.strftime(DATA_FMT), fin.strftime(DATA_FMT), **cred)
                segundos = time.time() - inicio_t
                if item.status == STATUS_CONCLUIDO:
                    resumo["ok"] += 1
                    resumo["novas"] += item.linhas_novas or 0
                    resumo["atualizadas"] += item.linhas_superadas or 0
                    resumo["duplicadas"] += item.linhas_duplicadas or 0
                    saida(f"{rotulo}: {item.total_linhas} linhas — "
                          f"{item.linhas_novas} novas, "
                          f"{item.linhas_superadas} atualizadas, "
                          f"{item.linhas_duplicadas} já existiam "
                          f"({segundos:.0f}s)")
                    break
                saida(f"{rotulo}: ERRO (tentativa {tentativa}/{tentativas}): "
                      f"{item.erro}")
                if tentativa < tentativas:
                    time.sleep(pausa * tentativa * 3)   # espera crescente
            else:
                resumo["falhas"].append((ini, fin))
            if n < len(lista):
                time.sleep(pausa)   # não sobrecarrega o portal
    finally:
        db.close()

    if resumo["ok"]:
        # dados novos: os dashboards deste processo recarregam; o servidor
        # percebe sozinho a mudança no banco na próxima consulta
        from app.modules.indicadores import nucleo
        nucleo.invalidar_cache(empresa_id)
    return resumo


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Baixa um período longo do vSky em janelas de 25 dias.")
    periodo = parser.add_mutually_exclusive_group(required=True)
    periodo.add_argument("--anos", type=float,
                         help="período até hoje, em anos (ex.: 3)")
    periodo.add_argument("--inicio", type=_data, help="data inicial")
    parser.add_argument("--fim", type=_data,
                        help="data final (padrão: hoje)")
    parser.add_argument("--a-partir-de", type=_data, dest="a_partir_de",
                        help="retoma a partir desta data (pula as anteriores)")
    parser.add_argument("--dias", type=int, default=DIAS_POR_JANELA,
                        help=f"dias por janela (padrão: {DIAS_POR_JANELA})")
    parser.add_argument("--tentativas", type=int, default=3,
                        help="tentativas por janela antes de desistir (padrão: 3)")
    parser.add_argument("--pausa", type=float, default=5.0,
                        help="segundos entre janelas (padrão: 5)")
    parser.add_argument("--empresa", type=int, default=1)
    parser.add_argument("--simular", action="store_true",
                        help="só lista as janelas, sem baixar")
    args = parser.parse_args(argv)

    fim = args.fim or date.today()
    inicio = args.inicio or fim - timedelta(days=round(args.anos * 365.25) - 1)
    if args.a_partir_de:
        inicio = max(inicio, args.a_partir_de)
    lista = janelas(inicio, fim, args.dias)

    print(f"Período: {inicio.strftime(DATA_FMT)} a {fim.strftime(DATA_FMT)} — "
          f"{len(lista)} janela(s) de até {args.dias} dias")
    if args.simular:
        for n, (ini, fin) in enumerate(lista, 1):
            print(f"  {n:3d}. {ini.strftime(DATA_FMT)} a {fin.strftime(DATA_FMT)}")
        return

    try:
        resumo = baixar(inicio, fim, args.empresa, args.dias, args.tentativas,
                        args.pausa)
    except KeyboardInterrupt:
        print("\nInterrompido. Rode de novo com --a-partir-de <data da janela "
              "em andamento> para continuar.")
        sys.exit(130)

    print(f"\nConcluído: {resumo['ok']}/{resumo['janelas']} janelas — "
          f"{resumo['novas']} linhas novas, {resumo['atualizadas']} "
          f"atualizadas, {resumo['duplicadas']} já existiam.")
    if resumo["falhas"]:
        print(f"{len(resumo['falhas'])} janela(s) falharam. Para refazer:")
        for ini, fin in resumo["falhas"]:
            print(f"  python -m app.modules.download_vsky.baixar_periodo "
                  f"--inicio {ini.strftime(DATA_FMT)} --fim {fin.strftime(DATA_FMT)}")
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
