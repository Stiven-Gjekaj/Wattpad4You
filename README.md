# Wattpad4You

Wattpad4You is a small command-line utility that downloads a public Wattpad story and turns it into a single PDF document. The script scrapes a story's table of contents, fetches each part, and renders the retrieved HTML with the bundled fonts so the finished PDF keeps emphasis, alignment, and special scripts intact.

## Features
- Extracts the story title and chapter list directly from a Wattpad story page.
- Downloads every public part through Wattpad's story text API.
- Converts the cleaned HTML content into a paginated PDF using [fpdf2](https://pyfpdf.github.io/fpdf2/).
- Ships with a set of DejaVu and Noto fonts so common Unicode characters (including the Yi script) render correctly without extra configuration.

## Requirements
- Python 3.10 or newer (because the script uses modern typing features).
- A working internet connection to reach `wattpad.com`.
- The Python packages listed in [`requirements.txt`](requirements.txt).

Install the dependencies in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage
Run the script with the full Wattpad story URL:

```bash
python w4tty.py https://www.wattpad.com/story/123456-your-story-title
```

Optional arguments:

- `--out PATH` — Custom output filename or path (defaults to `<story-slug>.pdf` in the current directory).
- `--timeout SECONDS` — Override the HTTP timeout (default: 20 seconds).

The script saves the generated PDF in the requested location and prints the destination path when it finishes. Large stories can take several minutes because each part is downloaded individually.

## Notes & Tips
- Only public story parts can be exported. Private or paywalled chapters will be skipped by Wattpad's API.
- The script registers every `.ttf` file located alongside `w4tty.py`. Keep the bundled fonts in the same directory or provide compatible fonts if you restructure the project.
- Respect Wattpad's Terms of Service when downloading content. Obtain permission from the author before redistributing a story.

## Development
Feel free to fork the project and extend it. Useful additions could include EPUB output, progress indicators, or concurrency to speed up downloads. Contributions are welcome!
