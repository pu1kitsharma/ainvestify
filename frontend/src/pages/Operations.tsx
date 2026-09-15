import {Link,Navigate,useSearchParams} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {api} from '../api/client';
import {preparationRefresh} from '../api/preparationRefresh';
import {useLeads} from '../api/hooks';
import PreparationWorkspace from '../components/PreparationWorkspace';
import type {AnalystWorkspace} from '../components/PreparationWorkspace';
import OperationsRecords from './OperationsRecords';
export default function Operations(){
 const [params]=useSearchParams();const leads=useLeads();
 const workspaces=useQuery({queryKey:['operations','summary',params.get('lead')],queryFn:()=>api.get<AnalystWorkspace[]>(`/api/operations/workspaces?summary=true&lead_id=${encodeURIComponent(params.get('lead')||'')}`),...preparationRefresh});
 if(params.get('view')==='records')return <OperationsRecords/>;
 if(leads.isLoading||workspaces.isLoading)return <p role="status">Loading company work…</p>;
 if(leads.error||workspaces.error)return <p role="alert">{leads.error?.message||workspaces.error?.message}</p>;
 const id=params.get('lead');if(!id)return <Navigate to="/" replace/>;
 const lead=leads.data?.find(l=>l.id===id&&l.company_profile&&l.status!=='dismissed');
 return lead?<PreparationWorkspace key={id} lead={lead} workspace={workspaces.data?.find(w=>w.lead_id===id)}/>:<p>Company unavailable. <Link to="/">Your companies</Link></p>;
}
