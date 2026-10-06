"""Wrapper de embeddings com recuperação assimétrica para o nomic-embed-text.

O `nomic-embed-text` (v1.5, 768 dims) foi treinado com prefixos de tarefa
("asymmetric retrieval"): documentos devem ser vetorizados com o prefixo
`search_document: ` e consultas com `search_query: `. Sem os prefixos o modelo
cai para um embedding "genérico" e a similaridade semântica degrada, trazendo
resultados por sentido vago em vez da intenção exata.

Este wrapper aplica os prefixos automaticamente ANTES de chamar o Ollama,
mantendo o texto cru (sem prefixo) armazenado/consultado pelo resto do código.

IMPORTANTE: ao ativar este wrapper (ou trocar o modelo), toda a base vetorial
precisa ser REINDEXADA (ver scripts/reindex_embeddings.py), pois os vetores
antigos foram gerados sem prefixo e ficariam desalinhados com o novo espaço.
"""


from langchain_ollama import OllamaEmbeddings

# Prefixo para documentos/chunks (indexação).
DOCUMENT_PREFIX = "search_document: "
# Prefixo para consultas (busca/query).
QUERY_PREFIX = "search_query: "


class NomicOllamaEmbeddings(OllamaEmbeddings):
    """OllamaEmbeddings com prefixos assimétricos do nomic-embed-text."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vetoriza documentos/chunks aplicando o prefixo `search_document:`."""
        prefixed = [f"{DOCUMENT_PREFIX}{t}" for t in texts]
        return super().embed_documents(prefixed)

    def embed_query(self, text: str) -> list[float]:
        """Vetoriza a consulta aplicando o prefixo `search_query:`."""
        return super().embed_query(f"{QUERY_PREFIX}{text}")

    def embed_document(self, text: str) -> list[float]:
        """Vetoriza um ÚNICO texto no formato de documento.

        Use para textos que se parecem com o conteúdo indexado (ex.: o
        documento hipotético gerado pelo HyDE), e NÃO para a pergunta do
        usuário. Delegado a `embed_documents` para reaproveitar o prefixo
        `search_document:`.
        """
        return self.embed_documents([text])[0]
