import logging
from datetime import datetime, timezone

import jsonschema
from beanie import PydanticObjectId

from server.src.models.script import Script, ScriptStatus, ScriptStep, ScriptType, ScriptVersion
from server.src.models.task import Task
from server.src.services.command_dispatcher import dispatch_command

logger = logging.getLogger(__name__)

SCRIPT_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {"type": "string"},
            "target": {"type": "string"},
            "params": {"type": "object"},
            "timeout": {"type": "integer", "minimum": 1},
        },
    },
}

VALID_ACTIONS = {
    "launch_app", "tap", "type", "swipe", "wait", "search",
    "scroll", "screenshot", "back", "home", "find_element",
    "assert_exists", "assert_not_exists", "conditional",
}

TARGET_REQUIRED_ACTIONS = {
    "tap", "type", "find_element", "assert_exists", "assert_not_exists",
}


def validate_steps(steps: list[dict]) -> list[str]:
    """Validate script steps against JSON schema and business rules."""
    errors: list[str] = []
    try:
        jsonschema.validate(steps, SCRIPT_SCHEMA)
    except jsonschema.ValidationError as e:
        errors.append(str(e.message))
        return errors

    for i, step in enumerate(steps):
        action = step.get("action", "")
        if action not in VALID_ACTIONS:
            errors.append(f"步骤 {i + 1}: 不支持的 action '{action}'")
        if action in TARGET_REQUIRED_ACTIONS and not step.get("target"):
            errors.append(f"步骤 {i + 1}: action '{action}' 需要 target")
    return errors


async def create_script(
    name: str,
    description: str | None,
    steps: list[dict] | None = None,
    script_type: str = "steps",
    python_code: str | None = None,
    created_by: PydanticObjectId | None = None,
) -> Script:
    st = ScriptType(script_type)

    if st == ScriptType.STEPS:
        if not steps:
            raise ValueError("steps 类型脚本必须提供 steps")
        errors = validate_steps(steps)
        if errors:
            raise ValueError("; ".join(errors))
    elif st == ScriptType.PYTHON:
        if not python_code:
            raise ValueError("python 类型脚本必须提供 python_code")

    script = Script(
        name=name,
        description=description,
        script_type=st,
        current_version=1,
        status=ScriptStatus.DRAFT,
        created_by=created_by,
    )
    await script.insert()

    parsed_steps = [ScriptStep(**s) for s in steps] if steps else []
    version = ScriptVersion(
        script_id=script.id,
        version=1,
        script_type=st,
        steps=parsed_steps,
        python_code=python_code,
    )
    await version.insert()

    return script


async def update_script(
    script_id: PydanticObjectId,
    steps: list[dict] | None = None,
    python_code: str | None = None,
    changelog: str | None = None,
    updated_by: PydanticObjectId | None = None,
) -> ScriptVersion:
    script = await Script.get(script_id)
    if not script:
        raise ValueError(f"脚本 {script_id} 不存在")

    st = script.script_type
    parsed_steps: list[ScriptStep] = []

    if st == ScriptType.PYTHON:
        if not python_code:
            raise ValueError("python 类型脚本必须提供 python_code")
    else:
        if not steps:
            raise ValueError("steps 类型脚本必须提供 steps")
        errors = validate_steps(steps)
        if errors:
            raise ValueError("; ".join(errors))
        parsed_steps = [ScriptStep(**s) for s in steps]

    new_version_num = script.current_version + 1

    version = ScriptVersion(
        script_id=script_id,
        version=new_version_num,
        script_type=st,
        steps=parsed_steps,
        python_code=python_code,
        changelog=changelog,
    )
    await version.insert()

    script.current_version = new_version_num
    script.updated_at = datetime.now(timezone.utc)
    await script.save()

    return version


async def publish_script(script_id: PydanticObjectId) -> Script:
    script = await Script.get(script_id)
    if not script:
        raise ValueError(f"脚本 {script_id} 不存在")

    script.status = ScriptStatus.PUBLISHED
    script.updated_at = datetime.now(timezone.utc)
    await script.save()

    version = await ScriptVersion.find_one(
        ScriptVersion.script_id == script_id,
        ScriptVersion.version == script.current_version,
    )
    if version:
        version.published_at = datetime.now(timezone.utc)
        await version.save()

    return script


async def rollback_script(
    script_id: PydanticObjectId,
    target_version: int,
) -> Script:
    script = await Script.get(script_id)
    if not script:
        raise ValueError(f"脚本 {script_id} 不存在")

    version = await ScriptVersion.find_one(
        ScriptVersion.script_id == script_id,
        ScriptVersion.version == target_version,
    )
    if not version:
        raise ValueError(f"版本 {target_version} 不存在")

    script.current_version = target_version
    script.updated_at = datetime.now(timezone.utc)
    await script.save()

    return script


async def get_versions(script_id: PydanticObjectId) -> list[ScriptVersion]:
    return await (
        ScriptVersion.find(ScriptVersion.script_id == script_id)
        .sort("-version")
        .to_list()
    )


async def gray_release(
    script_id: PydanticObjectId,
    device_ids: list[PydanticObjectId],
) -> list[Task]:
    script = await Script.get(script_id)
    if not script:
        raise ValueError(f"脚本 {script_id} 不存在")

    if script.status != ScriptStatus.PUBLISHED:
        raise ValueError("脚本必须为已发布状态才能灰度发布")

    tasks: list[Task] = []
    for device_id in device_ids:
        try:
            task = await dispatch_command(
                device_id=device_id,
                script_id=script_id,
                script_version=script.current_version,
            )
            tasks.append(task)
        except Exception as e:
            logger.error(f"灰度发布到设备 {device_id} 失败: {e}")

    return tasks
