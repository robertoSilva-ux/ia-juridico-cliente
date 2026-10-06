# ⚖️ Legaliz.ai - Assistente Jurídico Inteligente (MVP)

O **Legaliz.ai** é um MVP de uma plataforma jurídica que utiliza Inteligência Artificial local para auxiliar advogados na análise de documentos, pesquisa jurisprudencial e redação de peças.

---

## ✨ Funcionalidades

- **🔐 Autenticação Segura:** Sistema de login por email e senha com senhas criptografadas (bcrypt).
- **👥 Controle de Acesso (RBAC):** Diferenciação entre usuários comuns e administradores.
- **💬 Chat Jurídico com Contexto:** Converse com seus documentos. A IA prioriza as informações dos PDFs enviados e cita as fontes.
- **📂 Gerenciamento de Documentos:** Tela para upload e exclusão de documentos indexados.
- **📊 Painel Administrativo:** Gestão de usuários, reset de senhas e configuração de limites do sistema.
- **🔒 Privacidade Total:** Todo o processamento de IA é feito localmente via Ollama.

---

## 🛠️ Stack Tecnológica

- **Interface:** [Streamlit](https://streamlit.io/) + `streamlit-authenticator`
- **Orquestração de IA:** [LangChain](https://www.langchain.com/)
- **Banco de Dados:** [PostgreSQL](https://www.postgresql.org/) + [pgvector](https://github.com/pgvector/pgvector)
- **Modelos de IA:** [Ollama](https://ollama.com/) (Llama 3 + Nomic Embed)
- **Segurança:** `bcrypt` para hash de senhas.

---

## 🚀 Instalação e Configuração

Siga os passos abaixo para instalar o Legaliz.ai em um novo servidor ou máquina local (Linux recomendado).

### 1. Pré-requisitos de Hardware e Software

- **Sistema Operacional:** Linux (Ubuntu 22.04+ recomendado) ou Windows com WSL2.
- **Memória RAM:** Mínimo de **8GB** (necessário para rodar o modelo Llama 3 junto com o sistema).
- **Espaço em Disco:** Mínimo de **40GB** (para comportar imagens Docker e modelos de IA).
- **GPU (Opcional):** O sistema detecta automaticamente se há uma GPU NVIDIA disponível. Caso contrário, rodará via CPU (mais lento, mas funcional).
  - Se for usar GPU, instale o [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

### 2. Passo a Passo de Instalação

```bash
# Atualize o sistema
sudo apt update && sudo apt upgrade -y

# Instale o Docker (caso não tenha)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# (Opcional) Instale o NVIDIA Container Toolkit se for usar GPU
# Siga as instruções oficiais: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
# sudo apt-get install -y nvidia-container-toolkit

# Clone o repositório
git clone https://github.com/seu-usuario/legal-ai-mvp.git
cd legal-ai-mvp

# Dê permissão de execução ao script de setup
chmod +x setup.sh

# Execute o setup automatizado
./setup.sh
```

### 3. O que o Setup faz?
O script `setup.sh` automatiza as seguintes tarefas:
1. Sobe os containers do **PostgreSQL (pgvector)**, **Ollama** e a **Aplicação Streamlit**.
2. Aguarda a inicialização do serviço de IA.
3. Baixa automaticamente os modelos `llama3` (texto) e `nomic-embed-text` (embeddings).

### 4. Acesso ao Sistema

- **URL:** [http://localhost:8501](http://localhost:8501)
- **Credenciais Admin Padrão:**
  - **Login:** `admin@legaliz.ai`
  - **Senha:** `admin123`

---

## 🛠️ Stack Tecnológica e Portas
| Serviço | Tecnologia | Porta |
| :--- | :--- | :--- |
| Interface / App | Streamlit | `8501` |
| Banco de Dados | PostgreSQL + pgvector | `5439` |
| IA Engine | Ollama | `11434` |

---

## 📂 Estrutura do Projeto

```text
├── app/                # Código fonte Python
│   ├── main.py         # Interface, navegação e autenticação
│   ├── auth.py         # Lógica de login, hash e permissões
│   ├── agent.py        # Agente RAG e Retrieval
│   ├── ingest.py       # Ingestão de documentos
│   └── manage.py       # Gestão da base de dados
├── database/           # Scripts SQL (init.sql)
└── docs/               # AGENTS.md, README.md, TASKS.md, TESTING.md
```

---

## 🗺️ Roadmap de Evolução

- [x] **Sistema de Login:** Autenticação e Roles (Admin/User).
- [x] **Painel Admin:** Gestão de usuários e limites.
- [ ] **Isolamento de Contexto:** Garantir que um usuário não veja documentos de outro.
- [ ] **Redator de Petições:** Gerador estruturado em formato `.docx`.

---

## 📄 Licença
Fins demonstrativos de MVP.
