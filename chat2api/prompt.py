def flatten_messages(messages: list[dict]) -> str:
    parts = []
    system = "\n".join(m["content"] for m in messages if m["role"] == "system" and m["content"])
    if system:
        parts.append(f"System: {system}")
    for m in messages:
        if m["role"] == "system":
            continue
        content = m["content"]
        if not content and m.get("attachments"):
            # Lượt chỉ có file: vẫn phải có dòng để site biết đây là một lượt hỏi.
            content = "[đính kèm: " + ", ".join(a.name for a in m["attachments"]) + "]"
        if not content:
            continue
        who = "User" if m["role"] == "user" else "Assistant"
        parts.append(f"{who}: {content}")
    return "\n\n".join(parts)
