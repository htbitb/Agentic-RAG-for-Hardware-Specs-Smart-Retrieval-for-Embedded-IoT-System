"""Central Agent: ReAct loop + guardrails + verification + memory (plan sections 3 and 4).

    Input guardrail -> episodic context -> hardware-safety pre-check
      -> ReAct loop [LLM thought -> MCP tool call -> sanitized observation]*
      -> verification gate (reflection once, else abstain)
      -> memory write policy -> audit log
"""
import json
import time
import uuid

import config
from agent import approval, audit, guardrail
from agent.llm import SYSTEM_PROMPT, get_llm, parse_entities, route
from agent.memory import EpisodicMemory, ShortTermMemory
from agent.tools import ToolHub
from agent.verifier import verify


def _short(obj, n=400):
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + " ..."


class HardwareAgent:
    def __init__(self, transport="stdio", use_verification=True, use_guardrail=True, disabled_servers=None,
                 llm=None, name="full"):
        # vòng lặp v1 (UI cũ) chỉ có tool tra cứu: verifier v1 không hiểu bằng chứng sandbox/Board State (runtime v2 mới dùng chúng)
        disabled_servers = ("hw-sandbox", "board-state") if disabled_servers is None else disabled_servers
        self.hub = ToolHub(transport=transport, disabled_servers=disabled_servers, sanitize=use_guardrail)
        self.llm = llm or get_llm()
        self.use_verification = use_verification
        self.use_guardrail = use_guardrail
        self.episodic = EpisodicMemory()
        self.name = name

    def close(self):
        self.hub.close()

    # ------------------------------------------------------------------ main
    def ask(self, question: str, session_id: str = "default", seed: int | None = None) -> dict:
        t0 = time.time()
        qid = uuid.uuid4().hex[:8]
        self.hub.session_id = session_id
        trace, usage, observations = [], {"in": 0, "out": 0}, []
        audit.log("question", qid=qid, session=session_id, config=self.name, question=question)

        def finish(answer, status, verification=None):
            cost = usage["in"] / 1e6 * config.PRICE_IN_PER_M + usage["out"] / 1e6 * config.PRICE_OUT_PER_M
            verified = status == "answered" and (verification or {}).get("passed", not self.use_verification)
            ent = parse_entities(question)
            if verified and not (verification or {}).get("abstained"):
                cites = sorted({f"{s.get('doc')} p.{s.get('page') or s.get('page_start')}"
                                for o in observations for s in _sources(o["result"])})
                self.episodic.write(session_id, question, answer, ent["chips"], ent["pins"] + ent["registers"], cites)
            res = {"qid": qid, "question": question, "answer": answer, "status": status, "trace": trace,
                   "verification": verification, "observations": observations,
                   "pending_actions": [{k: a[k] for k in ("id", "filename")} for a in approval.pending(session_id)],
                   "metrics": {"latency_s": round(time.time() - t0, 3), "tokens_in": usage["in"],
                               "tokens_out": usage["out"], "cost_usd": round(cost, 6),
                               "tool_calls": len(observations), "llm": self.llm.name,
                               "simulated_llm": getattr(self.llm, "simulated", False)}}
            audit.log("answer", qid=qid, session=session_id, status=status, latency_s=res["metrics"]["latency_s"],
                      verified=bool(verified), answer=answer[:500])
            return res

        # 0) direct prompt-injection filter
        if self.use_guardrail:
            g = guardrail.check_user_input(question)
            trace.append({"type": "guardrail", "stage": "input", "detail": g})
            if g["blocked"]:
                audit.log("direct_injection_blocked", qid=qid, flags=g["flags"])
                return finish("Request blocked by the security guardrail (flags: " + ", ".join(g["flags"]) +
                              "). I can only answer hardware-documentation questions and never reveal "
                              "system instructions or secrets, nor bypass approvals.", "blocked")

        # 1) episodic memory retrieval (follow-up resolution)
        ent = parse_entities(question)
        last = self.episodic.last(session_id)
        related = self.episodic.related(session_id, question)
        ctx = None
        if last or related:
            ctx = (f"EPISODIC CONTEXT (previous turns of this session, use only to resolve references): "
                   f"last_chips={last['chips'] if last else []}; last_question={last['question'] if last else ''!r}; "
                   f"related={json.dumps(related, ensure_ascii=False)[:600]}")
            trace.append({"type": "memory", "detail": ctx})
        chips = ent["chips"] or (last["chips"] if last else [])

        # 2) hardware safety pre-check (deterministic, grounded in the fact store)
        if self.use_guardrail:
            refusal = self._hardware_check(question, chips, ent, trace, observations)
            if refusal:
                return finish(refusal, "refused")

        # 3) ReAct loop
        trace.append({"type": "plan", "detail": f"router hint: intent={route(question, ent | {'chips': chips})}, "
                                                f"chips={chips}, pins={ent['pins']}, registers={ent['registers']}"})
        stm = ShortTermMemory(SYSTEM_PROMPT)
        if ctx:
            stm.add({"role": "system", "content": ctx})
        stm.add({"role": "user", "content": f"QUESTION: {question}"})
        answer, verification, reflections = None, None, 0
        for step in range(config.MAX_STEPS):
            try:
                resp = self.llm.chat(stm.messages, self.hub.specs, seed=seed)
            except Exception as exc:  # LLM/API outage -> safe abstention, never a crash (AT2)
                audit.log("llm_error", qid=qid, error=str(exc))
                answer = f"Insufficient evidence: language model unavailable ({type(exc).__name__})."
                break
            usage["in"] += resp.usage["in"]
            usage["out"] += resp.usage["out"]
            if resp.tool_calls:
                stm.add({"role": "assistant", "content": resp.content or "",
                         "tool_calls": [{"id": c["id"], "type": "function",
                                         "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                                        | ({"extra_content": c["extra_content"]} if c.get("extra_content") else {})
                                        for c in resp.tool_calls]})
                for c in resp.tool_calls:
                    trace.append({"type": "action", "step": step, "tool": c["name"], "args": c["arguments"],
                                  "server": self.hub.owner.get(c["name"])})
                    if "__malformed__" in c["arguments"]:
                        result = {"error": "malformed JSON arguments - resend valid JSON"}
                    else:
                        result = self.hub.call(c["name"], c["arguments"])
                    observations.append({"tool": c["name"], "args": c["arguments"], "result": result})
                    trace.append({"type": "observation", "step": step, "tool": c["name"], "summary": _short(result),
                                  "security_flags": result.get("security_flags")})
                    stm.add({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, ensure_ascii=False)})
                continue

            answer = resp.content or ""
            trace.append({"type": "draft_answer", "step": step, "detail": answer[:600]})
            if not self.use_verification:
                break
            verification = verify(question, answer, [o["result"] for o in observations])
            trace.append({"type": "verification", "step": step, "detail": verification})
            if verification["passed"]:
                break
            if reflections < 1:  # reflection: give the model one chance to repair its answer
                reflections += 1
                stm.add({"role": "assistant", "content": answer})
                stm.add({"role": "user", "content": "VERIFICATION FAILED: " + "; ".join(verification["issues"]) +
                         ". Revise the answer using ONLY values present in the tool results, cite [doc p.N], "
                         "or reply 'Insufficient evidence'."})
                trace.append({"type": "reflection", "detail": verification["issues"]})
                continue
            answer = ("Insufficient evidence: the draft answer could not be verified against the retrieved sources ("
                      + "; ".join(verification["issues"][:3]) + ").")
            verification = {"passed": True, "abstained": True, "issues": [], "checked_claims": 0}
            break
        if answer is None:
            answer = "Insufficient evidence: step budget exhausted before a verified answer was found."
        return finish(answer, "answered", verification)

    # ----------------------------------------------------------- guardrail
    def _hardware_check(self, question, chips, ent, trace, observations):
        reqs = guardrail.parse_hardware_requests(question)
        if not reqs or not chips:
            return None
        chip = chips[0]
        for req in reqs:
            args = ({"chip": chip, "parameter": "supply voltage VDD"} if req["target"] == "supply"
                    else {"chip": chip, "parameter": "input voltage VIH pin", "vdd": ent["vdds"].get(chip, 3.3)})
            trace.append({"type": "action", "step": "guardrail", "tool": "get_electrical_specs", "args": args,
                          "server": self.hub.owner.get("get_electrical_specs")})
            res = self.hub.call("get_electrical_specs", args)
            observations.append({"tool": "get_electrical_specs", "args": args, "result": res})
            facts = res.get("results", [])
            v = guardrail.evaluate_hw(req, facts, vdd=ent["vdds"].get(chip, 3.3))
            trace.append({"type": "guardrail", "stage": "hardware_safety", "detail":
                          {"request": req, "verdict": v["verdict"], "limit_V": v["limit"]}})
            audit.log("hardware_safety_check", chip=chip, request=req, verdict=v["verdict"], limit=v["limit"])
            if v["verdict"] == "refuse":
                f = v["fact"]
                op = [x for x in facts if x.get("category") == "recommended_operating" and x.get("field_type") == f.get("field_type")]
                op_txt = "".join(f" Recommended operating range for {o['parameter']}: {o.get('min')}..{o.get('max')} "
                                 f"{o['unit']} [{o['doc']} p.{o['page']}]." for o in op[:2])
                return (f"REFUSED (hardware safety): applying {req['volts']} V to the {chip} {req['target']} exceeds "
                        f"the limit of {v['limit']} V ({f['parameter']}, {f['category']}) [{f['doc']} p.{f['page']}]. "
                        f"Exceeding an Absolute Maximum Rating can permanently damage the device, so I will not "
                        f"provide code or instructions for it.{op_txt} Use a level shifter / regulator instead.")
            if v["verdict"] == "warn":
                trace.append({"type": "guardrail", "stage": "hardware_safety",
                              "detail": f"WARNING: {req['volts']} V is above the recommended operating range"})
        return None


def _sources(obj):
    if isinstance(obj, dict):
        if "doc" in obj:
            yield obj
        for v in obj.values():
            yield from _sources(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _sources(v)
