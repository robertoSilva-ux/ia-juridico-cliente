# Prompt de Implementação — Legaliz.ai v0.4

## Contexto do Projeto

Você está trabalhando no **Legaliz.ai**, um assistente jurídico com IA local (Ollama + pgvector + Streamlit) rodando em Docker. A stack atual é:

- `app/main.py` — Interface Streamlit, navegação e autenticação (`streamlit-authenticator`)
- `app/auth.py` — Lógica de login, hash bcrypt e permissões
- `app/agent.py` — Pipeline RAG: embedding com `nomic-embed-text`, busca vetorial no pgvector, inferência com Llama 3
- `app/ingest.py` — Ingestão de PDFs em chunks
- `app/manage.py` — Gestão da base de documentos
- `database/init.sql` — Schema PostgreSQL com pgvector
- `docker-compose.yml` — Orquestra db (pgvector), ollama, app (streamlit), nginx, dns (dnsmasq), portainer
- `nginx/nginx.conf` — Reverse proxy com suporte a WebSocket para o Streamlit
- `dns/dnsmasq.conf` — DNS local da intranet

Leia **todos os arquivos do projeto** antes de começar qualquer implementação. Entenda o código existente antes de modificá-lo.

---

## Missão

Implemente as melhorias abaixo **em ordem**, validando cada uma antes de passar para a próxima. Ao final de cada item, informe o que foi alterado e qual arquivo foi modificado.

---

## Item 1 — Credenciais via `.env` (Segurança Crítica)

