# Dependências Frontend (Vendor)

Bibliotecas frontend oficiais da plataforma, conforme a [Especificação Base](../../../ESPECIFICACAO-BASE-SAAS.md) (seções 1 e 37.2).

Todos os arquivos são servidos localmente — **nunca utilizar CDN em produção**.

## Versões

| Biblioteca | Versão | Pasta | Uso |
|------------|--------|-------|-----|
| AdminLTE | 4.1.0 | `adminlte/` | Layout administrativo |
| Bootstrap | 5.3.8 | `bootstrap/` | Framework CSS base |
| Font Awesome | 6.7.2 | `fontawesome/` | Ícones (biblioteca única permitida) |
| HTMX | 2.0.10 | `htmx/` | Interatividade server-driven |
| Alpine.js | 3.15.12 | `alpinejs/` | Reatividade leve no frontend |
| jQuery | 3.7.1 | `jquery/` | Somente para plugins do AdminLTE |

## Inclusão no `base.html`

```html
<!-- CSS (no <head>) -->
<link rel="stylesheet" href="{{ url_for('static', path='vendor/fontawesome/css/all.min.css') }}">
<link rel="stylesheet" href="{{ url_for('static', path='vendor/bootstrap/css/bootstrap.min.css') }}">
<link rel="stylesheet" href="{{ url_for('static', path='vendor/adminlte/css/adminlte.min.css') }}">

<!-- JS (antes do </body>) -->
<script src="{{ url_for('static', path='vendor/jquery/jquery.min.js') }}"></script>
<script src="{{ url_for('static', path='vendor/bootstrap/js/bootstrap.bundle.min.js') }}"></script>
<script src="{{ url_for('static', path='vendor/adminlte/js/adminlte.min.js') }}"></script>
<script src="{{ url_for('static', path='vendor/htmx/htmx.min.js') }}"></script>
<script src="{{ url_for('static', path='vendor/alpinejs/alpine.min.js') }}" defer></script>
```

Observações:

- O `bootstrap.bundle.min.js` já inclui o Popper.js — não é necessário incluí-lo separadamente.
- O Alpine.js deve ser carregado com `defer`.
- O AdminLTE 4 usa Bootstrap 5 como base; a ordem de inclusão do CSS acima deve ser mantida.
- Os webfonts do Font Awesome (`fontawesome/webfonts/`) são referenciados por caminho relativo pelo `all.min.css` — as duas pastas devem permanecer juntas.

## Regras (spec §37.2, §35.13, §35.15)

- É proibido utilizar outro framework CSS sem aprovação do projeto.
- Somente Font Awesome para ícones — nunca misturar bibliotecas.
- Nunca alterar diretamente os arquivos desta pasta. Customizações vão em `static/css/global.css` e `static/css/modulo.css`.
- jQuery é permitido exclusivamente para plugins do AdminLTE.

## Atualização

Para atualizar uma biblioteca, baixe o pacote oficial do npm e substitua apenas os artefatos de distribuição (`dist/`), mantendo esta mesma estrutura de pastas. Registre a nova versão na tabela acima.
