#!/usr/bin/env python3
"""Reality DB batch import (2026-09-23): JSONL -> POST /api/reality/observations/batch.

Pipeline for scaling the data moat: vendor datasheet / literature entries are
normalized offline (explicit conversion basis in `note`), one JSON object per
line, then imported in a single idempotent batch.

Idempotency: every entry MUST carry a unique `externalKey`. Re-running the
same file results in created=0 / skipped=N (no duplicates).

Exit codes: 0 ok; 2 rejected (fix the file, see response); 3 network/server
error (retryable, nothing partially imported).

ASCII only on purpose (git-bash heredoc/GBK lesson, see deploy/demo notes).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def http_json(method, url, body, token):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        # platform auth header is the BARE token (no "Bearer " prefix)
        req.add_header("Authorization", token)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="JSONL file, one observation per line")
    ap.add_argument("--api-endpoint", required=True, help="e.g. http://localhost:18090")
    ap.add_argument("--token", help="bare auth token (or set ROBOVERIFY_TOKEN env)")
    ap.add_argument("--username")
    ap.add_argument("--password", help="prefer ROBOVERIFY_PASSWORD env over this flag "
                                       "(CLI args persist in shell history / process lists)")
    args = ap.parse_args()

    entries = []
    with open(args.file, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except ValueError as e:
                print("line %d: invalid JSON: %s" % (lineno, e), file=sys.stderr)
                return 2
            if not obj.get("externalKey"):
                print("line %d: externalKey is required for batch import" % lineno,
                      file=sys.stderr)
                return 2
            entries.append(obj)
    if not entries:
        print("no entries found in %s" % args.file, file=sys.stderr)
        return 2

    token = args.token or os.environ.get("ROBOVERIFY_TOKEN")
    if not token:
        password = args.password or os.environ.get("ROBOVERIFY_PASSWORD")
        if not (args.username and password):
            print("need --token (or ROBOVERIFY_TOKEN env) or --username + password "
                  "(--password flag or ROBOVERIFY_PASSWORD env)", file=sys.stderr)
            return 2
        try:
            login = http_json("POST", args.api_endpoint.rstrip("/") + "/api/auth/login",
                              {"username": args.username, "password": password}, None)
            token = login["data"]["token"]
        except (urllib.error.URLError, KeyError, ValueError) as e:
            print("login failed: %s" % e, file=sys.stderr)
            return 3

    try:
        resp = http_json("POST",
                         args.api_endpoint.rstrip("/") + "/api/reality/observations/batch",
                         {"observations": entries}, token)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code >= 500:
            # server-side failure: batch is transactional (nothing partially imported),
            # retry is safe -> exit 3 per contract, not "fix the file"
            print("server error (HTTP %d, retryable): %s" % (e.code, body), file=sys.stderr)
            return 3
        print("rejected (HTTP %d): %s" % (e.code, body), file=sys.stderr)
        return 2
    except urllib.error.URLError as e:
        print("server unreachable: %s (retryable)" % e, file=sys.stderr)
        return 3

    data = resp.get("data") or {}
    print("total=%s created=%s skipped=%s"
          % (data.get("total"), data.get("created"), data.get("skipped")))
    for r in data.get("results") or []:
        if not r.get("created"):
            print("  skipped (existing externalKey): %s" % r.get("externalKey"))
    # HTTP 200 means the server accepted the whole batch; its skipped count always
    # equals total - created, so no partial-failure exit-2 branch is reachable here.
    return 0


if __name__ == "__main__":
    sys.exit(main())
