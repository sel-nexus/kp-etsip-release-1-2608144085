/** Exercise report rendering, URL transitions and explicit downloads. */
import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { SessionProvider } from '../auth/SessionProvider';
import { AppRoutes } from '../../routes';
import { reportApi, applicationColumns, portfolioColumns } from './reportApi';
import { TOKEN_KEY } from '../../lib/api';
const user = { id:'65b000000000000000000001',name:'Test',email:'test@example.com',role:'Engineer',portfolioAccess:[],status:'Active',defaultLandingPage:null,mustChangePassword:false };
const app = { id:'65b200000000000000000001',name:'Persisted app',portfolioId:'65b100000000000000000001',criticality:'High',tier:2,lifecycleStatus:'Active',applicationHealthScore:82,qualityScore:79,automationCoverage:65,unitTestCoverage:72,openDefects:4,openCriticalDefects:1,riskLevel:'Medium' };
const portfolio = { id:app.portfolioId,name:'Persisted portfolio',ownerName:'Test owner',productArea:'Payments',status:'Active',applicationCount:0,qualityScore:null };
const json = (body:unknown,status=200) => new Response(JSON.stringify(body),{status});
function mount(kind='applications',role='Engineer',entry?:string) {
  localStorage.setItem(TOKEN_KEY,'test-token');
  const fetch = vi.spyOn(globalThis,'fetch').mockResolvedValueOnce(json({...user,role}));
  fetch.mockResolvedValueOnce(json({items:[kind==='applications'?app:portfolio],page:1,pageSize:10,total:11}));
  render(
    <MemoryRouter initialEntries={[entry ?? `/reports/${kind}?pageSize=10`]} future={{v7_startTransition:true,v7_relativeSplatPath:true}}>
      <SessionProvider><AppRoutes /></SessionProvider>
    </MemoryRouter>,
  );
  return fetch;
}
for (const kind of ['applications','portfolios']) {
  describe(kind,()=>{
    it('renders fixed columns and URL filters/paging without automatic export',async()=>{
      const fetch=mount(kind,'Engineer',`/reports/${kind}?format=csv&pageSize=10`);
      await screen.findByRole('table');
      expect(screen.getAllByRole('columnheader').map(h=>h.textContent)).toEqual(kind==='applications'?applicationColumns:portfolioColumns);
      expect(String(fetch.mock.calls[1][0])).not.toContain('format=');
      expect(fetch).toHaveBeenCalledTimes(2);
      fetch.mockResolvedValueOnce(json({items:[],page:2,pageSize:10,total:11}));
      await userEvent.click(screen.getByRole('button',{name:'Next'}));
      await screen.findByText(/No .* match your scope/);
      expect(String(fetch.mock.calls[2][0])).toContain('page=2');
      fetch.mockResolvedValueOnce(json({items:[],page:1,pageSize:25,total:0}));
      await userEvent.type(screen.getByLabelText('search'),'Absent');
      await userEvent.click(screen.getByRole('button',{name:'Apply filters'}));
      await waitFor(()=>expect(String(fetch.mock.calls[3][0])).toContain('search=Absent'));
      fetch.mockResolvedValueOnce(json({items:[],page:1,pageSize:25,total:0}));
      await userEvent.click(screen.getByRole('button',{name:'Clear filters'}));
      await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(5));
    });
    it('hides export from Read Only while keeping report viewing',async()=>{
      mount(kind,'Read Only');
      await screen.findByRole('table');
      expect(screen.queryByRole('button',{name:'Export CSV'})).not.toBeInTheDocument();
    });
    it('shows export pending, denial and successful blob download on retry',async()=>{
      const fetch=mount(kind);
      await screen.findByRole('table');
      let done!:(r:Response)=>void;
      fetch.mockImplementationOnce(()=>new Promise(resolve=>{done=resolve;}));
      await userEvent.click(screen.getByRole('button',{name:'Export CSV'}));
      expect(screen.getByRole('button',{name:'Exporting CSV…'})).toBeDisabled();
      await act(async()=>done(json({error:{code:'FORBIDDEN',message:'Export denied',fields:{}}},403)));
      expect(await screen.findByRole('alert')).toHaveTextContent('Export denied');
      vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:vi.fn(()=> 'blob:test'),revokeObjectURL:vi.fn()}));
      const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>undefined);
      fetch.mockResolvedValueOnce(new Response('id,name\r\n1,Test',{headers:{'Content-Type':'text/csv'}}));
      await userEvent.click(screen.getByRole('button',{name:'Export CSV'}));
      expect(await screen.findByText('CSV download started')).toBeVisible();
      expect(click).toHaveBeenCalledTimes(1);
      expect(String(fetch.mock.calls.at(-1)?.[0])).toContain('format=csv');
      expect(new Headers(fetch.mock.calls.at(-1)?.[1]?.headers).get('Authorization')).toBe('Bearer test-token');
    });
    it('reports load failure and retries rather than leaving stale data',async()=>{
      localStorage.setItem(TOKEN_KEY,'test-token');
      const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValueOnce(json(user)).mockRejectedValueOnce(new Error('offline'));
      render(<MemoryRouter initialEntries={[`/reports/${kind}`]} future={{v7_startTransition:true,v7_relativeSplatPath:true}}><SessionProvider><AppRoutes /></SessionProvider></MemoryRouter>);
      await screen.findByRole('alert');
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
      fetch.mockResolvedValueOnce(json({items:[],page:1,pageSize:25,total:0}));
      await userEvent.click(screen.getByRole('button',{name:'Retry'}));
      expect(await screen.findByText(/No .* match your scope/)).toBeVisible();
    });
  });
}
it.each([401,503])('CSV failure %s creates no download and expires only 401',async(status)=>{
  localStorage.setItem(TOKEN_KEY,'test-token');
  vi.spyOn(globalThis,'fetch').mockResolvedValueOnce(json({error:{code:'FAILED',message:'Failed',fields:{}}},status));
  await expect(reportApi.download('application-list',new URLSearchParams('search=Test'))).rejects.toThrow('Failed');
  expect(localStorage.getItem(TOKEN_KEY)).toBe(status===401?null:'test-token');
});
it('rejects non-CSV success and network failure',async()=>{
  const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValueOnce(json({}));
  await expect(reportApi.download('applications',new URLSearchParams())).rejects.toThrow('did not return CSV');
  fetch.mockRejectedValueOnce(new Error('offline'));
  await expect(reportApi.download('portfolios',new URLSearchParams())).rejects.toThrow('Unable to reach');
});

it('application inventory exports only on click and retains its list filters',async()=>{
  localStorage.setItem(TOKEN_KEY,'test-token');
  const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValueOnce(json(user)).mockResolvedValueOnce(json({items:[app],page:1,pageSize:25,total:1}));
  render(<MemoryRouter initialEntries={['/applications?riskLevel=Medium&format=csv']} future={{v7_startTransition:true,v7_relativeSplatPath:true}}><SessionProvider><AppRoutes /></SessionProvider></MemoryRouter>);
  await screen.findByRole('table');
  expect(String(fetch.mock.calls[1][0])).not.toContain('format=');
  fetch.mockResolvedValueOnce(json({error:{code:'AUDIT_WRITE_FAILED',message:'Audit unavailable',fields:{}}},503));
  await userEvent.click(screen.getByRole('button',{name:'Export CSV'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Audit unavailable');
  expect(String(fetch.mock.calls.at(-1)?.[0])).toContain('/applications?riskLevel=Medium&format=csv');
});
