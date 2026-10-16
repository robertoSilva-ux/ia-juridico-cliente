# ADR-0003 — O schema não semeia credencial; o admin inicial exige senha explícita

- **Status:** aceito
- **Data:** 2026-10-16
- **Achado relacionado:** P0-2 em [`../REVISAO_SEGURANCA.md`](../REVISAO_SEGURANCA.md)

## Contexto

`database/init.sql` inseria o administrador inicial com um hash bcrypt fixo no arquivo.
Confirmado por execução: o hash corresponde a **`admin123`**, e o `setup.sh` ainda imprimia
essa credencial no fim da instalação. Todo banco novo nascia, portanto, com credencial de
administrador conhecida — num produto que guarda documentos jurídicos.

## Decisão

1. O schema (`init.sql`) **não cria usuário nenhum**. Schema descreve estrutura, não dado
   de negócio nem credencial.
2. O admin inicial é criado por `app/init_admin.py`, que **falha** (exit code 1) quando
   `ADMIN_PASSWORD` está ausente, tem menos de 8 caracteres ou é um valor previsível
   (`admin123`, `admin`, `password`…). Nada de fallback silencioso.
3. O script é idempotente (`ON CONFLICT DO NOTHING`): rodar de novo **não** reseta a senha
   de quem já existe — e avisa explicitamente quando detecta que a instalação pode ainda
   ter a senha padrão antiga, indicando o caminho de troca pelo painel.
4. `setup.sh` valida `POSTGRES_PASSWORD`, `DATABASE_URL`, `ADMIN_PASSWORD` e `COOKIE_KEY`
   **antes** de subir os containers, recusa os placeholders dos templates e confere que a
   senha embutida em `DATABASE_URL` concorda com `POSTGRES_PASSWORD`.

## Consequências

- Não existe caminho em que o produto suba com credencial adivinhável.
- A instalação passou a exigir uma decisão consciente (definir a senha) — o que é o
  objetivo; o custo é um passo a mais no provisionamento, coberto pelo `setup.sh`.
- Bases já existentes que ainda tenham a credencial padrão **não** são corrigidas
  automaticamente (trocar senha de admin sem pedir seria pior): o script avisa e o
  backlog registra a rotação como item operacional (P0-6).

## Alternativas consideradas

1. **Manter a semeadura com senha aleatória impressa no log** — descartado: log de
   instalação vaza, e a senha acabaria em histórico de terminal/CI.
2. **Forçar troca de senha no primeiro login** — melhor como recurso de produto, mas exige
   tela nova e não resolve o problema de a credencial existir; anotado como evolução
   possível.
3. **Deixar o admin padrão e confiar no README** — descartado: foi o que aconteceu, e a
   documentação afirmava o contrário do que o código fazia.
