import {Link,Navigate,useSearchParams} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {api} from '../api/client';
import {preparationRefresh} from '../api/preparationRefresh';
import type {SourcedLead} from '../api/types';
import PreparationWorkspace from '../components/PreparationWorkspace';
import type {AnalystWorkspace} from '../components/PreparationWorkspace';
import OperationsRecords from './OperationsRecords';
import RoomPipeline from '../components/RoomPipeline';
export default function Operations(){
 const [params]=useSearchParams();
 return params.get('view')==='records'?<OperationsRecords/>:<CompanyPreparation/>;
}
function CompanyPreparation(){
 const [params]=useSearchParams();const id=params.get('lead');
 const leadQuery=useQuery({queryKey:['leads',id],queryFn:()=>api.get<SourcedLead>(`/api/leads/${encodeURIComponent(id!)}`),enabled:!!id});
 const workspaces=useQuery({queryKey:['operations','summary',params.get('lead')],queryFn:()=>api.get<AnalystWorkspace[]>(`/api/operations/workspaces?summary=true&lead_id=${encodeURIComponent(params.get('lead')||'')}`),...preparationRefresh});
 if(leadQuery.isLoading||workspaces.isLoading)return <p role="status">Loading company work…</p>;
 if(leadQuery.error||workspaces.error)return <p role="alert">{leadQuery.error?.message||workspaces.error?.message}</p>;
 if(!id)return <Navigate to="/" replace/>;
 const lead=leadQuery.data?.company_profile&&leadQuery.data.status!=='dismissed'?leadQuery.data:undefined;
 return lead?<PreparationWorkspace key={id} lead={lead} workspace={workspaces.data?.find(w=>w.lead_id===id)} materials={<RoomPipeline key={`room-${id}`} leadId={id}/>}/>:<p>Company unavailable. <Link to="/">Your companies</Link></p>;
}
