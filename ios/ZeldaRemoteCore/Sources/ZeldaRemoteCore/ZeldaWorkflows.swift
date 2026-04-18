import Foundation

/// Zelda / ALTTP–oriented quick prompts for on-the-go hacking (insert into chat).
public enum ZeldaWorkflows {
    public struct Preset: Identifiable, Sendable {
        public let id: String
        public let title: String
        public let prompt: String

        public init(id: String, title: String, prompt: String) {
            self.id = id
            self.title = title
            self.prompt = prompt
        }
    }

    public static let presets: [Preset] = [
        Preset(
            id: "explain-asm",
            title: "Explain ASM hook",
            prompt:
            "I'm patching ALTTP on SNES. Given a hook site, explain register width (A/X/Y), stack expectations, and safe patterns (JSL vs JML). Ask for the routine or paste disassembly."
        ),
        Preset(
            id: "trace-crash",
            title: "Trace a crash",
            prompt:
            "Help me trace a black screen or crash in an ALTTP hack: what Mesen2 traces, breakpoints, and memory watches would you use first? Keep steps CLI-first."
        ),
        Preset(
            id: "room-edit",
            title: "Dungeon room sanity",
            prompt:
            "Review a dungeon room edit plan: sprites, collision, tags, and minecart rails. List validation checks before writing the ROM."
        ),
        Preset(
            id: "session-resume",
            title: "Resume session",
            prompt:
            "I will run /sessions and /resume from slash commands. Summarize what you need from me to continue the last Zelda task safely."
        ),
    ]

    /// Slash commands implemented by `handle_command` in `z3cli/app/serve.py`.
    public static let slashHints: [(label: String, cmd: String, args: [String])] = [
        ("Sessions", "/sessions", []),
        ("Status", "/status", []),
    ]
}
