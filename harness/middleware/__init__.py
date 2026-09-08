from harness.middleware.approval_gate import ApprovalGate
from harness.middleware.error_recovery import ErrorRecovery
from harness.middleware.tool_auth import ToolAuth
from harness.middleware.trace import Trace

ORDER = ["tool_auth", "error_recovery", "approval_gate", "guards", "trace"]


def build_middleware(ctx):
    return [ToolAuth(), ErrorRecovery(), ApprovalGate(), Trace()]
