from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillDefinition:
    category: str
    name: str
    description: str
    body: str
    path: str


class SkillLibrary:
    """从本地 skill 目录加载提示词技能定义"""

    CATEGORY_NAMES = ("techniques", "reply-styles", "language-styles")

    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.skills = {category: {} for category in self.CATEGORY_NAMES}
        self.load_errors = []
        self.load()

    def load(self):
        self.skills = {category: {} for category in self.CATEGORY_NAMES}
        self.load_errors = []

        if not self.root_dir.exists():
            return

        for category in self.CATEGORY_NAMES:
            category_dir = self.root_dir / category
            if not category_dir.exists():
                continue

            for skill_dir in sorted(path for path in category_dir.iterdir() if path.is_dir()):
                skill_md_path = skill_dir / "SKILL.md"
                if not skill_md_path.exists():
                    continue

                try:
                    skill = self._parse_skill(skill_md_path, category)
                except Exception as exc:
                    self.load_errors.append(f"{skill_md_path}: {str(exc)}")
                    continue

                if skill is not None:
                    self.skills[category][skill.name] = skill

    def count_skills(self):
        return sum(len(items) for items in self.skills.values())

    def has_skills(self):
        return self.count_skills() > 0

    def get(self, category, name):
        return self.skills.get(category, {}).get(name)

    @staticmethod
    def _parse_skill(skill_md_path, category):
        content = skill_md_path.read_text(encoding="utf-8").strip()
        lines = content.splitlines()
        if len(lines) < 3 or lines[0].strip() != "---":
            raise ValueError("SKILL.md 缺少合法 frontmatter")

        closing_index = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                closing_index = index
                break

        if closing_index is None:
            raise ValueError("SKILL.md frontmatter 未正确闭合")

        metadata = {}
        for line in lines[1:closing_index]:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip("'\"")

        name = metadata.get("name", "").strip()
        description = metadata.get("description", "").strip()
        body = "\n".join(lines[closing_index + 1:]).strip()

        if not name:
            raise ValueError("缺少 name")
        if not description:
            raise ValueError("缺少 description")
        if not body:
            raise ValueError("缺少 body")

        return SkillDefinition(
            category=category,
            name=name,
            description=description,
            body=body,
            path=str(skill_md_path),
        )
