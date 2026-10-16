# ADR-0009 — Portão de resposta: recusa honesta e lastro no fragmento citado

- **Status:** aceito
- **Data:** 2026-10-16
- **Origem:** pedido do cliente — *"precisamos de respostas 100 % fundamentadas no RAG ou a
  honestidade de dizer que não encontrou"* — e as medições do `docs/PLANO_REFINAMENTO_RAG.md`

## Contexto

Três medições (GPU sã, base de dev) mostraram que a garantia pedida não existia e que os dois
caminhos "óbvios" não a entregam:

1. **A não-resposta passava como resposta.** Pergunta fora da base ("prazo de prescrição da
   usucapião extraordinária") → o modelo devolveu *"A vigência não está indicada nos
   documentos recuperados."*, com **15 fontes** a 67–69 % de similaridade e
   **`all_grounded: True`** no fact-check. O veredito **nunca chegava à tela**: `main.py`
   recebia `result["fact_check"]` e o descartava.
2. **Limiar de distância não separa "a base responde" de "não responde".** Medido com o
   `nomic-embed-text`: perguntas **com** resposta na base têm top-1 entre **0,15 e 0,27**;
   perguntas **fora** da base, entre **0,20 e 0,35**. As faixas se sobrepõem, e o
   `SIMILARITY_THRESHOLD` (0,80) é um não-portão — tudo passa e o `TOP_K=15` sempre enche.
3. **Mais dois defeitos medidos no fluxo:** a busca por metadados/palavra-chave devolvia
   `distance = 0.0` e a interface calculava `1 - 0.0` e escrevia **"Similaridade: 100,00%"**
   para um resultado que nunca foi comparado; e `FACT_CHECK_LLM_ENABLED` era configuração
   morta (documentada, nunca lida).

## Decisão

A resposta passa a ter **três barreiras em série**, e a interface mostra em qual delas a
resposta parou:

1. **Portão de suficiência** (`agent._contexto_suficiente`, ligado por
   `FACT_CHECK_LLM_ENABLED`): antes de gerar, uma chamada curta ao LLM pergunta se os trechos
   recuperados contêm **literalmente** o dispositivo/dado que a pergunta exige. "NAO" ⇒
   **recusa canônica, sem gerar resposta**. É o mecanismo que substitui o limiar de distância:
   medido no `phi4-mini`, 7/7 das perguntas legítimas liberadas e 4/6 das fora da base
   recusadas, a 0,5–2,0 s por chamada. Resposta ambígua, LLM fora do ar ou verificação
   desligada devolvem `None` = **segue o fluxo normal** (ausência de veredito não pode virar
   recusa, senão falha de infraestrutura derruba pergunta legítima).
2. **Lastro no fragmento CITADO** (`factcheck._classificar_sentenca`): sentença com citação
   válida tem o dado afirmado conferido contra o conteúdo do **fragmento que ela cita**, não
   contra o contexto agregado — citar `[1]` e afirmar o dado do `[3]` vira
   `lastro_fora_do_citado`. A citação é aceita nas duas grafias que chegam na prática, `[3]` e
   `[DOC 3]` (a segunda é a que o prompt manda usar).
3. **Portão de exibição** (`agent.get_response`): veredito `sem_lastro` (norma/dispositivo/
   citação que não existe no material, ou resposta vazia) **ou** `recusou` ⇒ **uma única**
   segunda leitura, com o motivo apontado no bloco da pergunta; persistindo o defeito, a
   resposta **não é exibida** e o sistema apresenta a **recusa canônica** — escrita pelo
   sistema, com o número de trechos examinados, o motivo e o que fazer para obter a resposta.
   O texto descartado vai para `descartada` e para o log de auditoria (prefixo
   `[RECUSA: motivo]`), nunca para a tela.

Complementos da mesma decisão: a recusa é reconhecida pela **primeira frase** (é afirmação
sobre a base, não sobre o direito) e aceita deformações do modelo pequeno ("NÃO ENCONTRAR NA
BASE"); resposta **sem nenhuma unidade verificável** (`sem_fonte`) é `parcial` e **avisa**, não
recusa; a lista de fontes mostra a **similaridade só quando ela foi medida** e marca quais
trechos a resposta citou; e as fontes de uma recusa aparecem como "nenhuma sustenta a
resposta".

## Consequências

Medido no mesmo mini-quiz + 6 perguntas fora da base (GPU sã, uma passagem por barreira):

| Critério | Antes | Depois |
|:---|:---|:---|
| Resposta exibida com norma/dispositivo sem lastro | 1 resposta errada com selo verde | **0** |
| Pergunta cuja resposta não está na base → recusa honesta | 0 de 7 | **7 de 7** |
| Perguntas legítimas respondidas | 6 de 6 (**com** 2 delas citando ano inventado) | **15 de 18 (83 %)**, 3 recusas (d4 2/3, d5 1/3) |
| Latência | mediana 7 s | mediana 7,9 s · p95 10,6 s |

- O custo real é **disponibilidade**: o modelo de 3,8 B não cumpre o contrato de saída de forma
  confiável e recusa perguntas cuja resposta está no material (d4 exige uma inferência
  — "(Incluído pela Lei nº 12.401, de 2011)" → "a lei que incluiu o art. 19-Q" — que ele não
  faz). A recusa é honesta, mas o advogado fica sem a resposta: o caminho é corpus oficial
  (P2-30) e recuperação (Fase 3 do plano, itens R-14..R-18), não afrouxar o portão.
- **Uma segunda leitura, nunca duas**: medido, um retry que termina em recusa disparava uma
  terceira chamada (recusa sobre recusa) e a resposta boa da primeira era perdida.
- Toda pergunta — respondida ou recusada — continua indo para o `audit_log`, agora com o motivo
  da recusa; a UI tem teste próprio para cada estado (`ok`, `parcial`, `recusada`, `erro`).
- **Limite declarado:** lastro não é correção. Uma resposta que usa um número real do contexto
  para a conclusão errada (caso medido: "idade mínima = 35 anos" quando o art. 54 traz 35 anos
  de *contribuição*) continua passando — isso é inferência, e o que existe para essa classe é
  prompt (arbitragem de regime, âncora por dispositivo), portão de recusa e medição por quiz,
  não garantia automática.

## Alternativas consideradas

1. **Portão por limiar de distância** (`SIMILARITY_THRESHOLD`) — descartado por medição: as
   faixas de dentro e de fora da base se sobrepõem; apertar o limiar recusaria pergunta
   legítima antes de recusar pergunta fora da base.
2. **Bloquear também a resposta sem nenhuma citação** (`sem_fonte`) — descartado por medição:
   uma resposta **correta** ("os municípios podem constituir consórcios") era descartada, a
   reescrita desistia e o advogado recebia recusa no lugar da resposta que já existia. Passou a
   ser aviso.
3. **Deixar a recusa por conta do modelo** (como estava no prompt) — descartado: a taxa de
   recusa correta medida foi de 0,07 a 0,29 entre modelos, e o texto do modelo deforma
   ("NÃO ENCONTRAR NA BASE"). O sistema decide a recusa; o modelo só relata ausência, que é
   detectada e canonicalizada.
4. **Remover o `FACT_CHECK_LLM_ENABLED` morto** em vez de implementá-lo — descartado depois da
   medição: é o único mecanismo que separa "a base responde" de "não responde" com acerto
   (7/7 e 4/6), a 0,5–2,0 s por chamada.
5. **Reescrever a resposta com o modelo maior quando a barreira reprova** — adiado: exige um
   segundo modelo na VRAM, que o orçamento do ADR-0008 não comporta.
