"""Memory (plan 3.3, R3).

Short-term memory  : the message list of the current question (system, user, tool
                     calls, observations). Long observations are truncated so the
                     context stays small (write policy: every tool result, trimmed
                     to MAX_OBS_CHARS; retrieval policy: whole list sent to the LLM).
Episodic memory    : SQLite table of past (question, answer, chips, entities) per
                     session. Write policy: ONLY verified, non-refused answers are
                     stored (so hallucinations never become "memory"). Retrieval
                     policy: (1) last episode of the same session to resolve
                     follow-ups like "and its deep-sleep current?"; (2) up to 3
                     keyword-overlap matches from the same session.
"""
import json
import re
import sqlite3
import time

import config

MAX_OBS_CHARS = 6000


class ShortTermMemory:
    def __init__(self, system_prompt: str):
        self.messages = [{"role": "system", "content": system_prompt}]

    def add(self, msg: dict):
        if msg.get("role") == "tool" and len(msg.get("content", "")) > MAX_OBS_CHARS:
            msg = {**msg, "content": msg["content"][:MAX_OBS_CHARS] + " ...[truncated]"}
        self.messages.append(msg)


class EpisodicMemory:
    def __init__(self, path=config.MEMORY_DB):
        self.con = sqlite3.connect(str(path), check_same_thread=False)
        self.con.execute("""CREATE TABLE IF NOT EXISTS episodes(
            session TEXT, ts REAL, question TEXT, answer TEXT, chips TEXT, entities TEXT, citations TEXT)""")
        self.con.commit()

    def write(self, session: str, question: str, answer: str, chips: list, entities: list, citations: list):
        self.con.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?)",
                         (session, time.time(), question, answer, json.dumps(chips), json.dumps(entities),
                          json.dumps(citations)))
        self.con.commit()

    def last(self, session: str) -> dict | None:
        r = self.con.execute("SELECT question, answer, chips, entities FROM episodes WHERE session=? "
                             "ORDER BY ts DESC LIMIT 1", (session,)).fetchone()
        return None if not r else {"question": r[0], "answer": r[1], "chips": json.loads(r[2]),
                                   "entities": json.loads(r[3])}

    def related(self, session: str, question: str, k: int = 3) -> list[dict]:
        q = set(re.findall(r"[a-z0-9_]{3,}", question.lower()))
        rows = self.con.execute("SELECT question, answer FROM episodes WHERE session=? ORDER BY ts DESC LIMIT 50",
                                (session,)).fetchall()
        scored = sorted(((len(q & set(re.findall(r"[a-z0-9_]{3,}", r[0].lower()))), r) for r in rows),
                        key=lambda x: -x[0])
        return [{"question": r[0], "answer": r[1][:300]} for s, r in scored[:k] if s > 1]

    def history(self, session: str, n: int = 20) -> list[dict]:
        rows = self.con.execute("SELECT ts, question, answer FROM episodes WHERE session=? ORDER BY ts DESC LIMIT ?",
                                (session, n)).fetchall()
        return [{"ts": r[0], "question": r[1], "answer": r[2]} for r in rows]
