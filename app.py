from dotenv import load_dotenv
from openai import OpenAI
import json
import os
import requests
import sqlite3
from datetime import datetime
from pypdf import PdfReader
import gradio as gr

load_dotenv(override=True)

# ----------------------------
# 1) Pushover Notifications
# ----------------------------
def push(text: str) -> None:
    requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": os.getenv("PUSHOVER_TOKEN"),
            "user": os.getenv("PUSHOVER_USER"),
            "message": text,
        },
        timeout=15,
    )

def record_user_details(email, name="Name not provided", notes="not provided"):
    push(f"Lead: {name} | {email} | notes={notes}")
    return {"recorded": "ok"}

def record_unknown_question(question):
    push(f"Unknown Q: {question}")
    return {"recorded": "ok"}

# ----------------------------
# 2) SQLite: Profile Q&A DB
# ----------------------------
DB_PATH = os.path.join("me", "profile_qa.db")

def get_db_connection():
    # check_same_thread=False avoids issues when Gradio uses threads
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS profile_qa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            tags TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_qa_question ON profile_qa(question)")
    conn.commit()
    conn.close()

def seed_db_if_empty():
    """
    Seeds a few Q&As if the table is empty.
    You can edit/add your own Q&As below.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM profile_qa")
    count = cur.fetchone()["c"]
    if count == 0:
        now = datetime.utcnow().isoformat()
        seed_rows = [
            ("What roles are you targeting?",
             "I’m targeting Data Engineer / Applied AI Engineer / Data Scientist roles focused on building practical AI systems, analytics, and automation.",
             "career,roles", now),
            ("What’s your strongest tech stack?",
             "Python, SQL, Tableau/Power BI, and building LLM-powered apps with tool-calling and structured workflows. I’m also exploring RAG and agentic patterns.",
             "skills,stack", now),
            ("Tell me about your most recent work.",
             "Recently I’ve been building analytics dashboards and automation workflows, and developing an AI-powered career assistant that can log leads and unanswered questions.",
             "experience,projects", now),
        ]
        cur.executemany(
            "INSERT INTO profile_qa(question, answer, tags, created_at) VALUES (?, ?, ?, ?)",
            seed_rows
        )
        conn.commit()
    conn.close()

def lookup_profile_qa(question: str, limit: int = 3):
    """
    Tool: searches the Q&A DB for the closest matches.
    Simple approach: exact match then LIKE match.
    """
    q = (question or "").strip()
    if not q:
        return {"matches": []}

    conn = get_db_connection()
    cur = conn.cursor()

    # 1) exact match (case-insensitive)
    cur.execute("""
        SELECT question, answer, tags
        FROM profile_qa
        WHERE lower(question) = lower(?)
        LIMIT ?
    """, (q, limit))
    rows = cur.fetchall()

    # 2) if no exact, do LIKE match
    if not rows:
        like = f"%{q.lower()}%"
        cur.execute("""
            SELECT question, answer, tags
            FROM profile_qa
            WHERE lower(question) LIKE ?
            ORDER BY id DESC
            LIMIT ?
        """, (like, limit))
        rows = cur.fetchall()

    conn.close()

    matches = [{"question": r["question"], "answer": r["answer"], "tags": r["tags"]} for r in rows]
    return {"matches": matches}

def upsert_profile_qa(question: str, answer: str, tags: str = ""):
    """
    Tool: add a Q&A (simple insert).
    You can extend this to do true upsert (update if exists).
    """
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        return {"saved": False, "reason": "question/answer missing"}

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO profile_qa(question, answer, tags, created_at) VALUES (?, ?, ?, ?)",
        (q, a, tags or "", datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return {"saved": True}

# ----------------------------
# 3) Tool Schemas for the LLM
# ----------------------------
record_user_details_json = {
    "name": "record_user_details",
    "description": "Record a user lead when they want to get in touch and provided an email address.",
    "parameters": {
        "type": "object",
        "properties": {
            "email": {"type": "string", "description": "The user's email"},
            "name": {"type": "string", "description": "The user's name if provided"},
            "notes": {"type": "string", "description": "Context to save about the conversation"}
        },
        "required": ["email"],
        "additionalProperties": False
    }
}

record_unknown_question_json = {
    "name": "record_unknown_question",
    "description": "Record any question the assistant couldn't answer.",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question that couldn't be answered"}
        },
        "required": ["question"],
        "additionalProperties": False
    }
}

lookup_profile_qa_json = {
    "name": "lookup_profile_qa",
    "description": "Search the profile Q&A database for relevant answers about Abhinav.",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "User's question to search for"},
            "limit": {"type": "integer", "description": "Max number of matches to return", "default": 3}
        },
        "required": ["question"],
        "additionalProperties": False
    }
}

upsert_profile_qa_json = {
    "name": "upsert_profile_qa",
    "description": "Add a new Q&A entry to the profile database (admin/internal use).",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Question text"},
            "answer": {"type": "string", "description": "Answer text"},
            "tags": {"type": "string", "description": "Comma-separated tags (optional)"}
        },
        "required": ["question", "answer"],
        "additionalProperties": False
    }
}

tools = [
    {"type": "function", "function": record_user_details_json},
    {"type": "function", "function": record_unknown_question_json},
    {"type": "function", "function": lookup_profile_qa_json},
    {"type": "function", "function": upsert_profile_qa_json},
]

# ----------------------------
# 4) Evaluator Schema + Eval/Optimize Loop
# ----------------------------
EVAL_SCHEMA = {
    "name": "Evaluation",
    "schema": {
        "type": "object",
        "properties": {
            "is_acceptable": {"type": "boolean"},
            "feedback": {"type": "string"},
            "violations": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["is_acceptable", "feedback", "violations"],
        "additionalProperties": False
    }
}

def build_eval_prompts(persona_name: str, system_context: str, history, user_message: str, assistant_reply: str):
    # Evaluator is strict: professionalism + no harassment/hate/sexual content + no profanity + no unsafe guidance.
    eval_system = (
        "You are a strict evaluator for a professional website assistant.\n"
        "Check the assistant reply for:\n"
        "- Professional tone (no rude, insulting, toxic language)\n"
        "- No profanity / slurs / hateful content\n"
        "- No sexual content\n"
        "- No instructions for wrongdoing\n"
        "- No hallucinated personal facts (don’t invent details not supported by the provided context)\n"
        "Return JSON only that matches the provided schema."
    )

    # Keep history short to evaluator: last few turns only
    short_history = history[-6:] if isinstance(history, list) else history

    eval_user = {
        "persona": persona_name,
        "context_excerpt": system_context[:4000],  # cap to keep it reasonable
        "recent_history": short_history,
        "user_message": user_message,
        "assistant_reply": assistant_reply,
        "task": "Decide if reply is acceptable. If not, explain how to fix it."
    }

    return eval_system, json.dumps(eval_user, ensure_ascii=False)

def evaluate_reply(client: OpenAI, persona_name: str, system_context: str, history, user_message: str, assistant_reply: str):
    eval_system, eval_payload = build_eval_prompts(persona_name, system_context, history, user_message, assistant_reply)

    # Try structured JSON output (preferred). If your SDK/version doesn’t support this, fallback below.
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": eval_system},
                {"role": "user", "content": eval_payload},
            ],
            response_format={"type": "json_schema", "json_schema": EVAL_SCHEMA}
        )
        content = resp.choices[0].message.content
        return json.loads(content)
    except Exception:
        # Fallback: ask for JSON and parse
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": eval_system + "\nReturn ONLY valid JSON."},
                {"role": "user", "content": eval_payload},
            ],
        )
        content = resp.choices[0].message.content
        # Best-effort parse
        try:
            return json.loads(content)
        except Exception:
            return {"is_acceptable": True, "feedback": "Evaluator parsing failed; allowing reply.", "violations": []}

def optimize_reply(client: OpenAI, persona_name: str, base_system_prompt: str, history, user_message: str,
                   rejected_reply: str, feedback: str):
    # Optimizer prompt: “rewrite with feedback”
    optimizer_system = (
        base_system_prompt
        + "\n\nIMPORTANT: Your previous answer was rejected by a strict evaluator."
        + "\nRewrite your response to be professional, safe, and aligned with the provided context."
        + "\nDo NOT include profanity, slurs, hateful or sexual content."
        + "\nDo NOT invent facts that aren't supported by the Summary/LinkedIn/Q&A DB."
    )

    optimizer_user = (
        f"User message:\n{user_message}\n\n"
        f"Rejected reply:\n{rejected_reply}\n\n"
        f"Evaluator feedback:\n{feedback}\n\n"
        "Now write the improved final answer only."
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": optimizer_system}] + history + [{"role": "user", "content": optimizer_user}],
    )
    return resp.choices[0].message.content

# ----------------------------
# 5) Agent Class
# ----------------------------
class Me:
    def __init__(self):
        self.openai = OpenAI()
        self.name = "Abhinav Varma Vathadi"

        init_db()
        seed_db_if_empty()

        # Load LinkedIn PDF
        reader = PdfReader("me/linkedin.pdf")
        self.linkedin = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                self.linkedin += text

        # Load summary
        with open("me/summary.txt", "r", encoding="utf-8") as f:
            self.summary = f.read()

    def handle_tool_call(self, tool_calls):
        # SAFER than raw globals(): allowlist only
        TOOL_MAP = {
            "record_user_details": record_user_details,
            "record_unknown_question": record_unknown_question,
            "lookup_profile_qa": lookup_profile_qa,
            "upsert_profile_qa": upsert_profile_qa,
        }

        results = []
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            print(f"Tool called: {tool_name}", flush=True)

            tool_fn = TOOL_MAP.get(tool_name)
            result = tool_fn(**arguments) if tool_fn else {"error": "unknown tool"}
            results.append(
                {"role": "tool", "content": json.dumps(result), "tool_call_id": tool_call.id}
            )
        return results

    def system_prompt(self):
        sp = (
            f"You are acting as {self.name}. You are answering questions on {self.name}'s website, "
            f"particularly questions related to {self.name}'s career, background, skills and experience. "
            "Be professional and engaging, as if talking to a potential client or future employer.\n\n"
            "Tool rules:\n"
            "- If you don't know the answer, call record_unknown_question.\n"
            "- If the user wants to connect, ask for their email and call record_user_details.\n"
            "- If a question looks like it can be answered from stored Q&A, call lookup_profile_qa first.\n"
            "Never invent facts not supported by Summary, LinkedIn, or Q&A database.\n"
        )
        sp += f"\n\n## Summary:\n{self.summary}\n\n## LinkedIn Profile:\n{self.linkedin}\n\n"
        sp += "Stay in character."
        return sp

    def chat(self, message, history):

        if not history:
            greeting = f"Hi, thanks for visiting my website - I’m {self.name}. How can I assist you today?"
        # If user just says hi/hello, reply only with greeting
            if message.strip().lower() in {"hi", "hello", "hey", "hii", "hai"}:
              return greeting
        # Otherwise, prepend greeting + continue with normal flow
            message = greeting + "\n\n" + message

        base_system = self.system_prompt()
        messages = [{"role": "system", "content": base_system}] + history + [{"role": "user", "content": message}]
        
        # 1) Tool calling loop (think → tool → think)
        done = False
        while not done:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=tools
            )
            if response.choices[0].finish_reason == "tool_calls":
                assistant_msg = response.choices[0].message
                tool_calls = assistant_msg.tool_calls
                tool_results = self.handle_tool_call(tool_calls)

                messages.append(assistant_msg)
                messages.extend(tool_results)
            else:
                done = True

        draft_reply = response.choices[0].message.content

        # 2) Evaluator → Optimizer loop (quality gate)
        max_retries = 2
        reply = draft_reply

        for _ in range(max_retries):
            evaluation = evaluate_reply(
                client=self.openai,
                persona_name=self.name,
                system_context=base_system,
                history=history,
                user_message=message,
                assistant_reply=reply
            )
            if evaluation.get("is_acceptable", True):
                return reply

            # Not acceptable → optimize and retry
            feedback = evaluation.get("feedback", "Make it more professional and safe.")
            reply = optimize_reply(
                client=self.openai,
                persona_name=self.name,
                base_system_prompt=base_system,
                history=history,
                user_message=message,
                rejected_reply=reply,
                feedback=feedback
            )

        # If still failing, return the last rewritten reply (usually safe after 1–2 passes)
        return reply

# ----------------------------
# 6) Run Gradio
# ----------------------------
if __name__ == "__main__":
    me = Me()
    gr.ChatInterface(me.chat, type="messages").launch()