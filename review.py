"""Private document review preferences; no external-action authorization."""
from pathlib import Path
import uuid
import career

MODES = {"manual", "ai-self-review"}
QUESTION = "Do you want to manually approve each document pair, or let your AI assistant self-review and finalize it?"


def preference(root, mode=None):
    root = Path(root).resolve()
    state = root / "state"
    path = state / "review-preference.json"
    if state.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise career.ValidationError("Review preference must stay in the private workspace state directory")
    value = None
    if path.exists():
        value = career.parse_pack(path)
        if (not isinstance(value, dict) or set(value) != {"format_version", "mode", "choice_id"}
                or type(value["format_version"]) is not int or value["format_version"] != 1
                or not isinstance(value["mode"], str) or value["mode"] not in MODES
                or not isinstance(value["choice_id"], str) or len(value["choice_id"]) != 32
                or any(c not in "0123456789abcdef" for c in value["choice_id"])):
            raise career.ValidationError("Review preference is invalid; preserve it and correct its format deliberately")
    if mode is not None:
        if not isinstance(mode, str) or mode not in MODES:
            raise career.ValidationError("Review mode is manual or ai-self-review")
        if (root.is_relative_to(Path(__file__).resolve().parent) or (root / ".git").exists()
                or not (root / "data").is_dir() or not (root / "profile.json").is_file()):
            raise career.ValidationError("Set the review preference in an initialized private workspace outside the checkout")
        if value is None or value["mode"] != mode:
            value = {"format_version": 1, "mode": mode, "choice_id": uuid.uuid4().hex}
            state.mkdir(exist_ok=True)
            career.atomic_text(path, career.pretty(value))
    return value


def status(root, mode=None):
    value = preference(root, mode)
    return {"mode": value["mode"] if value else "manual", "choice_recorded": value is not None,
            "onboarding_required": value is None, "question": QUESTION if value is None else None,
            "scope": "Document review and finalization only; never authorization to send or submit externally.",
            "change": "Use review-mode manual or review-mode ai-self-review after an explicit user choice."}
