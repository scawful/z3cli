import json
import subprocess
import unittest


class RouterdStdioContractTests(unittest.TestCase):
    def test_routerd_route_list_shapes(self) -> None:
        proc = subprocess.Popen(
            ["src/services/router/daemon_native/build/z3cli-routerd"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert proc.stdin is not None
            assert proc.stdout is not None

            def request(req_id: int, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
                payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
                proc.stdin.write(json.dumps(payload) + "\n")
                proc.stdin.flush()
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        raise AssertionError(f"routerd closed early (stderr={proc.stderr.read() if proc.stderr else ''})")
                    message = json.loads(line)
                    if message.get("id") == req_id:
                        return message

            proto = request(1, "route/list")
            result = proto.get("result")
            self.assertIsInstance(result, dict)
            assert isinstance(result, dict)
            self.assertEqual(sorted(result.keys()), ["activeRoute", "routes"])
            self.assertIsInstance(result["routes"], list)

            envelope = request(2, "route/list_envelope")
            env_result = envelope.get("result")
            self.assertIsInstance(env_result, dict)
            assert isinstance(env_result, dict)
            for key in ("active", "entries", "active_route", "routes"):
                self.assertIn(key, env_result)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    unittest.main()

