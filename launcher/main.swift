import AppKit

// This is a transient launcher. Steam owns the game process and its input context.
@MainActor final class Launcher: NSObject, NSApplicationDelegate {
    func parentPID(of pid: pid_t) -> pid_t? {
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/ps")
        process.arguments = ["-p", String(pid), "-o", "ppid="]
        process.currentDirectoryURL = FileManager.default.temporaryDirectory
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            guard process.terminationStatus == 0,
                  let text = String(data: data, encoding: .utf8) else { return nil }
            return pid_t(text.trimmingCharacters(in: .whitespacesAndNewlines))
        } catch { return nil }
    }

    func fail(_ message: String) {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = "GeForce NOW starten"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
        NSApp.terminate(nil)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let gameID = Bundle.main.object(forInfoDictionaryKey: "SteamGameID") as? String,
              let number = UInt64(gameID), number > 0,
              let runtime = Bundle.main.object(forInfoDictionaryKey: "GFNRuntimePath") as? String,
              FileManager.default.isExecutableFile(atPath: runtime + "/Contents/MacOS/GeForceNOW"),
              let url = URL(string: "steam://rungameid/" + gameID) else {
            fail("The GFN setup is missing or damaged. Run the Steam Controller setup again.")
            return
        }
        let steamURL = URL(fileURLWithPath: "/Applications/Steam.app")
        guard Bundle(url: steamURL)?.bundleIdentifier == "com.valvesoftware.steam" else {
            fail("Steam wurde unter /Applications/Steam.app nicht gefunden.")
            return
        }
        let apps = NSWorkspace.shared.runningApplications
        let steamPIDs = Set(apps.filter { $0.bundleIdentifier == "com.valvesoftware.steam" }.map(\.processIdentifier))
        for gfn in apps where gfn.executableURL?.lastPathComponent == "GeForceNOW" {
            guard let parent = parentPID(of: gfn.processIdentifier), steamPIDs.contains(parent),
                  gfn.executableURL?.path == runtime + "/Contents/MacOS/GeForceNOW" else {
                fail("GeForce NOW is already running outside the Steam shortcut. Quit GeForce NOW and open this app again so the controller layout can become active.")
                return
            }
        }
        let config = NSWorkspace.OpenConfiguration()
        config.activates = false
        NSWorkspace.shared.open([url], withApplicationAt: steamURL, configuration: config) { _, error in
            Task { @MainActor in
                if let error {
                    self.fail("Steam konnte nicht gestartet werden: " + error.localizedDescription)
                } else {
                    NSApp.terminate(nil)
                }
            }
        }
    }
}

let app = NSApplication.shared
let delegate = Launcher()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
