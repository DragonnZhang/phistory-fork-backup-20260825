from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from phistory.models import CaptureTarget, CommandResult


@dataclass(frozen=True)
class CaptureRunContext:
    target: CaptureTarget
    tap_output_dir: Path
    work_dir: Path
    env: dict[str, str]


@dataclass(frozen=True)
class CaptureExecution:
    result: CommandResult
    observed: dict[str, object] = field(default_factory=dict)


CaptureRunner = Callable[[CaptureRunContext], CaptureExecution]


def run_capture(context: CaptureRunContext) -> CaptureExecution:
    from phistory.drivers.dsh_web import run_dsh_web
    from phistory.drivers.oneshot import run_oneshot
    from phistory.drivers.pty import run_pty

    runners: dict[str, CaptureRunner] = {
        "oneshot": run_oneshot,
        "dsh-web": run_dsh_web,
        "pty": run_pty,
    }
    return runners[context.target.variant.driver](context)
