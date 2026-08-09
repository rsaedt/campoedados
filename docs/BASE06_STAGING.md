# Base 06 / 06.1 — Ambiente real de homologação

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

A Base 06.1 corrige a primeira versão da homologação:

> Variável de ambiente = segredo/configuração da infraestrutura.  
> Banco de dados = cliente, usuário, unidade, módulo, permissão e configuração operacional.

Portanto, organização, administrador, unidades, módulos contratados e identidades de canal **não são mais variáveis do Render**.

## Banco

- `DATABASE_URL`: conexão usada pela API em runtime.
- `MIGRATION_DATABASE_URL`: conexão usada exclusivamente pelo Alembic.
- URLs `postgres://` e `postgresql://` são normalizadas para `postgresql+psycopg://`.
- Porta `6543` é reconhecida como transaction pooler e usa `NullPool` automaticamente.

Cada deploy executa somente:

```bash
alembic upgrade head
python -m app.cli.staging_preflight
```

Não existe mais bootstrap automático por ENV.

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
```

O bucket é privado. Arquivos são content-addressed por SHA-256 e o banco guarda somente a referência persistente.

`SUPABASE_SERVICE_ROLE_KEY` é segredo exclusivamente server-side.

## Segurança do schema Supabase

A migration 0002:

- habilita RLS nas tabelas do produto;
- revoga acesso de `anon` e `authenticated` quando esses papéis existem;
- não cria políticas públicas por padrão.

A API do Campo e Dados usa conexão server-side direta ao PostgreSQL. Se futuramente alguma tabela precisar ser exposta via Data API, ela deverá receber uma política específica em migration própria.

## Contas de canal

### WhatsApp oficial

O modelo atual prevê um número oficial do Campo & Dados. As credenciais globais da Meta são segredo de infraestrutura e podem ser adicionadas ao Render quando o canal for ativado.

Usuários e telefones vinculados continuam no banco.

### Telegram por cliente

Tokens de bots não ficam mais em `CAMPOEDADOS_TELEGRAM_BOTS_JSON` nem em uma ENV por cliente.

Cada bot fica em `channel_accounts`:

```text
organização
canal = telegram
account_key
nome
id externo
credencial criptografada
segredo de webhook criptografado
status
```

Uma única chave de infraestrutura, `CAMPOEDADOS_CREDENTIAL_ENCRYPTION_KEY`, protege essas credenciais. Essa chave só precisa ser configurada quando contas Telegram reais forem ativadas e nunca deve ser gravada no banco ou no GitHub.

## Render Blueprint

O Blueprint pede apenas cinco valores secretos na criação inicial:

```text
DATABASE_URL
MIGRATION_DATABASE_URL
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
OPENAI_API_KEY
```

Demais ajustes de infraestrutura possuem valores no `render.yaml`.

Credenciais opcionais de canais não fazem parte do formulário inicial do Blueprint.

## Readiness

- `/health`: processo HTTP está vivo.
- `/ready`: banco e storage obrigatório estão disponíveis.

Se banco ou storage estiverem indisponíveis, `/ready` retorna `503`.

## Primeiro cliente/administrador

A Base 06.1 remove o bootstrap automático. O primeiro cadastro será feito deliberadamente no banco durante a homologação. Depois disso, cadastro de organizações, usuários, unidades, módulos e canais deve ocorrer pela camada administrativa do próprio Campo e Dados.

Esse procedimento evita transformar um mecanismo provisório de deploy em modelo permanente de provisionamento.

## Ordem atual de homologação

1. Criar projeto Supabase exclusivo de homologação.
2. Criar bucket privado `campoedados-staging-media`.
3. Criar serviço Render pelo `render.yaml`.
4. Informar somente os cinco secrets iniciais.
5. Deploy executa `alembic upgrade head` + preflight.
6. Conferir `/health` e `/ready`.
7. Criar o primeiro cadastro administrativo no PostgreSQL.
8. Cadastrar organização, unidades e módulos no banco.
9. Ativar Telegram ou WhatsApp quando desejado.
10. Enviar a primeira mensagem real e conferir Evento + auditoria.

## CI

O GitHub Actions sobe PostgreSQL 16 e valida:

1. instalação do projeto;
2. migrations até `head`;
3. existência de `channel_accounts`;
4. RLS habilitado nas tabelas do produto;
5. suíte completa das Bases 01–06.1.
