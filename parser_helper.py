import os
import json
import logging
import httpx

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"

VALID_SKILLS = [
    "Python", "JavaScript", "React", "Node.js", "Go", "Java",
    "DevOps", "Product", "Design", "Marketing", "Sales", "Other",
]
VALID_LEVELS = ["Junior", "Mid", "Senior", "Lead", "Unknown"]


async def parse_candidate(text: str) -> dict:
    prompt = f"""Extract candidate information from the text below and return a JSON object.

Text:
{text}

Return ONLY valid JSON with these fields (omit any field not found in the text):
- name: string (full name)
- email: string
- phone: string
- position: string (job title or role they are applying for)
- experience_level: one of {VALID_LEVELS}
- skills: array using only values from {VALID_SKILLS}
- linkedin: string (URL)
- notes: string (any relevant info not captured in the fields above)

Return the JSON object only, no markdown, no explanation."""

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            response = await http.post(
                GEMINI_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-goog-api-key": GEMINI_API_KEY,
                },
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            response.raise_for_status()

        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Strip markdown code fences if Gemini wraps the response
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()

        return json.loads(raw)
    except Exception as e:
        logger.warning("Parsing failed, falling back to raw notes: %s", e)
        return {"notes": text}
