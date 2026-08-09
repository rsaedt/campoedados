# Base 03 — Transferências, recebimentos e Agente Gerencial

## 1. Transferência entre unidades

Mensagem do operador:

`Carreguei 80 sacos de Seca 0,1 para NSG`

O sistema preserva a quantidade declarada (`80 sacos`), converte para a unidade-base conforme o peso configurado do produto e transfere o mesmo custo do estoque de origem. A expedição não cria receita nem despesa.

Na chegada:

`Chegaram os 80 sacos na NSG`

Se a quantidade recebida for igual à enviada, a transferência é recebida automaticamente e o custo acompanha o produto. Se houver diferença, o destino não é creditado até decisão gerencial e o evento fica em `waiting_manager`.

## 2. Recebimento de matéria-prima com NF

Mensagem:

`Chegou milho, segue NF`

O documento fica vinculado ao Evento com referência de armazenamento e dados extraídos. A Fábrica de Ração registra imediatamente a realidade física do estoque quando os dados necessários estão disponíveis.

Se o módulo Financeiro estiver habilitado, o mesmo Evento também cria a compra e suas parcelas como `pending_approval`. O operador não precisa ter acesso ao Financeiro: registrar o fato físico é uma permissão da Fábrica de Ração, e o efeito financeiro é interno.

## 3. Estado por módulo

Um único Evento pode estar em estados diferentes por módulo. Exemplo após chegada normal de milho:

- Fábrica de Ração: `processed`
- Financeiro: `waiting_manager`
- Evento geral: `waiting_manager`

Isso evita apagar ou atrasar a realidade física enquanto uma decisão administrativa está pendente.

## 4. Não conformidades

São encaminhadas ao Agente Gerencial, entre outras:

- quantidade recebida diferente da enviada em transferência;
- quantidade física recebida diferente da quantidade da NF;
- nota fiscal duplicada;
- operação que já dependia de aprovação por falta de estoque.

Aprovações e rejeições são auditadas por usuário, módulo, data e observação.

## 5. Modularidade

- Com Fábrica de Ração + Financeiro: o recebimento físico gera estoque e compra pendente.
- Somente com Fábrica de Ração: o recebimento continua funcionando e nenhum registro financeiro é criado.
- O Financeiro não é requisito comercial ou técnico para usar a Fábrica de Ração.
