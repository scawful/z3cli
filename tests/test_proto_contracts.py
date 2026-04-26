import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTO_ROOT = ROOT / "proto"


def _proto_files() -> list[Path]:
    return sorted(PROTO_ROOT.glob("*.proto"))


def test_proto_contracts_are_message_only_for_now() -> None:
    for path in _proto_files():
        text = path.read_text(encoding="utf-8")
        assert "\nservice " not in text, f"{path} should not bind to an RPC transport yet"


def test_proto_contracts_compile() -> None:
    protoc = shutil.which("protoc")
    if protoc is None:
        return

    output = Path("/tmp/z3cli_proto_contracts.pb")
    command = [
        protoc,
        f"--proto_path={PROTO_ROOT}",
        f"--descriptor_set_out={output}",
        "--include_imports",
        *[str(path.relative_to(PROTO_ROOT)) for path in _proto_files()],
    ]
    subprocess.run(command, cwd=PROTO_ROOT, check=True)


def test_proto_contracts_pass_protolint() -> None:
    protolint = shutil.which("protolint")
    if protolint is None:
        return

    subprocess.run(
        [protolint, "lint", str(PROTO_ROOT.relative_to(ROOT))],
        cwd=ROOT,
        check=True,
    )
