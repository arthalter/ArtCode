from __future__ import annotations

import re
from functools import lru_cache


class GlobError(ValueError):
    pass


@lru_cache(maxsize=512)
def _compile(pattern: str, path_mode: bool) -> re.Pattern[str]:
    if not pattern:
        raise GlobError("Glob pattern 不能为空")
    result = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            index += 1
            result.append(re.escape(pattern[index]))
        elif char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if path_mode and index < len(pattern) and pattern[index] == "/":
                    result.append("(?:.*/)?")
                    index += 1
                else:
                    result.append(".*")
                continue
            result.append("[^/]*" if path_mode else ".*")
        elif char == "?":
            result.append("[^/]" if path_mode else ".")
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end == -1:
                result.append(r"\[")
            else:
                content = pattern[index + 1 : end]
                if content.startswith("!"):
                    content = "^" + content[1:]
                result.append("[" + content.replace("\\", "\\\\") + "]")
                index = end
        else:
            result.append(re.escape(char))
        index += 1
    result.append("$")
    try:
        return re.compile("".join(result))
    except re.error as exc:
        raise GlobError(f"非法 Glob：{pattern}（{exc}）") from exc


def glob_match(pattern: str, value: str, *, path_mode: bool) -> bool:
    return _compile(pattern, path_mode).fullmatch(value) is not None
