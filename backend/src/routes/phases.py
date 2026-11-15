from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from ..config.database import get_db
from ..controllers.dependencies import current_user,roles
from ..constants.roles import Role
from ..schemas.phase import MigrationInput,SplitBatchInput
from ..services.phase_service import (
    list_versions,list_migrations,create_migration,migration_detail,
    upsert_entries,activate_migration,migration_progress_for_study,
)
router=APIRouter(tags=["phases"])


@router.get("/studies/{sid}/versions")
def versions(sid:int,db:Session=Depends(get_db),user=Depends(current_user)):
    return list_versions(db,sid)


@router.get("/studies/{sid}/phase-migrations")
def migrations(sid:int,db:Session=Depends(get_db),user=Depends(current_user)):
    return list_migrations(db,sid)


@router.get("/studies/{sid}/phase-progress")
def progress(sid:int,db:Session=Depends(get_db),user=Depends(current_user)):
    return migration_progress_for_study(db,sid)


@router.post("/studies/{sid}/phase-migrations",status_code=201)
def create(sid:int,data:MigrationInput,db:Session=Depends(get_db),
           user=Depends(roles(Role.ADMIN,Role.ANALYST))):
    return create_migration(db,sid,data,user)


@router.get("/phase-migrations/{mid}")
def show(mid:int,db:Session=Depends(get_db),user=Depends(current_user)):
    return migration_detail(db,mid)


@router.post("/phase-migrations/{mid}/entries")
def entries(mid:int,data:SplitBatchInput,db:Session=Depends(get_db),
            user=Depends(roles(Role.ADMIN,Role.ANALYST))):
    return upsert_entries(db,mid,data,user)


@router.post("/phase-migrations/{mid}/activate")
def activate(mid:int,db:Session=Depends(get_db),user=Depends(roles(Role.ADMIN))):
    return activate_migration(db,mid,user)
