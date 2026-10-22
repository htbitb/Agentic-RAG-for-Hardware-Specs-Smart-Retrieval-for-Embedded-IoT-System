# Agentic RAG for Hardware Specs (ESP32 / STM32G474 / nRF52840 / FreeRTOS)

Full explanation (what / why / how it runs): **[docs/explanation.html](docs/explanation.html)**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env                       # optional: add LLM_API_KEY, otherwise SimulatedLLM is used
.\.venv\Scripts\python.exe run_all.py        # build index + evaluation (3 seeds + attack suite)
.\.venv\Scripts\python.exe -m ui.server      # web UI on http://127.0.0.1:8000
.\.venv\Scripts\python.exe main.py -v "What is the ESP32 deep-sleep current with RTC timer and RTC memory?"
```

Simulated parts (see the HTML doc, section "Simulated / missing parts"):
LLM (no API key), STM32G474 + nRF52840 facts/corpus (no PDFs), one poisoned app note for injection tests.
