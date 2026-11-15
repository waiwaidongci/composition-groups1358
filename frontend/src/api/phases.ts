import {request} from './client';import {Component,PhaseVersion,PhaseMigration,PhaseProgress} from '../types/domain';
export const getVersions=(study:number)=>request<PhaseVersion[]>(`/studies/${study}/versions`);
export const getComponents=(id:number,versionId?:number)=>request<Component[]>(`/studies/${id}/components`+(versionId?`?version_id=${versionId}`:''));
export const getMigrations=(study:number)=>request<PhaseMigration[]>(`/studies/${study}/phase-migrations`);
export const getMigration=(id:number)=>request<PhaseMigration>(`/phase-migrations/${id}`);
export const getPhaseProgress=(study:number)=>request<PhaseProgress>(`/studies/${study}/phase-progress`);
export const createMigration=(study:number,data:{label:string;split_code:string;new_components:{code:string;label:string;unit?:string;meaning?:string}[]})=>request<PhaseMigration>(`/studies/${study}/phase-migrations`,{method:'POST',body:JSON.stringify(data)});
export const submitEntries=(migration:number,entries:{sample_code:string;values:Record<string,number>}[])=>request<{migration_id:number;updated:{sample_code:string;status:string;reason:string;submitted_sum:number|null}[];skipped:{sample_code:string;status:string;reason:string}[];applied:number;duplicates_only:boolean;progress:PhaseMigration['progress']}>(`/phase-migrations/${migration}/entries`,{method:'POST',body:JSON.stringify({entries})});
export const activateMigration=(migration:number)=>request<{migration:PhaseMigration;already_active:boolean;target_version:PhaseMigration['target_version']}>(`/phase-migrations/${migration}/activate`,{method:'POST',body:JSON.stringify({})});
