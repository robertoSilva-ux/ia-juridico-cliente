import copy
import logging
import re
import time

import psycopg2
import psycopg2.extras
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pgvector.psycopg2 import register_vector

from config import DATABASE_URL, EMBED_BATCH_SIZE
from database import get_db_connection
from legal_parser import enrich_chunk_metadata, parse_chunk

logger = logging.getLogger(__name__)


# Cabeçalho de dispositivo legal. O lookahead preserva o marcador no chunk
# seguinte; a âncora de linha evita separar referências como "art. 83" no meio
# de uma frase.
_ARTICLE_START = re.compile(
    r"(?<!\w)Art\.?\s*\d+[º°]?\s*[.\-–—]",
    re.IGNORECASE,
)


# Marcadores de dispositivo cujo espaçamento interno NÃO deve ser colapsado.
# O splitter e o legal_parser dependem do padrão "Art. 83"; colapsar o espaço
# entre "Art." e o número quebraria a detecção do dispositivo.
_ARTICLE_MARKER = re.compile(r"(?<=\bArt\.)\s+", re.IGNORECASE)


def normalize_whitespace(text):
    """Normaliza whitespace preservando a estrutura do dispositivo jurídico.

    O PyPDFLoader produz texto com hifenização de quebra de linha, múltiplos
    espaços, tabulações e espaços não separáveis (NBSP). Esse ruído degrada o
    embedding (o nomic-embed-text vê "aposentado- ria" como token diferente de
    "aposentadoria") e desperdiça orçamento de tokens do chunk.

    Regras aplicadas, nesta ordem:
      1. NBSP e outros espaços Unicode -> espaço ASCII simples.
      2. Hífen com quebra de linha -> remove a quebra, PRESERVA o hífen
         (ver justificativa na regra 2, abaixo).
      3. Espaços/tabs repetidos -> um único espaço.
      4. Espaços em torno de quebras de linha -> removidos.
      5. Três ou mais quebras -> no máximo duas (preserva parágrafos).
      6. Separador canônico de dispositivo: "Art.83"/"Art.  83" -> "Art. 83".

    As regras 2 e 6 protegem o chunking jurídico: a regex ``_ARTICLE_START``
    depende de um separador exato entre "Art." e o número para detectar o
    dispositivo, e os compostos hifenizados do domínio não podem ser unidos.
    """
    if not text:
        return text

    # 1. Espaços Unicode (NBSP, thin space, ideográficos) -> espaço simples.
    text = text.replace("\u00a0", " ").replace("\u2009", " ").replace("\u3000", " ")

    # 2. Hifenização de quebra de linha. O hífen colado na letra anterior com
    #    quebra logo depois é AMBÍGUO: pode ser hífen de quebra ("aposen-\ntadoria"
    #    = "aposentadoria") ou hífen legítimo da palavra ("salario-\nfamilia"
    #    = "salario-familia"). Sem dicionário não há como distinguir.
    #    DECISÃO: manter o hífen e apenas remover a quebra. No domínio jurídico
    #    os compostos hifenizados ("salário-família", "regime-próprio") são
    #    semanticamente críticos; corrompê-los é pior que deixar uma palavra
    #    partida, que o embedding absorve como ruído menor.
    text = re.sub(r"([A-Za-zÀ-ÿ])-\s*\n\s*", r"\1-", text)

    # 3. Espaços e tabs repetidos -> um espaço.
    text = re.sub(r"[ \t]+", " ", text)

    # 4. Espaços grudados em quebras de linha -> removidos em ambas as bordas.
    text = re.sub(r" *\n *", "\n", text)

    # 5. Sequências de 3+ quebras -> no máximo duas (mantém separação de parágrafo).
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 6. Garante o separador canônico entre "Art."/"art." e o número. Cobre dois
    #    casos que o PyPDFLoader produz e que quebram a detecção do dispositivo:
    #      - espaço duplicado:  "Art.  83" -> "Art. 83"
    #      - colado sem espaço: "Art.83"   -> "Art. 83"
    #    O lookahead (?=\d) evita tocar em "art." encerrando frase sem número.
    text = re.sub(r"(?<=\bArt\.)\s*(?=\d)", " ", text, flags=re.IGNORECASE)

    return text.strip()


def _copy_document(document, content):
    """Copia um Document mantendo metadata e substituindo page_content."""
    chunk = copy.copy(document)
    chunk.page_content = content.strip()
    return chunk


