"""Writes the synthetic debug bundles in fixtures/calls/.

These follow the documented shape of GET /executions/{id}/debug
(https://www.bolna.ai/docs/api-reference/executions/get_execution_debug).
They are hand-written examples, not real Bolna calls.
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "calls"


def turn(tid, endpoint, queue, llm_tts, tts_audio, llm=400):
    return {"sequence_id": tid, "turn_id": tid, "asr_end_to_user_end_ms": endpoint,
            "llm_start_to_asr_end_ms": queue, "llm_duration_ms": llm,
            "tts_start_to_llm_start_ms": llm_tts, "agent_speech_to_tts_start_ms": tts_audio}


def a(text, **kw):
    return {"kind": "message", "role": "agent", "text": text, **kw}


def u(text, **kw):
    return {"kind": "message", "role": "user", "text": text, **kw}


def tool(name, status, code, ms, ts):
    return {"kind": "function_call", "tool_name": name, "status": status,
            "response_status_code": code, "tool_latency_ms": ms, "ts_ms": ts}


def ev(label, ts):
    return {"kind": "event", "label": label, "ts_ms": ts}


def bundle(eid, use_case, turns, transcript, duration):
    return {"execution_id": eid, "unavailable": {},
            "execution": {"id": eid, "status": "completed", "conversation_duration": duration,
                          "context_details": {"recipient_data": {"use_case": use_case}}},
            "progression": {"call_start_at": "2026-10-24T10:00:00Z", "turns": turns,
                            "transcript": transcript},
            "logs": []}


CALLS = [
    bundle("a1c04e2b-0c55-4f0e-9d0a-6f1b2e7c9a01", "emi_reminder",
           [turn(1, 320, 80, 410, 190), turn(2, 360, 90, 380, 210), turn(3, 300, 70, 450, 200)], [
        a("Namaste Rahul ji, main Finserv se baat kar rahi hoon. Aapki EMI ki due date 5 November hai, kya aap"
          " ise time pe pay kar payenge?", interrupted=True),
        u("Ruko ruko, maine kal hi pay kar diya hai"),
        a("Achha, thank you Rahul ji. Main check karti hoon, kya aap UPI reference number bata sakte hain?"),
        u("Haan, 4471 se end hota hai"),
        a("Dhanyavaad, payment mil gaya hai. Aapka din shubh ho."),
        u("Theek hai, bye"),
        ev("hangup", 61000)], 61),

    bundle("b2d19a7e-5f3c-4b8e-8a64-2c0d9e1f7b02", "order_status",
           [turn(1, 340, 90, 420, 200), turn(2, 310, 100, 2950, 240), turn(3, 350, 80, 400, 190)], [
        a("Hi Priya, this is Kart support. I can see you have an order for running shoes, would you like an"
          " update on the delivery?", interrupted=True),
        u("haan"),
        a("Hi Priya, this is Kart support. I can see you have an order for running shoes, would you like an"
          " update on the delivery?"),
        u("Haan bolo, kab aayega?"),
        tool("get_order_status", "success", 200, 3400, 24000),
        a("Aapka order kal shaam 6 baje tak deliver ho jayega."),
        u("Ok thank you"),
        ev("hangup", 41000)], 41),

    bundle("c3e88b10-2a4d-4c7f-b1e9-7d5a3c2f0c03", "clinic_booking",
           [turn(1, 330, 70, 390, 180), turn(2, 340, 90, 2400, 260)], [
        a("Namaskar, Sunrise Clinic. Aap kis din appointment lena chahenge?"),
        u("Kal subah das baje Dr. Mehta ke saath"),
        tool("book_slot", "error", 500, 1800, 15500),
        a("Ek second, main slot check kar rahi hoon."),
        u("Hello? Kya hua, booking hua ki nahi?"),
        ev("hangup_after_silence", 34000)], 34),

    bundle("d4f2c7a9-8e1b-4d3a-9c55-0b6e4a8d1d04", "loan_lead",
           [turn(1, 2300, 80, 420, 210), turn(2, 340, 70, 400, 200), turn(3, 310, 90, 380, 190)], [
        a("Namaste, kya aap personal loan ke liye interested hain?"),
        u("Haan, mujhe do lakh chahiye"),
        a("Bilkul. Aapki monthly income kitni hai?"),
        u("Ek minute, mere paas PAN card bhi hai", not_sent_to_agent=True, ts_exact=False),
        u("Pachas hazaar mahina"),
        a("Dhanyavaad. Hamari team aapko aaj call karegi."),
        u("Ok ji, dhanyavaad"),
        ev("hangup", 52000)], 52),

    bundle("e5a6d3f1-1b9c-4e2d-8f70-3a8c5b9e2e05", "policy_renewal",
           [turn(1, 300, 80, 400, 200), turn(2, 290, 70, 410, 190)], [
        a("Hello Amit, aapki health policy 30 November ko expire ho rahi hai. Renewal ke liye main aapko"
          " teen plans bata sakti hoon, pehla plan hai", interrupted=True),
        u("ok ok"),
        a("Main aapko plans ka link WhatsApp pe bhej deti hoon."),
        u("Haan bhej do, theek hai bye"),
        ev("hangup", 28000)], 28),

    bundle("f6b3e9c2-7d4a-4f1b-a2c8-5e9d0f3a6f06", "emi_reminder",
           [turn(1, 330, 90, 420, 200), turn(2, 320, 80, 410, 210)], [
        a("Namaste Sunita ji, aapki EMI 5 November ko due hai. Late fee se bachne ke liye kripya time pe pay"
          " karein. Kya main aapko payment link bhej doon?"),
        u("Mera account freeze hai, main abhi nahi kar sakti"),
        a("Samajh gayi. Main aapki request team ko bhej rahi hoon, woh aapko call karenge."),
        u("Theek hai, dhanyavaad"),
        ev("hangup", 39000)], 39),
]

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for c in CALLS:
        (OUT / f"{c['execution_id'][:8]}.json").write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(CALLS)} bundles to {OUT}")
