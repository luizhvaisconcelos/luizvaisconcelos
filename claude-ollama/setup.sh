#!/usr/bin/env bash
# Setup: Claude Code + Ollama local (RTX 3090) - Linux (systemd)
# Uso: bash setup.sh [modelo] [contexto]
set -euo pipefail

MODEL="${1:-qwen3.8-27b-ag-TurboFCFusion-MTP:latest}"
CTX="${2:-32768}"

# 1. Pre-requisitos
command -v ollama >/dev/null || { echo "Ollama nao encontrado."; exit 1; }
command -v claude >/dev/null || { echo "Claude Code nao encontrado. Instale: curl -fsSL https://claude.ai/install.sh | bash"; exit 1; }
echo "Ollama: $(ollama --version)"
ollama list | grep -qF "$MODEL" || { echo "Modelo '$MODEL' nao existe em 'ollama list'."; exit 1; }

# 2. Config do servidor via drop-in systemd (escuta so em localhost)
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/claude-local.conf >/dev/null <<EOF
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_CONTEXT_LENGTH=${CTX}"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
for _ in $(seq 1 30); do curl -sf http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done

# 3. Launcher claude-local (env vars so valem para este processo)
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/claude-local" <<EOF
#!/usr/bin/env bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:11434
export ANTHROPIC_AUTH_TOKEN=ollama
export ANTHROPIC_API_KEY=
export ANTHROPIC_MODEL="${MODEL}"
export ANTHROPIC_SMALL_FAST_MODEL="${MODEL}"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
exec claude "\$@"
EOF
chmod +x "$HOME/.local/bin/claude-local"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc";; esac

# 4. Teste do endpoint compativel com Anthropic
echo "Testando /v1/messages ..."
if curl -sf --max-time 300 http://127.0.0.1:11434/v1/messages \
  -H "content-type: application/json" -H "x-api-key: ollama" -H "anthropic-version: 2023-06-01" \
  -d "{\"model\":\"${MODEL}\",\"max_tokens\":32,\"messages\":[{\"role\":\"user\",\"content\":\"responda apenas: ok\"}]}"; then
  echo -e "\nOK."
else
  echo "FALHOU: se for 404, atualize o Ollama ou use LiteLLM como proxy."
fi
echo "Pronto. Abra um novo terminal e rode: claude-local"
