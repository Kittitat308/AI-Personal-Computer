import base64
import csv
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
TEXT_SUFFIXES = {
    ".txt", ".md", ".csv", ".json", ".py", ".html", ".xml",
}
MAX_EXTRACTED_CHARACTERS = 60_000


def build_user_content(message: str, attachments: list[Path]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": message.strip()}]
    for path in attachments:
        resolved = path.resolve()
        suffix = resolved.suffix.lower()
        media_type = IMAGE_MEDIA_TYPES.get(suffix)
        if media_type:
            content.append(
                {
                    "type": "text",
                    "text": f"ภาพที่ผู้ใช้แนบ: {resolved.name}",
                }
            )
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(resolved.read_bytes()).decode("ascii"),
                    },
                }
            )
            continue

        extracted = extract_file_text(resolved)
        content.append(
            {
                "type": "text",
                "text": (
                    f"ไฟล์ที่ผู้ใช้แนบ: {resolved.name}\n"
                    f"ตำแหน่งไฟล์สำหรับ Worker: {resolved}\n"
                    "เนื้อหาที่สกัดได้จากไฟล์:\n"
                    + extracted[:MAX_EXTRACTED_CHARACTERS]
                ),
            }
        )
    return content


def extract_file_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        return _extract_open_xml(path, "word/document.xml")
    if suffix == ".pptx":
        return _extract_presentation(path)
    if suffix == ".xlsx":
        return _extract_workbook(path)
    raise ValueError(f"ไม่รองรับการอ่านไฟล์ {path.name}")


def _extract_open_xml(path: Path, member: str) -> str:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read(member))
    return "\n".join(_xml_text_blocks(root))


def _extract_presentation(path: Path) -> str:
    slides: list[str] = []
    with zipfile.ZipFile(path) as archive:
        members = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=_numeric_path_order,
        )
        for index, member in enumerate(members, start=1):
            root = ElementTree.fromstring(archive.read(member))
            text = "\n".join(_xml_text_blocks(root))
            slides.append(f"สไลด์ {index}\n{text}")
    return "\n\n".join(slides)


def _extract_workbook(path: Path) -> str:
    sheets: list[str] = []
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [" ".join(_xml_text_blocks(item)) for item in root]

        members = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
            ),
            key=_numeric_path_order,
        )
        for index, member in enumerate(members, start=1):
            root = ElementTree.fromstring(archive.read(member))
            rows: list[str] = []
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                values: list[str] = []
                for cell in row:
                    if not cell.tag.endswith("}c"):
                        continue
                    value = next(
                        (child.text or "" for child in cell if child.tag.endswith("}v")),
                        "",
                    )
                    if cell.attrib.get("t") == "s" and value.isdigit():
                        position = int(value)
                        if position < len(shared_strings):
                            value = shared_strings[position]
                    elif cell.attrib.get("t") == "inlineStr":
                        value = " ".join(_xml_text_blocks(cell))
                    values.append(value)
                if values:
                    output = io.StringIO()
                    csv.writer(output).writerow(values)
                    rows.append(output.getvalue().strip())
            sheets.append(f"ชีต {index}\n" + "\n".join(rows))
    return "\n\n".join(sheets)


def _xml_text_blocks(root) -> list[str]:
    blocks = []
    for element in root.iter():
        if element.tag.endswith("}t") and element.text:
            value = element.text.strip()
            if value:
                blocks.append(value)
    return blocks


def _numeric_path_order(value: str) -> int:
    match = re.search(r"(\d+)(?=\.xml$)", value)
    return int(match.group(1)) if match else 0
