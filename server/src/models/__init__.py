from .user import User
from .role import Role
from .device import Device
from .companion import CompanionMachine
from .apple_account import AppleAccount
from .script import Script, ScriptVersion
from .task import Task
from .configuration import Configuration
from .strategy import Strategy
from .device_group import DeviceGroup
from .audit_log import AuditLog

ALL_MODELS = [
    User,
    Role,
    Device,
    CompanionMachine,
    AppleAccount,
    Script,
    ScriptVersion,
    Task,
    Configuration,
    Strategy,
    DeviceGroup,
    AuditLog,
]
