using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

namespace DBBotLauncher
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            Directory.SetCurrentDirectory(appDir);
            string scriptPath = Path.Combine(appDir, "main.py");

            if (!File.Exists(scriptPath))
            {
                MessageBox.Show(
                    "File main.py was not found in directory:\n" + appDir, 
                    "DBBOT - Error", 
                    MessageBoxButtons.OK, 
                    MessageBoxIcon.Error
                );
                return;
            }

            string pythonw = FindPythonw();
            if (string.IsNullOrEmpty(pythonw))
            {
                MessageBox.Show(
                    "Python (pythonw.exe or pyw.exe) was not found on your system!\n\n" +
                    "Please install Python from https://www.python.org/ and make sure to check 'Add Python to PATH'.", 
                    "DBBOT - Python Not Found", 
                    MessageBoxButtons.OK, 
                    MessageBoxIcon.Warning
                );
                return;
            }

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonw;
            psi.Arguments = "\"" + scriptPath + "\"";
            psi.WorkingDirectory = appDir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;

            try
            {
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "Error launching bot:\n" + ex.Message, 
                    "DBBOT - Error", 
                    MessageBoxButtons.OK, 
                    MessageBoxIcon.Error
                );
            }
        }

        static string FindPythonw()
        {
            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            string cachePath = Path.Combine(appDir, ".python_path");

            // 0. Fast-path: Check cached python path from previous run
            try
            {
                if (File.Exists(cachePath))
                {
                    string cached = File.ReadAllText(cachePath).Trim();
                    if (!string.IsNullOrEmpty(cached) && File.Exists(cached))
                    {
                        return cached;
                    }
                }
            }
            catch { }

            string found = DiscoverPythonw();
            if (!string.IsNullOrEmpty(found))
            {
                try
                {
                    File.WriteAllText(cachePath, found);
                }
                catch { }
            }
            return found;
        }

        static string DiscoverPythonw()
        {
            string pathEnv = Environment.GetEnvironmentVariable("PATH") ?? "";

            // 1. Look for pythonw.exe in PATH
            foreach (string raw in pathEnv.Split(';'))
            {
                string p = raw.Trim();
                if (string.IsNullOrEmpty(p)) continue;
                try
                {
                    string candidate = Path.Combine(p, "pythonw.exe");
                    if (File.Exists(candidate)) return candidate;
                }
                catch { }
            }

            // 2. Look in %LocalAppData%\Programs\Python\Python*\pythonw.exe
            try
            {
                string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                string pyDir = Path.Combine(localApp, "Programs", "Python");
                if (Directory.Exists(pyDir))
                {
                    string[] dirs = Directory.GetDirectories(pyDir, "Python*");
                    Array.Sort(dirs);
                    Array.Reverse(dirs); // newest Python first
                    foreach (string dir in dirs)
                    {
                        string candidate = Path.Combine(dir, "pythonw.exe");
                        if (File.Exists(candidate)) return candidate;
                    }
                }
            }
            catch { }

            // 3. Look in C:\Python* or C:\Program Files\Python*
            try
            {
                string[] roots = { "C:\\", Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles) };
                foreach (string root in roots)
                {
                    if (string.IsNullOrEmpty(root) || !Directory.Exists(root)) continue;
                    string[] dirs = Directory.GetDirectories(root, "Python*");
                    Array.Sort(dirs);
                    Array.Reverse(dirs);
                    foreach (string dir in dirs)
                    {
                        string candidate = Path.Combine(dir, "pythonw.exe");
                        if (File.Exists(candidate)) return candidate;
                    }
                }
            }
            catch { }

            // 4. Look for pyw.exe in PATH or Windows directory
            foreach (string raw in pathEnv.Split(';'))
            {
                string p = raw.Trim();
                if (string.IsNullOrEmpty(p)) continue;
                try
                {
                    string candidate = Path.Combine(p, "pyw.exe");
                    if (File.Exists(candidate)) return candidate;
                }
                catch { }
            }

            string winDir = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            if (!string.IsNullOrEmpty(winDir))
            {
                string pywInWin = Path.Combine(winDir, "pyw.exe");
                if (File.Exists(pywInWin)) return pywInWin;
            }

            // 5. Fallback to python.exe if pythonw is missing
            foreach (string raw in pathEnv.Split(';'))
            {
                string p = raw.Trim();
                if (string.IsNullOrEmpty(p)) continue;
                try
                {
                    string candidate = Path.Combine(p, "python.exe");
                    if (File.Exists(candidate)) return candidate;
                }
                catch { }
            }

            return null;
        }
    }
}
