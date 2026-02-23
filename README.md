# Sistema de Diagnóstico Industrial — Streamlit Local + Ollama

Este repositório contém um aplicativo Streamlit local que gera diagnósticos industriais usando um motor de LLM hospedado localmente (Ollama).

Por que usar Ollama localmente?
- **Privacidade industrial**: todo o texto e dados sensíveis permanecem na infraestrutura local, sem envio para provedores de nuvem externos.
- **Latência e disponibilidade**: execução local reduz latência e evita dependência de conexões externas.
- **Controle de modelos**: escolhemos `llama3.1:latest` local para consistência e segurança operacional.

Como usar

1. Instale dependências:

```bash
pip install -r requirements.txt
```

2. Inicie o servidor Ollama local (pré-requisito) e carregue o modelo `llama3.1:latest` conforme sua instalação do Ollama.

3. Execute o app Streamlit:

```bash
streamlit run app.py
```

Arquivos
- `app.py`: aplicação Streamlit com 3 abas (Dashboard, Novo Diagnóstico, Histórico), integração com Ollama via `http://localhost:11434/api/generate` e persistência SQLite (`diagnostics.db`).
- `requirements.txt`: dependências necessárias.

Observações de avaliação
- O `system prompt` foi configurado para o papel de "Engenheiro de Manutenção Sênior" e instrui o modelo a retornar JSON estruturado.
- O nome da máquina é normalizado com `.strip().upper()` no formulário para evitar duplicatas no Dashboard.
- A temperatura está definida para `0.1` no payload de geração para priorizar precisão técnica.

Decisões de engenharia recentes

- Robustez de parsing: adicionamos extração robusta de JSON na resposta do modelo. O app tenta primeiro fazer `json.loads` direto; se o modelo retornar texto misturado, usamos uma extração por regex para localizar o primeiro objeto/array JSON no texto e fazer parse. Isso aumenta resiliência contra saídas do modelo que incluem explicações e blocos JSON.
- Temperatura baixa: a temperatura é fixada em `0.1` para reduzir criatividade e priorizar respostas técnicas e consistentes.
- Logs de diagnóstico: o `app.py` agora registra no terminal o prompt enviado ao Ollama, a resposta bruta (truncada) e o JSON parseado quando disponível — útil para auditoria e depuração local.

Atualizações importantes (Dashboard, exportação e performance)

- Stream desativado: as requisições ao Ollama usam `"stream": false` para garantir que a resposta chegue completa (evita problemas de leitura parcial e melhora consistência).
- Extração de resposta: quando a API do Ollama retorna JSON, o app prioriza o campo `response` e exibe seu conteúdo como Markdown no UI (texto simples estruturado), em vez de mostrar o JSON bruto.
- Timeout aumentado: o timeout da requisição foi aumentado para `120` segundos para acomodar respostas maiores sem falhas de leitura.
- Dashboard lado a lado: o `Dashboard` usa `st.columns(2)` para mostrar o gráfico de barras (número de diagnósticos por equipamento) e um gráfico de pizza de prioridades (severidade) lado a lado, usando Altair para melhor estética.
- Severidade fixa: as opções de severidade são estritamente `Baixa`, `Média`, `Alta` e `Crítica`.
- Normalização: o campo `machine_name` é salvo em MAIÚSCULAS no banco para evitar duplicação no gráfico.
- Exportação CSV: a aba `Histórico` tem um botão `st.download_button` para exportar todos os diagnósticos em CSV (`diagnostics.csv`).
- Métricas: o tempo de resposta do Ollama é impresso no terminal e gravado em `diagnostics.log` para análises e apresentação.

# manutencao-industrial-final.
Projeto final da unidade de IA generativa

## Resultados de Latência dos Modelos (teste local)

Teste executado em 2026-02-23 (UTC). Os modelos abaixo foram testados com um prompt simples "Ping: responda com PONG" e as latências registradas em `diagnostics.log`.

- `llama3.1:latest` — 46 s (OK)
- `phi3:latest` — falha (404 Not Found ao chamar /api/generate)
- `tinyllama:latest` — falha (404 Not Found ao chamar /api/generate)

Nota: por apresentar o melhor equilíbrio entre precisão técnica e tempo de resposta (≈46s no teste), o modelo `llama3.1:latest` foi escolhido como padrão no aplicativo.


Observações:

- Os resultados foram anexados em `diagnostics.log` para auditoria e comparação contínua.
- O mecanismo de seleção de modelo (`choose_model`) tentará usar o modelo padrão, mas se a latência for maior que 30s tentará `phi3` e `tinyllama` (se disponíveis), gravando as latências no log para comparação.
- Se alguns modelos retornarem erro 404, verifique a instalação/carregamento do modelo no servidor Ollama local.

## Interface Industrial

O visual do sistema foi projetado para uso em ambientes industriais: o fundo em cinza suave reduz contraste excessivo e fadiga visual sob iluminação de fábrica, enquanto o azul escuro (`#003366`) aplicado aos títulos e ícones melhora a legibilidade e hierarquia visual. Essas escolhas ajudam operadores a localizar rapidamente informações críticas (como severidade e título das abas) sem distrações.

Comandos úteis:

```powershell
Get-Content .\diagnostics.log -Tail 200
```
