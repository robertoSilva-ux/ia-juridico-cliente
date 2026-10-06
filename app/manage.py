import psycopg2

from config import DATABASE_URL


def list_documents(user_id=None, is_admin=False):
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            if is_admin:
                # Admin vê todos os documentos, com info de escopo
                cur.execute("""
                    SELECT
                        COALESCE(d.file_name, 'SEM_NOME') as name,
                        MAX(d.uploaded_at) as uploaded_at,
                        COUNT(*) as chunks,
                        d.scope
                    FROM documents d
                    GROUP BY d.file_name, d.scope
                    ORDER BY d.scope ASC, MAX(d.uploaded_at) DESC NULLS LAST
                """)
            else:
                # Usuário vê seus documentos + os globais
                cur.execute("""
                    SELECT
                        COALESCE(d.file_name, 'SEM_NOME') as name,
                        MAX(d.uploaded_at) as uploaded_at,
                        COUNT(*) as chunks,
                        d.scope
                    FROM documents d
                    WHERE d.owner_id = %s OR d.scope = 'global'
                    GROUP BY d.file_name, d.scope
                    ORDER BY d.scope ASC, MAX(d.uploaded_at) DESC NULLS LAST
                """, (user_id,))
            return cur.fetchall()


def delete_document(file_name, user_id=None, is_admin=False):
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            if is_admin:
                # Admin pode deletar qualquer documento
                if file_name == 'SEM_NOME':
                    cur.execute("DELETE FROM documents WHERE file_name IS NULL")
                else:
                    cur.execute("DELETE FROM documents WHERE file_name = %s", (file_name,))
            else:
                # Usuário só deleta seus próprios documentos privados
                if file_name == 'SEM_NOME':
                    cur.execute("DELETE FROM documents WHERE file_name IS NULL AND owner_id = %s", (user_id,))
                else:
                    cur.execute(
                        "DELETE FROM documents WHERE file_name = %s AND owner_id = %s AND scope = 'private'",
                        (file_name, user_id)
                    )
            conn.commit()


def update_document_scope(file_name, new_scope, user_id):
    """Admin altera o escopo de um documento (private <-> global)."""
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET scope = %s WHERE file_name = %s",
                (new_scope, file_name)
            )
            conn.commit()
