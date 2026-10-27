"""Delivery rules shared by commands and AI presentation on supported adapters."""


def text_chunks(text: str, platform: str) -> list[str]:
    """Keep every character, preferring line boundaries over cutting links or rows.

    Count UTF-16 units so supplementary characters also fit Discord's limit.
    QQ Official uses smaller batches to leave room for the host's reply formatting.
    """
    limit = {
        "discord": 2000,
        "qq_official": 1500,
        "qq_official_webhook": 1500,
    }.get(platform, 4000)
    chunks = []
    start = 0
    while start < len(text):
        end = start
        size = 0
        newline = None
        while end < len(text):
            units = 2 if ord(text[end]) > 0xFFFF else 1
            if size + units > limit:
                break
            size += units
            end += 1
            if text[end - 1] == "\n":
                newline = end
        if end < len(text) and newline is not None:
            end = newline
        chunks.append(text[start:end])
        start = end
    return chunks
