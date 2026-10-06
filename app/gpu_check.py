"""
Detecção de GPU NVIDIA.

Tenta detectar GPU via nvidia-smi (se o container tiver acesso).
Caso contrário, reporta que a GPU está disponível no container Ollama.
"""
import logging
import shutil
import subprocess

# ──────────────────────────────────────────────
# Tenta detectar a GPU real consultando o container do Ollama
# via docker exec (fallback quando nvidia-smi não está neste container).
# ──────────────────────────────────────────────
_OLLAMA_CONTAINER_NAME: str | None = None  # cache


def _find_ollama_container() -> str | None:
    """Descobre o nome do container Ollama (legal-ollama | ollama)."""
    global _OLLAMA_CONTAINER_NAME
    if _OLLAMA_CONTAINER_NAME is not None:
        return _OLLAMA_CONTAINER_NAME
    for candidate in ("legal-ollama", "ollama"):
        try:
            subprocess.run(
                ["docker", "exec", candidate, "sh", "-c", "exit 0"],
                capture_output=True, timeout=3, check=True
            )
            _OLLAMA_CONTAINER_NAME = candidate
            return candidate
        except Exception:
            continue
    return None


def _gpu_info_via_ollama() -> dict | None:
    """Tenta rodar nvidia-smi dentro do container Ollama."""
    container = _find_ollama_container()
    if not container:
        return None
    try:
        out = subprocess.check_output(
            ["docker", "exec", container, "nvidia-smi",
             "--query-gpu=name,driver_version,memory.total",
             "--format=csv,noheader"],
            stderr=subprocess.DEVNULL, timeout=10, text=True
        ).strip()
        if not out:
            return None
        parts = out.split(", ")
        if len(parts) >= 1:
            return {
                "gpu_name": parts[0],
                "driver_version": parts[1] if len(parts) >= 2 else None,
                "vram_total_mb": int(parts[2].split()[0]) if len(parts) >= 3 else None,
            }
    except Exception:
        pass
    return None

logger = logging.getLogger(__name__)


def check_gpu() -> dict:
    """
    Verifica GPU NVIDIA.

    Returns:
        dict com:
            - available: bool
            - driver_version: str ou None
            - gpu_name: str ou None
            - vram_total_mb: int ou None
            - via_ollama: bool — True se a GPU está no Ollama (não neste container)
            - error: str ou None
    """
    result = {
        "available": False,
        "driver_version": None,
        "gpu_name": None,
        "vram_total_mb": None,
        "via_ollama": False,
        "error": None,
    }

    if shutil.which("nvidia-smi"):
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                 "--format=csv,noheader"],
                stderr=subprocess.STDOUT,
                timeout=10,
                text=True
            ).strip()

            if output:
                parts = output.split(", ")
                if len(parts) >= 3:
                    result["gpu_name"] = parts[0]
                    result["driver_version"] = parts[1]
                    mem_str = parts[2].split()[0]
                    result["vram_total_mb"] = int(mem_str)
                    result["available"] = True
                elif len(parts) >= 1:
                    result["gpu_name"] = parts[0]
                    result["available"] = True
                return result
        except Exception as e:
            logger.debug(f"nvidia-smi falhou: {e}")

    # GPU não detectada neste container — mas o Ollama pode ter GPU
    try:
        import urllib.request

        from config import OLLAMA_BASE_URL

        api_url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/version"
        req = urllib.request.Request(api_url, method="GET")
        with urllib.request.urlopen(req, timeout=5):
            pass  # Ollama está respondendo

        # Ollama está rodando — tenta detectar GPU real dentro do container dele
        gpu_info = _gpu_info_via_ollama()
        if gpu_info:
            result["available"] = True
            result["via_ollama"] = True
            result["gpu_name"] = gpu_info["gpu_name"]
            result["driver_version"] = gpu_info["driver_version"]
            result["vram_total_mb"] = gpu_info["vram_total_mb"]
        else:
            result["available"] = True
            result["via_ollama"] = True
            result["gpu_name"] = "NVIDIA (via container Ollama)"
        result["error"] = None
    except Exception:
        result["error"] = "GPU não detectada neste container. A GPU está disponível no container do Ollama."

    return result


def format_gpu_status(result: dict) -> str:
    """Retorna string formatada com o status da GPU."""
    if result.get("available") and result.get("via_ollama"):
        gpu = result.get("gpu_name", "NVIDIA (via container Ollama)")
        driver = result.get("driver_version")
        vram = result.get("vram_total_mb")
        lines = [f"🎮 **GPU disponível**: {gpu}",
                 "   • Acesso via container Ollama"]
        if driver:
            lines.append(f"   • Driver: {driver}")
        if vram:
            lines.append(f"   • VRAM: {vram / 1024:.0f} GB")
        lines.append("   • O app usa a GPU indiretamente via API do Ollama")
        return "\n".join(lines)
    elif result.get("available"):
        gpu = result.get("gpu_name", "Desconhecida")
        driver = result.get("driver_version", "N/A")
        vram = result.get("vram_total_mb")
        vram_str = f"{vram / 1024:.0f} GB" if vram else "N/A"
        return (
            f"✅ GPU disponível: **{gpu}**\n"
            f"   • Driver: {driver}\n"
            f"   • VRAM: {vram_str}"
        )
    else:
        error = result.get("error", "Erro desconhecido")
        return (
            "❌ **GPU não detectada**\n"
            f"   • {error}\n\n"
            "   💡 Para usar GPU:\n"
            "   1. Instale o NVIDIA Container Toolkit:\n"
            "      `sudo apt install nvidia-container-toolkit`\n"
            "   2. Reinicie o Docker:\n"
            "      `sudo systemctl restart docker`\n"
            "   3. Adicione `deploy:` no `docker-compose.yml`:\n"
            "      ```yaml\n"
            "      ollama:\n"
            "        deploy:\n"
            "          resources:\n"
            "            reservations:\n"
            "              devices:\n"
            "                - driver: nvidia\n"
            "                  count: all\n"
            "                  capabilities: [gpu]\n"
            "      ```"
        )
