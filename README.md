# Agentic Profile & Lead Assistant

An agentic professional profile assistant built with Python + Gradio, using OpenAI tool-calling and a local SQLite Q&A store to retrieve curated profile answers and improve response consistency across sessions. Includes an evaluator-optimizer quality loop, runtime logging, and Pushover notifications for new leads and unanswered questions.

## Features
- Agentic profile assistant with tool-calling
- SQLite Q&A memory store for curated answers
- Evaluator → optimizer loop for quality control
- Runtime console logging for traceability
- Pushover push notifications for:
  - new leads
  - unanswered / high-priority questions

## Tech Stack
Python, Gradio, OpenAI tool-calling, SQLite, Pushover, dotenv

## Project Structure
```text
.
├─ app.py / main.py
├─ src/
├─ tests/                  # if present
├─ data/                   # optional (avoid committing sensitive data)
├─ README.md
├─ requirements.txt
├─ .env.example
└─ .gitignore