def split_legal_documents(documents, chunk_size=1000, chunk_overlap=100):
    """Divide PDFs jurídicos sem misturar dispositivos consecutivos.

    Os documentos do ``PyPDFLoader`` são páginas. O estado do dispositivo é
    mantido entre páginas: uma página sem novo ``Art. N`` continua o artigo
    anterior, e só um novo cabeçalho encerra a seção anterior. Artigos longos
    são subdivididos depois, sempre dentro da própria seção.
    """
    bounded_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    texts = [getattr(document, "page_content", "") for document in documents]
    if not documents or not all(isinstance(text, str) for text in texts):
        return bounded_splitter.split_documents(documents)
    if not any(_ARTICLE_START.search(text or "") for text in texts):
        return bounded_splitter.split_documents(documents)

    sections = []
    current_document = None
    current_text = []

    def flush_current():
        if current_document is not None and current_text:
            content = "\n".join(current_text).strip()
            if content:
                sections.append(_copy_document(current_document, content))

    for document, text in zip(documents, texts, strict=True):
        matches = list(_ARTICLE_START.finditer(text or ""))
        if not matches:
            # Cabeçalho, rodapé ou continuação de artigo na página seguinte.
            if current_document is not None and text.strip():
                current_text.append(text)
            continue

        prefix_end = matches[0].start()
        if prefix_end and text[:prefix_end].strip():
            if current_document is None:
                current_document = document
            current_text.append(text[:prefix_end])

        for index, match in enumerate(matches):
            # Um preâmbulo antes do primeiro Art. deve acompanhar o artigo,
            # não virar um chunk isolado. Já um artigo anterior em andamento
            # precisa ser fechado antes do novo cabeçalho.
            has_article = _ARTICLE_START.search("\n".join(current_text)) if current_text else None
            if current_document is not None and current_text and has_article:
                flush_current()
            current_document = document
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            article_text = text[match.start():end]
            if index == 0 and current_text and not has_article:
                current_text.append(article_text)
            else:
                current_text = [article_text]

    flush_current()
    return [chunk for section in sections
            for chunk in bounded_splitter.split_documents([section])]


def process_pdf(file_path, progress_cb=None):
    """Carrega e fragmenta um PDF aplicando normalização de whitespace.

    A normalização roda por página, ANTES do split jurídico, para que o
    chunking veja texto limpo e a detecção de "Art. N" opere sobre o formato
    canônico. Se normalizássemos depois do split, o texto armazenado e o texto
    embedado divergiriam do que o parser jurídico analisou.

    ``progress_cb`` (opcional) recebe floats 0.0->1.0 para a fase de extração.
    """
    loader = PyPDFLoader(file_path)
    documents = loader.load()

    total = len(documents) or 1
    for index, document in enumerate(documents):
        document.page_content = normalize_whitespace(document.page_content)
        if progress_cb is not None:
            progress_cb((index + 1) / total * 0.5)  # extração = 50% do trabalho

    return split_legal_documents(documents)


def ingest_document(
    file_path,
    embeddings_model,
    file_name,
    owner_id=None,
    scope='private',
    batch_size=EMBED_BATCH_SIZE,
    progress_cb=None,
    chunks=None,
):
    """Ingere UM documento do início ao fim, reportando progresso global.

    Unifica o caminho até então duplicado entre `process_pdf` + reindexação:
    extração, normalização, split, dedup, embedding e inserção.

    O progresso é decomposto em duas fases para que a barra seja honesta:
      - extração/normalização/split ....... 0.0 -> 0.5
      - embeddings + inserção no banco ..... 0.5 -> 1.0

    ``progress_cb`` recebe floats 0.0->1.0. ``chunks`` permite reutilizar uma
    fragmentação já feita (ex.: retomada), evitando reparsear o PDF.

    Devolve o número de chunks efetivamente indexados.
    """
    def _report(fraction):
        if progress_cb is not None:
            progress_cb(max(0.0, min(1.0, fraction)))

    if chunks is None:
        # Extração = metade do trabalho. process_pdf já reporta 0.0->0.5 via
        # callback; o wrapper abaixo reescala para manter a proporção.
        chunks = process_pdf(
            file_path,
            progress_cb=(lambda f: _report(f)) if progress_cb else None,
        )
    elif progress_cb is not None:
        _report(0.5)

    total = 0
    for fraction in store_in_postgres(
        chunks,
        embeddings_model,
        file_name,
        owner_id=owner_id,
        scope=scope,
        batch_size=batch_size,
    ):
        # store_in_postgres reporta 0.0->1.0 da fase de armazenamento; remapeia
        # para a metade final da barra global.
        _report(0.5 + 0.5 * fraction)
        total += 1

    _report(1.0)
    return total


def _embed_with_retry(embeddings_model, texts, max_retries=3, base_delay=2.0):
    if not texts:
        return []
    last_exc = None
    for attempt in range(max_retries):
        try:
            return embeddings_model.embed_documents(texts)
        except Exception as e:
            last_exc = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    'Embedding falhou na tentativa %d/%d (%s). Retentando em %.1fs...',
                    attempt + 1, max_retries, e, delay,
                )
                time.sleep(delay)
    logger.error('Embedding falhou apos %d tentativas: %s', max_retries, last_exc)
    raise last_exc


