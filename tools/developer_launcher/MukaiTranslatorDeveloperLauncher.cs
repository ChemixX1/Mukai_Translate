using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

internal static class MukaiTranslatorDeveloperLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string projectRoot = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        string pythonw = Path.Combine(projectRoot, ".venv", "Scripts", "pythonw.exe");
        string entryPoint = Path.Combine(projectRoot, "app", "launch_mukai.pyw");

        if (!File.Exists(pythonw) || !File.Exists(entryPoint))
        {
            MessageBox.Show(
                "No se encontró el entorno de desarrollo de Mukai Translator.\n\n" +
                "Mantén este EXE en la raíz del proyecto y ejecuta una vez:\n" +
                "tools\\setup_development.ps1",
                "Mukai Translator - Desarrollo",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return 1;
        }

        if (args.Length == 1 && string.Equals(args[0], "--self-test", StringComparison.OrdinalIgnoreCase))
        {
            return 0;
        }

        var commandArguments = new List<string>
        {
            "-W",
            "ignore::SyntaxWarning",
            "-W",
            "ignore::DeprecationWarning",
            entryPoint,
        };
        commandArguments.AddRange(args);

        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string logDirectory = Path.Combine(localAppData, "MukaiTranslator", "logs");
        Directory.CreateDirectory(logDirectory);

        var startInfo = new ProcessStartInfo
        {
            FileName = pythonw,
            Arguments = JoinArguments(commandArguments),
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        startInfo.EnvironmentVariables["MUKAI_DEVELOPER_LAUNCH"] = "1";
        startInfo.EnvironmentVariables["MUKAI_LAUNCH_LOG"] = Path.Combine(logDirectory, "mukai-launch.log");
        startInfo.EnvironmentVariables["HF_HUB_DISABLE_XET"] = "1";
        startInfo.EnvironmentVariables["PYTHONWARNINGS"] = "ignore::SyntaxWarning,ignore::DeprecationWarning";

        try
        {
            Process.Start(startInfo);
            return 0;
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                "No se pudo abrir Mukai Translator.\n\n" + exception.Message,
                "Mukai Translator - Desarrollo",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return 1;
        }
    }

    private static string JoinArguments(IEnumerable<string> arguments)
    {
        var result = new StringBuilder();
        foreach (string argument in arguments)
        {
            if (result.Length > 0)
            {
                result.Append(' ');
            }
            result.Append(QuoteArgument(argument ?? string.Empty));
        }
        return result.ToString();
    }

    private static string QuoteArgument(string argument)
    {
        var result = new StringBuilder(argument.Length + 2);
        result.Append('"');
        int backslashes = 0;
        foreach (char character in argument)
        {
            if (character == '\\')
            {
                backslashes++;
                continue;
            }
            if (character == '"')
            {
                result.Append('\\', backslashes * 2 + 1);
                result.Append('"');
                backslashes = 0;
                continue;
            }
            result.Append('\\', backslashes);
            backslashes = 0;
            result.Append(character);
        }
        result.Append('\\', backslashes * 2);
        result.Append('"');
        return result.ToString();
    }
}
