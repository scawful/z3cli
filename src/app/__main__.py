import asyncio
import sys


def main() -> int:
    if "--serve" in sys.argv:
        sys.argv.remove("--serve")
        from app.serve import serve_main

        asyncio.run(serve_main(sys.argv[1:]))
        return 0
    if "--bridge" in sys.argv:
        sys.argv.remove("--bridge")
        from app.ws_bridge import bridge_main

        asyncio.run(bridge_main(sys.argv[1:]))
        return 0

    from app.repl import main as repl_main

    return asyncio.run(repl_main())


if __name__ == "__main__":
    raise SystemExit(main())
