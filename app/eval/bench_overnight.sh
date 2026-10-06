#!/bin/bash
# Bancada noturna legaliz.ai — 2026-09-12
# 20 iterações q6 por modelo (default ctx) + variantes num_ctx 8192
# + quiz completo x3 para os 3 modelos rápidos.
# Ordem: rápido -> lento, para ter dados úteis desde as primeiras horas.
set -u
cd /home/roberto/codigos/legaliz.ai/legaliz.ai-mvp

QWEN2507="hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"
REL=/app/eval/relatorios
HOST_REL=~/codigos/legaliz.ai/legaliz.ai-mvp/app/eval/relatorios

run() { # $1=model $2=ctx $3=iters $4=quiz $5=tag
  echo "=== START $(date +%H:%M:%S) model=$1 ctx=$2 iters=$3 tag=$5 ==="
  docker compose exec \
    -e LLM_MODEL="$1" -e BENCH_MODEL="$1" \
    -e BENCH_NUM_CTX="$2" -e BENCH_ITERS="$3" \
    -e BENCH_QUIZ="$4" -e BENCH_OUT="$REL/bench_$5.json" \
    -T app python3 eval/benchmark_models.py || echo "FAIL $5"
  echo "=== END $(date +%H:%M:%S) tag=$5 ==="
}

# 1) Qwen3-2507: default ctx + 8192 + quiz completo x3
run "$QWEN2507" 0 20 "$REL/quiz_loop_q6.json" qwen2507_ctxdef_20x
run "$QWEN2507" 8192 20 "$REL/quiz_loop_q6.json" qwen2507_ctx8192_20x
run "$QWEN2507" 0 1 "$REL/quiz_completo_v2.json" qwen2507_quizfull_r1
run "$QWEN2507" 0 1 "$REL/quiz_completo_v2.json" qwen2507_quizfull_r2
run "$QWEN2507" 0 1 "$REL/quiz_completo_v2.json" qwen2507_quizfull_r3

# 2) gemma3:4b-it-qat: default + 8192 + quiz completo x3
run gemma3:4b-it-qat 0 20 "$REL/quiz_loop_q6.json" gemma3_ctxdef_20x
run gemma3:4b-it-qat 8192 20 "$REL/quiz_loop_q6.json" gemma3_ctx8192_20x
run gemma3:4b-it-qat 0 1 "$REL/quiz_completo_v2.json" gemma3_quizfull_r1
run gemma3:4b-it-qat 0 1 "$REL/quiz_completo_v2.json" gemma3_quizfull_r2
run gemma3:4b-it-qat 0 1 "$REL/quiz_completo_v2.json" gemma3_quizfull_r3

# 3) phi4-mini:3.8b: default + 8192 + quiz completo x3
run phi4-mini:3.8b 0 20 "$REL/quiz_loop_q6.json" phi4_ctxdef_20x
run phi4-mini:3.8b 8192 20 "$REL/quiz_loop_q6.json" phi4_ctx8192_20x
run phi4-mini:3.8b 0 1 "$REL/quiz_completo_v2.json" phi4_quizfull_r1
run phi4-mini:3.8b 0 1 "$REL/quiz_completo_v2.json" phi4_quizfull_r2
run phi4-mini:3.8b 0 1 "$REL/quiz_completo_v2.json" phi4_quizfull_r3

# 4) qwen3:4b (thinking): só default (conhecido lento; 8192 só piora)
run qwen3:4b 0 20 "$REL/quiz_loop_q6.json" qwen3_ctxdef_20x

# 5) llama3:8B baseline (vaza pra CPU — referência de lentidão)
run llama3:latest 0 20 "$REL/quiz_loop_q6.json" llama3_ctxdef_20x

echo "BANCADA_COMPLETA $(date +%H:%M:%S)"

# Consolidação automática no fim (host-side, só lê os JSON)
echo "=== CONSOLIDANDO ==="
python3 app/eval/consolidate_bench.py 2>&1 | tail -12
