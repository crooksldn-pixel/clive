import XCTest
@testable import CrooksControlCore

/// What the owner reads when something breaks.
final class HumanisingTests: XCTestCase {

    /// Words that mean nothing to a man who has turned on a Mac and a tablet. If one of these
    /// reaches a sentence, the sentence has failed, whatever else it says.
    let jargon = [
        "exit status", "exit code", "127", "errno", "ENOENT", "NSPOSIXErrorDomain",
        "Traceback", "stacktrace", "stderr", "stdout", "subprocess", "SIGTERM",
        "0x", "nil", "Optional(", "Error Domain",
    ]

    func assertHuman(_ sentence: String, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertFalse(sentence.isEmpty, "an empty sentence explains nothing", file: file, line: line)
        for word in jargon {
            XCTAssertFalse(sentence.contains(word),
                           "“\(word)” is not English: \(sentence)", file: file, line: line)
        }
        XCTAssertTrue(sentence.first?.isUppercase ?? false,
                      "it is a sentence, so it starts like one: \(sentence)", file: file, line: line)
    }

    // MARK: - The named case

    func testExitStatus127NeverReachesTheOwner() {
        let failure = ControlFailure.exited(
            code: 127,
            stderr: "/bin/sh: line 1: crooks-control: command not found\n"
        )
        let sentence = failure.sentence
        assertHuman(sentence)
        XCTAssertTrue(sentence.contains("not where this app expected it"), sentence)
        XCTAssertEqual(failure.advice, "Open the logs to see exactly what it said.")
        // The number is not lost — it is exactly where it belongs.
        XCTAssertTrue(failure.technicalDetail.contains("127"))
    }

    func testExitStatus127WithNothingOnStderrStillSaysSomethingUseful() {
        let sentence = ControlFailure.exited(code: 127, stderr: "").sentence
        assertHuman(sentence)
        XCTAssertEqual(sentence, "CROOKS OS could not finish that.")
    }

    func testAPythonTracebackBecomesOneSentence() {
        let stderr = """
        Traceback (most recent call last):
          File "/Users/george/crooks-assistant/scripts/control.py", line 812, in <module>
            sys.exit(main())
          File "/Users/george/crooks-assistant/scripts/control.py", line 781, in main
            code, doc = build_document(args)
        ModuleNotFoundError: No module named 'httpx'
        """
        let sentence = ControlFailure.exited(code: 1, stderr: stderr).sentence
        assertHuman(sentence)
        XCTAssertTrue(sentence.contains("make venv"), "say the fix: \(sentence)")
        XCTAssertFalse(sentence.contains("control.py"), "a file and a line number are not a fix")
    }

    func testEveryFailureProducesEnglish() {
        let all: [ControlFailure] = [
            .noCheckout,
            .noPython(path: "/Users/george/crooks-assistant/.venv/bin/python"),
            .commandNotFound("crooks-control"),
            .exited(code: 2, stderr: "Permission denied"),
            .exited(code: 1, stderr: "ConnectionRefusedError: [Errno 61] Connection refused"),
            .exited(code: 1, stderr: "fatal: not a git repository (or any of the parent directories): .git"),
            .emptyAnswer(stderr: ""),
            .unreadableAnswer(raw: "<html><body>502 Bad Gateway</body></html>"),
            .wrongContract(.scriptIsNewer(4)),
            .timedOut(seconds: 30),
            .refusedCommand(.isAShell("bash")),
        ]
        for failure in all {
            assertHuman(failure.sentence)
        }
    }

    func testAMissingVirtualenvSaysWhichFolderAndWhatToRun() {
        // The failure this rule was written for. It used to surface as "The operation couldn't
        // be completed. No such file or directory", which names neither the file, nor the fix,
        // nor which of the two machines had the problem.
        let failure = ControlFailure.noPython(path: "/Users/george/crooks-assistant/.venv/bin/python")
        assertHuman(failure.sentence)
        XCTAssertTrue(failure.sentence.contains("/Users/george/crooks-assistant/.venv/bin/python"))
        XCTAssertTrue((failure.advice ?? "").contains("make venv"))
    }

    func testConnectionRefusedIsTranslatedIntoPressStart() {
        let sentence = ControlFailure.exited(code: 1, stderr: "curl: (7) Connection refused").sentence
        assertHuman(sentence)
        XCTAssertTrue(sentence.contains("press START"), sentence)
    }

    func testTheLastMeaningfulLineSkipsTheFrames() {
        let raw = """
        Traceback (most recent call last):
          File "a.py", line 1, in <module>
          File "b.py", line 2, in run

        RuntimeError: the shop is shut
        """
        XCTAssertEqual(Humanising.lastMeaningfulLine(raw), "RuntimeError: the shop is shut")
    }

    // MARK: - Nothing credential-shaped in a sentence

    func testASecretInStderrNeverReachesTheSentence() {
        // stderr is text control.py's own redact() never saw: it is the shell's, or the
        // subprocess's, and it arrives here raw.
        let token = "shpat_" + String(repeating: "a1b2c3d4", count: 4)
        let failure = ControlFailure.exited(
            code: 1,
            stderr: "Shopify refused the token \(token): 401 Unauthorized"
        )
        XCTAssertFalse(failure.sentence.contains(token), failure.sentence)
        XCTAssertFalse(failure.technicalDetail.contains(token),
                       "Developer Mode shows everything EXCEPT this")
    }

    func testEveryShapeTheControlScriptRedactsIsRedactedHereToo() {
        // The same list as SECRET_SHAPES in scripts/control.py. Two lists that drift apart are
        // worse than one, because whichever side is behind is the side that leaks.
        let secrets = [
            "shpat_0123456789abcdef", "shpca_0123456789abcdef", "shpss_0123456789abcdef",
            "shppa_0123456789abcdef", "sk-ant-api03-Abc123Def456", "sk-proj-Abc123Def456",
            "ghp_0123456789abcdefghij", "gho_0123456789abcdefghij",
            "github_pat_0123456789abcdefghij", "xoxb-0123-4567-abcdef", "xoxp-0123-4567-abcdef",
            "ya29.A0ARrdaM-abcdef", "AIzaSyA-abcdefghij",
        ]
        for secret in secrets {
            let scrubbed = Redaction.scrub("it said \(secret) and stopped")
            XCTAssertFalse(scrubbed.contains(secret), "not redacted: \(secret) → \(scrubbed)")
            XCTAssertTrue(scrubbed.contains(Redaction.mask), scrubbed)
        }
    }

    func testANamedCredentialKeepsItsNameAndLosesItsValue() {
        let scrubbed = Redaction.scrub("ANTHROPIC_API_KEY=hunter2hunter2 was rejected")
        XCTAssertFalse(scrubbed.contains("hunter2hunter2"), scrubbed)
        XCTAssertTrue(scrubbed.contains("ANTHROPIC_API_KEY"),
                      "which credential it was is the useful half: \(scrubbed)")
    }

    func testGitShasAreNotTreatedAsSecrets() {
        // A rule that hid forty hex characters would make the entire update screen useless in
        // order to protect something that is not a secret.
        let sha = "2b25230a5ae4df73c23c839ce5441058a54e26bb"
        XCTAssertEqual(Redaction.scrub("updated to \(sha)"), "updated to \(sha)")
        XCTAssertFalse(Redaction.looksLikeASecret(sha))
    }

    func testRedactionLeavesOrdinaryEnglishAlone() {
        let sentence = "CROOKS OS is running and answering on 127.0.0.1:8000."
        XCTAssertEqual(Redaction.scrub(sentence), sentence)
    }
}
