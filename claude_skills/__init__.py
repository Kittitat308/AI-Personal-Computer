"""Skills that only the Claude provider can run.

They rely on Claude CLI built-in tools, so unlike ``skills/`` they are not
exposed to other models.
"""

from core.config import CLAUDE_SKILLS_DIR, PROJECT_ROOT
from core.skill_registry import SkillDefinition


DOCUMENT_TOOLS = ("Read", "Write", "Edit", "Bash", "Glob", "Grep")
DOCUMENTS_DIR = PROJECT_ROOT / "documents"


def claude_skill_definitions() -> list[SkillDefinition]:
    return [
        SkillDefinition(
            skill_id="web_research",
            description=(
                "ค้นหาและอ่านข้อมูลสาธารณะจากเว็บเพื่อให้คำตอบที่เป็นปัจจุบัน "
                "ตรวจสอบย้อนกลับได้ และมีแหล่งอ้างอิง เช่น ข่าว งานวิจัย "
                "ข้อมูลผลิตภัณฑ์ การเปรียบเทียบ และเนื้อหาจาก URL สาธารณะ"
            ),
            directory=CLAUDE_SKILLS_DIR / "web_research",
            tool_names=(),
            builtin_tool_names=("WebSearch", "WebFetch"),
        ),
        SkillDefinition(
            skill_id="docx",
            description=(
                "สร้าง อ่าน แก้ไข และจัดรูปแบบเอกสาร Microsoft Word นามสกุล .docx "
                "เช่น รายงาน จดหมาย บันทึก ตาราง และเอกสารที่มีรูปภาพ"
            ),
            directory=None,
            tool_names=(),
            builtin_tool_names=DOCUMENT_TOOLS,
            working_directory=DOCUMENTS_DIR,
        ),
        SkillDefinition(
            skill_id="xlsx",
            description=(
                "สร้าง อ่าน แก้ไข วิเคราะห์ และจัดรูปแบบไฟล์ตารางคำนวณ Microsoft "
                "Excel นามสกุล .xlsx เช่น สูตร ตาราง กราฟ และการสรุปข้อมูล"
            ),
            directory=None,
            tool_names=(),
            builtin_tool_names=DOCUMENT_TOOLS,
            working_directory=DOCUMENTS_DIR,
        ),
        SkillDefinition(
            skill_id="pptx",
            description=(
                "สร้าง อ่าน แก้ไข และจัดรูปแบบงานนำเสนอ Microsoft PowerPoint "
                "นามสกุล .pptx เช่น สไลด์ ข้อความ ตาราง กราฟ และรูปภาพ"
            ),
            directory=None,
            tool_names=(),
            builtin_tool_names=DOCUMENT_TOOLS,
            working_directory=DOCUMENTS_DIR,
        ),
        SkillDefinition(
            skill_id="pdf",
            description=(
                "สร้าง อ่าน ตรวจสอบ แก้ไข และแปลงไฟล์ PDF รวมถึงดึงข้อความ "
                "รวม แยก หรือจัดการหน้าเอกสาร PDF"
            ),
            directory=None,
            tool_names=(),
            builtin_tool_names=DOCUMENT_TOOLS,
            working_directory=DOCUMENTS_DIR,
        ),
    ]
