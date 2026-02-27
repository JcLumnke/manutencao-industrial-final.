import streamlit as st
import pandas as pd
import requests
import sqlite3
import json
import re
import time
import altair as alt
from typing import Optional
import logging
from datetime import datetime

DB_PATH = "diagnostics.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.1:latest"

# Preferred fallback models to try if default is slow
FALLBACK_MODELS = ["phi3:latest", "tinyllama:latest"]

# Logging for diagnostic visibility in terminal
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("diagnostic_app")
# Logger específico para métricas (grava em diagnostics.log)
metrics_logger = logging.getLogger("diagnostic_metrics")
metrics_logger.setLevel(logging.INFO)
metrics_handler = logging.FileHandler("diagnostics.log")
metrics_handler.setLevel(logging.INFO)
metrics_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
metrics_logger.addHandler(metrics_handler)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_name TEXT,
            symptoms TEXT,
            severity TEXT,
            diagnosis_text TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_diagnostic(machine_name, symptoms, severity, diagnosis_text):
    # Ensure machine name is normalized before saving
    machine_name = machine_name.strip().upper() if machine_name else machine_name
    # Normalize severity (correct variants -> standardized labels)
    sev = (severity or "").strip()
    if sev.lower() in ("media", "média"):
        severity = "Média"
    elif sev.lower() in ("baixa",):
        severity = "Baixa"
    elif sev.lower() in ("alta",):
        severity = "Alta"
    elif sev.lower() in ("crítica", "critica"):
        severity = "Crítica"
    else:
        # fallback to provided value with capitalization
        severity = severity
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO diagnostics (machine_name, symptoms, severity, diagnosis_text, created_at) VALUES (?, ?, ?, ?, ?)",
        (machine_name, symptoms, severity, diagnosis_text, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    logger.info("Diagnóstico salvo: machine=%s severity=%s", machine_name, severity)


def load_diagnostics():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM diagnostics ORDER BY created_at DESC", conn)
    conn.close()
    return df


def call_ollama(system_prompt: str, user_content: str, temperature: float = 0.1, max_tokens: int = 512) -> str:
    # Build the combined prompt: system instructions first to act as 'Engenheiro de Manutenção Sênior'
    prompt = f"{system_prompt}\n\nDADOS DO DIAGNÓSTICO:\n{user_content}\n\nPor favor responda em texto simples e estruturado usando os cabeçalhos 'Causa:', 'Risco:' e 'Ação:'. Seja técnico e sucinto."  # noqa: E501

    # Use model from session_state if chosen, otherwise default
    model = st.session_state.get('active_model', MODEL_NAME)
    payload = {
        "model": model,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    def _extract_json_from_text(text: str):
        # Try direct parse
        try:
            return json.loads(text)
        except Exception:
            pass

        # Find first JSON object or array in the text
        m = re.search(r"(\{(?:.|\n)*?\}|\[(?:.|\n)*?\])", text)
        if m:
            candidate = m.group(1)
            try:
                return json.loads(candidate)
            except Exception:
                return None
        return None

    try:
        # Log prompt and payload for debugging
        logger.info("Enviando prompt ao Ollama (modelo=%s)\nPrompt:\n%s", MODEL_NAME, prompt)
        logger.debug("Payload: %s", json.dumps(payload, ensure_ascii=False))

        start = time.perf_counter()
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        elapsed = time.perf_counter() - start
        # Print response time to terminal for quick visibility
        print(f"Ollama response time: {elapsed:.3f} seconds")
        logger.info("Ollama response time: %.3f seconds", elapsed)
        # Also record metrics to diagnostics.log
        try:
            metrics_logger.info("Ollama response time: %.3f seconds", elapsed)
        except Exception:
            logger.exception("Falha ao gravar métricas em diagnostics.log")

        resp_text = None
        try:
            data = resp.json()
            # Prefer the explicit 'response' field when present
            if isinstance(data, dict) and 'response' in data:
                resp_field = data['response']
                resp_text = resp_field if isinstance(resp_field, str) else json.dumps(resp_field, ensure_ascii=False)
            else:
                # Fallback: prefer other common fields
                for key in ("output", "text", "content", "result"):
                    if key in data:
                        resp_text = data[key] if isinstance(data[key], str) else json.dumps(data[key], ensure_ascii=False)
                        break
                if resp_text is None:
                    resp_text = json.dumps(data, ensure_ascii=False)
        except Exception:
            resp_text = resp.text

        # Log the raw response (truncated)
        if resp_text:
            logger.info("Resposta bruta do Ollama (trunc): %s", resp_text[:2000])

        # Try to extract JSON structure from resp_text
        parsed = _extract_json_from_text(resp_text)
        if parsed is not None:
            logger.info("Resposta parseada para JSON com sucesso.")
            logger.debug("Parsed JSON: %s", json.dumps(parsed, ensure_ascii=False))
            return json.dumps(parsed, ensure_ascii=False)
        logger.info("Nenhum JSON detectado na resposta; retornando texto cru.")
        return resp_text
    except Exception as e:
        logger.exception("Erro ao chamar Ollama")
        return f"ERROR_CALLING_OLLAMA: {e}"


def parse_structured_text(text: str) -> dict:
    """Parse text structured with headings Causa:, Risco:, Ação: (case-insensitive).
    Returns a dict with keys 'Causa', 'Risco', 'Ação' when found, otherwise empty strings.
    """
    if not text:
        return {"Causa": "", "Risco": "", "Ação": "", "raw": ""}

    # If text is JSON, return raw
    trimmed = text.strip()
    if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
        return {"Causa": "", "Risco": "", "Ação": "", "raw": text}

    headings = ["CAUSA", "RISCO", "AÇÃO"]
    # Find headings positions
    pattern = re.compile(r"^(causa:|risco:|ação:)", re.IGNORECASE | re.MULTILINE)
    parts = []
    last_pos = 0
    last_head = None
    matches = list(pattern.finditer(text))
    if not matches:
        return {"Causa": "", "Risco": "", "Ação": "", "raw": text}

    result = {"Causa": "", "Risco": "", "Ação": "", "raw": text}
    for i, m in enumerate(matches):
        head = m.group(1).rstrip(':').strip().upper()
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        content = text[start:end].strip()
        if head == 'CAUSA':
            result['Causa'] = content
        elif head == 'RISCO':
            result['Risco'] = content
        elif head == 'AÇÃO' or head == 'ACAO' or head == 'AÇÃO':
            result['Ação'] = content

    return result


def list_ollama_models() -> list:
    """Try to list models from Ollama; attempt common endpoints and return available model names."""
    candidates = ["http://localhost:11434/api/models", "http://localhost:11434/models", "http://localhost:11434/api/list"]
    for url in candidates:
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            # data may be list of dicts or dict
            models = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and 'name' in item:
                        models.append(item['name'])
                    elif isinstance(item, str):
                        models.append(item)
            elif isinstance(data, dict):
                # dict of models
                for k in data.keys():
                    models.append(k)
            if models:
                return models
        except Exception:
            continue
    return []


def test_model_latency(model_name: str, timeout: float = 30.0) -> Optional[float]:
    """Send a small prompt to measure latency for a model. Returns elapsed seconds or None on failure."""
    payload = {"model": model_name, "prompt": "Ping: responda com 'PONG'", "temperature": 0.0, "max_tokens": 10, "stream": False}
    try:
        start = time.perf_counter()
        resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        elapsed = time.perf_counter() - start
        return elapsed
    except Exception as e:
        logger.warning("Teste de latência falhou para %s: %s", model_name, e)
        return None


def choose_model(preferred: str = MODEL_NAME) -> str:
    """Choose a model: try preferred; if latency >30s, try fallbacks and log comparison."""
    # If we already chose in session, reuse
    if st.session_state.get('active_model'):
        return st.session_state['active_model']

    models_available = list_ollama_models()
    logger.info("Models available: %s", models_available)
    metrics_logger.info("Models available: %s", models_available)

    def measure(m):
        t = test_model_latency(m, timeout=30.0)
        metrics_logger.info("Latency test %s: %s", m, t)
        return t

    # Try preferred first
    t_pref = measure(preferred)
    if t_pref is not None and t_pref <= 30.0:
        st.session_state['active_model'] = preferred
        return preferred

    # Try any discoverable fallback models first
    for fb in FALLBACK_MODELS:
        t_fb = measure(fb)
        if t_fb is not None and t_fb <= 30.0:
            st.session_state['active_model'] = fb
            return fb

    # As last resort, pick first available model from discovery
    if models_available:
        st.session_state['active_model'] = models_available[0]
        return models_available[0]

    # Default
    st.session_state['active_model'] = preferred
    return preferred


def main():
    st.set_page_config(page_title="Sistema de Diagnóstico - Local (Ollama)", layout="wide")
    # Apply a soft light theme and card styling for a modern, clean UI
    st.markdown(
        """
        <style>
        /* Page background - slightly darker soft gray (kept) */
        .reportview-container, .main, .block-container { background-color: #eef3f6; color: #0f1720; }
        /* Form card styling */
        .form-card { background-color: #ffffff; border-radius: 12px; padding: 16px; box-shadow: 0 6px 18px rgba(16,24,40,0.06); }
        /* Rounded inputs and buttons */
        .stTextInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>select { border-radius: 8px; }
        .stButton>button { border-radius: 8px; }
        /* Adjust headings color (main title kept dark) */
        h1, h2, h3 { color: #0f1720; }
        /* Tabs styling: larger, dark-blue color, increased icon size */
        [role="tab"] { font-size: 1.4rem !important; color: #003366 !important; padding: 10px 16px !important; }
        [role="tab"][aria-selected="true"] { color: #003366 !important; background-color: rgba(0,51,102,0.08) !important; border-radius: 10px !important; }
        [role="tab"] svg, [role="tab"] img { transform: scale(1.6); }
        /* Title + right icon layout: larger title and icon */
        .title-row { display:flex; align-items:center; justify-content:space-between; }
        .title-row h1 { margin: 0; font-size: 2.4rem; }
        .title-icon { width:80px; height:80px; display:flex; align-items:center; justify-content:center; }
        .title-icon svg { width:80px; height:80px; transform: scale(1.35); }
        /* Force header icon color to dark blue */
        .title-icon svg path { fill: #003366 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Title with industrial SVG icon on the right
    st.markdown(
        """
        <div class="title-row">
          <h1> Sistema inteligente de Diagnóstico Industrial </h1>
          <div class="title-icon">
            <svg width="80" height="80" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 15.5C13.933 15.5 15.5 13.933 15.5 12C15.5 10.067 13.933 8.5 12 8.5C10.067 8.5 8.5 10.067 8.5 12C8.5 13.933 10.067 15.5 12 15.5Z" fill="#003366"/>
              <path d="M19.4 13.5c.04-.5.04-1 .0-1.5l2.1-1.6-2-3.5-2.5.5c-.4-.3-.8-.6-1.3-.8l-.4-2.6h-4l-.4 2.6c-.5.2-.9.5-1.3.8L4.6 6.9 2.6 10.4 4.7 12l-.1 1.5c-.04.5-.04 1 0 1.5L2.6 16.6 4.6 20l2.5-.5c.4.3.8.6 1.3.8l.4 2.6h4l.4-2.6c.5-.2.9-.5 1.3-.8L19.4 20 21.4 16.6 19.3 15l.1-1.5z" fill="#003366" opacity="0.95"/>
              <rect x="3" y="17" width="3" height="3" rx="0.5" fill="#003366"/>
              <rect x="8" y="14" width="2" height="6" rx="0.5" fill="#003366"/>
              <rect x="12" y="12" width="2" height="8" rx="0.5" fill="#003366"/>
            </svg>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    init_db()

    tabs = st.tabs(["📊 Dashboard", "🆕 Novo Diagnóstico", "📜 Histórico"])

    # System prompt in Portuguese for 'Engenheiro de Manutenção Sênior'
    system_prompt = (
        "Você é um Engenheiro de Manutenção Sênior. Forneça um diagnóstico técnico curto e objetivo, "
        "priorizando segurança, causa raiz e ações corretivas. Responda em texto simples e estruturado com os cabeçalhos:\n"
        "Causa:\nRisco:\nAção:\nUse linguagem técnica e sucinta; não retorne JSON, apenas texto com essas seções."
    )

    # Choose active model (auto-optimization)
    active = choose_model()
    # model display removed from sidebar for a cleaner UI (llama3.1 remains default)

    # Dashboard
    with tabs[0]:
        st.header("Dashboard")
        df = load_diagnostics()
        if df.empty:
            st.info("Nenhum diagnóstico salvo ainda.")
        else:
            # Normalize machine names to MAIÚSCULAS for grouping
            df['machine_name'] = df['machine_name'].astype(str).str.strip().str.upper()
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Número de diagnósticos por máquina")
                agg = df.groupby("machine_name").size().reset_index(name="count")
                agg = agg.sort_values("count", ascending=False)
                # Colored bars per machine
                bar = alt.Chart(agg).mark_bar().encode(
                    x=alt.X('machine_name:N', sort='-y', title='Equipamento'),
                    y=alt.Y('count:Q', title='Contagem'),
                    color=alt.Color('machine_name:N', legend=None, scale=alt.Scale(scheme='category20')),
                    tooltip=['machine_name', 'count']
                ).properties(height=350)
                st.altair_chart(bar, use_container_width=True)

                # KPI: total critical failures
                total_crit = int(df[df['severity'] == 'Crítica'].shape[0])
                st.metric("Falhas Críticas", total_crit)
            with col2:
                st.subheader("Distribuição por Severidade")
                # Ensure severity categories fixed order
                sev = df['severity'].value_counts().reindex(["Baixa", "Média", "Alta", "Crítica"]).fillna(0).reset_index()
                sev.columns = ['severity', 'count']
                # semafórico: Baixa=green, Média=yellow, Alta=orange, Crítica=red
                severity_colors = ["#2ecc71", "#f1c40f", "#e67e22", "#e74c3c"]
                pie = alt.Chart(sev).mark_arc().encode(
                    theta=alt.Theta(field='count', type='quantitative'),
                    color=alt.Color(field='severity', type='nominal', scale=alt.Scale(domain=["Baixa", "Média", "Alta", "Crítica"], range=severity_colors)),
                    tooltip=['severity', 'count']
                ).properties(height=350)
                st.altair_chart(pie, use_container_width=True)

            st.subheader("Últimos diagnósticos")
            st.dataframe(df[["id", "machine_name", "severity", "created_at"]].head(50))

    # Novo Diagnóstico
    with tabs[1]:
        st.header("Novo Diagnóstico")
        # form card wrapper for rounded border and shadow
        st.markdown('<div class="form-card">', unsafe_allow_html=True)
        with st.form("form_diagnostico"):
            machine_name = st.text_input("Nome do Equipamento", max_chars=100)
            # Apply normalization requirement: .strip().upper()
            machine_name_proc = machine_name.strip().upper() if machine_name else ""
            severity = st.selectbox("Severidade", ["Baixa", "Média", "Alta", "Crítica"] )
            symptoms = st.text_area("Sintomas / Observações")
            submitted = st.form_submit_button("Gerar diagnóstico")

            if submitted:
                if not machine_name_proc or not symptoms:
                    st.error("Por favor informe o nome da máquina e os sintomas.")
                else:
                    user_content = (
                        f"Machine: {machine_name_proc}\nSeverity: {severity}\nTimestamp: {datetime.utcnow().isoformat()}\nSymptoms: {symptoms}"
                    )
                    with st.spinner("Chamando motor Ollama para gerar diagnóstico..."):
                        diagnosis = call_ollama(system_prompt, user_content, temperature=0.1)

                    save_diagnostic(machine_name_proc, symptoms, severity, diagnosis)

                    st.success("Diagnóstico salvo com sucesso.")
                    # Parse structured text (Causa / Risco / Ação) and display cleanly
                    parsed_sections = parse_structured_text(diagnosis)
                    if parsed_sections.get('raw') and not (parsed_sections.get('Causa') or parsed_sections.get('Risco') or parsed_sections.get('Ação')):
                        # Raw text (no headings detected) - show as Markdown
                        st.subheader("Resposta do modelo")
                        st.markdown(parsed_sections['raw'])
                    else:
                        if parsed_sections.get('Causa'):
                            st.subheader('Causa')
                            st.markdown(parsed_sections['Causa'])
                        if parsed_sections.get('Risco'):
                            st.subheader('Risco')
                            st.markdown(parsed_sections['Risco'])
                        if parsed_sections.get('Ação'):
                            st.subheader('Ação')
                            st.markdown(parsed_sections['Ação'])

                    # Clear session state to avoid repeating responses, but preserve active_model
                    try:
                        active_model_preserve = st.session_state.get('active_model')
                        st.session_state.clear()
                        if active_model_preserve:
                            st.session_state['active_model'] = active_model_preserve
                    except Exception:
                        pass
                    # close form card wrapper
                    st.markdown('</div>', unsafe_allow_html=True)

    # Histórico
    with tabs[2]:
        st.header("Histórico de Diagnósticos")
        df_all = load_diagnostics()
        if df_all.empty:
            st.info("Nenhum diagnóstico disponível")
        else:
            # Normalize machine names for display and export
            df_all['machine_name'] = df_all['machine_name'].astype(str).str.strip().str.upper()
            st.dataframe(df_all[['id','machine_name','severity','created_at']])
            # Export button for CSV
            csv = df_all.to_csv(index=False)
            st.download_button("Exportar CSV", data=csv, file_name="diagnostics.csv", mime="text/csv")
            st.markdown("---")
            for _, row in df_all.iterrows():
                with st.expander(f"[{row['created_at']}] {row['machine_name']} - {row['severity']}"):
                    st.write("**Sintomas:**")
                    st.write(row['symptoms'])
                    st.write("**Diagnóstico (modelo):**")
                    # try parse structured text sections
                    parsed_sections = parse_structured_text(row['diagnosis_text'])
                    if parsed_sections.get('raw') and not (parsed_sections.get('Causa') or parsed_sections.get('Risco') or parsed_sections.get('Ação')):
                        # Raw text or JSON stored previously - display as Markdown for readability
                        st.markdown(row['diagnosis_text'])
                    else:
                        if parsed_sections.get('Causa'):
                            st.write('**Causa:**')
                            st.markdown(parsed_sections['Causa'])
                        if parsed_sections.get('Risco'):
                            st.write('**Risco:**')
                            st.markdown(parsed_sections['Risco'])
                        if parsed_sections.get('Ação'):
                            st.write('**Ação:**')
                            st.markdown(parsed_sections['Ação'])


if __name__ == "__main__":
    main()      # Para rodar localmente, use: streamlit run app.py
