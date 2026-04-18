import XCTest
@testable import ZeldaRemoteCore

final class ParsedRPCTests: XCTestCase {
    func testParseResponse() {
        let line = #"{"jsonrpc":"2.0","id":1,"result":{"ok":true}}"#
        guard case let .response(id, _) = ParsedRPC.parseLine(line) else {
            return XCTFail("expected response")
        }
        XCTAssertEqual(id, 1)
    }

    func testParseRpcError() {
        let line = #"{"jsonrpc":"2.0","id":2,"error":{"code":-1,"message":"bad"}}"#
        guard case let .rpcError(id, message) = ParsedRPC.parseLine(line) else {
            return XCTFail("expected rpcError")
        }
        XCTAssertEqual(id, 2)
        XCTAssertEqual(message, "bad")
    }

    func testParseNotification() {
        let line = #"{"jsonrpc":"2.0","method":"text","params":{"delta":"hi"}}"#
        guard case let .notification(method, params) = ParsedRPC.parseLine(line) else {
            return XCTFail("expected notification")
        }
        XCTAssertEqual(method, "text")
        XCTAssertEqual(params["delta"] as? String, "hi")
    }
}
