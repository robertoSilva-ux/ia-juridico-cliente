#!/bin/bash
# Retomada da bancada legaliz.ai — pós-reboot 16:50
# Falta: qwen3:4b (12 iterações de 20) + llama3:latest (20x, baseline) + consolidação
set -u
cd /home/roberto/codigos/legaliz.ai/legaliz.ai-mvp
REL=/app/eval/relatorios

echo "=== subindo containers ==="
docker compose up -d 2>&1 | tail -2
sleep 8

echo "=== START $(date +%H:%M:%S) qwen3:4b cont (12 iterações restantes) ==="
docker compose exec -e LLM_MODEL=qwen3:4b -e BENCH_MODEL=qwen3:4b \
  -e BENCH_NUM_CTX=0 -e BENCH_ITERS=12 \
  -e BENCH_QUIZ="$REL/quiz_loop_q6.json" -e BENCH_OUT="$REL/bench_qwen3_cont.json" \
  -T app python3 eval/benchmark_models.py || echo "FAIL qwen3_cont"

# funde 8 (pré-reboot) + 12 (pós-reboot) em bench_qwen3_ctxdef_20x.json
python3 - <<'PYEOF'
import json
base = json.load(open('app/eval/relatorios/bench_qwen3_ctxdef_20x.json'))
cont = json.load(open('app/eval/relatorios/bench_qwen3_cont.json'))
for i, r in enumerate(cont['runs']):
    r['iter'] = len(base['runs']) + i + 1
base['runs'].extend(cont['runs'])
base['iters'] = 20
base['resumed_note'] = '8 runs pre-reboot + 12 pos-reboot'
json.dump(base, open('app/eval/relatorios/bench_qwen3_ctxdef_20x.json', 'w'),
          ensure_ascii=False, indent=1)
print('qwen3 fundido:', len(base['runs']), 'runs')
PYEOF
rm -f app/eval/relatorios/bench_qwen3_cont.json

echo "=== START $(date +%H:%M:%S) llama3:latest 20x (baseline CPU) ==="
docker compose exec -e LLM_MODEL=llama3:latest -e BENCH_MODEL=llama3:latest \
  -e BENCH_NUM_CTX=0 -e BENCH_ITERS=20 \
  -e BENCH_QUIZ="$REL/quiz_loop_q6.json" -e BENCH_OUT="$REL/bench_llama3_ctxdef_20x.json" \
  -T app python3 eval/benchmark_models.py || echo "FAIL llama3"

echo "BANCADA_COMPLETA $(date +%H:%M:%S)"
python3 app/eval/consolidate_bench.py 2>&1 | tail -14
