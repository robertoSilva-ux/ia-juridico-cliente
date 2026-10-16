# ADR-0007 — Citação de norma exige par número+ano no contexto

- **Status:** aceito
- **Data:** 2026-10-16
- **Origem:** resposta errada entregue ao usuário com selo verde — *"A Lei nº 8080/2011
  regula o Sistema Único de Saúde"* (a Lei 8.080 é de **19/09/1990**)

## Contexto

O fact-check pós-geração verificava três coisas: citações `[n]` da resposta contra os
documentos recuperados, dispositivos (`art. N`, `§N`, inciso), e quantidades com unidade
("180 dias"), além de um índice lexical por sentença. **A identidade da norma — qual lei,
de que ano — não era verificada em lugar nenhum.**

Medido com a base real: o modelo escreveu *"Lei nº 8080/2011"*. O **8080** veio do **nome do
arquivo** (`LEI-8080-ESQUEMATIZADA1.pdf`, que aparece no cabeçalho de cada `[DOC]` do
contexto) e o **2011**, de um trecho de outra lei — *"(Incluído pela Lei nº 12.401, de
2011)"*. Cada pedaço existia em algum lugar do contexto, e os testes por token aprovaram:
`all_grounded: True` numa resposta errada.

Os benchmarks dos próprios autores confirmam o alcance do problema: em ~200 execuções
registradas (`app/eval/relatorios/bench_*20x.json`, cinco modelos), `no_support` foi **0,00
em todas** — a checagem nunca reprovava nada.

Um segundo caso, na mesma base, mostrou que a checagem também precisa distinguir
severidade: o modelo respondeu *"a Lei 8.080, de 9 de dezembro de 1990"* — número certo,
data inventada — sendo que **o material não registra o ano em nenhum fragmento**.

## Decisão

1. Toda citação de norma na resposta (lei, lei complementar, decreto, decreto-lei, medida
   provisória, emenda constitucional) é extraída com **número normalizado** (sem pontos,
   `8.080` → `8080`) e **ano normalizado** (`/91` → `1991`), e conferida contra o contexto.
2. A unidade de verificação é o **par**: número e ano têm de aparecer **juntos no conteúdo de
   um mesmo fragmento**. Não basta cada um existir em algum lugar do material — é exatamente
   essa composição que produziu o "8080/2011".
3. **A identidade do próprio documento** (coluna `numero_doc`/`ano_doc` ou, na falta dela, o
   resultado de `parse_file_name` sobre o nome do arquivo) conta como lastro **para aquela
   norma** — o pipeline fornece esse rótulo ao modelo, citá-lo não é invenção. Ela nunca cria
   par com o ano lido em outro documento.
4. Severidade em **três níveis**, porque "não posso verificar" não é o mesmo que "está errado":

| Situação | Veredito |
|:---|:---|
| Número que não existe em lugar nenhum do contexto | `no_support` / `norma_sem_lastro` |
| Número existe e o contexto registra **outro** ano para ele | `no_support` / `ano_incompativel` |
| Número existe, nenhum ano consta do contexto | `partial` / `ano_nao_consta` |

## Consequências

- O caso relatado passa a ser sinalizado (verificado na base real), e a causa fica explícita
  no motivo (`ano_nao_consta`, `ano_incompativel`, `norma_sem_lastro`), o que permite à
  interface dizer **o que** conferir em vez de um aviso genérico.
- Resposta correta continua limpa: há teste específico de não-regressão para cada nível, com
  a base sintética montada a partir do caso real.
- Custo: mais um padrão de extração no fact-check, que já era o ponto mais intrincado do
  pipeline; e a checagem é **conservadora** — quando o material traz o ano em um fragmento e
  o número em outro, a data sai como não verificável. Isso é intencional (é a mesma liberdade
  que o modelo usou para errar) e deixa de ser limitante quando o corpus é o texto oficial,
  onde número e data aparecem no cabeçalho de cada página (ver P2-30 no backlog).
- Não cobre: erro de *enquadramento* (número certo usado para a conclusão errada) nem
  conteúdo inventado sem número. O fact-check é uma rede de segurança para a classe de erro
  mais danosa de um produto jurídico — identificação de norma —, não um validador semântico.

## Alternativas consideradas

1. **Verificar cada token separadamente** (como os checks anteriores) — descartado: foi
   exatamente isso que aprovou "8080" + "2011".
2. **Aceitar o número em qualquer lugar do contexto e o ano em qualquer outro** — descartado:
   é a definição do bug; com a base saturada de "(Incluído pela Lei nº X, de AAAA)" o modelo
   acerta por acaso e erra com frequência.
3. **Marcar como `no_support` todo ano não encontrado** — descartado por gerar alarme falso em
   resposta correta cujo ano simplesmente não está no material (foi o caso medido); a
   distinção `partial` mantém o aviso honesto e proporcional.
4. **Usar um LLM para checar a citação** (juiz automático) — mais caro, não determinístico e
   inútil aqui: comparar número e ano é problema de string, não de julgamento. Um juiz de LLM
   pode entrar depois para o que a string não vê (enquadramento e conteúdo).
