from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


# Text that is stripped and must not be blank.
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: Text
    skill_ids: list[str] = Field(min_length=1)

    @field_validator("skill_ids")
    @classmethod
    def normalize_skill_ids(cls, values: list[str]) -> list[str]:
        normalized = []

        for value in values:
            skill_id = value.strip()

            if not skill_id:
                raise ValueError("skill IDs must not be blank")

            if skill_id in normalized:
                raise ValueError("skill IDs must not contain duplicates")

            normalized.append(skill_id)

        return normalized


class ChatResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["chat", "task"]
    response: Text
    task: TaskRequest | None = None

    @model_validator(mode="after")
    def validate_task_relationship(self):
        if self.type == "chat" and self.task is not None:
            raise ValueError("chat responses must not include a task")

        if self.type == "task" and self.task is None:
            raise ValueError("task responses must include a task")

        return self


class WorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "needs_input", "failed"]
    response: Text


class AdminResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "needs_input", "failed", "cancelled"]
    response: Text


class ConfirmationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["allow", "deny", "unclear"]
