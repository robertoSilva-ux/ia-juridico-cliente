#!/usr/bin/env python3
"""Testes unitários do sweep_tuning.py (Task 9).

Testa a lógica de consolidação do run_sweep SEM rodar subprocessos reais:
mocka subprocess.run e valida que cada combinação vira uma env var limpa,
que o resultado correto é coletado do arquivo de saída, e que erros do
subprocesso são capturados em vez de abortar a varredura.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_orig = {}

def setUpModule():
    # evita import real de config/agent (não necessários pra run_sweep)
    for m in ['config', 'agent', 'database', 'run_eval']:
        _orig[m] = sys.modules.get(m)

def tearDownModule():
    for m, v in _orig.items():
        if v is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = v


class TestRunSweep(unittest.TestCase):
    def _load_sweep(self):
        import importlib.util
        eval_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / 'eval'
        spec = importlib.util.spec_from_file_location("sweep_tuning", eval_dir / 'sweep_tuning.py')
        mod = importlib.util.module_from_spec(spec)
        # APP_DIR/SCRIPT_DIR apontam para o eval dir real
        mod.APP_DIR = eval_dir.parent
        mod.SCRIPT_DIR = eval_dir
        spec.loader.exec_module(mod)
        return mod

    def _fake_proc(self, returncode=0, stdout='DONE\n', stderr=''):
        p = MagicMock()
        p.returncode = returncode
        p.stdout = stdout
        p.stderr = stderr
        return p

    def test_gera_arquivo_de_saida_por_combinacao(self, tmp_path=None):
        import tempfile
        mod = self._load_sweep()
        tmp = Path(tempfile.mkdtemp())
        quiz = Path(tempfile.mkdtemp()) / 'quiz.json'
        quiz.write_text(json.dumps({'questions': []}))

        def fake_run(cmd, env=None, **kw):
            # escreve o arquivo de saída esperado e simula sucesso
            out = Path(env['OUT_PATH'])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({'top_k': int(env['TOP_K']),
                                       'threshold': float(env['SIMILARITY_THRESHOLD']),
                                       'source_recall': 0.833}))
            return self._fake_proc(0)

        with patch.object(mod.subprocess, 'run', side_effect=fake_run):
            results = mod.run_sweep([5, 15], [0.8], quiz, tmp)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['top_k'], 5)
        self.assertEqual(results[1]['top_k'], 15)
        self.assertEqual(results[0]['source_recall'], 0.833)

    def test_env_contem_topk_e_threshold_limpos(self):
        import tempfile
        mod = self._load_sweep()
        tmp = Path(tempfile.mkdtemp())
        quiz = Path(tempfile.mkdtemp()) / 'quiz.json'
        quiz.write_text(json.dumps({'questions': []}))
        seen = {}

        def fake_run(cmd, env=None, **kw):
            seen['TOP_K'] = env['TOP_K']
            seen['THRESHOLD'] = env['SIMILARITY_THRESHOLD']
            out = Path(env['OUT_PATH'])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({'top_k': int(env['TOP_K']), 'threshold': float(env['SIMILARITY_THRESHOLD'])}))
            return self._fake_proc(0)

        with patch.object(mod.subprocess, 'run', side_effect=fake_run):
            mod.run_sweep([30], [0.6], quiz, tmp)

        self.assertEqual(seen['TOP_K'], '30')
        self.assertEqual(seen['THRESHOLD'], '0.6')

    def test_captura_erro_de_subprocesso(self):
        import tempfile
        mod = self._load_sweep()
        tmp = Path(tempfile.mkdtemp())
        quiz = Path(tempfile.mkdtemp()) / 'quiz.json'
        quiz.write_text(json.dumps({'questions': []}))

        with patch.object(mod.subprocess, 'run', return_value=self._fake_proc(returncode=1, stderr='boom')), \
             patch.object(mod.sys.stderr, 'write'):
            results = mod.run_sweep([5], [0.8], quiz, tmp)

        self.assertEqual(len(results), 1)
        self.assertIn('error', results[0])


if __name__ == '__main__':
    unittest.main()
