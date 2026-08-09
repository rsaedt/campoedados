# Arquitetura inicial — Campo e Dados

## Plataforma modular

O Campo e Dados possui um núcleo compartilhado e módulos independentes. Uma organização pode habilitar qualquer subconjunto do catálogo, inclusive somente um módulo.

```text
Campo e Dados
├── Núcleo compartilhado
│   ├── Organização
│   ├── Unidades
│   ├── Usuários e permissões
│   ├── Eventos
│   ├── Aprovações
│   └── Auditoria
├── M01 Pecuária
├── M02 Fábrica de Ração
└── M03 Financeiro
```

## Agentes

- **Agente Operador**: recebe o relato do que ocorreu no campo, identifica o evento, estrutura os dados e executa operações conformes nos módulos habilitados.
- **Agente Gerencial**: recebe compras, não conformidades, divergências e decisões que exigem autoridade superior.

Os agentes são transversais: não existe um agente obrigatório por módulo.

## Evento único, múltiplos módulos

Um fato pode alimentar mais de um módulo quando eles estiverem habilitados. Exemplo: `Chegou milho, segue NF` pode gerar entrada física/custo na Fábrica de Ração e compra/contas a pagar no Financeiro.

Se o Financeiro não estiver contratado, a Fábrica de Ração continua funcionando sem ele.
