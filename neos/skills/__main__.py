"""CLI tool for managing skills

Usage:
    python -m neos.skills create <skill_name> --type=<skill_type>
    python -m neos.skills list
    python -m neos.skills validate <skill_dir>
"""

import argparse
import sys
from pathlib import Path
from neos.skills.base import SkillType
from neos.skills.manager.auto_discovery import (
    discover_skills,
    validate_skill_directory,
    get_discovery_report,
)


def create_skill_template(skill_name: str, skill_type: str, output_dir: Path = None):
    """Create a new skill template

    Args:
        skill_name: Name of the skill
        skill_type: Type of skill (document, research, etc.)
        output_dir: Output directory (defaults to neos/skills/custom)
    """
    # Validate skill type
    try:
        skill_type_enum = SkillType(skill_type)
    except ValueError:
        valid_types = [t.value for t in SkillType]
        print(f"❌ Invalid skill type: {skill_type}")
        print(f"Valid types: {', '.join(valid_types)}")
        return False

    # Default output directory
    if output_dir is None:
        output_dir = Path("neos/skills/custom")

    # Create skill directory
    skill_dir = output_dir / skill_name
    if skill_dir.exists():
        print(f"❌ Skill directory already exists: {skill_dir}")
        return False

    try:
        skill_dir.mkdir(parents=True, exist_ok=False)
        print(f"✓ Created directory: {skill_dir}")

        # Create SKILL.md with frontmatter
        skill_md = skill_dir / "SKILL.md"
        skill_md_content = f"""---
name: {skill_name}
type: {skill_type}
version: 1.0.0
description: {skill_name.replace('_', ' ').title()} skill
capabilities:
  - capability_1
  - capability_2
dependencies: []
---

# {skill_name.replace('_', ' ').title()} Skill

## Description
Describe your skill here.

## Capabilities
- Capability 1: Description
- Capability 2: Description

## Usage
```python
result = await skill_manager.execute_skill(
    "{skill_name}",
    {{
        "action": "example_action",
        "param1": "value1"
    }}
)
```

## Requirements
List any special requirements or setup instructions.

## Version
1.0.0
"""
        skill_md.write_text(skill_md_content)
        print(f"✓ Created SKILL.md")

        # Create skill.py template
        skill_py = skill_dir / "skill.py"
        skill_py_content = f'''"""
{skill_name.replace('_', ' ').title()} Skill implementation
"""

from typing import Dict, Any
import logging

from neos.skills.base import BaseSkill, SkillResult, SkillType


logger = logging.getLogger(__name__)


class {skill_name.replace('_', ' ').title().replace(' ', '')}Skill(BaseSkill):
    """{skill_name.replace('_', ' ').title()} Skill"""

    def __init__(self, **kwargs):
        super().__init__(
            name="{skill_name}",
            skill_type=SkillType.{skill_type.upper()},
            description="{skill_name.replace('_', ' ').title()} skill",
            capabilities=["capability_1", "capability_2"],
            version="1.0.0",
            **kwargs
        )

    async def initialize(self) -> bool:
        """Initialize the skill

        Returns:
            True if initialization succeeds
        """
        try:
            # Add initialization logic here
            logger.info(f"Initializing {skill_name} skill...")

            self.is_available = True
            logger.info(f"{skill_name} skill initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize {skill_name} skill: {{e}}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """Execute the skill

        Args:
            params: {{
                "action": str,  # Action to perform
                # Add more parameters as needed
            }}

        Returns:
            SkillResult with execution results
        """
        if not self.is_available:
            return SkillResult.error_result(
                error="{skill_name} skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action")
        if not action:
            return SkillResult.error_result(
                error="Action parameter is required",
                skill_name=self.name,
            )

        try:
            # Add your skill logic here
            logger.info(f"Executing {skill_name} skill with action: {{action}}")

            # Example implementation
            if action == "example_action":
                result_data = {{
                    "message": "Success",
                    "action": action
                }}

                return SkillResult.success_result(
                    data=result_data,
                    skill_name=self.name,
                    metadata={{"action": action}}
                )
            else:
                return SkillResult.error_result(
                    error=f"Unknown action: {{action}}",
                    skill_name=self.name,
                )

        except Exception as e:
            logger.error(f"Failed to execute {skill_name} skill: {{e}}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def cleanup(self) -> None:
        """Clean up skill resources"""
        self.is_available = False
        logger.info(f"{skill_name} skill cleaned up")
'''
        skill_py.write_text(skill_py_content)
        print(f"✓ Created skill.py")

        # Create __init__.py
        init_py = skill_dir / "__init__.py"
        class_name = skill_name.replace('_', ' ').title().replace(' ', '') + 'Skill'
        init_py_content = f'''"""{skill_name.replace('_', ' ').title()} Skill"""

from .skill import {class_name}

__all__ = ["{class_name}"]
'''
        init_py.write_text(init_py_content)
        print(f"✓ Created __init__.py")

        # Create requirements.txt
        requirements_txt = skill_dir / "requirements.txt"
        requirements_txt.write_text("# Add your skill dependencies here\n")
        print(f"✓ Created requirements.txt")

        print()
        print("=" * 60)
        print(f"✅ Skill template created successfully!")
        print(f"📁 Location: {skill_dir}")
        print()
        print("Next steps:")
        print(f"1. Edit {skill_dir}/SKILL.md to update description and capabilities")
        print(f"2. Implement your logic in {skill_dir}/skill.py")
        print(f"3. Add dependencies to {skill_dir}/requirements.txt")
        print(f"4. Test your skill:")
        print(f"   python -m neos.skills validate {skill_dir}")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"❌ Error creating skill template: {e}")
        # Cleanup on error
        if skill_dir.exists():
            import shutil
            shutil.rmtree(skill_dir)
        return False


