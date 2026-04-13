import asyncio
import sys

if "--serve" in sys.argv:
    sys.argv.remove("--serve")
    from z3cli.app.serve import serve_main
    asyncio.run(serve_main(sys.argv[1:]))
else:
    from z3cli.app.repl import main
    asyncio.run(main())
