# Saca el logo de cada app (accesos directos y apps del menu Inicio) y lo guarda como PNG.
# Lo ejecuta Jarvis al abrirse; solo genera los que faltan.
param([string]$ListFile, [string]$OutDir)

$code = @"
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class TalosIcons
{
    [StructLayout(LayoutKind.Sequential)]
    struct SIZE { public int cx; public int cy; }

    [ComImport, Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItemImageFactory
    {
        [PreserveSig]
        int GetImage(SIZE size, int flags, out IntPtr phbm);
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHCreateItemFromParsingName(
        [MarshalAs(UnmanagedType.LPWStr)] string path, IntPtr pbc,
        [MarshalAs(UnmanagedType.LPStruct)] Guid riid,
        [MarshalAs(UnmanagedType.Interface)] out IShellItemImageFactory item);

    [DllImport("gdi32.dll")]
    static extern bool DeleteObject(IntPtr handle);

    public static bool Save(string path, string file, int size)
    {
        IShellItemImageFactory factory;
        SHCreateItemFromParsingName(path, IntPtr.Zero, new Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), out factory);
        SIZE s; s.cx = size; s.cy = size;
        IntPtr handle;
        int hr = factory.GetImage(s, 0x4, out handle);   // 0x4 = solo el icono
        Marshal.ReleaseComObject(factory);
        if (hr != 0 || handle == IntPtr.Zero) return false;
        try
        {
            using (Bitmap src = Image.FromHbitmap(handle))
            using (Bitmap dst = new Bitmap(src.Width, src.Height, PixelFormat.Format32bppArgb))
            {
                bool alpha = false;
                if (Image.GetPixelFormatSize(src.PixelFormat) == 32)
                {
                    BitmapData data = src.LockBits(new Rectangle(0, 0, src.Width, src.Height), ImageLockMode.ReadOnly, src.PixelFormat);
                    try
                    {
                        for (int y = 0; y < data.Height; y++)
                            for (int x = 0; x < data.Width; x++)
                            {
                                Color c = Color.FromArgb(Marshal.ReadInt32(data.Scan0, data.Stride * y + 4 * x));
                                if (c.A > 0) alpha = true;
                                dst.SetPixel(x, y, c);
                            }
                    }
                    finally { src.UnlockBits(data); }
                }
                if (alpha) dst.Save(file, ImageFormat.Png); else src.Save(file, ImageFormat.Png);
            }
        }
        finally { DeleteObject(handle); }
        return true;
    }
}
"@

Add-Type -TypeDefinition $code -ReferencedAssemblies System.Drawing
$items = Get-Content -Raw -Encoding UTF8 $ListFile | ConvertFrom-Json
$made = 0
$failed = 0
foreach ($item in $items) {
    $out = Join-Path $OutDir ($item.key + ".png")
    if (Test-Path $out) { continue }
    try {
        if ([TalosIcons]::Save($item.path, $out, 64)) { $made++ } else { $failed++ }
    } catch { $failed++ }
}
Write-Output "hechos=$made fallidos=$failed"
