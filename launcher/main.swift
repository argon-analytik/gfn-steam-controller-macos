import AppKit
import CoreServices

// This is a transient launcher. Steam owns the game process and its input context.
@MainActor final class Launcher: NSObject, NSApplicationDelegate {
    var preflight: Process?

    func prepareRuntime(_ runtime: String, completion: @escaping @MainActor () -> Void) {
        guard let resources = Bundle.main.resourceURL else {
            fail("The controller setup is incomplete.")
            return
        }
        let process = Process()
        let logURL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/gfn-steam-controller-macos/launcher.log")
        do {
            try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(),
                                                   withIntermediateDirectories: true)
            try Data().write(to: logURL, options: .atomic)
            let log = try FileHandle(forWritingTo: logURL)
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = [resources.appendingPathComponent("ControllerRepair/ensure-runtime.zsh").path, runtime]
            process.currentDirectoryURL = FileManager.default.temporaryDirectory
            process.standardOutput = log
            process.standardError = log
            process.terminationHandler = { finished in
                try? log.close()
                Task { @MainActor in
                    self.preflight = nil
                    if finished.terminationStatus == 0 {
                        // Steam execs the binary directly. Refresh LaunchServices
                        // so GamePolicy sees the rebuilt bundle's Game Mode opt-out.
                        let status = LSRegisterURL(URL(fileURLWithPath: runtime) as CFURL, true)
                        if status == noErr {
                            completion()
                        } else {
                            self.fail("The updated GFN app could not be registered (" + String(status) + ").")
                        }
                    } else {
                        self.fail("The controller fix could not be prepared for this GFN version. GFN was not started.\n\nDetails: " + logURL.path)
                    }
                }
            }
            preflight = process
            try process.run()
        } catch {
            preflight = nil
            fail("The controller check could not start: " + error.localizedDescription)
        }
    }

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
        alert.messageText = "Start GeForce NOW"
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
            fail("The GFN setup is missing or damaged. Please run the Steam controller setup again.")
            return
        }
        let steamURL = URL(fileURLWithPath: "/Applications/Steam.app")
        guard Bundle(url: steamURL)?.bundleIdentifier == "com.valvesoftware.steam" else {
            fail("Steam was not found at /Applications/Steam.app.")
            return
        }
        let apps = NSWorkspace.shared.runningApplications
        let steamPIDs = Set(apps.filter { $0.bundleIdentifier == "com.valvesoftware.steam" }.map(\.processIdentifier))
        for gfn in apps where gfn.executableURL?.lastPathComponent == "GeForceNOW" {
            guard let parent = parentPID(of: gfn.processIdentifier), steamPIDs.contains(parent),
                  gfn.executableURL?.path == runtime + "/Contents/MacOS/GeForceNOW" else {
                fail("GeForce NOW is already running outside the Steam shortcut. Quit GeForce NOW and open this app again to activate the controller layout.")
                return
            }
        }
        // Already running in the correct Steam context: only bring it forward.
        // Never rebuild underneath an active stream.
        if apps.contains(where: { $0.executableURL?.path == runtime + "/Contents/MacOS/GeForceNOW" }) {
            openSteam(url, at: steamURL)
        } else {
            prepareRuntime(runtime) { self.openSteam(url, at: steamURL) }
        }
    }

    func openSteam(_ url: URL, at steamURL: URL) {
        let config = NSWorkspace.OpenConfiguration()
        config.activates = false
        NSWorkspace.shared.open([url], withApplicationAt: steamURL, configuration: config) { _, error in
            Task { @MainActor in
                if let error {
                    self.fail("Steam could not start: " + error.localizedDescription)
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