def list_skills(skills_dir: Path = None):
    """List all available skills

    Args:
        skills_dir: Directory to scan (defaults to neos/skills/builtin)
    """
    if skills_dir is None:
        skills_dir = Path("neos/skills/builtin")

    print("=" * 60)
    print("Discovered Skills")
    print("=" * 60)

    if not skills_dir.exists():
        print(f"❌ Skills directory not found: {skills_dir}")
        return False

    discovered = discover_skills(skills_dir, check_deps=False)

    if not discovered:
        print(f"No skills found in {skills_dir}")
        return True

    for skill_info in discovered:
        print(f"\n📦 {skill_info.name}")
        print(f"   Type: {skill_info.skill_type.value}")
        print(f"   Version: {skill_info.version}")
        print(f"   Description: {skill_info.description}")
        print(f"   Capabilities: {', '.join(skill_info.capabilities[:3])}" +
              ("..." if len(skill_info.capabilities) > 3 else ""))

    print()
    print("=" * 60)
    print(f"Total: {len(discovered)} skills")
    print("=" * 60)

    return True


def validate_skill(skill_dir: Path):
    """Validate a skill directory

    Args:
        skill_dir: Path to skill directory
    """
    print("=" * 60)
    print(f"Validating Skill: {skill_dir}")
    print("=" * 60)

    if not skill_dir.exists():
        print(f"❌ Directory not found: {skill_dir}")
        return False

    # Run validation
    is_valid, message = validate_skill_directory(skill_dir)

    if is_valid:
        print(f"✅ {message}")
        print()
        print("Skill structure:")
        for file in ["SKILL.md", "skill.py", "__init__.py", "requirements.txt"]:
            file_path = skill_dir / file
            if file_path.exists():
                print(f"  ✓ {file}")
            else:
                print(f"  - {file} (optional)")

        return True
    else:
        print(f"❌ {message}")
        return False


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="NEOS Skills Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a new skill
  python -m neos.skills create my_skill --type=research

  # List all builtin skills
  python -m neos.skills list

  # List custom skills
  python -m neos.skills list --dir=neos/skills/custom

  # Validate a skill
  python -m neos.skills validate neos/skills/custom/my_skill

  # Generate discovery report
  python -m neos.skills report
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Create command
    create_parser = subparsers.add_parser("create", help="Create a new skill template")
    create_parser.add_argument("name", help="Skill name (e.g., my_skill)")
    create_parser.add_argument(
        "--type",
        required=True,
        choices=[t.value for t in SkillType],
        help="Skill type"
    )
    create_parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="Output directory (default: neos/skills/custom)"
    )

    # List command
    list_parser = subparsers.add_parser("list", help="List available skills")
    list_parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="Skills directory (default: neos/skills/builtin)"
    )

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a skill directory")
    validate_parser.add_argument("skill_dir", type=Path, help="Path to skill directory")

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate skill discovery report")
    report_parser.add_argument(
        "--dir",
        type=Path,
        default=Path("neos/skills/builtin"),
        help="Skills directory (default: neos/skills/builtin)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute command
    if args.command == "create":
        success = create_skill_template(args.name, args.type, args.dir)
        return 0 if success else 1

    elif args.command == "list":
        success = list_skills(args.dir)
        return 0 if success else 1

    elif args.command == "validate":
        success = validate_skill(args.skill_dir)
        return 0 if success else 1

    elif args.command == "report":
        report = get_discovery_report(args.dir)
        print(report)
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
