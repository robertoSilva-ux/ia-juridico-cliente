import logging

import psycopg2
from config import DATABASE_URL

logger = logging.getLogger(__name__)

# Sentinela usada pela UI para chunks legados sem nome de arquivo (main.py).
SEM_NOME = 'SEM_NOME'


def _resolve_target_owner(is_admin, user_id, owner_id):
    """Define de QUEM é o documento alvo de uma operação de gerenciamento.

    Escopo e exclusão são atributos do arquivo de UM usuário. Quando o filtro era
    só por `file_name`, um clique em "Tornar Global" promovia também o arquivo
    privado homônimo de TODOS os outros usuários — nomes como "peticao.pdf" se
    repetem na prática (ver docs/REVISAO_SEGURANCA.md, P0-3). Regra agora:

    - usuário comum age apenas sobre os próprios documentos;
    - admin age sobre os próprios por padrão, ou sobre o dono informado
      explicitamente (`owner_id`) — que é o que o painel passa ao listar.
    """
    if user_id is None:
        raise ValueError('Operação de gerenciamento exige o user_id de quem age.')
    if is_admin and owner_id is not None:
        return owner_id
    if not is_admin and owner_id is not None and owner_id != user_id:
        raise PermissionError('Usuário comum não pode agir sobre documentos de outro dono.')
    return user_id


def list_documents(user_id=None, is_admin=False):
    """Lista documentos agrupados por (arquivo, escopo, dono).

    O dono entra no GROUP BY e no retorno porque dois usuários podem ter arquivos
    com o mesmo nome: sem separá-los, o painel do admin não distinguia um do
    outro e as ações de escopo/exclusão acertavam os dois de uma vez.
    """
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            if is_admin:
                # Admin vê todos os documentos, com escopo e dono
                cur.execute("""
                    SELECT
                        COALESCE(d.file_name, 'SEM_NOME') as name,
                        MAX(d.uploaded_at) as uploaded_at,
                        COUNT(*) as chunks,
                        d.scope,
                        d.owner_id,
                        u.email as owner_email
                    FROM documents d
                    LEFT JOIN users u ON u.id = d.owner_id
                    GROUP BY d.file_name, d.scope, d.owner_id, u.email
                    ORDER BY d.scope ASC, d.owner_id ASC NULLS FIRST,
                             MAX(d.uploaded_at) DESC NULLS LAST
                """)
            else:
                # Usuário vê seus documentos + os globais
                cur.execute("""
                    SELECT
                        COALESCE(d.file_name, 'SEM_NOME') as name,
                        MAX(d.uploaded_at) as uploaded_at,
                        COUNT(*) as chunks,
                        d.scope,
                        d.owner_id,
                        u.email as owner_email
                    FROM documents d
                    LEFT JOIN users u ON u.id = d.owner_id
                    WHERE d.owner_id = %s OR d.scope = 'global'
                    GROUP BY d.file_name, d.scope, d.owner_id, u.email
                    ORDER BY d.scope ASC, d.owner_id ASC NULLS FIRST,
                             MAX(d.uploaded_at) DESC NULLS LAST
                """, (user_id,))
            return cur.fetchall()


def delete_document(file_name, user_id=None, is_admin=False, owner_id=None):
    """Remove os chunks de um documento, sempre com escopo por dono.

    Usuário comum remove apenas documento privado próprio; admin remove o de um
    dono específico (o seu, por padrão). Antes, o delete do admin era
    `WHERE file_name = %s`: apagar "peticao.pdf" apagava o arquivo privado de
    todos os usuários que tivessem um arquivo com esse nome.

    `SEM_NOME` é o caso especial dos chunks legados, sem nome de arquivo e sem
    dono (pré-tenant): limpeza de manutenção, restrita a `owner_id IS NULL` para
    não tocar em linhas de ninguém.

    Retorna o número de chunks efetivamente removidos (0 = nada casou).
    """
    target_owner = _resolve_target_owner(is_admin, user_id, owner_id)
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            if file_name == SEM_NOME:
                if is_admin:
                    cur.execute("DELETE FROM documents WHERE file_name IS NULL AND owner_id IS NULL")
                else:
                    cur.execute("DELETE FROM documents WHERE file_name IS NULL AND owner_id = %s", (user_id,))
            elif is_admin:
                cur.execute(
                    "DELETE FROM documents WHERE file_name = %s AND owner_id = %s",
                    (file_name, target_owner)
                )
            else:
                # Usuário só deleta seus próprios documentos privados
                cur.execute(
                    "DELETE FROM documents WHERE file_name = %s AND owner_id = %s AND scope = 'private'",
                    (file_name, target_owner)
                )
            deleted = cur.rowcount
            conn.commit()
            return deleted


def update_document_scope(file_name, new_scope, user_id=None, is_admin=False, owner_id=None):
    """Altera o escopo (private <-> global) do documento de UM dono.

    `owner_id` identifica o dono do arquivo alvo; por padrão é o próprio usuário
    que age. Também sincroniza `sources.scope` na MESMA transação: as duas
    tabelas respondem à pergunta "o documento do dono X é global?" e divergir
    significa que a recuperação e o painel discordam sobre o que é público.

    Retorna o número de chunks alterados (0 = nada casou — nenhum documento do
    dono alvo com esse nome).
    """
    if new_scope not in ('private', 'global'):
        raise ValueError(f"Escopo inválido: {new_scope!r} (esperado 'private' ou 'global').")
    target_owner = _resolve_target_owner(is_admin, user_id, owner_id)
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET scope = %s WHERE file_name = %s AND owner_id = %s",
                (new_scope, file_name, target_owner)
            )
            changed = cur.rowcount
            cur.execute(
                "UPDATE sources SET scope = %s WHERE file_name = %s AND owner_id = %s",
                (new_scope, file_name, target_owner)
            )
            conn.commit()
            return changed
