"""Script para criar o admin inicial na primeira execução.

Exige ADMIN_EMAIL/ADMIN_PASSWORD no .env. O schema do banco não semeia mais
credencial nenhuma (antes, `database/init.sql` inseria 'admin@legaliz.ai' com o
hash de 'admin123' fixo) e este script também NÃO cai em senha padrão: sem senha
aceitável, ele falha em vez de criar um admin adivinhável
(ver docs/REVISAO_SEGURANCA.md, P0-2).
"""
import os
import sys

import bcrypt
import psycopg2
from config import DATABASE_URL

# Valores já públicos (documentação/repositório) ou padrões óbvios: nunca aceitar,
# porque são os primeiros que qualquer atacante tenta.
SENHAS_PROIBIDAS = frozenset({"admin123", "admin", "password", "changeme", "legaliz", "12345678"})
MIN_SENHA = 8


def validar_senha_admin(senha: str) -> str | None:
    """Retorna a mensagem de erro da senha do admin, ou None se estiver aceitável."""
    if not senha:
        return (
            "ADMIN_PASSWORD não definida no .env. Defina uma senha forte "
            f"(mínimo {MIN_SENHA} caracteres) antes de subir o sistema."
        )
    if senha.lower() in SENHAS_PROIBIDAS:
        return (
            f"ADMIN_PASSWORD usa um valor padrão/público ({senha!r}), que é o primeiro "
            "que qualquer pessoa tenta. Escolha outra senha no .env."
        )
    if len(senha) < MIN_SENHA:
        return f"ADMIN_PASSWORD tem {len(senha)} caracteres; o mínimo é {MIN_SENHA}."
    return None


def init_admin() -> int:
    """Cria o admin inicial se ainda não existir. Devolve o exit code do processo."""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@legaliz.ai")
    admin_password = os.getenv("ADMIN_PASSWORD", "")

    problema = validar_senha_admin(admin_password)
    if problema:
        print(f"❌ {problema}")
        print("   O admin inicial NÃO foi criado: o banco não deve nascer com credencial conhecida.")
        return 1

    hashed = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Migração: Garante que system_settings.value seja TEXT
                cur.execute("ALTER TABLE system_settings ALTER COLUMN value TYPE TEXT;")

                # Insere admin se não existir (idempotente; senha existente é preservada)
                cur.execute("""
                    INSERT INTO users (email, name, password_hash, role)
                    VALUES (%s, %s, %s, 'admin')
                    ON CONFLICT (email) DO NOTHING
                    RETURNING id
                """, (admin_email, "Administrador", hashed))
                criado = cur.fetchone() is not None

                # Insere limite padrão se não existir
                cur.execute("""
                    INSERT INTO system_settings (key, value)
                    VALUES ('max_users', '10')
                    ON CONFLICT (key) DO NOTHING
                """)
                conn.commit()

        if criado:
            print(f"✅ Admin '{admin_email}' criado com a senha definida em ADMIN_PASSWORD.")
        else:
            print(f"ℹ️  Admin '{admin_email}' já existia — senha atual preservada.")
            print("   Se esse banco ainda tem a senha padrão antiga ('admin123'), troque-a agora:")
            print("   painel → Painel Admin → Gestão de Usuários → Resetar Senha.")
        return 0
    except Exception as e:
        print(f"❌ Erro ao criar admin: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(init_admin())
