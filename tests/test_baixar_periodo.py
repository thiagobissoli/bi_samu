"""Download de período longo do vSky em janelas de 25 dias."""

from datetime import date, timedelta

import pytest

from app.modules.download_vsky import baixar_periodo as bp


def test_janelas_de_25_dias_sem_buracos_nem_sobreposicao():
    inicio, fim = date(2023, 9, 26), date(2026, 9, 25)      # 3 anos
    lista = bp.janelas(inicio, fim)
    assert lista[0][0] == inicio and lista[-1][1] == fim
    for ini, fin in lista[:-1]:
        assert (fin - ini).days == 24                         # 25 dias
    for (_, fim_a), (ini_b, _) in zip(lista, lista[1:]):
        assert ini_b == fim_a + timedelta(days=1)
    assert len(lista) == -(-((fim - inicio).days + 1) // 25)  # teto


def test_ultima_janela_pode_ser_menor():
    lista = bp.janelas(date(2026, 1, 1), date(2026, 1, 30))
    assert lista == [(date(2026, 1, 1), date(2026, 1, 25)),
                     (date(2026, 1, 26), date(2026, 1, 30))]


def test_periodo_invalido():
    with pytest.raises(ValueError):
        bp.janelas(date(2026, 2, 1), date(2026, 1, 1))


def test_simular_nao_baixa(capsys, monkeypatch):
    monkeypatch.setattr(bp, "baixar", lambda *a, **k: pytest.fail("baixou"))
    bp.main(["--inicio", "01/01/2026", "--fim", "2026-03-01", "--simular"])
    saida = capsys.readouterr().out
    assert "3 janela(s)" in saida and "26/01/2026 a 19/02/2026" in saida


def test_retomar_pula_janelas_anteriores(capsys):
    bp.main(["--inicio", "01/01/2026", "--fim", "01/03/2026",
             "--a-partir-de", "20/02/2026", "--simular"])
    assert "Período: 20/02/2026 a 01/03/2026" in capsys.readouterr().out
