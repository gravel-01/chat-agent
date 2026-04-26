def truncate_text(text, limit=140):
    value = (text or "").strip().replace("\r", " ")
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def format_count(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def clamp(value, minimum, maximum):
    if maximum < minimum:
        return minimum
    return max(minimum, min(value, maximum))
