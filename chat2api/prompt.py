def flatten_messages(messages: list[dict]) -> str:
    parts = []
    system = "\n".join(m["content"] for m in messages if m["role"] == "system" and m["content"])
    if system:
        parts.append(f"System: {system}")
    for m in messages:
        if m["role"] == "system" or not m["content"]:
            continue
        who = "User" if m["role"] == "user" else "Assistant"
        parts.append(f"{who}: {m['content']}")
    return "\n\n".join(parts)
