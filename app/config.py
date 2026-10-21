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

# Escopo por norma na recuperação (P2-32). Quando a PERGUNTA nomeia a norma
# ("Lei 8.080", "Decreto 3.048"), a busca semântica consulta primeiro os trechos
# dessa norma e só COMPLETA as vagas restantes com a busca livre. Medido: a base
# de dev tem 1.716 dos 2.141 fragmentos num único decreto, e o tamanho relativo
# do documento decidia quem aparecia — em pergunta sobre a Lei 8.080, 1 de 15
# lugares era da 8.080 e o primeiro vinha em 10º. Com escopo: 12–15 de 15, a
# norma pedida em 1º. Nunca custa recall (completa com a busca livre), mas
# depende de a pergunta nomear a norma.
NORM_SCOPE_ENABLED = os.getenv("NORM_SCOPE_ENABLED", "true").lower() in ("true", "1", "yes", "on")
# Teto de trechos de um MESMO ARQUIVO no contexto, aplicado antes do MMR (P2-32).
# O documento da norma pedida fica isento. Não descarta nada: quem passa do teto
# vai para o fim da lista (preenchimento), porque cortar fragmento de dispositivo
# é o defeito que a ingestão já pagou caro para consertar. 0 desliga.
MAX_CHUNKS_PER_DOC = int(os.getenv("MAX_CHUNKS_PER_DOC", "4"))

# Peso por "regime jurídico" (ADR-0013). Nasceu para desempatar RPPS x RGPS quando a base
# misturava Vade Mecum e apostila; hoje são três normas escritas à mão, com casamento por
# NOME DE ARQUIVO (`vade_mecum` não está mais na base), `excluded` que derruba emenda e
# constituição justamente em pergunta de RGPS (a EC 103 altera o RGPS) e nenhum marcador de
# saúde/SUS. MEDIDO em 2026-10-20: (a) posição da norma pedida no top-15, empate 11/11 com e
# sem peso; (b) A4 do mini-quiz, 12/18 dos dois lados; (c) nas perguntas de RGPS o peso
# ESTREITA o contexto para o 3.048 (15/15 trechos, expulsando EC 103 e LC 142) — a maior
# taxa de citação era artefato dessa homogeneização, não acerto de regime. Default: desligado.
# Ver docs/adr/0013-retirada-do-peso-por-regime.md. `true` reproduz o comportamento antigo.
REGIME_BOOST_ENABLED = os.getenv("REGIME_BOOST_ENABLED", "false").lower() in ("true", "1", "yes", "on")

# Fact-check / groundedness — verificação pós-geração (Auffarth "RAG The Seminal Papers",
# IsSup per-sentence groundedness). Divide a resposta em sentenças e verifica se cada uma
# está apoiada no contexto recuperado. A parte estrutural é determinística e roda sempre:
# citações [n] conferidas contra os trechos e o dado afirmado conferido no fragmento CITADO.
FACT_CHECK_ENABLED = os.getenv("FACT_CHECK_ENABLED", "true").lower() in ("true", "1", "yes", "on")
# Portão de SUFICIÊNCIA do contexto: uma chamada extra ao LLM (curta, antes de gerar) que
# responde se os trechos recuperados contêm literalmente o dispositivo/dado que a pergunta
# exige. "NAO" ⇒ recusa canônica, sem gerar resposta.
# É o mecanismo que decide a recusa honesta: o limiar de distância NÃO separa "a base
# responde" de "não responde" (medido: top-1 0,15–0,27 dentro da base contra 0,20–0,35 fora,
# com o nomic-embed-text). Medido no phi4-mini: 7/7 das perguntas legítimas liberadas, 4/6
# das fora da base recusadas, a 0,5–2,0 s por chamada (docs/PLANO_REFINAMENTO_RAG.md, R-8).
# Desligar devolve o comportamento anterior (responde sempre, com o risco de inventar).
FACT_CHECK_LLM_ENABLED = os.getenv("FACT_CHECK_LLM_ENABLED", "true").lower() in ("true", "1", "yes", "on")

