# =========================================================
# LISTAGEM DE MODELOS DE IA
# =========================================================
# O Legaliz.ai roda exclusivamente com modelos locais (Ollama).
# O suporte a provedores externos (OpenAI, Groq, etc.) foi removido.

import ollama_utils


def get_all_models_choices():
    """Lista os modelos disponíveis para seleção (apenas locais/Ollama)."""
    choices = []
    for m in ollama_utils.get_available_models():
        choices.append(f"[Ollama] {m}")
    return choices
