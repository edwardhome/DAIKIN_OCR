"""Expose reported token counts without leaking provider response bodies."""

TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def _count(value):
    # bool is a subclass of int; strings and floats are not trustworthy API counts.
    return value if type(value) is int and value >= 0 else None


def normalize_token_usage(provider, raw_result):
    result = dict.fromkeys(TOKEN_FIELDS)
    if not isinstance(raw_result, dict):
        return result
    if provider == "nvidia":
        usage = raw_result.get("usage")
        if not isinstance(usage, dict):
            return result
        result = {
            "input_tokens": _count(usage.get("prompt_tokens")),
            "output_tokens": _count(usage.get("completion_tokens")),
            "total_tokens": _count(usage.get("total_tokens")),
        }
    elif provider == "ollama":
        result["input_tokens"] = _count(raw_result.get("prompt_eval_count"))
        result["output_tokens"] = _count(raw_result.get("eval_count"))
    elif provider == "gemini":
        usage = raw_result.get("usageMetadata")
        if not isinstance(usage, dict):
            return result
        result["input_tokens"] = _count(usage.get("promptTokenCount"))
        result["total_tokens"] = _count(usage.get("totalTokenCount"))
        candidates = _count(usage.get("candidatesTokenCount"))
        thoughts = _count(usage.get("thoughtsTokenCount"))
        no_tools = "toolUsePromptTokenCount" not in usage or (
            _count(usage["toolUsePromptTokenCount"]) == 0
        )
        if candidates is not None and thoughts is not None:
            result["output_tokens"] = candidates + thoughts
        elif (
            result["input_tokens"] is not None
            and result["total_tokens"] is not None
            and result["total_tokens"] >= result["input_tokens"]
            and no_tools
        ):
            # Total includes thoughts. An absent thoughts count does not imply zero.
            output = result["total_tokens"] - result["input_tokens"]
            if all(count is None or output >= count for count in (candidates, thoughts)):
                result["output_tokens"] = output
        if (
            result["total_tokens"] is None
            and no_tools
            and all(result[key] is not None for key in ("input_tokens", "output_tokens"))
        ):
            result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
        return result
    else:
        return result
    if result["total_tokens"] is None and all(
        result[key] is not None for key in ("input_tokens", "output_tokens")
    ):
        result["total_tokens"] = result["input_tokens"] + result["output_tokens"]
    return result


def aggregate_token_usage(usages):
    """An absent count on any call means that component's total is unknown."""
    return {
        key: sum(usage[key] for usage in usages)
        if usages and all(usage[key] is not None for usage in usages)
        else None
        for key in TOKEN_FIELDS
    }
