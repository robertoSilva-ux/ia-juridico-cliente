# Decisões de arquitetura (ADR) — Legaliz.ai

Registro das decisões que moldam o produto, do mais recente para o mais antigo, para
consulta posterior: **por que** algo é como é, o que foi descartado e o que a decisão
custa. Cada arquivo é imutável depois de aceito — mudar de ideia significa um ADR novo
que substitui o anterior (o antigo passa a `substituído por ADR-XXXX`).

| ADR | Assunto | Status |
|:---|:---|:---|
| [0001](0001-segredo-do-cookie-vem-do-ambiente.md) | Segredo de assinatura do cookie de sessão vem do ambiente, com validação de força | aceito |
| [0002](0002-isolamento-por-dono.md) | Isolamento entre clientes por dono do documento (escopo, exclusão, dedup, `sources`) | aceito |
| [0003](0003-admin-inicial-sem-semeadura.md) | O schema não semeia credencial; o admin inicial exige `ADMIN_PASSWORD` | aceito |
| [0004](0004-ambiente-de-desenvolvimento-hibrido.md) | Ambiente de desenvolvimento híbrido (banco em container, Ollama e app nativos) | aceito |
| [0005](0005-dependencias-pinadas-e-verificacao.md) | Dependências pinadas com lock e verificação automatizada obrigatória | aceito |
| [0006](0006-retorno-de-acao-sobrevive-ao-rerun.md) | Retorno de ação vai por `flash()`, não por `st.success()` antes de `st.rerun()` | aceito |
| [0007](0007-fact-check-exige-par-numero-ano.md) | Citação de norma exige par número+ano no contexto (identidade de lei conferida) | aceito |
| [0008](0008-modelo-por-orcamento-de-vram.md) | Modelo padrão escolhido por orçamento de VRAM medido (`phi4-mini:3.8b` @8192) | aceito |
| [0009](0009-portao-de-resposta-e-recusa-honesta.md) | Portão de resposta: suficiência, lastro no fragmento citado e recusa honesta | aceito |
| [0010](0010-preambulo-e-conteudo-indexavel.md) | O preâmbulo é conteúdo indexável e rotulado (preâmbulo por página, identidade lida das páginas) | aceito |
| [0011](0011-corpus-oficial-em-texto.md) | Corpus oficial entra como texto (conversão fora da app, página sintética), não como PDF gerado | aceito |
| [0012](0012-escopo-por-norma-e-teto-por-documento.md) | Recuperação escopa pela norma que a pergunta nomeia e limita trechos por documento | aceito |
| [0013](0013-retirada-do-peso-por-regime.md) | O peso por regime sai do caminho de recuperação (flag desligada por padrão) | aceito |

## Formato

```markdown
# ADR-XXXX — Título no imperativo

- **Status:** proposto | aceito | substituído por ADR-YYYY
- **Data:** AAAA-MM-DD

## Contexto      — o problema e as forças em jogo (inclui o que foi medido)
## Decisão       — o que passa a valer
## Consequências — o que ganhamos e o que aceitamos perder
## Alternativas  — o que foi descartado e por quê
```

Decisões de **produto e de cliente** (TLS, retenção de dados, OCR) não entram aqui como
aceitas: ficam em [`../BACKLOG.md`](../BACKLOG.md) com status `🅿️` até haver decisão de
quem responde por elas.
