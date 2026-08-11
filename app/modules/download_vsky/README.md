# Módulo Download vSky

Integra o sistema ao portal **vSky** (VELP): autentica com as credenciais
configuradas, gera o relatório **"Total de Registros Analítico"** para um
período e importa todas as linhas do XLS para o banco — sem duplicar.

## Funcionamento

1. Um administrador informa em `/download_vsky/config` a URL do portal
   (padrão `https://gestao-es.vskysamu.com.br`), usuário, senha (criptografada
   via ConfigService §39.12) e, opcionalmente, o código do cliente.
2. Na tela principal, o usuário escolhe **data inicial** e **data final** e
   clica em **Gerar e importar**. O módulo então reproduz o fluxo do portal
   (JSF/PrimeFaces):
   - `POST login.jsf` com `ViewState`;
   - clique AJAX no item de menu "Total de Registros Analítico";
   - `POST` do formulário `frm_relatorios` (`bt_gerar_report`) que devolve o XLS.
   Os ids dinâmicos do JSF (`j_idtNN`, `ViewState`) são extraídos das páginas
   a cada execução.
3. O XLS é salvo em `uploads/empresa_<id>/download_vsky/<ano>/<mes>/` e cada
   linha vira um registro em `vsky_registros_analiticos` (61 colunas do
   relatório). **Dedupe:** `linha_hash` = SHA-256 da linha inteira, único por
   empresa — linhas idênticas (no arquivo ou já importadas) são descartadas.
4. Cada execução fica registrada em `vsky_importacoes` com status, total de
   linhas, novas, duplicadas e eventual erro — tudo auditado (§11).

## Rotas

- `GET /download_vsky` — importações + formulário de período (HTML)
- `POST /download_vsky/importar` — gera o relatório no vSky e importa
- `GET /download_vsky/registros` — registros importados (busca + paginação)
- `GET /download_vsky/{id}/arquivo` — baixa o XLS original da importação
- `POST /download_vsky/{id}/delete` — soft delete da importação
- `GET|POST /download_vsky/config` — credenciais/URL do portal
- `GET /download_vsky/api` — importações (JSON, formato padrão §17)
- `POST /download_vsky/api` — importa período (JSON: `data_inicial`, `data_final`)

## Permissões

`download_vsky.listar`, `download_vsky.baixar`, `download_vsky.excluir`,
`download_vsky.configurar` — sincronizadas do `manifest.json`
(o perfil Administrador recebe todas).

## Arquivos principais

| Arquivo | Responsabilidade |
|---------|------------------|
| vsky_client.py | Automação HTTP do portal JSF (login + geração do XLS) |
| prontuario_client.py | Baixa o PDF "Detalhes do Atendimento" de uma ocorrência (reusa o login; navega `consultar_ocorrencia.xhtml`) |
| importer.py | Parse do XLS (xlrd), normalização e hash de linha |
| service.py | Orquestração: gerar → salvar XLS → importar sem duplicar |
| models.py | `VskyImportacao` e `VskyRegistroAnalitico` (61 colunas) |
| repository.py | Consultas por tenant + verificação de hashes em lote |
| routes.py / templates/ | Telas de importação, registros e configuração |
