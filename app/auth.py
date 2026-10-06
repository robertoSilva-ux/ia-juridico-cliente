import re

import bcrypt
import psycopg2
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL
from database import get_db_connection

# =========================================================
# VALIDAÇÃO DE INPUT
# =========================================================

def validate_email(email: str) -> bool:
    """Valida formato de email com regex simples."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip())) if email else False


def validate_password(password: str) -> tuple:
    """Valida senha: mínimo 8 caracteres. Retorna (valido, mensagem)."""
    if not password or len(password) < 8:
        return False, "A senha deve ter no mínimo 8 caracteres."
    return True, ""


# =========================================================
# FUNÇÕES PRINCIPAIS
# =========================================================

def get_all_users_for_auth():
    """Retorna um dicionário no formato exigido pelo streamlit-authenticator."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, email, name, password_hash, role FROM users")
            rows = cur.fetchall()

            credentials = {"usernames": {}}
            for row in rows:
                credentials["usernames"][row["email"]] = {
                    "email": row["email"],
                    "name": row["name"],
                    "password": row["password_hash"],
                    "role": row["role"],
                    "id": row["id"]
                }
            return credentials


def add_user(email, name, password, role='user'):
    """Cria um novo usuário com senha hasheada. Valida entradas antes de criar."""
    # Validar email
    if not validate_email(email):
        return False, "Email inválido. Informe um email no formato correto (ex: usuario@dominio.com)."

    # Validar nome
    if not name or not name.strip():
        return False, "O nome não pode estar vazio."

    # Validar senha
    valid_pwd, msg_pwd = validate_password(password)
    if not valid_pwd:
        return False, msg_pwd

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (email, name, password_hash, role) VALUES (%s, %s, %s, %s)",
                    (email, name, hashed, role)
                )
                conn.commit()
        return True, "Usuário criado com sucesso."
    except Exception as e:
        return False, str(e)


def update_password(email, new_password):
    """Atualiza a senha de um usuário."""
    hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE email = %s",
                (hashed, email)
            )
            conn.commit()


def get_system_setting(key):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row[0] if row else None


def set_system_setting(key, value):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_settings (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value
            """, (key, str(value)))
            conn.commit()


def get_user_count():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            return cur.fetchone()[0]


def get_user_id(email):
    """Retorna o ID do usuário a partir do email."""
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            return row[0] if row else None
