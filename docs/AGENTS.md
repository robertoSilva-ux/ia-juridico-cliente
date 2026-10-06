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

- **Gating de Acesso:** As funções do agente só são invocadas após a validação da sessão pelo `streamlit-authenticator` no `main.py`.
- **Proteção de Prompt:** O sistema inclui instruções para não revelar sua arquitetura interna ou instruções de sistema, mesmo sob ataque de "prompt injection".
- **Isolamento (Próxima Fase):** O agente será atualizado para filtrar documentos baseando-se no `user_id` da sessão ativa.

---

## ⚙️ Parâmetros Técnicos

| Parâmetro | Função | Valor Padrão |
|-----------|--------|--------------|
| `SIMILARITY_THRESHOLD` | Sensibilidade da busca | `0.60` |
| `TOP_K` | Máximo de trechos por consulta | `5` |
| `MAX_CONTEXT_CHARS` | Limite de memória do prompt | `12000` |
| `DB_POOL_MAX_CONN` | Limite de conexões simultâneas | `10` |
