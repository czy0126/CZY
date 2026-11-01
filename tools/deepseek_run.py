"""Run one saved, narrowly scoped DeepSeek Flash prompt without exposing its key.

Example:
    python armA/deepseek_flash_run.py --prompt armA/16to1-next-deepseek-prompt.md \
        --reply armA/16to1-next-deepseek-reply.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--reply", type=Path, required=True)
    parser.add_argument("--thinking", choices=["enabled","disabled"], default="disabled")
    parser.add_argument("--max-tokens", type=int, default=1500)
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
    key = (Path(r"D:\workshop\circuit_net\deepseekapi.txt")).read_text(encoding="utf-8").strip()
    payload = {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": prompt}],
        "thinking": {"type": args.thinking},
        "max_tokens": args.max_tokens,
    }
    request = Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"DeepSeek HTTP {exc.code}; reply not written") from None
    except URLError as exc:
        raise SystemExit(f"DeepSeek network error: {type(exc.reason).__name__}; reply not written") from None
    reply = result["choices"][0]["message"]["content"]
    metadata = {"model": result.get("model"), "usage": result.get("usage"), "finish_reason": result["choices"][0].get("finish_reason")}
    args.reply.parent.mkdir(parents=True, exist_ok=True)
    args.reply.write_text(reply, encoding="utf-8", newline="\n")
    args.reply.with_suffix(".meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {args.reply}; total_tokens={result.get('usage', {}).get('total_tokens', 'unknown')}")


if __name__ == "__main__":
    main()
