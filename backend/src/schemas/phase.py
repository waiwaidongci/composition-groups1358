from typing import Annotated,Union
from pydantic import BaseModel,Field,StrictFloat,StrictInt,ConfigDict

StrictNumber=Annotated[Union[StrictInt,Annotated[StrictFloat,Field(allow_inf_nan=False)]],Field()]


class NewComponent(BaseModel):
    model_config=ConfigDict(extra="forbid")
    code:str=Field(min_length=1,max_length=40,pattern=r"^[A-Za-z0-9_.-]+$")
    label:str=Field(min_length=1,max_length=80)
    unit:str=Field(default="",max_length=40)
    meaning:str=Field(default="",max_length=400)


class MigrationInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    label:str=Field(min_length=2,max_length=160)
    split_code:str=Field(min_length=1,max_length=40)
    new_components:list[NewComponent]=Field(min_length=2,max_length=2)


class SplitEntryInput(BaseModel):
    """One sample's split amounts; at least one of sample_id/sample_code must be set."""
    model_config=ConfigDict(extra="forbid")
    sample_id:int|None=Field(default=None,strict=True,ge=1)
    sample_code:str|None=Field(default=None,min_length=1,max_length=80)
    values:dict[str,StrictNumber]=Field(min_length=0,max_length=2)


class SplitBatchInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    entries:list[SplitEntryInput]=Field(min_length=1,max_length=300)


class VersionOutput(BaseModel):
    id:int
    study_id:int
    version:int
    label:str
    status:str
    source_version_id:int|None
    created_at:str
    activated_at:str
    retired_at:str
    invalidated_reason:str
    lock_version:int
