# AGENTS.md - Arquitetura do Agente RAG

Este documento detalha a camada de inteligência do **Legaliz.ai**, localizada em `app/agent.py`.

---

## 🤖 O Agente Jurídico

O agente é um pipeline de **Retrieval-Augmented Generation (RAG)** otimizado para o contexto jurídico brasileiro.

### 🧩 Fluxo de Execução

1. **Vetorização:** A pergunta do usuário é convertida em um vetor de 768 dimensões usando o modelo `nomic-embed-text`.
2. **Busca Semântica:** O sistema consulta a tabela `documents` usando a métrica de **Distância de Cosseno**.
3. **Filtro de Relevância:** Apenas trechos com distância menor que `SIMILARITY_THRESHOLD` (configurável) são aceitos.
4. **Construção de Contexto:** Os trechos recuperados são numerados e formatados com metadados (nome do arquivo).
5. **Inferência:** O LLM (**Llama 3**) recebe o contexto e a pergunta, gerando uma resposta técnica e citando as fontes.

---

## 🛡️ Segurança e Acesso

- **Gating de Acesso:** As funções do agente só são invocadas após a validação da sessão pelo `streamlit-authenticator` no `main.py`. O cookie de sessão é assinado com `COOKIE_KEY` (obrigatória, ≥32 bytes) — sem ela a aplicação não inicia.
- **Isolamento por dono:** a recuperação passa `user_id` para os três caminhos de busca (semântico, metadados e palavra-chave) e filtra `scope = 'global' OR owner_id = <usuário>`. Todo documento tem dono; dedup e `sources` são únicos por `(file_name, owner_id)`. Ver [`REVISAO_SEGURANCA.md`](REVISAO_SEGURANCA.md).
- **Ancoragem:** o `system-role.md` proíbe afirmar ou citar dispositivo que não esteja literalmente no contexto, e o fact-check pós-geração sinaliza sentença sem lastro.
- **Prompt injection indireta (⚠️ pendente):** o contexto recuperado entra na mensagem *human* como dado, mas o prompt **não** instrui explicitamente o modelo a tratar o conteúdo dos PDFs como dados e ignorar instruções vindas dele. Um documento malicioso indexado na base poderia tentar redirecionar a resposta. Está no backlog como **P1-8**.

## ⚙️ Parâmetros Técnicos

| Parâmetro | Função | Valor Padrão |
|-----------|--------|--------------|
| `SIMILARITY_THRESHOLD` | Sensibilidade da busca (distância de cosseno máxima) | `0.80` |
| `TOP_K` | Máximo de trechos por consulta | `5` |
| `MAX_CONTEXT_CHARS` | Limite de memória do prompt | `12000` |
| `DB_POOL_MAX` | Limite de conexões do pool (`database.py`) | `10` |

> **Nota:** `SIMILARITY_THRESHOLD` é uma *distância* de cosseno — quanto **menor**, mais
> exigente o filtro. Os valores de produção vigentes ficam no `.env` (hoje `TOP_K=15`).
