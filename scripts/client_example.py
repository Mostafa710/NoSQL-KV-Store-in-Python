#!/usr/bin/env python3
"""Sample CLI usage of KVClient. Usage: python scripts/client_example.py [--port 4000] get KEY | set KEY VALUE | delete KEY | bulkset KEY1 VAL1 KEY2 VAL2 ..."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from client import KVClient, KVClientError


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=4000)
    p.add_argument("cmd", choices=["get", "set", "delete", "bulkset"], help="Command")
    p.add_argument("args", nargs="*", help="Key, or key value, or key value pairs for bulkset")
    args = p.parse_args()
    client = KVClient(host=args.host, port=args.port)
    try:
        if args.cmd == "get":
            if len(args.args) != 1:
                print("Usage: get KEY", file=sys.stderr)
                sys.exit(1)
            val = client.Get(args.args[0])
            if val is None:
                print("(not found)")
            else:
                print(val.decode("utf-8", errors="replace"))
        elif args.cmd == "set":
            if len(args.args) != 2:
                print("Usage: set KEY VALUE", file=sys.stderr)
                sys.exit(1)
            client.Set(args.args[0], args.args[1].encode("utf-8"))
            print("OK")
        elif args.cmd == "delete":
            if len(args.args) != 1:
                print("Usage: delete KEY", file=sys.stderr)
                sys.exit(1)
            ok = client.Delete(args.args[0])
            print("deleted" if ok else "not found")
        elif args.cmd == "bulkset":
            if len(args.args) % 2 != 0:
                print("Usage: bulkset KEY1 VAL1 KEY2 VAL2 ...", file=sys.stderr)
                sys.exit(1)
            items = [(args.args[i], args.args[i + 1].encode("utf-8")) for i in range(0, len(args.args), 2)]
            client.BulkSet(items)
            print("OK")
    except KVClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
