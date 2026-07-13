import os
import httpx

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = "1041c1422acf47a7a9a54e533a3e2129"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

GRADE_MAP = {
    "Junior": "Jun",
    "Mid": "Mid",
    "Senior": "Senior",
    "Lead": "Lead",
    "Unknown": "Unknown",
}

VALID_SKILLS = {
    "Python", "JavaScript", "React", "Node.js", "Go", "Java",
    "DevOps", "Product", "Design", "Marketing", "Sales", "Other",
}


async def create_candidate_entry(candidate: dict, submitted_by: str) -> str:
    properties: dict = {
        "Name": {
            "title": [{"text": {"content": candidate.get("name") or "Unknown"}}]
        },
        "Phase": {"select": {"name": "New Lead"}},
        "Submitted By": {"rich_text": [{"text": {"content": submitted_by}}]},
    }

    if candidate.get("email"):
        properties["Email"] = {"email": candidate["email"]}

    if candidate.get("phone"):
        properties["Phone"] = {"phone_number": candidate["phone"]}

    if candidate.get("position"):
        properties["Position"] = {
            "rich_text": [{"text": {"content": candidate["position"][:2000]}}]
        }

    grade = GRADE_MAP.get(candidate.get("experience_level", ""))
    if grade:
        properties["Grade"] = {"select": {"name": grade}}

    skills = [s for s in (candidate.get("skills") or []) if s in VALID_SKILLS]
    if skills:
        properties["Skills"] = {"multi_select": [{"name": s} for s in skills]}

    if candidate.get("linkedin"):
        properties["LinkedIn"] = {"url": candidate["linkedin"]}

    if candidate.get("notes"):
        properties["Screening Notes"] = {
            "rich_text": [{"text": {"content": candidate["notes"][:2000]}}]
        }

    payload = {"parent": {"database_id": DATABASE_ID}, "properties": properties}

    async with httpx.AsyncClient(timeout=15) as http:
        response = await http.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json=payload,
        )
        response.raise_for_status()
        return response.json()["url"]
