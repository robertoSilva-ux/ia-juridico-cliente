# ADR-0001 — O segredo de assinatura do cookie de sessão vem do ambiente

- **Status:** aceito
- **Data:** 2026-10-16
- **Achado relacionado:** P0-1 em [`../REVISAO_SEGURANCA.md`](../REVISAO_SEGURANCA.md)

## Contexto

A biblioteca de autenticação (`streamlit-authenticator`) assina o cookie de sessão com
JWT/HS256 e recebe a chave de assinatura no construtor. No código, essa chave era o
literal `"legal_ai_key"`, versionado — e o repositório é público.

O impacto não é teórico: quem conhece a chave gera um JWT com
`{"username": "admin@legaliz.ai", "exp_date": <futuro>}` e o `get_cookie()` da biblioteca
aceita, porque valida apenas assinatura, presença de `username` e expiração. Verificado
assinando um token com a chave do repositório e decodificando com o próprio código da
biblioteca: **aceito** (com aviso de chave curta — 12 bytes contra os 32 recomendados pela
RFC 7518 §3.2).

## Decisão

A chave passa a ser lida do ambiente (`COOKIE_KEY`), **sem valor padrão**, e a aplicação
**recusa iniciar** quando ela está ausente, tem menos de 32 bytes ou é um valor conhecido
(`legal_ai_key`, `some_key`, `changeme`…). A validação é uma função pura em
`app/config.py` (`cookie_key_problem`) e o portão fica em `app/main.py`, antes de qualquer
acesso ao banco. O `setup.sh` também valida a variável antes de subir os containers.

## Consequências

- Forjar sessão deixa de ser possível sem conhecer um segredo que nunca foi publicado.
- **A chave passa a ser uma obrigação operacional**: sem ela o sistema não sobe (falha
  alta e explicada, com o comando de geração na mensagem) — é intencional.
- Trocar a chave invalida as sessões ativas; ela precisa ser **estável** entre reinícios.
- Cada instalação de cliente tem a sua chave (documentado no `.env.example` e no
  `.env.cliente`).

## Alternativas consideradas

1. **Manter um padrão forte no código** (ex.: gerado no primeiro boot e gravado em disco) —
   descartado: cria estado oculto, dificulta reprovisionamento e transforma um erro de
   configuração em comportamento implícito.
2. **Trocar a biblioteca de autenticação** (sessão própria, OIDC) — anotado como pendência
   de produto no backlog (P2-6); não resolve por si o problema de ter um segredo
   versionado em qualquer camada.
3. **Apenas avisar (warning) quando a chave for fraca** — descartado: o produto nasce com
   um bypass de autenticação se ninguém olhar o log.
