# Base 06 / 06.1 / 06.2 / 06.3 — Ambiente real de homologação

## Objetivo

Levar o Campo e Dados para um ambiente persistente, público por HTTPS e preparado para receber webhooks reais, sem transformar dados de cliente em configuração do servidor.

Arquitetura:

```text
WhatsApp / Telegram / API
          |
          v
Render — campoedados-staging-api
          |
          +--> PostgreSQL Supabase (clientes, usuários, módulos, eventos, estoques)
          |
          +--> Supabase Storage privado (foto, PDF, áudio)
          |
          +--> OpenAI (transcrição/leitura documental)
```

## Princípio de configuração

> Variável de ambiente = segredo/configuração da infraestrutura.  
> Banco de dados = cliente, usuário, unidade, módulo, permissão e configuração operacional.

Portanto, organização, administrador, unidades, módulos contratados e identidades de canal **não são variáveis do Render**.

## Banco

- `DATABASE_URL`: conexão usada pela API em runtime.
- `MIGRATION_DATABASE_URL`: conexão usada exclusivamente pelo Alembic.
- URLs `postgres://` e `postgresql://` são normalizadas para `postgresql+psycopg://`.
- Porta `6543` é reconhecida como transaction pooler e usa `NullPool` automaticamente.
- Na homologação atual, o Session/Shared pooler na porta `5432` pode ser usado nas duas URLs.

Cada deploy executa somente:

```bash
alembic upgrade head
python -m app.cli.staging_preflight
```

Não existe bootstrap automático por ENV.

## Dados de cliente ficam no PostgreSQL

Persistidos no banco:

- organizações/agropecuárias;
- unidades/fazendas;
- usuários;
- vínculos e papéis;
- módulos contratados;
- permissões;
- produtos, fórmulas e estoques;
- eventos e auditoria;
- identidades de WhatsApp/Telegram;
- contas de canal por organização.

Isso permite cadastrar centenas ou milhares de clientes sem alterar o Render.

## Módulos

O catálogo contém:

- `livestock` — Pecuária;
- `feed_mill` — Fábrica de Ração;
- `finance` — Financeiro.

O catálogo existir não habilita módulo para cliente algum. Cada organização possui sua combinação em `organization_modules`.

## Storage de mídia

Homologação usa:

```text
CAMPOEDADOS_MEDIA_STORAGE=supabase
CAMPOEDADOS_SUPABASE_STORAGE_BUCKET=campoedados-staging-media
SUPABASE_URL=...
SUPABASE_SECRET_KEY=sb_secret_...
```

O bucket é privado. Arquivos são content-addressed por SHA-256 e o banco guarda somente a referência persistente.

`SUPABASE_SECRET_KEY` é segredo exclusivamente server-side. O código mantém compatibilidade temporária com a antiga `SUPABASE_SERVICE_ROLE_KEY`, mas o Blueprint novo não a solicita.

## Segurança do schema Supabase

A migration 0002:

- habilita RLS nas tabelas do produto;
- revoga acesso de `anon` e `authenticated` quando esses papéis existem;
- não cria políticas públicas por padrão.

A migration 0003:

- habilita RLS também em `alembic_version`;
- revoga `anon` e `authenticated` nessa tabela interna;
- remove o segundo índice único redundante de `access_tokens.token_hash`.

RLS sem políticas nas tabelas do produto é intencional neste estágio: a aplicação acessa o PostgreSQL server-side e as tabelas não devem ficar abertas pela Data API. Se uma tabela precisar ser exposta futuramente, receberá grants e políticas específicas em migration própria.

## Primeiro cliente — onboarding controlado

A Base 06.3 adiciona um comando administrativo manual. Ele **não roda no deploy** e não usa ENV para dados de cliente.

Exemplo:

```bash
python -m app.cli.onboard_organization \
  --org-name "Agro Homologação" \
  --org-slug agro-homolog \
  --admin-name "Administrador" \
  --unit "SH7=Fazenda SH7" \
  --unit "NSG=Fazenda NSG" \
  --module livestock \
  --module feed_mill \
  --module finance
```

O comando cria em uma única transação:

1. organização;
2. administrador e membership;
3. unidades;
4. combinação de módulos contratados;
5. permissões administrativas somente nos módulos habilitados;
6. entrada de auditoria;
7. token administrativo.

O token bruto é exibido **uma única vez** no terminal. O banco armazena somente SHA-256. O comando recusa um slug já existente para não transformar uma reexecução em alteração silenciosa de cliente.

`--admin-email` é opcional. Pode ser informado quando desejado.

## Contas de canal

### WhatsApp oficial

O modelo atual prevê um número oficial do Campo & Dados. As credenciais globais da Meta são segredo de infraestrutura e podem ser adicionadas ao Render quando o canal for ativado.

Usuários e telefones vinculados continuam no banco.

### Telegram por cliente

Tokens de bots não ficam em ENV por cliente.

Cada bot fica em `channel_accounts`, com credencial e segredo de webhook criptografados. Uma única chave de infraestrutura, `CAMPOEDADOS_CREDENTIAL_ENCRYPTION_KEY`, protege essas credenciais quando o Telegram for ativado.

## Render Blueprint

O Blueprint pede apenas cinco valores secretos na criação inicial:

```text
DATABASE_URL
MIGRATION_DATABASE_URL
SUPABASE_URL
SUPABASE_SECRET_KEY
OPENAI_API_KEY
```

Demais ajustes de infraestrutura possuem valores no `render.yaml`.

## Readiness

- `/health`: processo HTTP está vivo.
- `/ready`: banco e storage obrigatório estão disponíveis.

Se banco ou storage estiverem indisponíveis, `/ready` retorna `503`.

## Ordem atual de homologação

1. Supabase e bucket privado criados.
2. Render criado pelo `render.yaml`.
3. Deploy verde com migrations e preflight.
4. Aplicar Base 06.3 pelo próximo deploy.
5. Executar onboarding controlado no Render Shell.
6. Confirmar organização, usuário, unidades, módulos e permissões no PostgreSQL.
7. Testar API autenticada com o token administrativo.
8. Cadastrar dados mínimos do primeiro módulo em homologação.
9. Enviar primeiro Evento real pelo Agente Operador.
10. Testar foto/PDF/áudio e Agente Gerencial.
11. Ativar Telegram/WhatsApp real quando desejado.

## CI

O GitHub Actions sobe PostgreSQL 16 e valida:

1. instalação do projeto;
2. migrations até `head`;
3. 28 tabelas esperadas;
4. RLS em todas as tabelas públicas, inclusive `alembic_version`;
5. ausência do índice duplicado em `access_tokens.token_hash`;
6. onboarding transacional e regras de módulos;
7. suíte completa sem regressões.
