# OCRmyPDF GUI

A simple Tkinter GUI wrapper for [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF).

## Requirements

- Python 3
- [OCRmyPDF](https://ocrmypdf.readthedocs.io/) installed and on your `PATH`
- Standard library only (`tkinter`, `subprocess`, `threading`, `queue`, `os`, `sys`) — no extra pip installs needed

## Usage

```bash
python ocrmypdf_gui.py [optional_path_to_pdf]
```

Pass a PDF path as an argument (e.g. from SumatraPDF, see below) to load it automatically, or leave blank and select a file from the GUI.

## SumatraPDF Integration

You can open PDFs directly into this GUI from SumatraPDF as an "External Viewer":

1. In SumatraPDF, go to **Settings → Advanced Options**. This opens a text config file.
2. Find the `ExternalViewers [ ... ]` section.
3. Add an entry pointing to your Python executable and this script, for example:

```
ExternalViewers [
	[
		CommandLine = "C:\Path\To\Python312\python.exe" "C:\Path\To\ocrmypdf_gui.py" "%1"
		Name = OCRmyPDF
		Filter = *.pdf
	]
]
```

1. Save the file. You can now use the menu and choose **File** → **OCRmyPDF** to open it in this GUI.