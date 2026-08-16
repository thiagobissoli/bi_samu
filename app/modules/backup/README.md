# Módulo Backup

Cópia de segurança do banco de dados. O sistema guarda os registros
importados do vSky (mais de 400 mil), os prontuários baixados, os relatórios
RAC aprovados e as configurações — inclusive as credenciais do portal. Uma
falha de disco sem cópia levaria tudo.

## O que faz

- `mysqldump` comprimido em gzip (ou cópia consistente do SQLite, quando o
  banco é SQLite), gravado numa pasta configurável.
- Agendamento diário na hora escolhida (APScheduler), restaurado no start.
- Retenção: mantém as N cópias mais recentes e apaga o excedente.
- Download da cópia pela tela, com o nome resolvido dentro da pasta
  (nome com `..` é recusado).

## Estrutura (§35.2)

| Arquivo | Responsabilidade |
|---------|------------------|
| service.py | Geração da cópia, listagem, expurgo, caminho seguro |
| scheduler.py | Job diário (APScheduler) e sincronização com a configuração |
| routes.py | Endpoints |
| constants.py | Chaves de configuração e padrões |
| permissions.py | `backup.visualizar`, `backup.executar` |
| manifest.json | Manifesto do módulo (§38.3) |

## Rotas

- `GET /backup/` — tela (agendamento + cópias existentes)
- `POST /backup/config` — salva agendamento, retenção e pasta
- `POST /backup/executar` — gera uma cópia agora
- `GET /backup/baixar?nome=` — baixa uma cópia
- `GET /backup/api` — situação em JSON (formato §17)

## Configuração

| Chave | Padrão | Para que serve |
|-------|--------|----------------|
| `backup_ativo` | desligado | Liga a cópia diária |
| `backup_hora` | `02:00` | Hora da cópia |
| `backup_manter` | `14` | Quantas cópias guardar |
| `backup_diretorio` | `uploads/backups` | Pasta de destino |

Guardar num disco diferente do banco protege contra falha de hardware.

## Restaurar

```
gunzip < samu-AAAAMMDD-HHMMSS.sql.gz | mysql -u root -p samu
```

Para restaurar num banco novo, crie-o antes
(`CREATE DATABASE samu CHARACTER SET utf8mb4;`).

## Detalhes que não são óbvios

- **A senha nunca vai na linha de comando.** Argumento de processo é visível
  a qualquer usuário da máquina (`ps aux`); a senha segue por `MYSQL_PWD`.
- **`--set-gtid-purged=OFF` é obrigatório.** Sem ele o dump carrega o GTID do
  servidor e a restauração falha justamente no caso mais provável — recuperar
  na mesma instância: *"@@GLOBAL.GTID_PURGED cannot be changed"*. MariaDB não
  conhece a opção, então o dump é repetido sem ela.
- **`--single-transaction`** evita travar as tabelas durante a cópia, que leva
  cerca de 15 s para uma base de ~460 MB (66 MB comprimidos).
- **Teste a restauração periodicamente.** Cópia nunca testada não é cópia.
