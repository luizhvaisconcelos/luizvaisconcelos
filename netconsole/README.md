# NetConsole — console multi-vendor para APs e switches

Agregador que consolida inventário, status e clientes de **Cisco Meraki**, **Aruba Central** e
**Ruckus SmartZone** em uma única UI/API, com ação de reboot, RBAC e trilha de auditoria.
Roda em uma VM (Docker ou systemd), sem depender de nuvem própria.

> **Escopo honesto:** isto *não* substitui as controladoras. É uma camada de visibilidade + ações
> pontuais sobre as APIs oficiais. Configuração profunda (SSID, VLAN, firmware) deve continuar
> na ferramenta do vendor, ou ser adicionada driver a driver (ver "Roadmap").

## Status dos drivers

| Vendor | Inventário | Clientes | Reboot | Validação |
|---|---|---|---|---|
| Meraki (Dashboard API v1) | AP, SW, MX | sim | sim | API estável e bem documentada; testada com HTTP simulado |
| Aruba Central (API clássica) | AP, SW, GW | sim | sim | **validar no seu tenant** (cluster/endpoint de reboot variam) |
| Ruckus SmartZone | AP | sim (best-effort) | sim | **validar na sua versão** (`api_version`); switches ICX ainda não |
| Demo | simulado | sim | sim | para testar a UI sem hardware |

Os testes (`pytest`) usam respostas HTTP simuladas — **nenhum equipamento real foi testado**.
Comece com um token **somente leitura** em cada vendor e teste o reboot só em um AP de laboratório.

## Subir na VM (Docker)

```bash
cd netconsole
cp .env.example .env
sed -i "s/^NETCONSOLE_ADMIN_TOKEN=.*/NETCONSOLE_ADMIN_TOKEN=$(openssl rand -hex 32)/" .env
sed -i "s/^NETCONSOLE_VIEWER_TOKEN=.*/NETCONSOLE_VIEWER_TOKEN=$(openssl rand -hex 32)/" .env
docker compose up -d --build
```

Acesse `http://127.0.0.1:8080` (ou via reverse proxy com TLS) e entre com o token. Em **Provedores**
adicione o vendor "Demo" para ver a UI funcionando, depois os reais.

Sem Docker: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt &&
uvicorn --factory app.main:app_factory --host 127.0.0.1 --port 8080`.

## Credenciais por vendor

- **Meraki:** Dashboard > My profile > API key (use conta com acesso *read-only*; para reboot, *org admin* ou network admin).
- **Aruba Central:** API Gateway > System Apps & Tokens. Informe também client_id/secret/refresh_token para renovação
  automática (o refresh token é de uso único; o console grava o novo par cifrado).
- **Ruckus SmartZone:** usuário local com perfil de leitura (e permissão de AP reboot se desejar a ação). Porta 8443 acessível da VM.

## Segurança (recomendações)

- Credenciais dos vendors ficam **cifradas** (Fernet) no SQLite; chave em `NETCONSOLE_SECRET_KEY` ou `data/secret.key` (0600). **Faça backup da chave** junto do banco.
- Dois perfis: `admin` (gerencia provedores, reboot, auditoria) e `viewer` (NOC/helpdesk, somente leitura).
- Toda ação mutável é registrada em `/api/audit` (quem, o quê, quando) — útil para ISO 27001 / LGPD.
- Coloque atrás de reverse proxy com TLS e restrinja por firewall/VLAN de gestão. O console armazena MACs/IPs/hostnames
  de alunos e professores (**dados pessoais** sob a LGPD): defina retenção e acesso mínimo.
- O token é um segredo compartilhado simples. Para produção maior, coloque SSO/MFA no proxy (oauth2-proxy + Entra ID/Google).
- Ruckus com cert autoassinado: prefira instalar a CA na VM em vez de desligar `verify_tls`.
- Backup: `data/` (DB + chave). Ex.: `tar czf netconsole-$(date +%F).tgz data/`.

## Adicionar um vendor (ex.: Fortinet FortiAP/FortiSwitch, Ubiquiti UniFi, Extreme)

Crie `app/drivers/meu_vendor.py` implementando `Driver` (`test`, `devices`, `clients`, `reboot`), declare os `fields`
de configuração e registre em `app/drivers/__init__.py`. A UI gera o formulário automaticamente.

## Roadmap sugerido

1. Alertas (webhook Teams/Slack/e-mail) quando AP/SW ficar offline > N min.
2. Histórico de status (série temporal) + exportar métricas Prometheus (`/metrics`) para Grafana.
3. Ações em lote e janelas de manutenção; gestão de firmware.
4. SNMP/LLDP genérico para vendors sem API (switches legados).
5. SSO/OIDC nativo e RBAC por site/unidade.