def _get_or_create_source(conn, file_name, owner_id=None, scope='private'):
    from legal_parser import build_title, parse_file_name
    meta = parse_file_name(file_name)
    title = build_title(meta)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sources (file_name, title, tipo_doc, numero_doc, ano_doc, owner_id, scope) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (file_name) DO UPDATE SET "
            "    title = COALESCE(EXCLUDED.title, sources.title), "
            "    tipo_doc = COALESCE(EXCLUDED.tipo_doc, sources.tipo_doc), "
            "    numero_doc = COALESCE(EXCLUDED.numero_doc, sources.numero_doc), "
            "    ano_doc = COALESCE(EXCLUDED.ano_doc, sources.ano_doc), "
            "    owner_id = COALESCE(EXCLUDED.owner_id, sources.owner_id), "
            "    scope = COALESCE(EXCLUDED.scope, sources.scope) "
            "RETURNING id",
            (file_name, title, meta['tipo'], meta['numero'], meta['ano'], owner_id, scope),
        )
        row = cur.fetchone()
        return row[0] if row else None


def store_in_postgres(chunks, embeddings_model, file_name, owner_id=None, scope='private', batch_size=EMBED_BATCH_SIZE):
    if not chunks:
        return

    total_chunks = len(chunks)

    # Filtra chunks com NUL (0x00) — o pgvector/Postgres rejeita o caractere
    valid = [c for c in chunks if '\x00' not in c.page_content]
    if len(valid) != total_chunks:
        logger.warning(f"{total_chunks - len(valid)} chunks descartados por NUL (0x00).")
    total_chunks = len(valid)
    if total_chunks == 0:
        return

    # --- Dedup: remove chunks cujo conteúdo já existe no banco p/ o mesmo arquivo ---
    # Evita reindexar um documento que já foi ingerido (ex.: upload duplicado),
    # poupando calls de embedding e mantendo o TOP_K livre de cópias.
    deduped = _filter_existing(valid, file_name)
    skipped = total_chunks - len(deduped)
    if skipped:
        logger.info(f"{skipped} chunks já existentes no banco — pulados (dedup).")
    total_chunks = len(deduped)
    if total_chunks == 0:
        logger.info("Nenhum chunk novo a indexar (tudo já existia).")
        return
    valid = deduped

    # Conectar ao postgres usando gerenciador de contexto
    with psycopg2.connect(DATABASE_URL) as conn:
        register_vector(conn)
        source_id = _get_or_create_source(conn, file_name, owner_id=owner_id, scope=scope)
        with conn.cursor() as cur:
            for i in range(0, total_chunks, batch_size):
                batch = valid[i:i + batch_size]
                texts = [chunk.page_content for chunk in batch]

                # Gerar embeddings para o lote atual
                embeddings = _embed_with_retry(embeddings_model, texts)

                # Preparar os dados para inserção com metadados jurídicos
                data_list = []
                for chunk, embedding in zip(batch, embeddings, strict=True):
                    # Extrair metadados jurídicos do chunk
                    legal_meta = parse_chunk(chunk.page_content, file_name)
                    enriched_metadata = enrich_chunk_metadata(chunk.page_content, file_name, chunk.metadata)

                    data_list.append((
                        file_name,
                        chunk.page_content,
                        psycopg2.extras.Json(enriched_metadata),
                        embedding,
                        owner_id,
                        scope,
                        legal_meta['artigo'],
                        legal_meta['paragrafo'],
                        legal_meta['inciso'],
                        legal_meta['tipo_doc'],
                        legal_meta['numero_doc'],
                        legal_meta['ano_doc'],
                        source_id,
                    ))

                # Inserção do lote com colunas jurídicas
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO documents
                       (file_name, content, metadata, embedding, owner_id, scope,
                        artigo, paragrafo, inciso, tipo_doc, numero_doc, ano_doc, source_id)
                       VALUES %s""",
                    data_list
                )
                conn.commit()

                # Reportar progresso
                progress = min((i + batch_size) / total_chunks, 1.0)
                yield progress


def _filter_existing(chunks, file_name):
    """Filtra chunks cujo conteúdo já está no banco para o mesmo file_name.

    Consulta os conteúdos já indexados uma única vez (IN) e remove duplicatas.
    Isso evita reindexar documentos ingeridos mais de uma vez.
    """
    if not chunks:
        return []
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content FROM documents WHERE file_name = %s",
                    (file_name,),
                )
                existing = {row[0] for row in cur.fetchall()}
        if not existing:
            return chunks
        return [c for c in chunks if c.page_content not in existing]
    except Exception as e:
        # Se a consulta falhar, indexa tudo (não bloqueia a ingestão por causa do dedup)
        logger.warning(f"Dedup não executado (falha ao consultar existentes): {e}")
        return chunks
