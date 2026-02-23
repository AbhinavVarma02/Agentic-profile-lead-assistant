# Agentic Profile & Lead Assistant

An agentic professional profile assistant built with Python + Gradio, using OpenAI tool-calling and a local SQLite Q&A store to retrieve curated profile answers and improve response consistency across sessions. Includes an evaluator-optimizer quality loop, runtime logging, and Pushover notifications for new leads and unanswered questions.

## Live Demo
- Hugging Face Space: https://huggingface.co/spaces/abhinavvathadi/agentic-profile-lead-assistant
> Note: The public demo runs without any personal `me/` data. Local-only Q&A memory (SQLite) stays on your machine.

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


## Environment variables
```md
## Environment variables
- OPENAI_API_KEY (required)
- PUSHOVER_USER_KEY (optional)
- PUSHOVER_API_TOKEN (optional)

Tip: For public deployments, store secrets in Hugging Face → Settings → Secrets.

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

## Highlights 
- Built an agentic professional profile assistant (Python + Gradio) using OpenAI tool-calling and a SQLite Q&A store to improve response consistency across sessions.
- Implemented an evaluator-optimizer quality loop with runtime console logging and Pushover notifications for unanswered questions and new leads, enabling fast follow-ups and safer outputs.
