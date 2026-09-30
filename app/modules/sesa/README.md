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

A página inicial mostra alertas dos envios atrasados e dos que vencem em
até 5 dias.
