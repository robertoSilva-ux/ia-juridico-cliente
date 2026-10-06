"""
Detecção de GPU NVIDIA.

Tenta detectar GPU via nvidia-smi (se o container tiver acesso direto).
Caso contrário, usa a variável de ambiente GPU_NAME (opcional) ou reporta
acesso via container Ollama com nome genérico.
"""
import logging
import os
import shutil
import subprocess

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

    # 1. Tenta nvidia-smi direto (se o container tiver acesso à GPU)
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

    # 2. Fallback: verifica se Ollama está respondendo (GPU disponível via container)
    try:
        import urllib.request

        from config import OLLAMA_BASE_URL

        api_url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/version"
        req = urllib.request.Request(api_url, method="GET")
        with urllib.request.urlopen(req, timeout=5):
            pass  # Ollama está respondendo

        result["available"] = True
        result["via_ollama"] = True

        # 2a. Se o usuário definiu GPU_NAME no .env, usa ele
        env_gpu = os.environ.get("GPU_NAME", "").strip()
        if env_gpu:
            result["gpu_name"] = env_gpu
        else:
            result["gpu_name"] = "NVIDIA (via container Ollama)"

        result["error"] = None
    except Exception:
        result["error"] = "GPU não detectada. A GPU está disponível no container do Ollama."

    return result


def format_gpu_status(result: dict) -> str:
    """Retorna string formatada com o status da GPU."""
    if result.get("available") and result.get("via_ollama"):
        gpu = result.get("gpu_name", "NVIDIA (via container Ollama)")
        lines = [f"🎮 **GPU disponível**: {gpu}",
                 "   • Acesso via container Ollama"]
        driver = result.get("driver_version")
        vram = result.get("vram_total_mb")
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