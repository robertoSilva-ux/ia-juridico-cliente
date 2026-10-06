"""Script para criar admin inicial na primeira execução."""
import os

import bcrypt
import psycopg2

from config import DATABASE_URL


def init_admin():
    admin_email = os.getenv("ADMIN_EMAIL", "admin@legaliz.ai")
    admin_password = os.getenv("ADMIN_PASSWORD")

    if not admin_password:
        print("AVISO: ADMIN_PASSWORD não definida. Usando senha padrão 'admin123'.")
        print("DEFINA ADMIN_PASSWORD no .env para segurança.")
        admin_password = "admin123"

    hashed = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Migração: Garante que system_settings.value seja TEXT
                cur.execute("ALTER TABLE system_settings ALTER COLUMN value TYPE TEXT;")

                # Insere admin se não existir
                cur.execute("""
                    INSERT INTO users (email, name, password_hash, role)
                    VALUES (%s, %s, %s, 'admin')
                    ON CONFLICT (email) DO NOTHING
                """, (admin_email, "Administrador", hashed))

                # Insere limite padrão se não existir
                cur.execute("""
                    INSERT INTO system_settings (key, value)
                    VALUES ('max_users', '10')
                    ON CONFLICT (key) DO NOTHING
                """)
                conn.commit()
                print(f"✅ Admin '{admin_email}' verificado/criado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao criar admin: {e}")

if __name__ == "__main__":
    init_admin()
