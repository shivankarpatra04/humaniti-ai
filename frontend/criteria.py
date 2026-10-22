"""Criterion names and the two report sections; the frontend cannot import them from app."""

CRITERIA = {
    "bg_8x8": "8×8 background",
    "camera_on": "Camera on while teaching",
    "lighting": "Lighting and camera position",
    "rapport": "Rapport before teaching",
    "new_joiner_intro": "New joiners introduced",
    "individual_attention": "Individual attention",
    "homework": "Homework",
    "conclusion": "Conclusion",
    "energy": "Energy and pleasant interaction",
    "clarity": "Clarity",
    "extras": "Extras",
}
# same split as app/llm/schemas.py (decision 32): what agreed with QA, and what QA has to check
MEASURED = ("bg_8x8", "camera_on", "lighting", "homework", "individual_attention")
NEEDS_QA_CHECK = ("rapport", "new_joiner_intro", "energy", "conclusion", "clarity", "extras")
VERDICTS = {
    "met": "✅ met",
    "partly": "⚠️ partly",
    "not_met": "❌ not met",
    "not_applicable": "– not applicable",
}


def criterion_name(criterion: str) -> str:
    return CRITERIA.get(criterion, criterion)
