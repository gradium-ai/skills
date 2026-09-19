#!/usr/bin/env python3
"""Small Jev adapter. No API calls occur on import or --help."""

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit


INSPECT_PAGE = """(() => ({
  url: location.href,
  text: (document.body?.innerText || '').slice(0, 16000),
  text_truncated: (document.body?.innerText || '').length > 16000,
  frames: [...document.querySelectorAll('iframe')].slice(0,100).map((e, index) => ({
    index, url: e.getAttribute('src') ? e.src : '', title: e.title || '',
    srcdoc: e.hasAttribute('srcdoc')
  })),
  fields: [...document.querySelectorAll('input:not([type="hidden"]),select,button')]
    .filter(e => e.getClientRects().length &&
      e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}))
    .slice(0, 150).map(e => ({tag: e.tagName, type: e.type,
      label: (e.labels?.[0]?.innerText || e.getAttribute('aria-label') || e.innerText || '').slice(0,200),
      value: ['password','file'].includes(e.type) ? '[redacted]' : String(e.value || '').slice(0,2000),
      checked: e.checked, disabled: e.disabled}))
}))()"""


def http_url(value):
    if not isinstance(value, str) or any(ord(c) < 33 or ord(c) == 127 for c in value) or '\\' in value:
        raise ValueError("URL contains whitespace, control characters, or backslashes")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or '@' in parsed.netloc:
        raise ValueError("Use an HTTP(S) URL without embedded credentials")
    parsed.port  # Reject invalid or out-of-range ports before opening a browser.
    return value


def frame_url(evidence, index):
    frames = evidence.get("frames", [])
    if index < 0 or index >= len(frames):
        raise ValueError("Frame index is not present in the current page; inspect again")
    frame = frames[index]
    if frame.get("srcdoc"):
        raise ValueError("Inline srcdoc frames cannot be opened as standalone pages")
    return http_url(frame["url"])


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def output_result(result, include_content=False, include_values=False):
    """Minimize logs, not model inputs. Opt-in content can still contain secrets."""
    if not include_content:
        summary = {k: result[k] for k in (
            "status", "verification", "ticks", "actions", "elapsed_ms", "error_type",
            "message", "inspection_error", "cleanup_error", "browser") if k in result}
        if "checks" in result:
            summary["checks"] = [{"kind": c["kind"], "passed": c["passed"]} for c in result["checks"]]
        if "inspection" in result:
            summary["inspection_available"] = True
        summary["content_omitted"] = True
        return summary
    content = copy.deepcopy(result)
    if not include_values:
        for field in content.get("controls", []) + content.get("inspection", {}).get("fields", []):
            field.pop("value", None)
    return content


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url")
    goal = p.add_mutually_exclusive_group()
    goal.add_argument("--goal")
    goal.add_argument("--goal-file", type=Path)
    p.add_argument("--expect-url", help="Exact final URL assertion")
    p.add_argument("--expect-text", action="append", default=[])
    p.add_argument("--max-ticks", type=positive_int, default=40)
    p.add_argument("--timeout-seconds", type=positive_int, default=120)
    p.add_argument("--keep-open", action="store_true")
    p.add_argument("--output", type=Path)
    p.add_argument("--viewport-height", type=positive_int, default=780,
                   help="Use 2400 to expose long forms; default preserves upstream layout")
    p.add_argument("--inspect-only", action="store_true", help="Observe without model calls or actions")
    p.add_argument("--allow-actions", action="store_true",
                   help="Explicitly enable model calls and autonomous browser inputs")
    p.add_argument("--include-page-content", action="store_true",
                   help="Include potentially sensitive page text, URLs, labels and frame URLs")
    p.add_argument("--include-field-values", action="store_true",
                   help="Include ordinary form values; requires --include-page-content")
    p.add_argument("--session-id", help="Inspect a kept Browser Harness session; requires --inspect-only")
    p.add_argument("--frame-index", type=int, help="Open this observed iframe URL before starting the goal")
    p.add_argument("--expect-frame-url", help="Required exact expected URL for frame handoff")
    return p


