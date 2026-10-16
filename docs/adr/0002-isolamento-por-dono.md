# ADR-0002 — Isolamento entre clientes por dono do documento

- **Status:** aceito
- **Data:** 2026-10-16
- **Achados relacionados:** P0-3 e P0-4 em [`../REVISAO_SEGURANCA.md`](../REVISAO_SEGURANCA.md)

## Contexto

O produto guarda documentos de clientes e promete que um usuário não vê o do outro. A
recuperação já filtrava por dono (`scope = 'global' OR owner_id = %s`), mas **todas as
operações de escrita e de manutenção usavam o nome do arquivo como chave**:

- mudar escopo: `UPDATE documents SET scope = %s WHERE file_name = %s`;
- excluir (admin): `DELETE FROM documents WHERE file_name = %s`;
- dedup da ingestão: `SELECT content FROM documents WHERE file_name = %s`;
- fonte (`sources`): `UNIQUE (file_name)`.

`file_name` se repete na prática (`peticao.pdf`, `contrato.pdf`). Medido em Postgres real:
um clique em "Tornar Global" promovia **também** o arquivo privado homônimo de todos os
outros usuários; e o upload do segundo usuário com o mesmo nome era **integralmente
descartado** pelo dedup — sem erro, com a interface dizendo "indexado com sucesso".

## Decisão

O **dono** passa a ser parte da chave em todas as operações: escopo, exclusão, dedup e
`UNIQUE` da tabela `sources`. Regras que acompanham a decisão:

1. Operação de escrita **exige saber quem age** (`user_id`); sem isso, falha em vez de
   varrer a base. Admin age sobre **um dono por vez**, informado explicitamente.
2. A unicidade da fonte considera o dono nulo como um único "sem dono":
   `UNIQUE (file_name, COALESCE(owner_id, -1))`, e o `ON CONFLICT` é escrito igual ao
   índice. Motivo: em índice único NULL é distinto de NULL, então com a coluna crua o
   conflito **nunca** casava para as cargas em lote/legado (`--owner-id None`, o caminho do
   corpus global) e cada carga inseria uma linha nova de `sources`.
3. Mudanças de schema vêm com **migração idempotente** para bases existentes
   (`database/migrate_sources_owner.sql`), e a migração reaponta `documents.source_id`
   **antes** de remover fontes duplicadas — `source_id` é `ON DELETE CASCADE`, então a
   ordem inversa apagaria chunks dos clientes.
4. `documents.scope` e `sources.scope` são atualizados na **mesma transação**: as duas
   tabelas respondem à mesma pergunta.

## Consequências

- Um usuário não consegue mais afetar (nem por acidente) documento de outro.
- O painel do admin passou a agrupar e exibir por `(arquivo, escopo, dono)`: dois donos com
  arquivos homônimos aparecem separados, em vez de virar uma linha só.
- Custo: mais um parâmetro circulando (`owner_id`) e uma migração a rodar em instalações
  existentes. Em banco com duplicatas, `CREATE UNIQUE INDEX` falha — daí o bloco de
  consolidação na migração **e** no `init.sql`.
- A ingestão ganhou um teste de integração específico para o caso "sem dono" (o que teria
  pegado a regressão introduzida na primeira versão desta correção).

## Alternativas consideradas

1. **Chave composta no nome do arquivo** (`owner_id/nome.pdf`) — descartado: resolve por
   convenção, não por invariante, e quebra com dados legados.
2. **Tabela `documents` sem unicidade, dedup só na aplicação** — descartado: foi
   exatamente a situação anterior, em que a invariante dependia do código estar certo.
3. **Isolar por banco/schema por cliente** (mais forte) — anotado como opção futura para
   contratos que exijam separação física; hoje custaria uma operação por cliente sem
   ganho imediato para o uso previsto.
4. **Manter `user_id=None` como "sem escopo"** — descartado como padrão: é o modo mais
   perigoso (lê todos os tenants). Segue existindo como caminho explícito de scripts, e
   está registrado no backlog (P2-15) para receber um parâmetro obrigatório.
