import json
import logging

import requests

from config import OLLAMA_BASE_URL

# =========================================================
# UTILITÁRIOS DE FORMATAÇÃO
# =========================================================

def human_size(num_bytes):
    """Formata bytes em humano (B/KB/MB/GB)."""
    try:
        num_bytes = float(num_bytes)
    except (TypeError, ValueError):
        return "—"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024 or unit == "TB":
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{int(num_bytes)} B"
        num_bytes /= 1024


# =========================================================
# CONEXÃO
# =========================================================

def is_ollama_connected():
    """Check if Ollama service is responding."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception as e:
        logging.error(f"Ollama não está respondendo: {e}")
        return False


# =========================================================
# LISTAGEM / CONSULTA
# =========================================================

def _safe_get(url, timeout=5):
    """GET com tratamento de erro padronizado."""
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logging.error(f"Erro em GET {url}: {e}")
    return None


def get_available_models():
    """List available models using Ollama /api/tags endpoint"""
    data = _safe_get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
    if data:
        models = data.get("models", [])
        return [m["name"] for m in models]
    return []


def list_models(detailed=False):
    """Lista modelos instalados. Retorna lista de dicts.

    detailed=True inclui metadados (tamanho, família, parâmetros, quantização,
    data de modificação). Cada item tem no mínimo 'name'.
    """
    data = _safe_get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
    if not data:
        return []
    models = data.get("models", [])
    if not detailed:
        return [m["name"] for m in models]
    result = []
    for m in models:
        details = m.get("details", {}) or {}
        result.append({
            "name": m.get("name"),
            "size": m.get("size"),
            "modified_at": m.get("modified_at"),
            "family": details.get("family"),
            "parameter_size": details.get("parameter_size"),
            "quantization_level": details.get("quantization_level"),
            "context_length": details.get("context_length"),
        })
    return result


def get_running_models():
    """List currently loaded models using /api/ps"""
    data = _safe_get(f"{OLLAMA_BASE_URL}/api/ps", timeout=3)
    if data:
        models = data.get("models", [])
        return [m["name"] for m in models]
    return []


def get_running_details():
    """Lista modelos carregados com detalhes de VRAM/contexto via /api/ps."""
    data = _safe_get(f"{OLLAMA_BASE_URL}/api/ps", timeout=5)
    if not data:
        return []
    result = []
    for m in data.get("models", []):
        result.append({
            "name": m.get("name"),
            "size_vram": m.get("size_vram"),
            "size": m.get("size"),
            "context_length": m.get("context_length"),
            "expires_at": m.get("expires_at"),
        })
    return result


# =========================================================
# AÇÕES DE CICLO DE VIDA
# =========================================================

def delete_model(model_name):
    """Remove um modelo do Ollama (DELETE /api/delete)."""
    try:
        resp = requests.delete(
            f"{OLLAMA_BASE_URL}/api/delete",
            json={"model": model_name},
            timeout=30,
        )
        if resp.status_code in (200, 204):
            return True, "Modelo removido."
        return False, f"Falha ao remover (HTTP {resp.status_code}): {resp.text[:200]}"
    except Exception as e:
        logging.error(f"Erro ao remover modelo {model_name}: {e}")
        return False, str(e)


def stop_model(model_name):
    """Unload a model by sending a generate request with keep_alive=0"""
    try:
        # According to Ollama docs, to unload a model, request generate or chat with keep_alive=0
        requests.post(f"{OLLAMA_BASE_URL}/api/generate", json={
            "model": model_name,
            "keep_alive": 0
        }, timeout=5)
        return True, f"Modelo '{model_name}' descarregado."
    except Exception as e:
        logging.error(f"Erro ao parar o modelo {model_name}: {e}")
        return False, str(e)


def warmup_model(model_name, keep_alive="5m"):
    """Warmup model by sending a minimal generate request."""
    try:
        requests.post(f"{OLLAMA_BASE_URL}/api/generate", json={
            "model": model_name,
            "prompt": "",
            "keep_alive": keep_alive,
        }, timeout=1)
        return True, f"Aquecimento solicitado para '{model_name}'."
    except requests.exceptions.ReadTimeout:
        pass  # Esperado: carregar modelo leva tempo
        return True, f"Carregando '{model_name}' em segundo plano…"
    except Exception as e:
        logging.error(f"Erro no warmup do modelo {model_name}: {e}")
        return False, str(e)


def pull_model(model_name: str):
    """Faz pull (download/atualização) de um modelo do Ollama, com progresso.

    É um gerador: cada iteração emite um dict do stream /api/pull. Em caso de
    falha, emite {"error": mensagem}.
    """
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/pull",
            json={"name": model_name},
            stream=True,
            timeout=3600,
        )
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                yield json.loads(line)
    except Exception as e:
        logging.error(f"Erro ao baixar modelo {model_name}: {e}")
        yield {"error": str(e)}


def pull_model_blocking(model_name: str, progress_cb=None):
    """Envolve pull_model para uso em chamadas que esperam conclusão.

    progress_cb(percent: float|None, status: str) é chamado a cada atualização.
    Retorna (ok: bool, mensagem: str).
    """
    last_status = "iniciando…"
    try:
        for update in pull_model(model_name):
            if "error" in update:
                return False, update["error"]
            if progress_cb is not None:
                if "completed" in update and update.get("total"):
                    progress_cb(update["completed"] / update["total"], update.get("status", "baixando…"))
                else:
                    progress_cb(None, update.get("status", last_status))
            if update.get("status"):
                last_status = update["status"]
            if update.get("status") == "success":
                return True, f"Modelo '{model_name}' pronto."
    except Exception as e:
        logging.error(f"Erro ao baixar modelo {model_name}: {e}")
        return False, str(e)
    return False, "Não foi possível concluir o download do modelo."