def run(args, agent_factory, clock=time.monotonic):
    if not args.inspect_only and not args.allow_actions:
        raise ValueError("Choose --inspect-only or explicitly enable --allow-actions")
    started = clock()
    agent = agent_factory(args.url, args.goal, screenshots=False)
    result = {}
    try:
        handoff = None
        if getattr(args, "frame_index", None) is not None:
            evidence = agent.browser.evaluate(INSPECT_PAGE)
            target = frame_url(evidence, args.frame_index)
            if not args.expect_frame_url or target != args.expect_frame_url:
                raise ValueError("Frame URL changed or was not supplied; inspect again before handoff")
            handoff = {"source_url": evidence["url"], "frame_index": args.frame_index, "url": target}
            agent.close()
            # Only a URL observed in the current DOM is eligible. No model-generated URLs.
            agent = agent_factory(target, args.goal, screenshots=False)
        height = getattr(args, "viewport_height", 780)
        if height != 780:
            agent.browser.call("Emulation.setDeviceMetricsOverride", width=1120, height=height,
                               deviceScaleFactor=1, mobile=False)
            agent.state["page"] = agent.browser.observe(screenshot=False)
        state = agent.snapshot()
        ticks = 0
        inspect_only = getattr(args, "inspect_only", False)
        while not inspect_only and state["status"] not in {"done", "blocked"}:
            if ticks >= args.max_ticks or clock() - started >= args.timeout_seconds:
                break
            state = agent.command("tick")
            ticks += 1
            print(json.dumps({"tick": ticks, "status": state["status"],
                              "actions": len(state["history"])}), file=sys.stderr, flush=True)
        stopped = state["status"] if state["status"] in {"done", "blocked"} else "budget_exhausted"
        # Independent, current browser evidence; never the model's DONE assertion.
        page = agent.browser.observe(screenshot=False)
        checks = []
        if args.expect_url:
            checks.append({"kind": "url", "expected": args.expect_url,
                           "passed": page.get("url") == args.expect_url})
        for expected in args.expect_text:
            checks.append({"kind": "visible_text", "expected": expected,
                           "passed": expected.casefold() in page.get("text", "").casefold()})
        verified = bool(checks) and all(c["passed"] for c in checks)
        result = {
            "status": stopped,
            "verification": "passed" if verified else "failed" if checks else "not_requested",
            "checks": checks,
            "ticks": ticks,
            "actions": len(state["history"]),
            "elapsed_ms": round((clock() - started) * 1000),
            "page": {k: page.get(k) for k in ("url", "title", "text")},
            "controls": [{k: a[k] for k in ("label", "role", "value", "checked", "selected") if k in a}
                         for a in page.get("actions", []) if a.get("node") is not None],
        }
        # Broader read-only diagnostics remain outside Jev's decision prompt.
        try:
            result["inspection"] = agent.browser.evaluate(INSPECT_PAGE)
        except Exception as error:
            result["inspection_error"] = type(error).__name__
        if handoff:
            result["frame_handoff"] = handoff
        if inspect_only:
            result["status"] = "inspected"
            result["verification"] = "not_requested"
        if args.keep_open:
            result["browser"] = {"target": agent.browser.target, "session": agent.browser.session}
        return result, 0 if inspect_only or (stopped == "done" and verified) else 2
    finally:
        if not args.keep_open:
            try:
                agent.close()
            except Exception as error:
                # Preserve task evidence while making an owned-tab cleanup failure visible.
                result["cleanup_error"] = type(error).__name__
                print("Owned tab cleanup failed; inspect Chrome.", file=sys.stderr)
        else:
            print(json.dumps({"kept_browser": {"target": agent.browser.target,
                                                "session": agent.browser.session}}), file=sys.stderr)


def main(argv=None):
    args = parser().parse_args(argv)
    output = None
    setup_complete = False
    try:
        if args.inspect_only == args.allow_actions:
            raise ValueError("Choose exactly one of --inspect-only and --allow-actions")
        if args.include_field_values and not args.include_page_content:
            raise ValueError("--include-field-values requires --include-page-content")
        if (args.frame_index is None) != (args.expect_frame_url is None):
            raise ValueError("Frame handoff requires both --frame-index and --expect-frame-url")
        if args.expect_frame_url:
            http_url(args.expect_frame_url)
        if not args.session_id:
            if not args.url:
                raise ValueError("Supply --url or --session-id with --inspect-only")
            http_url(args.url)
        args.goal = args.goal_file.read_text(encoding="utf-8") if args.goal_file else args.goal
        if args.inspect_only:
            args.goal = args.goal or "Inspect the current page without taking any actions."
        if not args.goal or not args.goal.strip() or any(not value.strip() for value in args.expect_text):
            raise ValueError("Goals and text assertions must not be empty")
        if args.session_id and (not args.inspect_only or args.frame_index is not None or args.viewport_height != 780):
            raise ValueError("Existing sessions support read-only inspection only; omit frame and viewport options")
        missing = [key for key in ("TYPESAFE_API_KEY",) if not os.environ.get(key)] if not args.inspect_only else []
        if missing:
            raise ValueError("Missing environment variables: " + ", ".join(missing))
        if not args.inspect_only and os.environ.get("TEXT_MODEL_API_KEY"):
            endpoint = os.environ.get("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1")
            http_url(endpoint)
            if urlsplit(endpoint).scheme != "https":
                raise ValueError("Text-model API credentials require an HTTPS endpoint")
        # Reserve output before any browser side effects; never overwrite prior results.
        if args.output:
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            output = os.fdopen(fd, "w", encoding="utf-8")
        setup_complete = True
        if args.session_id:
            from browser_harness.helpers import cdp
            reply = cdp("Runtime.evaluate", session_id=args.session_id,
                        expression=INSPECT_PAGE, returnByValue=True)
            if reply.get("exceptionDetails") or not isinstance(reply.get("result", {}).get("value"), dict):
                raise RuntimeError("Could not inspect the current session")
            result, code = {"status": "inspected", "verification": "not_requested",
                            "inspection": reply["result"]["value"]}, 0
        else:
            from jev_ultrafast import Agent
            result, code = run(args, Agent)
    except (Exception, KeyboardInterrupt) as error:
        # Provider exceptions can contain request data. Don't dump arbitrary errors or traces.
        result = {"status": "error", "error_type": type(error).__name__,
                  "message": "Run stopped. Inspect current browser state before retrying."}
        if isinstance(error, (ValueError, FileNotFoundError, FileExistsError, ModuleNotFoundError)):
            # Only expose actionable setup errors occurring before importing/starting Jev.
            if not setup_complete:
                result["message"] = str(error)
        code = 1
    result = output_result(result, args.include_page_content, args.include_field_values)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if output:
        with output:
            output.write(payload + "\n")
    # A private output file should not also spray page content into terminal/chat logs.
    print(json.dumps(output_result(result), ensure_ascii=False, indent=2) if output else payload, flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
