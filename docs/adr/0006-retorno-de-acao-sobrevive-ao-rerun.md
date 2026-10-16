# ADR-0006 — Retorno de ação vai por `flash()`, não por `st.success()`

- **Status:** aceito
- **Data:** 2026-10-16
- **Origem:** relato do usuário de que a ingestão "não avisava nada" — só dava para
  saber que havia concluído porque a linha nova aparecia na tabela de documentos

## Contexto

O padrão usado em todo o `main.py` era:

```python
st.success("Documento indexado com sucesso!")
st.rerun()
```

`st.rerun()` interrompe o script e re-executa: **a renderização da execução atual é
descartada**, junto com a mensagem que acabou de ser emitida. Quem clicava em
"Processar e Indexar" não via confirmação nenhuma — e, para um PDF pequeno, também
não via a barra de progresso, porque `store_in_postgres` emite **um progresso por
lote de 128 fragmentos** e um PDF menor cabe num único lote (0% → 100% na mesma
execução que some).

O padrão `st.success` + `st.rerun` estava em **6 pontos** (ingestão privada e
global, exclusão de fragmentos em dois lugares, cadastro de usuário, troca de
senha) e havia ainda **2 pontos que trocavam o escopo de um documento sem dizer
nada** (rerun seco). Ou seja: não era um bug isolado da ingestão, era a convenção
de retorno da interface que estava errada.

## Decisão

1. Existe **um** caminho de retorno para ações que terminam com `st.rerun()`:
   `ui_feedback.flash(mensagem, tipo)` registra no `st.session_state` e
   `render_flash()` (chamado no alto da página autenticada, antes do roteamento)
   exibe **uma única vez** na execução seguinte — em qualquer página, já que o
   rerun pode cair em outra.
2. Nenhuma ação afirma sucesso por conta própria: a mensagem carrega o resultado
   real devolvido pelo backend (ex.: `ingest_document` devolve quantos fragmentos
   foram gravados; zero fragmentos vira **aviso**, não sucesso).
3. O retorno é **texto do backend**, não decoração do `main.py`: a função que
   exibe devolve `(mensagem, tipo)` e quem chama apenas registra — por isso o
   componente de ingestão vive em `ui_feedback.py`, importável e testável, e não
   inline em um script com efeitos no import.

## Consequências

- A confirmação de uma ação existe na tela mesmo quando a ação é instantânea.
- A mensagem é a mesma em qualquer página (o feedback não se perde num rerun que
  muda o contexto de renderização).
- Custo aceito: a mensagem aparece **uma execução depois** da ação (imperceptível —
  o rerun é imediato) e some no próximo rerun, o que é o comportamento desejado
  para um aviso de "acabou de acontecer".
- Efeito colateral bem-vindo: como o tipo vem do resultado, o caso "PDF sem texto
  (escaneado)" e o caso "tudo já estava na base" pararam de ser anunciados como
  sucesso (fecha o **P1-6**).
- O `st.status` que envolve a indexação continua existindo para o *durante*
  (barra + estágio); ele é descartado pelo rerun, e é o `flash` que garante o
  *depois*. São dois propósitos, dois mecanismos.

## Alternativas consideradas

1. **`st.toast()`** — sobrevive ao rerun por desenho e é uma linha só, mas
   desaparece sozinho em poucos segundos e não deixa registro na tela: ruim para
   "o que acabou de acontecer com o meu arquivo" (o usuário pode estar olhando
   para o lado). Fica como opção para avisos efêmeros no futuro, não para isso.
2. **Remover o `st.rerun()`** — para a ingestão funcionaria (a tabela é renderizada
   depois do botão, na mesma execução), mas não para as ações dentro da lista de
   documentos (exclusão/troca de escopo), onde o rerun é necessário para a lista
   refletir a mudança. Fixar uma regra única é melhor do que depender de a ordem
   de renderização estar certa em cada tela.
3. **Escrever a mensagem em `st.session_state` e renderizar com `st.tabs`/`st.status`
   persistente** — mais maquinário para o mesmo efeito; o `flash` já é o mínimo
   necessário (duas funções, sem estado global além de uma chave).
