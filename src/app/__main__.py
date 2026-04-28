import asyncio
import sys

from app.launcher import (
    HELP_TEXT,
    exec_ink_frontend,
    is_backend_only_invocation,
    repo_root_from_app_file,
    strip_legacy_repl_flag,
)


def main() -> int:
    argv = sys.argv[1:]
    if "--serve" in argv:
        argv.remove("--serve")
        sys.argv = [sys.argv[0], *argv]
        from app.serve import serve_main

        asyncio.run(serve_main(argv))
        return 0
    if "--bridge" in argv:
        argv.remove("--bridge")
        sys.argv = [sys.argv[0], *argv]
        from app.ws_bridge import bridge_main

        asyncio.run(bridge_main(argv))
        return 0

    if argv in (["--help"], ["-h"]):
        print(HELP_TEXT, end="")
        return 0

    argv, use_legacy_repl = strip_legacy_repl_flag(argv)
    sys.argv = [sys.argv[0], *argv]
    if not use_legacy_repl and not is_backend_only_invocation(argv):
        return exec_ink_frontend(repo_root_from_app_file(__file__), argv)

    from app.repl import main as repl_main

    return asyncio.run(repl_main())


if __name__ == "__main__":
    raise SystemExit(main())
