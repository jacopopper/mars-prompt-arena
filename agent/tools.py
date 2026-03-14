"""Tool registry and validation helpers for the CANIS-1 action surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import Action


@dataclass(frozen=True)
class ToolArgumentSpec:
    """Describes a single tool parameter and its validation rules."""

    name: str
    value_type: type | tuple[type, ...]
    description: str
    required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[Any, ...] | None = None

    def validate(self, value: Any) -> str | None:
        """Return a human-readable validation error, or ``None`` when valid."""

        expected_types = self.value_type if isinstance(self.value_type, tuple) else (self.value_type,)
        if isinstance(value, bool) and bool not in expected_types:
            return f"parameter '{self.name}' must be {self._type_label()}"
        if not isinstance(value, expected_types):
            return f"parameter '{self.name}' must be {self._type_label()}"

        if self.choices is not None and value not in self.choices:
            choices = ", ".join(repr(choice) for choice in self.choices)
            return f"parameter '{self.name}' must be one of: {choices}"

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric_value = float(value)
            if self.minimum is not None and numeric_value < self.minimum:
                return f"parameter '{self.name}' must be >= {self.minimum}"
            if self.maximum is not None and numeric_value > self.maximum:
                return f"parameter '{self.name}' must be <= {self.maximum}"

        if isinstance(value, str) and not value.strip():
            return f"parameter '{self.name}' must be a non-empty string"

        return None

    def to_json_schema(self) -> dict[str, Any]:
        """Return a JSON schema fragment compatible with Gemini function tools."""

        schema_type = "number"
        if self._is_string():
            schema_type = "string"
        elif self._is_integer():
            schema_type = "integer"

        schema: dict[str, Any] = {
            "type": schema_type,
            "description": self.description,
        }
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.choices is not None:
            schema["enum"] = list(self.choices)
        return schema

    def _type_label(self) -> str:
        """Build a readable label for error messages."""

        expected_types = self.value_type if isinstance(self.value_type, tuple) else (self.value_type,)
        labels = []
        for expected_type in expected_types:
            if expected_type is float:
                labels.append("a number")
            elif expected_type is int:
                labels.append("an integer")
            elif expected_type is str:
                labels.append("a string")
            else:
                labels.append(expected_type.__name__)
        return " or ".join(labels)

    def _is_string(self) -> bool:
        """Return whether the argument expects a string."""

        expected_types = self.value_type if isinstance(self.value_type, tuple) else (self.value_type,)
        return str in expected_types

    def _is_integer(self) -> bool:
        """Return whether the argument expects an integer without floats."""

        expected_types = self.value_type if isinstance(self.value_type, tuple) else (self.value_type,)
        return int in expected_types and float not in expected_types


@dataclass(frozen=True)
class ToolSpec:
    """Defines one callable robot tool and its argument schema."""

    name: str
    description: str
    arguments: dict[str, ToolArgumentSpec]

    def to_gemini_function(self) -> dict[str, Any]:
        """Return a Gemini-compatible function declaration."""

        properties = {
            argument_name: argument.to_json_schema()
            for argument_name, argument in self.arguments.items()
        }
        required = [
            argument_name
            for argument_name, argument in self.arguments.items()
            if argument.required
        ]
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


TOOL_SPECS: dict[str, ToolSpec] = {
    "walk": ToolSpec(
        name="walk",
        description="Move the robot in a cardinal direction for a short duration.",
        arguments={
            "direction": ToolArgumentSpec(
                name="direction",
                value_type=str,
                description="Movement direction relative to the robot body.",
                choices=("forward", "backward", "left", "right"),
            ),
            "speed": ToolArgumentSpec(
                name="speed",
                value_type=(int, float),
                description="Movement speed from 0.1 to 1.0.",
                minimum=0.1,
                maximum=1.0,
            ),
            "duration": ToolArgumentSpec(
                name="duration",
                value_type=(int, float),
                description="Movement duration in seconds from 0.2 to 5.0.",
                minimum=0.2,
                maximum=5.0,
            ),
        },
    ),
    "turn": ToolSpec(
        name="turn",
        description="Rotate the robot in place by a signed angle in degrees.",
        arguments={
            "angle_deg": ToolArgumentSpec(
                name="angle_deg",
                value_type=(int, float),
                description="Turn angle in degrees between -180 and 180.",
                minimum=-180.0,
                maximum=180.0,
            )
        },
    ),
    "stand": ToolSpec(
        name="stand",
        description="Stand up into a mobile posture.",
        arguments={},
    ),
    "sit": ToolSpec(
        name="sit",
        description="Sit down into a resting posture.",
        arguments={},
    ),
    "scan": ToolSpec(
        name="scan",
        description="Scan the environment in a full circle and report notable targets.",
        arguments={},
    ),
    "navigate_to": ToolSpec(
        name="navigate_to",
        description="Move toward a known target by ID.",
        arguments={
            "target_id": ToolArgumentSpec(
                name="target_id",
                value_type=str,
                description="Identifier of a known object or waypoint.",
            )
        },
    ),
    "report": ToolSpec(
        name="report",
        description="Summarize the current pose and any discovered targets.",
        arguments={},
    ),
}

VALID_TOOLS = frozenset(TOOL_SPECS)


def validate_action(action: Action) -> str | None:
    """Return an error message for an invalid action, or ``None`` when valid."""

    if action.skill not in TOOL_SPECS:
        return f"unknown tool '{action.skill}'"

    if not isinstance(action.params, dict):
        return "action params must be a dictionary"

    tool_spec = TOOL_SPECS[action.skill]
    unexpected = sorted(set(action.params) - set(tool_spec.arguments))
    if unexpected:
        return f"unexpected parameter(s) for '{action.skill}': {', '.join(unexpected)}"

    for argument_name, argument_spec in tool_spec.arguments.items():
        if argument_name not in action.params:
            if argument_spec.required:
                return f"missing parameter '{argument_name}' for '{action.skill}'"
            continue

        error = argument_spec.validate(action.params[argument_name])
        if error is not None:
            return error

    return None


def gemini_tool_declarations() -> list[dict[str, Any]]:
    """Return all tool declarations in Gemini function format."""

    return [tool_spec.to_gemini_function() for tool_spec in TOOL_SPECS.values()]


def build_tool_trace(actions: list[Action]) -> list[dict[str, Any]]:
    """Convert actions into a UI-friendly trace payload."""

    return [{"name": action.skill, "params": dict(action.params)} for action in actions]
