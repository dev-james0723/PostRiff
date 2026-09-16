import {api} from './api.ts';
import type {Channel} from './types.ts';

export type SetupInput = {channel:string;nativeFormat:string;accountLabel:string;destinationLabel:string};
export type SetupSource = {url:string;checkedAt:string|null;state:string;note:string};
export type SetupChannel = Channel & {availableRoute:string;candidateRoute:string|null;routeDriver:string|null;routeTestId:string|null;pilotScope:string;documentationState:string;sources:SetupSource[];blockers:string[]};
export type SetupReadiness = {catalogVersion:string;phase:string;channels:SetupChannel[];connectedCount:number;publishReadyCount:number};
export type SetupCandidate = {schemaVersion:number;catalogVersion:string;state:string;scope:string;target:SetupInput & {identityState:string;operation:string};availableRoute:string;candidateRoute:string|null;routeDriver:null;routeTestId:null;pilotScope:string;documentationState:string;sources:SetupSource[];requirements:{id:string;state:string;detail:string}[];unresolved:string[];setupAuthorized:boolean;publicationAuthorized:boolean;remoteScheduling:boolean;connected:boolean;publishReady:boolean;externalActions:unknown[];manifestHash:string};

export function isSetupCandidate(value:SetupCandidate):boolean {
  return value.state==='candidate_only' && value.scope==='setup_assessment_only'
    && value.setupAuthorized===false && value.publicationAuthorized===false
    && value.remoteScheduling===false && value.connected===false && value.publishReady===false
    && value.target?.identityState==='unverified_labels' && value.routeDriver===null && value.routeTestId===null
    && Array.isArray(value.externalActions) && value.externalActions.length===0;
}
export const routeLabel=(route:string|null)=>route==='official_api'?'Official API candidate':route==='controlled_browser'?'Browser candidate': 'Route review needed';
export const setupApi={
  readiness:()=>api<SetupReadiness>('/api/setup/readiness'),
  prepare:async(input:SetupInput)=>{
    const {candidate}=await api<{candidate:SetupCandidate}>('/api/setup/candidates',{method:'POST',body:JSON.stringify(input)});
    if(!isSetupCandidate(candidate))throw new Error('The setup response is not a safe candidate. Reload Studio and retry.');
    return candidate;
  },
};
