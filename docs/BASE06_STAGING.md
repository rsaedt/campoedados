# Base 06 — Ambiente real de homologação

## Objetivo

Levar o Campo e Dados da validação em CI para um ambiente persistente, público por HTTPS e preparado para receber webhooks reais.

Arquitetura de homologação:

```text
WhatsApp / Telegram / API
          |
          v
Render — campoedados-staging-api
          |
          +--> PostgreSQL Supabase (dados estruturados)
          |
          +--> Supabase Storage privado (foto, PDF, áudio)
          |
          +--> OpenAI (transcrição/leitura documental)
```

Produção não é criada nesta base. Homologação deve usar projeto Supabase, credenciais, bucket e serviço Render próprios.

## Banco

- `DATABASE_URL`: conexão usada pela API em runtime.
- `MIGRATION_DATABASE_URL`: conexão usada exclusivamente pelo Alembic.
- URLs `postgres://` e `postgresql://` são normalizadas para `postgresql+psycopg://`.
- Porta `6543` é reconhecida como transaction pooler e usa `NullPool` automaticamente.
- Para backend persistente, preferir conexão adequada ao ambiente e manter pool pequeno.

Cada deploy executa:

```bash
alembic upgrade head
python -m app.cli.staging_preflight
python -m app.cli.bootstrap_staging
```

A migration inicial cria o schema completo atual e o catálogo dos módulos:

- `livestock` — Pecuária;
- `feed_mill` — Fábrica de Ração;
- `finance` — Financeiro.

Criar o catálogo NÃO habilita um módulo para cliente algum. Habilitação continua em `organization_modules`.

## Storage de mídia

Em homologação:

```text
CAMPOEDADOS_MEDIA_STORAGE=supabase
CAMPOEDADOS_SUPABASE_STORAGE_BUCKET=campoedados-staging-media
```

O bucket deve ser criado como **privado** no projeto Supabase de homologação.

Os arquivos são gravados por SHA-256:

```text
sha256/ab/cd/<hash>.pdf
```

O banco guarda uma referência do tipo:

```text
supabase://campoedados-staging-media/sha256/ab/cd/<hash>.pdf
```

A chave `SUPABASE_SERVICE_ROLE_KEY` é exclusivamente server-side e nunca deve ir para navegador, mensagem ou repositório.

## Readiness

- `/health`: liveness; informa que o processo HTTP está vivo.
- `/ready`: readiness; verifica banco e configuração obrigatória do storage.

O Blueprint Render usa `/ready` como health check. Se o banco estiver indisponível ou o storage obrigatório estiver mal configurado, a API responde `503` e a nova instância não deve receber tráfego.

## Bootstrap inicial

O bootstrap é idempotente e só roda quando:

```text
CAMPOEDADOS_BOOTSTRAP_ENABLED=true
```

Campos obrigatórios:

```text
CAMPOEDADOS_BOOTSTRAP_ORG_NAME
CAMPOEDADOS_BOOTSTRAP_ORG_SLUG
CAMPOEDADOS_BOOTSTRAP_ADMIN_NAME
CAMPOEDADOS_BOOTSTRAP_ADMIN_EMAIL
CAMPOEDADOS_BOOTSTRAP_ADMIN_TOKEN
CAMPOEDADOS_BOOTSTRAP_UNITS_JSON
CAMPOEDADOS_BOOTSTRAP_MODULES
```

Exemplo de duas unidades:

```json
[
  {"code":"SH7","name":"SH7"},
  {"code":"NSG","name":"NSG"}
]
```

Exemplos válidos de contratação:

```text
feed_mill
finance
livestock
feed_mill,finance
livestock,feed_mill
livestock,finance
livestock,feed_mill,finance
```

O script também cria o primeiro administrador com permissão total SOMENTE nos módulos habilitados.

Opcionalmente, pode criar identidade de canal já no bootstrap usando `CAMPOEDADOS_BOOTSTRAP_CHANNEL_IDENTITIES_JSON`. Caso contrário, identidades podem ser cadastradas pela API administrativa depois do primeiro login/token.

## Render Blueprint

O `render.yaml` cria/prepara o serviço:

```text
campoedados-staging-api
```

Configuração principal:

- Python 3.11;
- plano `starter`;
- região `oregon`;
- `preDeployCommand` com migration + preflight + bootstrap;
- `uvicorn` ouvindo em `$PORT`;
- health check em `/ready`;
- secrets como `sync: false`.

O serviço só deve ser ligado a um projeto Supabase de HOMOLOGAÇÃO. Nunca reutilizar credenciais de produção.

## Ordem de criação do ambiente

1. Criar projeto Supabase exclusivo de homologação.
2. Criar bucket privado `campoedados-staging-media`.
3. Obter connection strings no painel Supabase.
4. Criar o serviço no Render a partir de `render.yaml`.
5. Preencher secrets e variáveis de bootstrap.
6. Primeiro deploy executa migration e bootstrap.
7. Conferir `/health` e `/ready`.
8. Conferir `GET /v1/me` usando o token administrativo do bootstrap.
9. Configurar uma identidade de canal.
10. Conectar primeiro Telegram ou WhatsApp ao webhook público HTTPS.
11. Enviar uma mensagem real e conferir Evento + auditoria.

## Dados de negócio

A Base 06 NÃO injeta estoque, fórmulas ou lançamentos fictícios em homologação.

Isso é proposital. O ambiente nasce estruturalmente real, mas os dados de Fábrica de Ração precisam vir do cadastro/importação homologada. Assim não mascaramos problemas com estoque sintético.

O módulo Pecuária existe no catálogo e no controle de acesso, mas os fluxos pecuários do novo núcleo modular ainda precisam ser implementados/homologados antes de serem usados como operação real.

## Validação CI

O GitHub Actions agora sobe PostgreSQL 16 real e executa:

1. instalação do projeto;
2. `alembic upgrade head`;
3. conferência das tabelas criadas;
4. bootstrap duas vezes para provar idempotência;
5. validação de que apenas os módulos escolhidos ficaram habilitados;
6. suíte completa `pytest` das Bases 01–06.
