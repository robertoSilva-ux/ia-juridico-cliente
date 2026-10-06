import os

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:***@db:5432/legal_db")
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "5"))

# IVFFlat: numero de listas sondadas por query de similaridade. Valores
# maiores melhoram recall as custas de latencia; 10 e um bom trade-off para
# a base atual. Aplicado via SET ivfflat.probes em database.get_db_connection.
IVFFLAT_PROBES = int(os.getenv("IVFFLAT_PROBES", "10"))

# Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

# Embeddings — tamanho do lote enviado ao /api/embed em cada chamada
# Default 128 (GPU aguenta; modelo nomic-embed-text, 768 dims).
# Loop de ingestão manda `batch_size` chunks por request.
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "128"))

# LLM
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_NUM_CTX = int(os.getenv("LLM_NUM_CTX", "0"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.80"))
TOP_K = int(os.getenv("TOP_K", "5"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "12000"))

# Re-ranking por MMR (Maximal Marginal Relevance) — técnica de compression/recuperação
# em 2 estágios (ver Kimothi "A Simple Guide to RAG" e Auffarth "RAG The Seminal Papers").
# Busca um top-k mais largo na 1ª etapa e depois re-ranqueia com MMR para reduzir
# redundância (ex.: notas de rodapé da doutrina que duplicam contexto) antes de mandar
# pro prompt.
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() in ("true", "1", "yes", "on")
# Quantas vezes o TOP_K final buscar na 1ª etapa (ex.: TOP_K=5 -> busca 5*3=15).
RERANK_TOP_K_MULTIPLIER = int(os.getenv("RERANK_TOP_K_MULTIPLIER", "3"))
# Trade-off relevância (1.0) vs redundância (0.0). Default 0.7: prioriza relevância
# mas penaliza docs muito parecidos entre si.
RERANK_LAMBDA_MULT = float(os.getenv("RERANK_LAMBDA_MULT", "0.7"))

# Fact-check / groundedness — verificação pós-geração (Auffarth "RAG The Seminal Papers",
# IsSup per-sentence groundedness). Divide a resposta em sentenças e verifica se cada uma
# está apoiada no contexto recuperado. Parte estrutural (citações [n]) roda sempre;
# a verificação semântica (LLM) é opcional p/ não adicionar latência.
FACT_CHECK_ENABLED = os.getenv("FACT_CHECK_ENABLED", "true").lower() in ("true", "1", "yes", "on")
# Verifica cada sentença com o LLM (segunda chamada) além da checagem de citações.
# Default false: evita dobrar latência/custo por pergunta.
FACT_CHECK_LLM_ENABLED = os.getenv("FACT_CHECK_LLM_ENABLED", "false").lower() in ("true", "1", "yes", "on")

# HyDE (Hypothetical Document Embeddings) — query transformation para recall lexical
# jurídico (ver Kimothi "A Simple Guide to RAG", cap. 6 "HyDE"). O LLM gera uma
# resposta hipotética à query SEM acessar a base; o embedding dessa resposta (com
# vocabulário jurídico) recupera chunks parecidos com a "resposta ideal", preenchendo
# o vocabulário gap (ex.: "aposentadoria" -> "carência/período de contribuição/art. 201").
# Aplicado SÓ no caminho semântico e em FUSÃO com a busca pela query original (RRF),
# para não perder precisão por overexpansion/drift (aviso do Kimothi).
HYDE_ENABLED = os.getenv("HYDE_ENABLED", "true").lower() in ("true", "1", "yes", "on")
# Quantos docs trazer de CADA ranking (query original + HyDE) antes da fusão.
HYDE_TOP_K = int(os.getenv("HYDE_TOP_K", "8"))
# Peso da query original na fusão RRF (>= 1.0). Kimothi alerta que overexpansion
# dilui o foco da query original; por isso a busca pela query conta mais que a HyDE,
# que apenas COMPLEMENTA com docs que passam no threshold. 1.0 = peso igual.
HYDE_QUERY_WEIGHT = float(os.getenv("HYDE_QUERY_WEIGHT", "1.4"))