# Teto do cache de dispositivos da base (P1-1). O fact-check confere dispositivo citado
# contra os dispositivos que EXISTEM no escopo do dono — não contra a base inteira (que
# validava documento de outro cliente e carregava o corpus todo na memória de um
# container de 512 MB). Passado o teto, a validação segue com o que coube e o log avisa.
FACT_CHECK_CACHE_MAX_ROWS = int(os.getenv("FACT_CHECK_CACHE_MAX_ROWS", "20000"))
FACT_CHECK_CACHE_MAX_CHARS = int(os.getenv("FACT_CHECK_CACHE_MAX_CHARS", "8000000"))

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
# dilui o foco da query original; por isso a busca pela query conta mais que a
# HyDE, que apenas COMPLEMENTA com docs que passam no threshold. 1.0 = peso igual.
HYDE_QUERY_WEIGHT = float(os.getenv("HYDE_QUERY_WEIGHT", "1.4"))

# =========================================================
# SEGREDO DO COOKIE DE SESSÃO (autenticação)
# =========================================================
# O streamlit-authenticator assina o cookie de sessão com JWT/HS256 usando esta
# chave (models/cookie_model.py: jwt.encode(..., self.cookie_key, 'HS256') no
# set e jwt.decode(token, self.cookie_key, ['HS256']) no check). Ela é, portanto,
# um SEGREDO DE AUTENTICAÇÃO: quem conhece a chave forja um cookie válido para
# qualquer usuário — inclusive admin — e entra sem senha.
#
# Por isso NÃO existe valor padrão aqui: sem COOKIE_KEY forte, a aplicação se
# recusa a subir (ver `cookie_key_problem()` e o guard em main.py). Um literal
# "legal_ai_key" chegou a ir para o repositório público, o que permitia forjar
# o cookie de admin com o pyjwt (ver docs/REVISAO_SEGURANCA.md, P0-1).
#
# ATENÇÃO: a chave precisa ser ESTÁVEL entre reinícios/deploys — trocá-la
# invalida as sessões ativas (todo mundo faz login de novo).
COOKIE_KEY = os.getenv("COOKIE_KEY", "")

# Nome do cookie de sessão. Não é segredo (aparece no navegador), mas fica aqui
# para que o nome usado pela aplicação e pelas ferramentas de verificação seja
# um só — o smoke test monta o autenticador exatamente como o app o monta.
COOKIE_NAME = os.getenv("COOKIE_NAME", "legal_ai_cookie")

# Mínimo em bytes para HMAC-SHA256. 32 bytes = 256 bits (RFC 7518 §3.2); abaixo
# disso o pyjwt emite InsecureKeyLengthWarning.
COOKIE_KEY_MIN_BYTES = 32

# Valores conhecidos por estarem em documentação/tutoriais/repositório: nunca
# aceitar, porque são exatamente o que um atacante tenta primeiro.
COOKIE_KEY_BLOCKLIST = frozenset({"legal_ai_key", "some_key", "changeme", "secret", "admin123"})


def cookie_key_problem(key: str | None = None) -> str | None:
    """Valida a chave de assinatura do cookie de sessão.

    Retorna a mensagem do problema (para a UI/CLI exibir) ou None quando a chave
    está adequada. Função pura, sem I/O, para ser testável isoladamente e para o
    chamador decidir abortar a inicialização.
    """
    value = COOKIE_KEY if key is None else key
    gerar = 'python3 -c "import secrets; print(secrets.token_urlsafe(48))"'
    if not value:
        return (
            "COOKIE_KEY não definida no .env — sem ela o cookie de sessão não pode "
            f"ser assinado com segurança. Gere uma com:\n  {gerar}"
        )
    if value in COOKIE_KEY_BLOCKLIST:
        return (
            f"COOKIE_KEY usa um valor conhecido/público ({value!r}). Com ele qualquer "
            "pessoa forja um cookie de admin e entra sem senha. Gere uma nova com:\n"
            f"  {gerar}"
        )
    if len(value.encode("utf-8")) < COOKIE_KEY_MIN_BYTES:
        return (
            f"COOKIE_KEY tem {len(value.encode('utf-8'))} bytes; o mínimo é "
            f"{COOKIE_KEY_MIN_BYTES} bytes (256 bits, RFC 7518 §3.2). Gere uma com:\n"
            f"  {gerar}"
        )
    return None
