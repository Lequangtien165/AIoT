"""Platform-specific ONNX Runtime settings for InsightFace recognition.

Recognition runs on Windows AMD64 with NVIDIA CUDA and on macOS Apple
Silicon with Apple CoreML (GPU, Neural Engine, or CPU through CoreML).
This module is pure Python: importing it never pulls in OpenCV, ONNX
Runtime, or InsightFace.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecognitionRuntime:
    """Preferred ONNX Runtime providers and accelerator for one platform.

    `providers` keeps the order that must be handed to InsightFace.
    An entry is either a provider name or a `(name, options)` tuple, so
    CoreML options like `MLComputeUnits=ALL` survive provider selection.
    """

    name: str
    accelerator_provider: str
    providers: tuple[Any, ...]

    @property
    def provider_names(self) -> tuple[str, ...]:
        return tuple(
            entry[0] if isinstance(entry, tuple) else entry
            for entry in self.providers
        )


def get_recognition_runtime(
    system: str | None = None, machine: str | None = None
) -> RecognitionRuntime:
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()

    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return RecognitionRuntime(
            name="windows-amd64",
            accelerator_provider="CUDAExecutionProvider",
            providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
        )

    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return RecognitionRuntime(
            name="macos-arm64",
            accelerator_provider="CoreMLExecutionProvider",
            providers=(
                (
                    "CoreMLExecutionProvider",
                    {
                        "MLComputeUnits": "ALL",
                        "RequireStaticInputShapes": "0",
                    },
                ),
                "CPUExecutionProvider",
            ),
        )

    raise RuntimeError(
        f"Unsupported platform for recognition: {system} {machine}. "
        "This project supports Windows AMD64 (CUDA) and macOS Apple Silicon (CoreML)."
    )
