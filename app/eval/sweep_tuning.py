#!/usr/bin/env python3
"""Varredura de tuning: TOP_K x SIMILARITY_THRESHOLD (Task 9).

Roda o quiz (eval/quiz.json) para cada combinação de TOP_K x SIMILARITY_THRESHOLD
e consolida as métricas de recuperação isolada (source_hit e article_hit) num
relatório comparativo.

Por que subprocesso por combinação: agent.py captura TOP_K/SIMILARITY_THRESHOLD
como DEFAULT de função no import (from config import (...)). Recarregar config no
mesmo processo não altera esses defaults. Logo, cada combinação roda num processo
Python novo, com a env var setada antes de qualquer import, garantindo valores limpos.

Uso (de dentro do container app):
  python3 eval/sweep_tuning.py --top-k 5 15 30 --threshold 0.80 0.60
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent

_RUNNER = '''
import os, sys, json
from pathlib import Path
sys.path.insert(0, os.environ['APP_DIR'])
sys.path.insert(0, os.environ['SCRIPT_DIR'])
import run_eval as re_eval
from agent import get_response

quiz_path = Path(os.environ['QUIZ_PATH'])
top_k = int(os.environ['TOP_K'])
threshold = float(os.environ['SIMILARITY_THRESHOLD'])

quiz = re_eval.load_quiz(quiz_path)
combo = {'top_k': top_k, 'threshold': threshold, 'questions': []}
total_source = 0
hit_source = 0
total_article = 0
hit_article = 0

for q in quiz['questions']:
    resp = get_response(q['question'])
    sources = resp.get('sources', [])
    expected_files = [f for f in q.get('expected_files', []) if f]
    files = [s.get('file_name') for s in sources if s.get('file_name')]
    files_low = {f.lower(): f for f in files}
    sh = [f for f in expected_files
          if any(f.lower() in fl or fl in f.lower() for fl in files_low)]
    if expected_files:
        total_source += len(expected_files)
        hit_source += len(sh)
    expected_article = q.get('expected_article')
    ah = None
    if expected_article is not None:
        artigos = {str(s.get('artigo')) for s in sources
                   if s.get('artigo') is not None}
        total_article += 1
        ah = str(expected_article) in artigos
        if ah:
            hit_article += 1
    combo['questions'].append({
        'id': q['id'],
        'source_hit': len(sh),
        'source_total': len(expected_files),
        'article_hit': ah,
    })

combo['source_recall'] = round(hit_source / total_source, 3) if total_source else None
combo['article_accuracy'] = round(hit_article / total_article, 3) if total_article else None

out_path = os.environ['OUT_PATH']
Path(out_path).parent.mkdir(parents=True, exist_ok=True)
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(combo, f, ensure_ascii=False)
print('DONE source_recall=' + str(combo.get('source_recall')) + ' article_acc=' + str(combo.get('article_accuracy')))
'''


def run_sweep(top_k_values, threshold_values, quiz_path, tmp_dir):
    results = []
    for top_k in top_k_values:
        for threshold in threshold_values:
            out_path = tmp_dir / f'sweep_{top_k}_{threshold}.json'
            env = dict(os.environ)
            env['TOP_K'] = str(top_k)
            env['SIMILARITY_THRESHOLD'] = str(threshold)
            env['APP_DIR'] = str(APP_DIR)
            env['SCRIPT_DIR'] = str(SCRIPT_DIR)
            env['QUIZ_PATH'] = str(quiz_path)
            env['OUT_PATH'] = str(out_path)

            print(f'[sweep] TOP_K={top_k} THRESHOLD={threshold} ...', flush=True)
            proc = subprocess.run(
                [sys.executable, '-c', _RUNNER],
                env=env, capture_output=True, text=True,
            )
            if proc.returncode != 0:
                print(f'  ERRO returncode={proc.returncode}', flush=True)
                print('  stderr tail:', proc.stderr.strip()[-800:], flush=True)
                results.append({'top_k': top_k, 'threshold': threshold, 'error': proc.stderr.strip()[-500:]})
                continue
            last = ''
            lines_out = proc.stdout.strip().splitlines()
            if lines_out:
                last = lines_out[-1]
            print(f'  {last}', flush=True)
            if out_path.exists():
                results.append(json.loads(out_path.read_text(encoding='utf-8')))
            else:
                results.append({'top_k': top_k, 'threshold': threshold, 'error': 'sem saida'})
    return results


def main():
    ap = argparse.ArgumentParser(description='Sweep TOP_K x SIMILARITY_THRESHOLD')
    ap.add_argument('--top-k', nargs='+', type=int, default=[5, 15, 30])
    ap.add_argument('--threshold', nargs='+', type=float, default=[0.80, 0.60])
    ap.add_argument('--quiz', type=str, default='quiz.json')
    args = ap.parse_args()

    quiz_path = SCRIPT_DIR / args.quiz
    if not quiz_path.exists():
        print(f'Quiz não encontrado: {quiz_path}', file=sys.stderr)
        sys.exit(1)

    tmp_dir = SCRIPT_DIR / 'relatorios' / 'sweep_tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)

    results = run_sweep(args.top_k, args.threshold, quiz_path, tmp_dir)

    out = SCRIPT_DIR / 'relatorios' / 'sweep_tuning.json'
    payload = {'generated_at': datetime.now().isoformat(), 'results': results}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print()
    print('=== TABELA COMPARATIVA ===')
    print('TOP_K | THRESHOLD | source_recall | article_acc')
    print('-' * 54)
    for r in results:
        sr = r.get('source_recall')
        aa = r.get('article_accuracy')
        err = r.get('error')
        if err:
            print(f"{r['top_k']:>5} | {r['threshold']:>9} | ERRO: {err[:40]}")
        else:
            print(f"{r['top_k']:>5} | {r['threshold']:>9} | {str(sr):>13} | {str(aa):>11}")
    print(f'Relatório: {out}')


if __name__ == '__main__':
    main()
