// OpenFinance.exe — opens the app like a desktop program.
//
// It is a launcher, not the app: Docker Desktop and this repository have to be on the
// machine. If the stack already answers it only opens the window; otherwise it runs
// `docker compose up -d` and waits for the API. Build with build.cmd next to this file.
//
// Written for the C# 5 compiler that ships with Windows (.NET Framework 4), so no string
// interpolation and no null-conditional operators.

using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;
using System.Windows.Forms;

static class Launcher
{
    const string HealthUrl = "http://localhost:8000/health";
    const string AppUrl = "http://localhost:5173";

    // Compose services are `restart: unless-stopped`, so right after Docker Desktop starts
    // they come back on their own. Waiting briefly before `compose up` avoids racing them.
    const int RestartGraceSeconds = 45;
    const int StartupTimeoutSeconds = 90;
    const int CommandTimeoutSeconds = 300; // a first run pulls and builds images

    [STAThread]
    static int Main(string[] args)
    {
        if (!Healthy())
        {
            if (Run("docker", "info", null, 30) != 0)
                return Fail("Docker is not running.\n\nStart Docker Desktop, wait until it says it is running, then open OpenFinance again.");

            if (!WaitForHealth(RestartGraceSeconds))
            {
                // Compose names its project after the folder it runs in, so the wrong folder
                // means a second, empty stack rather than the one with your data in it —
                // which is what happened the first time this ran while the API was
                // restarting. The folder therefore comes from, in order: the argument,
                // compose-dir.txt beside this exe, and only then the repository around it.
                string dir = args.Length > 0 ? args[0] : (ReadComposeDirFile() ?? FindComposeDir());
                if (dir == null || !File.Exists(Path.Combine(dir, "docker-compose.yml")))
                    return Fail("Could not find docker-compose.yml.\n\nKeep OpenFinance.exe inside the repository, or pass the folder that holds docker-compose.yml as its argument.");

                if (Run("docker", "compose up -d", dir, CommandTimeoutSeconds) != 0)
                    return Fail("`docker compose up -d` failed in\n" + dir + "\n\nRun it in a terminal there to see why.");

                if (!WaitForHealth(StartupTimeoutSeconds))
                    return Fail("The app did not answer within " + StartupTimeoutSeconds + " seconds.\n\nCheck `docker compose logs api` in\n" + dir);
            }
        }

        OpenWindow();
        return 0;
    }

    static bool Healthy()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(HealthUrl);
            request.Timeout = 2000;
            request.Proxy = null; // localhost; skips proxy auto-detection, which can take seconds
            using (var response = (HttpWebResponse)request.GetResponse())
                return response.StatusCode == HttpStatusCode.OK;
        }
        catch (WebException)
        {
            return false;
        }
    }

    static bool WaitForHealth(int seconds)
    {
        var deadline = DateTime.UtcNow.AddSeconds(seconds);
        while (DateTime.UtcNow < deadline)
        {
            if (Healthy()) return true;
            Thread.Sleep(1000);
        }
        return Healthy();
    }

    /// <summary>Exit code of the command, or -1 if it could not start or ran out of time.</summary>
    static int Run(string file, string arguments, string workingDirectory, int timeoutSeconds)
    {
        var info = new ProcessStartInfo(file, arguments);
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        if (workingDirectory != null) info.WorkingDirectory = workingDirectory;
        try
        {
            using (var process = Process.Start(info))
            {
                if (!process.WaitForExit(timeoutSeconds * 1000))
                {
                    process.Kill();
                    return -1;
                }
                return process.ExitCode;
            }
        }
        catch (Win32Exception)
        {
            return -1; // not installed, or not on PATH
        }
    }

    /// <summary>First line of compose-dir.txt beside the exe, or null if there is none.</summary>
    static string ReadComposeDirFile()
    {
        string file = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "compose-dir.txt");
        if (!File.Exists(file)) return null;
        foreach (string line in File.ReadAllLines(file))
        {
            string trimmed = line.Trim();
            if (trimmed.Length > 0) return trimmed;
        }
        return null;
    }

    /// <summary>The nearest folder at or above this exe that holds docker-compose.yml.</summary>
    static string FindComposeDir()
    {
        var dir = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory);
        while (dir != null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "docker-compose.yml"))) return dir.FullName;
            dir = dir.Parent;
        }
        return null;
    }

    static void OpenWindow()
    {
        // Edge's app mode: no tabs, no address bar, its own taskbar entry.
        string[] roots =
        {
            Environment.GetEnvironmentVariable("ProgramFiles(x86)"),
            Environment.GetEnvironmentVariable("ProgramFiles"),
        };
        foreach (string root in roots)
        {
            if (root == null) continue;
            string edge = Path.Combine(root, @"Microsoft\Edge\Application\msedge.exe");
            if (!File.Exists(edge)) continue;
            Process.Start(edge, "--app=" + AppUrl);
            return;
        }
        Process.Start(AppUrl); // default browser
    }

    static int Fail(string message)
    {
        MessageBox.Show(message, "OpenFinance", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        return 1;
    }
}