**Problema:** `docker-compose.yml` contém credenciais hardcoded (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`).

**Implementação:**

1. Crie o arquivo `.env` na raiz do projeto com as variáveis:
```
POSTGRES_USER=user
POSTGRES_PASSWORD=password
POSTGRES_DB=legal_db
DATABASE_URL=postgresql://user:password@db:5432/legal_db
OLLAMA_BASE_URL=http://ollama:11434
```

2. Atualize `docker-compose.yml` para referenciar o `.env` usando `${VARIAVEL}` em todos os campos de credenciais e URLs.

3. Crie `.env.example` com os mesmos campos mas com valores placeholder (ex: `POSTGRES_PASSWORD=TROQUE_AQUI`). Este arquivo **será** commitado no repositório.

4. Crie ou atualize `.gitignore` garantindo que `.env` esteja listado e **nunca** seja commitado.

5. Atualize `setup.sh`: antes de subir os containers, verificar se `.env` existe. Se não existir, copiar `.env.example` para `.env` e exibir aviso pedindo para o usuário revisar as credenciais antes de continuar.

**Validação:** `docker compose config` deve resolver todas as variáveis sem erro. Nenhuma credencial deve aparecer literal no `docker-compose.yml`.

---

## Item 2 — Healthchecks e dependências corretas

**Problema:** Se o PostgreSQL ou o Ollama demorarem para subir, o container `app` falha silenciosamente.

**Implementação:**

1. No `docker-compose.yml`, adicione `healthcheck` ao serviço `db`:
```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
  interval: 10s
  timeout: 5s
  retries: 5
```

2. Adicione `healthcheck` ao serviço `ollama`:
```yaml
healthcheck:
  test: ["CMD-SHELL", "ollama list > /dev/null 2>&1 || exit 1"]
  interval: 15s
  timeout: 10s
  retries: 10
  start_period: 30s
```

3. Atualize o serviço `app` para usar `depends_on` com condição:
```yaml
depends_on:
  db:
    condition: service_healthy
  ollama:
    condition: service_healthy
```

4. Faça o mesmo para o `nginx` depender do `app` com `condition: service_started`.

**Validação:** `docker compose up -d` deve mostrar os containers subindo na ordem correta, com o `app` aguardando o banco e o ollama ficarem healthy.

---

## Item 3 — Limite de recursos dos containers

**Problema:** O Llama 3 pode consumir toda a RAM do servidor, derrubando os outros serviços.

**Implementação:**

No `docker-compose.yml`, adicione `deploy.resources` em cada serviço:

```yaml
# ollama — maior alocação pois roda o LLM
ollama:
  deploy:
    resources:
      limits:
        memory: 6G
      reservations:
        memory: 2G

# app — streamlit é leve
app:
  deploy:
    resources:
      limits:
        memory: 512M
        cpus: "1.0"

# db — banco precisa de memória consistente
db:
  deploy:
    resources:
      limits:
        memory: 512M

# nginx e dns — mínimo
nginx:
  deploy:
    resources:
      limits:
        memory: 64M

dns:
  deploy:
    resources:
      limits:
        memory: 64M
```

Ajuste os valores de `ollama` de acordo com a RAM total disponível no servidor (a soma de todos os limites não deve ultrapassar 80% da RAM total).

**Validação:** `docker stats` após subir os containers deve mostrar os limites aplicados.

---

## Item 4 — Forçar troca de senha admin no primeiro acesso

**Problema:** O `README.md` documenta publicamente as credenciais padrão `admin@legaliz.ai / admin123`, que nunca são forçadas a trocar.

**Implementação:**

1. Na tabela `users` (em `database/init.sql`), adicione a coluna:
```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE;
```
Garanta que o usuário admin inicial seja inserido com `must_change_password = TRUE`.

2. Em `auth.py`, crie a função `check_must_change_password(email)` que consulta esse campo.

3. Em `main.py`, após o login bem-sucedido, antes de renderizar qualquer página:
   - Chame `check_must_change_password()` com o email da sessão.
   - Se retornar `True`, redirecione para uma tela exclusiva de troca de senha (não permita navegar para outras páginas enquanto não trocar).
   - A tela deve solicitar nova senha e confirmação, validar mínimo de 8 caracteres, e após salvar com bcrypt, atualizar `must_change_password = FALSE`.

4. No Painel Admin, ao criar um novo usuário ou resetar senha, sempre definir `must_change_password = TRUE`.

**Validação:** Ao logar com `admin@legaliz.ai / admin123` pela primeira vez, o sistema deve bloquear na tela de troca de senha antes de qualquer outra navegação.

---

## Item 5 — Multi-tenancy: isolamento de documentos por usuário

**Problema:** Todos os documentos na tabela `documents` são visíveis para todos os usuários no RAG.

**Implementação:**

1. Em `database/init.sql`, adicione a coluna na tabela `documents`:
```sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS scope VARCHAR(10) DEFAULT 'private' CHECK (scope IN ('private', 'global'));
```
- `scope = 'private'`: visível apenas para o `owner_id`.
- `scope = 'global'`: visível para todos (usado pelo Admin para leis e jurisprudência).

2. Em `ingest.py`, ao inserir chunks na tabela `documents`, receba e salve o `user_id` da sessão atual e defina `scope = 'private'`.

3. Em `agent.py`, na query de busca vetorial, adicione o filtro:
```sql
WHERE (scope = 'global' OR owner_id = :current_user_id)
```
O `current_user_id` deve ser passado como parâmetro para a função de busca — **nunca** interpolado diretamente na query (use parâmetros bind para evitar SQL injection).

4. Em `manage.py`, filtre a listagem de documentos pelo mesmo critério: o usuário comum vê apenas os seus; o admin vê todos.

5. No Painel Admin, ao exibir documentos, adicione um indicador visual de `scope` (🔒 Privado / 🌐 Global) e permita que o admin altere o scope de qualquer documento.

**Validação:** Crie dois usuários distintos, suba um PDF com cada um, e confirme que ao perguntar no chat, cada usuário só recebe contexto dos seus próprios documentos e dos globais.

---

## Item 6 — Backup automatizado do PostgreSQL

**Problema:** O volume `postgres_data` não tem rotina de backup. Uma falha de disco apaga tudo.

**Implementação:**

1. Adicione um novo serviço no `docker-compose.yml`:
```yaml
backup:
  image: postgres:16-alpine
  container_name: legal-backup
  environment:
    PGPASSWORD: ${POSTGRES_PASSWORD}
  volumes:
    - ./backups:/backups
    - ./scripts/backup.sh:/backup.sh:ro
  entrypoint: ["crond", "-f", "-d", "8"]
  depends_on:
    db:
      condition: service_healthy
  restart: unless-stopped
```

2. Crie `scripts/backup.sh`:
```bash
#!/bin/sh
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="/backups/legaliz_${TIMESTAMP}.sql.gz"
pg_dump -h db -U ${POSTGRES_USER} ${POSTGRES_DB} | gzip > "$BACKUP_FILE"
echo "Backup criado: $BACKUP_FILE"
# Manter apenas os últimos 7 backups
ls -t /backups/*.sql.gz | tail -n +8 | xargs rm -f
```

3. Configure o cron dentro do container para rodar o backup diariamente às 2h da manhã.

4. Crie a pasta `backups/` na raiz do projeto e adicione `backups/*.sql.gz` ao `.gitignore`.

5. No Painel Admin do Streamlit, adicione uma seção "Backup" que mostre a lista de backups disponíveis com data/hora e tamanho, e um botão para acionar um backup manual imediato via `subprocess` chamando o script.

**Validação:** Após subir, aguardar ou acionar manualmente e confirmar que um arquivo `.sql.gz` aparece na pasta `backups/`.

---

## Item 7 — Auditoria de perguntas

**Problema:** Não há registro de quem perguntou o quê — requisito de conformidade para sistemas jurídicos.

**Implementação:**

1. Em `database/init.sql`, crie a tabela:
```sql
CREATE TABLE IF NOT EXISTS audit_log (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  user_email VARCHAR(255),
  question TEXT NOT NULL,
  response_summary TEXT,
  sources_used TEXT[],
  created_at TIMESTAMP DEFAULT NOW()
);
```

2. Em `agent.py`, após gerar cada resposta, salve no `audit_log`:
   - `user_id` e `user_email` da sessão ativa
   - a pergunta completa
   - os primeiros 500 caracteres da resposta como `response_summary`
   - os nomes dos arquivos usados como fontes em `sources_used`

3. No Painel Admin, adicione uma aba "Auditoria" que exiba os logs em uma tabela paginada (20 registros por página), com filtros por usuário e por período (date range).

4. Adicione botão de exportação dos logs filtrados para CSV.

**Validação:** Fazer uma pergunta no chat e confirmar que o registro aparece na aba Auditoria do Painel Admin.

---

## Item 8 — Modelo de IA configurável via Painel Admin

**Problema:** O modelo `llama3` está hardcoded em `agent.py`. Trocar de modelo exige edição de código.

**Implementação:**

1. Em `database/init.sql`, insira na tabela `system_settings`:
```sql
INSERT INTO system_settings (key, value) VALUES ('llm_model', 'llama3') ON CONFLICT (key) DO NOTHING;
INSERT INTO system_settings (key, value) VALUES ('embed_model', 'nomic-embed-text') ON CONFLICT (key) DO NOTHING;
```

2. Em `agent.py`, substitua os nomes de modelo hardcoded por leitura dinâmica da tabela `system_settings` a cada inicialização do agente. Use cache de 60 segundos para não consultar o banco a cada pergunta.

3. No Painel Admin, adicione uma seção "Configurações de IA" com:
   - Um `st.selectbox` que lista os modelos disponíveis no Ollama (consultando `http://ollama:11434/api/tags` via requests).
   - Campos separados para modelo de linguagem e modelo de embedding.
   - Botão "Salvar" que persiste a escolha na tabela `system_settings`.
   - Aviso visual: "Trocar o modelo de embedding requer re-indexação de todos os documentos."

**Validação:** Trocar o modelo no Painel Admin e confirmar que a próxima pergunta no chat usa o novo modelo consultando os logs do Ollama.

---

## Convenções obrigatórias durante toda a implementação

- **Idioma:** Toda string visível ao usuário em `pt-BR`. Logs internos podem ser em inglês.
- **SQL seguro:** Nunca interpolar variáveis diretamente em queries. Sempre usar parâmetros bind (`:param` com psycopg2 ou `%s`).
- **Senhas:** Nunca logar, nunca retornar em API response, sempre processar via bcrypt.
- **Erros:** Todo bloco de acesso ao banco deve ter `try/except` com mensagem amigável ao usuário via `st.error()` e log técnico no console.
- **Migrations:** Toda alteração de schema deve usar `IF NOT EXISTS` ou `IF NOT EXISTS` para ser idempotente — o `init.sql` pode ser executado mais de uma vez.
- **Commits:** Ao final de cada item, liste exatamente quais arquivos foram criados ou modificados.

---

## Ordem de execução recomendada

```
Item 1 → Item 2 → Item 3 → Item 4 → Item 5 → Item 6 → Item 7 → Item 8
```

Não pule itens. Cada um pode depender do anterior (ex: Item 5 depende de conhecer o `user_id` que vem do sistema de autenticação já estabilizado nos itens anteriores).

Ao concluir todos os itens, atualize o `TASKS.md` marcando os itens do roadmap como concluídos e incrementando a versão do MVP.
