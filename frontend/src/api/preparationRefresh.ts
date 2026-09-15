type WorkspaceStatus = {automation?: {status: string}};

// Another tab or worker may resume a failed job. These refreshes only read
// saved work; they never submit preparation or invoke a model.
export const preparationRefresh = {
  refetchOnWindowFocus: true,
  refetchOnReconnect: true,
  refetchInterval: (query: {state: {data?: WorkspaceStatus[]}}) => {
    const workspaces = query.state.data;
    if (workspaces?.some(w => ['queued', 'running'].includes(w.automation?.status || ''))) return 2000;
    if (workspaces?.some(w => ['failed', 'interrupted'].includes(w.automation?.status || ''))) return 5000;
    return 30000;
  },
};
