# Envios à SESA

Controle dos documentos que o SAMU envia à SESA todo mês, trimestre ou ano,
conforme a planilha "Processos da qualidade - SESA". A primeira parte
implementada é a das **certidões mensais** (IT.QUA.002.000).

## Telas

| URL | O que faz |
|---|---|
| `/sesa/` | Matriz do ano: cada envio × os 12 meses, com prazo e situação |
| `/sesa/certidoes` | Abre as certidões do mês corrente |
| `/sesa/{chave}/{AAAA-MM}` | Um envio: links dos portais, anexos, leitura dos PDFs, pacote .zip, texto do despacho e registro do envio |
| `/sesa/cadastros` | CNPJ, feriados extras, prazos, canal, destinatários, links e instruções |

## Certidões

Os portais (SEFAZ-ES, Receita/PGFN, Caixa, Prefeitura da Serra e TST) pedem
CAPTCHA ou verificação da Cloudflare. Por isso a emissão continua sendo
feita por uma pessoa. O sistema cuida do resto:

- **Leitura do PDF** (`extrator.py`): lê número, emissão, validade e
  resultado, e confere se o CNPJ é o do SAMU. A comparação é pela raiz, porque
  a certidão da União e a do TST valem para matriz e filiais.
- **Avisos** quando a certidão vence antes do prazo de envio, quando o
  resultado é positivo ou irregular, ou quando o CNPJ é de outra empresa.
- **Reaproveitamento**: uma certidão ainda válida no prazo do mês seguinte
  pode ser usada de novo com um clique, com o mesmo arquivo.
- **Pacote .zip** com os arquivos numerados e **texto do despacho** para
  colar no E-Docs.
- **Registro do envio**, com data e protocolo. Depois do registro, os arquivos
  ficam travados até alguém desfazê-lo.

## Encaminhamentos do SAMU (documento gerado)

O item "Encaminhamento dos Hospitais" do envio de Adversidades tem o botão
**Gerar a partir do vSky**, que leva a `/sesa/encaminhamentos/{AAAA-MM}`.

1. A tela mostra os filtros do relatório 115 do vReport ("Atendimentos por
   Hospital de Destino") para o mês anterior ao envio.
2. A pessoa envia o `Report.xls` (Save → Microsoft Excel).
3. Confere os hospitais: quem entra no documento, o nome e a sigla. A seleção
   fica salva em `sesa_hospitais`.
4. O sistema gera o `.docx` (`encaminhamentos.py`), com uma página por
   hospital no modelo da SESA: tabela de compromisso e memória de cálculo com
   os números por extenso. O documento é anexado ao envio.

Total = recebidos do SAMU; secundário = Inter-hospitalar; primário (APH) =
Pré-hospitalar. O brasão do cabeçalho é enviado em Cadastros SESA.

## Saída de USA (documento gerado)

Item das prestações de contas dos convênios 007 e 008. O botão **Gerar a
partir do vSky** leva a `/sesa/saida-usa/{AAAA-MM}?para={convênio}`.

Diferente dos Encaminhamentos, não há upload: o relatório é calculado dos
registros que o sistema já importa do vSky. Uma **saída** é um empenho que
iniciou deslocamento — a mesma regra do módulo de Indicadores
(`tema_saidas_ambulancia`); daí separa-se USA de USB pela coluna `recurso`.

A tela mostra o resumo (saídas de USA/USB, total, média/dia) e as quebras por
unidade, município, código e dia. O botão gera uma planilha `.xlsx` (uma aba
por quebra) e a anexa ao envio. Período: o mês anterior ao envio.

## Prazos

`prazos.py` tem só funções puras. Um prazo pode ser o n-ésimo dia útil do mês
ou um dia corrido; se o dia corrido cair num dia não útil, vale o dia útil
seguinte. Não contam como dias úteis:

- fins de semana e feriados nacionais;
- Carnaval, Paixão de Cristo e Corpus Christi;
- N. Sra. da Penha (ES);
- as datas em `sesa_feriados_extras`.

A **competência** é o mês do envio, que corresponde às colunas da planilha.

## Permissões

| Permissão | Libera |
|---|---|
| `sesa.visualizar` | ver a matriz e os envios, baixar arquivos |
| `sesa.anexar` | anexar, reaproveitar, corrigir e remover arquivos |
| `sesa.enviar` | registrar ou desfazer o envio |
| `sesa.cadastros` | editar o catálogo |

## Portais pendentes e aviso de vencimento

- **Abrir portais pendentes**: um clique abre, em abas, os portais das
  certidões que ainda não servem para o envio do mês. Entram as que faltam
  sem nenhuma anterior válida para reaproveitar e as que têm pendência. Se o
  navegador bloquear as abas, a tela pede para permitir pop-ups.
- **Aviso de vencimento** (`avisos.py` e `scheduler.py`): todo dia às 7h, e
  2 minutos depois do boot, quem tem `sesa.anexar` recebe no sino e por
  e-mail as certidões que vencem em até `sesa_aviso_vencimento_dias` (7 por
  padrão). O aviso sai uma vez por certidão (tabela
  `sesa_avisos_vencimento`). Se uma certidão nova já foi anexada, a antiga
  não gera aviso. O link do e-mail usa `sesa_endereco_sistema`, preenchido
  na primeira visita às telas da SESA.

A página inicial mostra alertas dos envios atrasados e dos que vencem em
até 5 dias.
