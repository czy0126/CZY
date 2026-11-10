"""Run one saved, narrowly scoped DeepSeek Flash prompt without exposing its key.

Example:
    python armA/deepseek_flash_run.py --prompt armA/16to1-next-deepseek-prompt.md \
        --reply armA/16to1-next-deepseek-reply.md
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--reply", type=Path, required=True)
    parser.add_argument("--thinking", choices=["enabled","disabled"], default="disabled")
    parser.add_argument("--max-tokens", type=int, default=1500)
    parser.add_argument("--key-file", type=Path,
                        help="Credential file path; alternatively set DEEPSEEK_API_KEY or DEEPSEEK_API_KEY_FILE")
    parser.add_argument("--claude-settings", type=Path,
                        help="Read ONLY Anthropic-compatible DeepSeek connection fields from this JSON; never send the file")
    parser.add_argument("--context-file", type=Path, action="append", default=[],
                        help="Append a local UTF-8 evidence excerpt to the prompt")
    args = parser.parse_args()
    if args.max_tokens <= 0:
        parser.error("--max-tokens must be positive")
    if args.reply.exists():
        parser.error("reply already exists; refuse to overwrite evidence")

    prompt = args.prompt.read_text(encoding="utf-8")
    if args.context_file:
        excerpts = []
        for source in args.context_file:
            path = source.resolve()
            if not path.is_relative_to(ROOT) or path == ROOT / "deepseekapi.txt":
                parser.error(f"context file must be inside workspace and not the API key: {source}")
            body = path.read_text(encoding="utf-8")
            if len(body) > 150000:
                parser.error(f"context file exceeds 150000 characters: {source}")
            excerpts.append(f"\n\n## Evidence: {path.relative_to(ROOT)}\n{body}")
        prompt += "".join(excerpts)
    key_path = args.key_file or Path(os.environ.get("DEEPSEEK_API_KEY_FILE", r"D:\workshop\circuit_net\deepseekapi.txt"))
    if args.claude_settings and any(source.resolve() == args.claude_settings.resolve() for source in args.context_file):
        parser.error("settings credentials cannot be sent as context")
    if any(source.resolve() == key_path.resolve() for source in args.context_file):
        parser.error("credential file cannot be sent as context")
    endpoint="https://api.deepseek.com/chat/completions"
    model="deepseek-flash"
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip() if args.key_file is None else ""
    if args.claude_settings:
        env=json.loads(args.claude_settings.read_text(encoding="utf-8-sig")).get("env", {})
        base_url=env.get("ANTHROPIC_BASE_URL", "").rstrip("/")
        if urlparse(base_url).scheme != "https" or urlparse(base_url).netloc != "api.deepseek.com" or urlparse(base_url).path != "/anthropic":
            parser.error("settings must point to the official DeepSeek Anthropic endpoint")
        key=env.get("ANTHROPIC_AUTH_TOKEN", "").strip()
        if not key:
            parser.error("DeepSeek token missing in selected settings")
        model=env.get("ANTHROPIC_MODEL", "deepseek-flash")
        endpoint=base_url+"/v1/messages"
    if not key:
        try:
            key = key_path.read_text(encoding="utf-8-sig").strip()
        except FileNotFoundError:
            raise SystemExit("DeepSeek credential file missing; use --key-file or DEEPSEEK_API_KEY. No request sent.") from None
    if not key or "\n" in key or "\r" in key:
        raise SystemExit("DeepSeek credential must be one nonempty line. No request sent.")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "thinking": {"type": args.thinking},
        "max_tokens": args.max_tokens,
    }
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if args.claude_settings:
        headers["anthropic-version"]="2023-06-01"
        if args.thinking == "enabled":
            payload["thinking"]={"type":"enabled","budget_tokens":1024}
        else:
            payload["thinking"]={"type":"disabled"}
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"DeepSeek HTTP {exc.code}; reply not written") from None
    except URLError as exc:
        raise SystemExit(f"DeepSeek network error: {type(exc.reason).__name__}; reply not written") from None
    if args.claude_settings:
        reply="\n".join(block["text"] for block in result.get("content",[]) if block.get("type")=="text")
        finish=result.get("stop_reason")
    else:
        reply = result["choices"][0]["message"]["content"]
        finish=result["choices"][0].get("finish_reason")
    if not reply:
        raise SystemExit("DeepSeek returned no text; no reply written")
    metadata = {"model": result.get("model"), "usage": result.get("usage"), "finish_reason": finish}
    args.reply.parent.mkdir(parents=True, exist_ok=True)
    args.reply.write_text(reply, encoding="utf-8", newline="\n")
    args.reply.with_suffix(".meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {args.reply}; total_tokens={result.get('usage', {}).get('total_tokens', 'unknown')}")


if __name__ == "__main__":
    main()
