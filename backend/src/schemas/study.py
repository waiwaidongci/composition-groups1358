from pydantic import BaseModel
class StudyOutput(BaseModel):
    id:int
    code:str
    name:str
    description:str
    source:str
    default_delta:float
    sample_count:int
    component_count:int
    group_counts:dict
    zero_rows:int
    supported:bool
    reason:str
    active_version:dict|None=None
    version_count:int=0
    migration_in_progress:int=0
