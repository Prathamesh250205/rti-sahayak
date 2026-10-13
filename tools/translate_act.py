"""One-off: translate the Act's 83 indexed chunks into Hindi and Marathi.

The official Hindi (DoPT) and Marathi (Maharashtra SIC) PDFs are image scans /
legacy-font files with no extractable text, so the site shows these AI
translations - labelled unofficial, linking to the official PDFs, with the
English one click away. Output: data/index/translations.json
{"hi": {chunk_id: text}, "mr": {...}}, committed; the site never calls an LLM
for this. Resumable: re-running only fills in missing or failed chunks.

Free-tier friendly: chunks go to Gemini in batches (~10 requests per
language, inside its ~20/day cap); anything that fails validation is retried
one chunk at a time on Groq (lower quality - check the printed list).

    python -m tools.translate_act
"""
import json
import os
import re
import sys
import time

from llm import client as llm
from rag.retriever import INDEX_DIR

OUT = os.path.join(INDEX_DIR, "translations.json")
LANG = {"hi": "Hindi", "mr": "Marathi"}
BATCH_CHARS = 12000  # ~7 Gemini requests per language
# Terms as used in the official Hindi Act and Maharashtra's Marathi version.
GLOSSARY = {
    "hi": "section = धारा; sub-section = उपधारा; clause = खंड; proviso = परंतुक; Public Information Officer = लोक सूचना अधिकारी; "
          "Central Public Information Officer = केन्द्रीय लोक सूचना अधिकारी; State Public Information Officer = राज्य लोक सूचना अधिकारी; "
          "public authority = लोक प्राधिकारी; Central Information Commission = केन्द्रीय सूचना आयोग; State Information Commission = राज्य सूचना आयोग; "
          "Chief Information Commissioner = मुख्य सूचना आयुक्त; Information Commissioner = सूचना आयुक्त; "
          "appropriate Government = समुचित सरकार; third party = पर व्यक्ति; information = सूचना; record = अभिलेख; appeal = अपील",
    "mr": "section = कलम; sub-section = पोट-कलम; clause = खंड; proviso = परंतुक; Public Information Officer = जन माहिती अधिकारी; "
          "Central Public Information Officer = केंद्रीय जन माहिती अधिकारी; State Public Information Officer = राज्य जन माहिती अधिकारी; "
          "public authority = सार्वजनिक प्राधिकरण; Central Information Commission = केंद्रीय माहिती आयोग; State Information Commission = राज्य माहिती आयोग; "
          "Chief Information Commissioner = मुख्य माहिती आयुक्त; Information Commissioner = माहिती आयुक्त; "
          "appropriate Government = समुचित शासन; third party = त्रयस्थ पक्ष; information = माहिती; record = अभिलेख; appeal = अपील",
}
RULES = (
    "You translate excerpts of India's Right to Information Act, 2005 from English into {lang}, in the formal "
    "register of Indian legislation. Use exactly these terms: {glossary}. The excerpts were extracted from a PDF, "
    "so they have artefacts: '(/)' means '(1)', 'vvithin' means 'within', words may be run together or split "
    "across lines - read through them. Translate everything; do not add, omit, explain or summarise. Keep every "
    "number and every section/sub-section/clause marker such as 6(1), (a), (i), and keep a line break wherever "
    "the English starts a new numbered item. Use international digits (0-9)."
)


def ok(english: str, out) -> bool:
    if not isinstance(out, str) or len(re.findall(r"[ऀ-ॿ]", out)) < 10:
        return False
    if not 0.5 <= len(out) / max(len(english), 1) <= 2.5:
        return False
    if re.search(r"(?:[A-Za-z,]+ +){5}", out):  # a sentence left in English
        return False
    # Office titles must not be swapped (Groq once wrote "State Information
    # Commissioner" as "State Public Information Officer").
    en = " ".join(english.split())
    for term_en, term_out in (("Commissioner", "आयुक्त"), ("Information Officer", "(सूचना|माहिती) अधिकारी")):
        if bool(re.search(term_en, en)) != bool(re.search(term_out, out)):
            return False
    if re.search(r"Commission\b", en) and "आयोग" not in out:
        return False
    # \b skips OCR junk like ".4ct" (= "Act"), whose digit has no number to keep
    return set(re.findall(r"\b\d+\b", english)) <= set(re.findall(r"\b\d+\b", out))


def call(provider: str, prompt: str, system: str) -> str:
    llm.PROVIDER_CHAIN = (provider,)
    # Gemini is a reasoning model: thinking tokens count against this budget.
    return llm.generate(prompt, system=system, max_tokens=30000 if provider == "gemini" else 4000)


gemini_quota_left = True


def translate_batch(lang: str, items: list[tuple[str, str]]) -> dict:
    global gemini_quota_left
    if not gemini_quota_left:
        return {}
    system = RULES.format(lang=LANG[lang], glossary=GLOSSARY[lang]) + (
        " You will get a JSON object mapping ids to English excerpts. Reply with ONLY a JSON object mapping the "
        "same ids to their translations.")
    for attempt in range(3):  # 503 "high demand" is common and transient
        try:
            raw = call("gemini", json.dumps(dict(items), ensure_ascii=False), system)
            return llm.parse_json_object(raw)
        except (llm.LLMError, ValueError) as e:
            print("  batch failed:", str(e)[:160], file=sys.stderr)
            if "RESOURCE_EXHAUSTED" in str(e):  # daily cap: the rest go to Groq
                gemini_quota_left = False
                return {}
            time.sleep(30 * (attempt + 1))
    return {}


def translate_one(lang: str, english: str):
    system = RULES.format(lang=LANG[lang], glossary=GLOSSARY[lang]) + f" Output only the {LANG[lang]} translation."
    for attempt in range(4):
        try:
            out = call("groq", english, system).strip()
            if ok(english, out):
                return out
        except llm.LLMError as e:
            print("  groq:", str(e)[:120], file=sys.stderr)
        time.sleep(20 * (attempt + 1))  # per-minute token limits
    return None


def main():
    chunks = json.load(open(os.path.join(INDEX_DIR, "chunks.json"), encoding="utf-8"))
    docs = dict(zip(chunks["ids"], chunks["documents"]))
    done = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    save = lambda: json.dump(done, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    for lang in LANG:
        have = done.setdefault(lang, {})
        todo = [cid for cid in chunks["ids"] if cid not in have]
        batches, cur, size = [], [], 0
        for cid in todo:
            if cur and size + len(docs[cid]) > BATCH_CHARS:
                batches.append(cur); cur, size = [], 0
            cur.append(cid); size += len(docs[cid])
        if cur:
            batches.append(cur)
        print(f"{lang}: {len(todo)} chunks in {len(batches)} Gemini batches")
        for n, batch in enumerate(batches, 1):
            got = translate_batch(lang, [(cid, docs[cid]) for cid in batch])
            good = [cid for cid in batch if ok(docs[cid], got.get(cid))]
            for cid in good:
                have[cid] = got[cid].strip()
            save()
            print(f"  batch {n}/{len(batches)}: {len(good)}/{len(batch)} ok")
            if gemini_quota_left:
                time.sleep(13)  # Gemini free tier: 5 requests/minute
        missing = [cid for cid in chunks["ids"] if cid not in have]
        for cid in missing:
            out = translate_one(lang, docs[cid])
            if out:
                have[cid] = out
                save()
            print(f"  groq retry {cid}: {'ok' if out else 'FAILED'}")
    save()
    print({lang: f"{len(v)}/{len(docs)}" for lang, v in done.items()})


if __name__ == "__main__":
    main()
