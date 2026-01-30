from pathlib import Path
import subprocess

def markdown_file_to_docx(md_path: Path, docx_path: Path) -> None:
    docx_path.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["pandoc", str(md_path), "-o", str(docx_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return docx_path.read_bytes()
