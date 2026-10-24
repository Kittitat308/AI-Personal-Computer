from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1)
    skill_ids: list[str] = Field(min_length=1)

    @field_validator("instruction")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("instruction must not be blank")

        return value

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
    response: str = Field(min_length=1)
    task: TaskRequest | None = None

    @field_validator("response")
    @classmethod
    def normalize_response(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("response must not be blank")

        return value

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
    response: str = Field(min_length=1)

    @field_validator("response")
    @classmethod
    def normalize_response(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("response must not be blank")

        return value


class AdminResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "needs_input", "failed", "cancelled"]
    response: str = Field(min_length=1)

    @field_validator("response")
    @classmethod
    def normalize_response(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("response must not be blank")

        return value
